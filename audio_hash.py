#!/usr/bin/env python3
"""Keep three sources of truth in sync: the files on disk, this audio-hash database, and Music.app.

  audio_hash.py lite  <source> <folder>    disk -> database, quick (alias: add)
  audio_hash.py audit <source> <folder>    disk <-> database, full audit, then fix
        [--dry-run]       report only; change nothing, hash nothing
        [--verify N|all]  also re-hash N random unchanged files (or all) to catch silent changes
  audio_hash.py validate-library           database <-> Music.app, for the 'library' source
        [--cached]        reuse the last Music.app snapshot instead of asking Music (~10 min)
        [--folder PATH]   library folder (default: the configured library, see mlt_config.py)
  audio_hash.py sql "<query>"
  Full rebuild: move the database to the Trash, then run lite (or audit) for each source.

  A full check of the library is:  audit library <folder>  then  validate-library

Common options: --db PATH (default <data>/audio-hashes.sqlite, see mlt_config.py), --jobs N

Examples:
  audio_hash.py lite  library   ~/Music/Music/Media
  audio_hash.py audit recovered ~/Music/Recovered --dry-run
  audio_hash.py validate-library

The hash is ffmpeg's MD5 of the audio packets copied without re-encoding
(ffmpeg -map 0:a:0 -c copy -f md5), so retagging or changing artwork doesn't change it,
while a different encoding (mp3 vs m4a, or a re-rip) does.

lite:  walks the folder; hashes files that are new or whose size or mtime changed;
       drops rows for files that are gone. Prints counts only.
audit: the same walk, plus: retries files that failed to hash before, recognises moved or
       renamed files (gone path + new path with the same audio), finds rows recorded under
       this source but outside the folder, and optionally re-hashes unchanged files.
       Writes "<date> Audit <source>.tsv" listing every discrepancy and what was done.
validate-library: asks Music.app for every file track's location (one Apple event per track,
       because the bulk request fails when any file is missing), stores it in the music_tracks
       table, and reports:
         orphans    files in the folder that no track points to (classified: same audio as a
                    track, same album folder + file name, inside an Extras/LP bundle, small, or
                    unique)
         missing    tracks whose file is gone (no location, or the path doesn't exist)
         unindexed  tracks whose file exists but isn't in the database (run lite first) or
                    lives outside the library folder
       Writes "<date> Validate Library.txt" and ".tsv".
Reports are written to the configured reports folder (mlt_config.py).

Database tables:
  files(path PK, source, root, rel, ext, size, mtime, audio_md5, error, hashed_at)
  music_tracks(pid PK, location, name, artist, album, kind, snapshot_at)
"""
import os, sys, sqlite3, subprocess, datetime, random, tempfile, unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import mlt_config as C

EXT = {'.m4a', '.mp3', '.m4p', '.m4v', '.mp4', '.wav', '.aif', '.aiff', '.aac', '.mov', '.caf', '.flac', '.m4b'}
FFMPEG = next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(p)), 'ffmpeg')
REPORTS = C.REPORTS
TODAY = datetime.date.today().isoformat()
SMALL = 300_000
nfc = lambda s: unicodedata.normalize('NFC', s)

def opt(name, default):
    a = sys.argv
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default

DB = os.path.expanduser(opt('--db', C.DB))
JOBS = int(opt('--jobs', str(os.cpu_count() or 8)))

def connect():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript('''
      create table if not exists files(
        path text primary key, source text not null, root text, rel text, ext text,
        size integer, mtime real, audio_md5 text, error text, hashed_at text);
      create index if not exists files_md5 on files(audio_md5);
      create index if not exists files_source on files(source);
      create index if not exists files_md5_source on files(audio_md5, source);
      create view if not exists dupes as                -- every pair of files with identical audio
        select a.source a_source, a.path a_path, b.source b_source, b.path b_path, a.audio_md5
        from files a join files b on a.audio_md5 = b.audio_md5 and a.path < b.path
        where a.audio_md5 is not null;
      create table if not exists music_tracks(
        pid text primary key, location text, name text, artist text, album text, kind text,
        snapshot_at text);
      create index if not exists music_tracks_loc on music_tracks(location);
    ''')
    return db

