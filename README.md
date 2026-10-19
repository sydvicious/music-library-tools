# music-library-tools

Tools for keeping a large, long-lived Apple Music library (macOS Music.app with locally stored
files) honest: finding files Music has lost track of, files on disk that no track points to,
duplicate audio, and recovering lost tracks from old backups.

The core idea is **three sources of truth kept in sync**:

1. **the disk**: the media files in the library folder
2. **a database**: an SQLite catalog of every file's path, size, mtime and an *audio-only* MD5
   (ffmpeg hashes the audio packets, so retagging or new artwork doesn't change it)
3. **Music.app**: every track's file location, read directly from Music's database file (`musicdb.py`); an XML you export yourself can be used as a cross-check

Each is snapshotted to a TSV sorted by path, and one merge pass classifies every path.

## Requirements

- macOS with Music.app, Python 3, and `ffmpeg` (`brew install ffmpeg`)
- Xcode command-line tools, only for `music_dump.swift`

## Configuration

Paths come from `mlt_config.py`: environment variables, or `~/.config/music-library-tools/config.json`:

```json
{
  "library": "~/Music/iTunes/iTunes Media",
  "data": "~/Music/Recovered",
  "reports": "~/Library/Mobile Documents/com~apple~CloudDocs/Recovered Music",
  "primary_mac": "My Mac"
}
```

`library` is Music's media folder. `data` holds the database and snapshots. `reports` receives
the dated reports. Run `./sync_check.py paths` to see what's in effect.

## Everyday tools

| Script | What it does |
|---|---|
| `audio_hash.py lite <source> <folder>` | Quick update: hash new or changed files, drop vanished ones |
| `audio_hash.py audit <source> <folder> [--dry-run] [--verify N\|all]` | Full disk-vs-database audit: retries failures, detects moves by hash, optional re-verification |
| `audio_hash.py sql "<query>"` | Ad-hoc SQL against the catalog (`files` table, `dupes` view) |
| `sync_check.py library-check --export [--notify]` | The whole check: lite hash, export Music's XML, snapshot disk + db, 3-way merge, summary and notification |
| `sync_check.py library-check --xml Library.xml` | The same check with an XML you exported yourself |
| `dup_report.py` | Report of identical audio within the library; known, intended sets can be listed by MD5 in `~/.config/music-library-tools/dup-ignore.txt` |
| `prune_empty_dirs.py [ROOT] [--dry-run]` | Remove folders that are empty or contain only `.DS_Store` |
| `export_library.js` | Drives File > Library > Export Library… through Accessibility actions (no keystrokes) |
| `musicdb.py tracks\|summary\|playlists` | Reads Music's `Library.musicdb` directly (reverse-engineered; Music can be closed). Tracks not in the master library playlist are reported as ghost records |
| `musicdb.py watch [PID ...]` | Tracks whether given persistent IDs stay in the library; logs to `<data>/snapshots/watch.log` and notifies on change (run hourly by a launchd agent) |
| `music_dump.swift` | Dumps the library through Apple's iTunesLibrary framework. Fast, but it reads a shared media library (TV and Books too) that can be stale, so the check uses the XML instead |

A full rebuild of the database is: move it to the Trash, then run `lite` again.

### Merge classes

| disk | db | Music | class |
|---|---|---|---|
| ✓ | ✓ | ✓ | `ok`, or `changed` if size/mtime differ from the db |
| ✓ | ✓ | | `orphan`: hashed, but no track points to it |
| ✓ | | ✓ | `unhashed` |
| ✓ | | | `orphan-unhashed` |
| | ✓ | ✓ | `missing` |
| | ✓ | | `stale-row` |
| | | ✓ | `missing`, or `cache-gone` for an Apple Music download whose cache file was deleted |

Paths are compared case-insensitively after Unicode NFC normalization. APFS is case-insensitive,
and Music keeps whatever case a path had when the track was added.

## Nightly check

`check_app/build_check_app.sh` builds `~/Applications/Music Library Check.app` and a launchd
agent that opens it at 3:00 AM. The app opens Music in the background if needed (then waits 15
minutes so it can sync and save its database), runs `library-check`, and posts a notification. Output is appended to
`<data>/snapshots/library-check.log`. Snapshot TSVs older than 14 days are deleted.

It needs no Accessibility or Automation permission, only access to Music's library folder, which
macOS asks for on the first manual run (`open -a "Music Library Check"`). The app runs the Python
scripts from this repository, so only changes to `check_app_main.js` need a rebuild, and a
rebuild means granting that access again. (`export_library.js` and `--export` remain for manual
use; the nightly run no longer exports.)

## Manifest

Every `library-check` run also writes a manifest beside the media folder (`<library>/../Manifests`), so it
travels with every copy or backup of the library:

- `Manifests/latest/`: `Library.musicdb` (Music's database), `audio-hashes.sqlite`, `files.tsv` (every file under
  the media folder with full path, size, mtime and audio MD5) and `music-tracks.tsv` (every track record in
  Music's database). Replaced on each run.
- `Manifests/YYYY-MM-DD/`: gzipped `files.tsv` and `music-tracks.tsv` for that day (about 4 MB), kept.

Backups that accumulate everything ever written can be restored to any day by copying only the files in that
day's `files.tsv`. `sync_check.py manifest` writes one without running the check.

## recovery/

One-off scripts from recovering a library that had lost files over many years and Mac migrations:
searching Time Machine and rsync backups (`recover_from_backup.py`), matching tracks to files
(`find_missing_tracks.py`), re-adding tracks to Music while restoring play counts, ratings and
playlists (`readd_tracks.js`), and the first orphan report (`orphan_report.py`, superseded by
`sync_check.py`). They work, but they're less general than the tools above.