def audio_md5(path):
    try:
        r = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-i', path, '-map', '0:a:0', '-c', 'copy', '-f', 'md5', '-'],
                           capture_output=True, text=True, timeout=600)
        out = r.stdout.strip()
        if r.returncode == 0 and out.startswith('MD5='): return out[4:], None
        return None, (r.stderr.strip().splitlines() or ['ffmpeg failed'])[-1][:300]
    except Exception as e:
        return None, str(e)[:300]

def walk(folder):
    """{path: (ext, size, mtime)} for every media file under folder (skipping dot files/dirs)."""
    print(f'Listing {folder} ...', flush=True)
    found = {}
    for dp, dns, fns in os.walk(folder):
        dns[:] = [d for d in dns if not d.startswith('.')]
        for f in fns:
            ext = os.path.splitext(f)[1].lower()
            if f.startswith('.') or ext not in EXT: continue
            p = os.path.join(dp, f)
            try: st = os.stat(p)
            except OSError: continue
            found[p] = (ext, st.st_size, st.st_mtime)
    return found

def hash_all(db, source, folder, todo, label='hashed'):
    """todo: list of (path, ext, size, mtime). Hashes in parallel, writes rows. Returns {path: (md5, err)}."""
    results, done, errs = {}, 0, 0
    now = datetime.datetime.now().isoformat(timespec='seconds')
    with ThreadPoolExecutor(JOBS) as ex:
        futs = {ex.submit(audio_md5, t[0]): t for t in todo}
        for fut in as_completed(futs):
            p, ext, size, mtime = futs[fut]; md5, err = fut.result()
            results[p] = (md5, err)
            db.execute('insert or replace into files values (?,?,?,?,?,?,?,?,?,?)',
                       (p, source, folder, os.path.relpath(p, folder), ext, size, mtime, md5, err, now))
            done += 1; errs += err is not None
            if done % 500 == 0:
                db.commit(); print(f'  {done}/{len(todo)} {label} ({errs} errors)', flush=True)
    db.commit()
    return results

# ---------------------------------------------------------------- lite
def lite(source, folder):
    folder = os.path.abspath(os.path.expanduser(folder))
    db = connect()
    known = {p: (s, m) for p, s, m in db.execute('select path, size, mtime from files where source=?', (source,))}
    found = walk(folder)
    todo = [(p, e, s, m) for p, (e, s, m) in found.items() if known.get(p) != (s, m)]
    gone = [p for p in known if p not in found and p.startswith(folder + '/')]
    if gone:
        db.executemany('delete from files where path=?', [(p,) for p in gone]); db.commit()
    print(f'{len(found)} media files; {len(todo)} to hash; {len(gone)} removed from index. Using {JOBS} jobs.', flush=True)
    res = hash_all(db, source, folder, todo)
    errs = sum(1 for m, e in res.values() if e)
    print(f'Done: {len(res)} hashed, {errs} errors. Database: {DB}')

# ---------------------------------------------------------------- audit
def audit(source, folder, dry=False, verify=None):
    folder = os.path.abspath(os.path.expanduser(folder))
    db = connect()
    rows = {p: dict(size=s, mtime=m, md5=h, err=e, root=r) for p, s, m, h, e, r in
            db.execute('select path, size, mtime, audio_md5, error, root from files where source=?', (source,))}
    found = walk(folder)
    inside = {p: r for p, r in rows.items() if p.startswith(folder + '/')}
    outside = sorted(p for p in rows if not p.startswith(folder + '/'))

    new      = sorted(p for p in found if p not in inside)
    missing  = sorted(p for p in inside if p not in found)
    size_ch  = sorted(p for p in found if p in inside and found[p][1] != inside[p]['size'])
    mtime_ch = sorted(p for p in found if p in inside and found[p][1] == inside[p]['size'] and found[p][2] != inside[p]['mtime'])
    changed  = set(size_ch) | set(mtime_ch)
    failed   = sorted(p for p in found if p in inside and p not in changed and not inside[p]['md5'])
    unchanged = [p for p in found if p in inside and p not in changed and inside[p]['md5']]
    if verify == 'all': check = unchanged
    elif verify: check = random.sample(unchanged, min(int(verify), len(unchanged)))
    else: check = []

    print(f'{len(found)} on disk, {len(inside)} in database: {len(new)} new, {len(missing)} missing, '
          f'{len(size_ch)} size changed, {len(mtime_ch)} date changed, {len(failed)} previously failed, '
          f'{len(outside)} recorded outside the folder' + (f', {len(check)} to verify' if check else ''), flush=True)

    report = []   # (issue, path, detail, action)
    if dry:
        # Without hashing, a move can only be guessed from size + file name.
        by_sig = defaultdict(list)
        for p in missing: by_sig[(inside[p]['size'], os.path.basename(p).lower())].append(p)
        for p in new:
            m = by_sig.get((found[p][1], os.path.basename(p).lower()))
            report.append(('new', p, ('possibly moved from ' + m[0]) if m else '', 'would hash'))
        for p in missing: report.append(('missing', p, '', 'would drop'))
        for p in size_ch: report.append(('size-changed', p, f"{inside[p]['size']} -> {found[p][1]}", 'would re-hash'))
        for p in mtime_ch: report.append(('date-changed', p, '', 'would re-hash'))
        for p in failed: report.append(('previously-failed', p, inside[p]['err'] or '', 'would retry'))
        for p in check: report.append(('verify', p, '', 'would re-hash and compare'))
    else:
        old_md5 = {p: inside[p]['md5'] for p in size_ch + mtime_ch + check}
        todo = [(p, *found[p]) for p in new + size_ch + mtime_ch + failed + check]
        res = hash_all(db, source, folder, todo)
        miss_by_md5 = defaultdict(list)
        for p in missing:
            if inside[p]['md5']: miss_by_md5[inside[p]['md5']].append(p)
        moved_from = set()
        for p in new:
            m, e = res[p]
            src = miss_by_md5.get(m) if m else None
            if src:
                s = src.pop(0); moved_from.add(s)
                report.append(('moved', p, 'from ' + s, 'hashed'))
            else:
                report.append(('new', p, e or '', 'hashed' if m else 'hash failed'))
        db.executemany('delete from files where path=?', [(p,) for p in missing]); db.commit()
        for p in missing:
            if p not in moved_from: report.append(('missing', p, '', 'dropped'))
        for p in size_ch + mtime_ch:
            m, e = res[p]
            same = 'same audio' if m and m == old_md5[p] else ('audio changed' if m else e)
            report.append(('size-changed' if p in size_ch else 'date-changed', p, same, 're-hashed'))
        for p in failed:
            m, e = res[p]
            report.append(('previously-failed', p, e or '', 'fixed' if m else 'still fails'))
        mism = 0
        for p in check:
            m, e = res[p]
            if m != old_md5[p]:
                mism += 1; report.append(('verify-mismatch', p, f'{old_md5[p]} -> {m or e}', 're-hashed'))
        if check: print(f'Verified {len(check)} unchanged files: {mism} mismatches', flush=True)
    for p in outside: report.append(('outside-folder', p, f"root {rows[p]['root']}", 'left alone'))

    out = os.path.join(REPORTS, f'{TODAY} Audit {source}.tsv')
    with open(out, 'w') as f:
        f.write('issue\tpath\tdetail\taction\n')
        for r in report: f.write('\t'.join(r) + '\n')
    counts = defaultdict(int)
    for r in report: counts[r[0]] += 1
    print(('Dry run: ' if dry else 'Done: ') + (', '.join(f'{k} {v}' for k, v in sorted(counts.items())) or 'no discrepancies'))
    print(f'Report: {out}')

# ---------------------------------------------------------------- validate-library
JXA = r'''
function run(argv){
  const ft = Application("Music").libraryPlaylists[0].fileTracks;
  const pid = ft.persistentID(), nm = ft.name(), ar = ft.artist(), al = ft.album(), kd = ft.kind();
  const n = pid.length, out = [];
  const clean = s => (s == null ? "" : String(s)).replace(/[\t\n\r]/g, " ");
  for (let j = 0; j < n; j++) {
    let loc = "";
    try { const x = ft[j].location(); if (x) loc = x.toString(); } catch (e) {}
    out.push([pid[j], loc, nm[j], ar[j], al[j], kd[j]].map(clean).join("\t"));
    if (j % 2000 === 0) console.log("  " + j + "/" + n + " tracks");
  }
  $.NSString.alloc.initWithUTF8String(out.join("\n"))
    .writeToFileAtomicallyEncodingError(argv[0], true, $.NSUTF8StringEncoding, null);
  return n + " tracks";
}
'''

def snapshot_music(db):
    print('Asking Music.app for every track location (about 10 minutes for ~38k tracks) ...', flush=True)
    with tempfile.TemporaryDirectory() as td:
        js, tsv = os.path.join(td, 'snap.js'), os.path.join(td, 'snap.tsv')
        open(js, 'w').write(JXA)
        r = subprocess.run(['osascript', '-l', 'JavaScript', js, tsv], text=True, stdout=subprocess.PIPE)
        if r.returncode != 0 or not os.path.exists(tsv): sys.exit('Music.app snapshot failed')
        now = datetime.datetime.now().isoformat(timespec='seconds')
        rows = []
        for line in open(tsv, encoding='utf-8'):
            parts = line.rstrip('\n').split('\t')
            if len(parts) == 6: rows.append(tuple(parts) + (now,))
    db.execute('delete from music_tracks')
    db.executemany('insert or replace into music_tracks values (?,?,?,?,?,?,?)', rows)
    db.commit()
    print(f'Snapshot: {len(rows)} file tracks', flush=True)

def validate_library(folder, cached=False):
    folder = os.path.abspath(os.path.expanduser(folder))
    prefix = folder + '/'
    db = connect()
    if not cached or not db.execute('select count(*) from music_tracks').fetchone()[0]:
        snapshot_music(db)
    snap_at = db.execute('select max(snapshot_at) from music_tracks').fetchone()[0]
    tracks = db.execute('select pid, location, name, artist, album, kind from music_tracks').fetchall()
    files = {nfc(p): (s, m) for p, s, m in db.execute(
        "select path, size, audio_md5 from files where source='library'")}
    last_hash = db.execute("select max(hashed_at) from files where source='library'").fetchone()[0]

    referenced = set()
    missing, unindexed = [], []
    for pid, loc, name, artist, album, kind in tracks:
        desc = f'{artist} — {album} — {name}'
        if not loc:
            missing.append((pid, '', desc, 'no file location')); continue
        p = nfc(loc); referenced.add(p)
        if p in files: continue
        if not os.path.exists(loc): missing.append((pid, p, desc, 'file not found'))
        elif not p.startswith(prefix): unindexed.append((pid, p, desc, 'outside library folder'))
        else: unindexed.append((pid, p, desc, 'not in database (run lite)'))

    lib_md5 = defaultdict(list)
    for p, (s, m) in files.items():
        if p in referenced and m: lib_md5[m].append(p)
    def akey(p):
        parts = p.split('/'); return (parts[-2].lower(), parts[-1].lower())
    lib_akey = {akey(p): p for p in referenced if p.startswith(prefix)}
    orphans = []
    for p, (s, m) in sorted(files.items(), key=lambda x: x[0].lower()):
        if p in referenced or not p.startswith(prefix): continue
        if '.ite/' in p or '.itlp/' in p or 'iTunes LP (' in p: cls, ref = 'in-bundle', ''
        elif m and m in lib_md5:         cls, ref = 'same-audio-as-track', lib_md5[m][0]
        elif akey(p) in lib_akey:        cls, ref = 'same-name-as-track', lib_akey[akey(p)]
        elif s < SMALL:                  cls, ref = 'small', ''
        elif not m:                      cls, ref = 'unhashable', ''
        else:                            cls, ref = 'unique', ''
        orphans.append((cls, p, s, ref))

    rel = lambda p: p[len(prefix):] if p.startswith(prefix) else p
    base = os.path.join(REPORTS, f'{TODAY} Validate Library')
    with open(base + '.tsv', 'w') as f:
        f.write('section\tclass\tpid\tpath\tbytes\tdetail\n')
        for c, p, s, ref in orphans: f.write(f'orphan\t{c}\t\t{rel(p)}\t{s}\t{rel(ref)}\n')
        for pid, p, d, why in missing: f.write(f'missing\t{why}\t{pid}\t{rel(p)}\t\t{d}\n')
        for pid, p, d, why in unindexed: f.write(f'unindexed\t{why}\t{pid}\t{rel(p)}\t\t{d}\n')
    oc = defaultdict(int)
    for o in orphans: oc[o[0]] += 1
    kinds = ('unique', 'same-audio-as-track', 'same-name-as-track', 'small', 'unhashable', 'in-bundle')
    with open(base + '.txt', 'w') as f:
        f.write(f'Music.app vs the audio-hash database for {folder}\n')
        f.write(f'Music snapshot {snap_at}; files last hashed {last_hash}. Paths relative to the library folder.\n')
        f.write(f'{len(tracks)} file tracks, {len(files)} files in database\n\n')
        f.write(f'Orphans (files no track points to): {len(orphans)}\n')
        for k in kinds:
            if oc[k]: f.write(f'  {k:20} {oc[k]}\n')
        f.write(f'Missing (track whose file is gone): {len(missing)}\n')
        f.write(f'Unindexed (track file not in database): {len(unindexed)}\n\n')
        for k in kinds:
            sel = [o for o in orphans if o[0] == k]
            if not sel: continue
            f.write(f'== orphan: {k} ({len(sel)}) ==\n')
            for c, p, s, ref in sel:
                f.write(f'  {rel(p)}  ({s/1e6:.1f} MB)' + (f'\n      = {rel(ref)}' if ref else '') + '\n')
            f.write('\n')
        for title, sel in (('missing', missing), ('unindexed', unindexed)):
            if not sel: continue
            f.write(f'== {title} ({len(sel)}) ==\n')
            for pid, p, d, why in sorted(sel, key=lambda x: x[2].lower()):
                f.write(f'  {d}  [{why}] {pid}' + (f'\n      {rel(p)}' if p else '') + '\n')
            f.write('\n')
    print(f'{len(orphans)} orphans ' + str(dict(oc)) + f', {len(missing)} missing, {len(unindexed)} unindexed')
    print(f'Report: {base}.txt')

def sql(q):
    db = connect(); cur = db.execute(q)
    if cur.description: print('\t'.join(d[0] for d in cur.description))
    for row in cur: print('\t'.join('' if v is None else str(v) for v in row))
    db.commit()

if __name__ == '__main__':
    takes = ('--db', '--jobs', '--verify', '--folder')
    a = [x for i, x in enumerate(sys.argv[1:], 1) if not x.startswith('--') and sys.argv[i - 1] not in takes]
    if len(a) == 3 and a[0] in ('lite', 'add'): lite(a[1], a[2])
    elif len(a) == 3 and a[0] == 'audit': audit(a[1], a[2], dry='--dry-run' in sys.argv, verify=opt('--verify', None))
    elif len(a) == 1 and a[0] == 'validate-library':
        validate_library(opt('--folder', C.LIBRARY), cached='--cached' in sys.argv)
    elif len(a) == 2 and a[0] == 'sql': sql(a[1])
    else: sys.exit(__doc__)
