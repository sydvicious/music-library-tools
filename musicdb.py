#!/usr/bin/env python3
"""Read Music.app's library database (Library.musicdb) directly — no Music.app, no scripting.

  musicdb.py tracks [out.tsv]       one row per track (same columns as music-dump, plus 'visible')
  musicdb.py summary                counts: tracks, visible, ghosts, playlists
  musicdb.py playlists              playlist names and sizes
  musicdb.py watch [PID ...]         record whether these tracks are in the library (adds PIDs to the
                                    watch list); with no PIDs, check the list. Logs to
                                    <data>/snapshots/watch.log and notifies when one turns into a ghost.

The format is undocumented and reverse-engineered, so a macOS update may break it; when it does,
this fails loudly (which is itself a warning that Music changed under you).

File layout (as of Music 1.7, macOS 27):
  'hfma' header: magic, header length (u32 @4), file length (u32 @8), version string (@16),
  max encrypted length (u32 @0x54). The payload after the header is AES-128-ECB encrypted up to
  that length (rounded down to 16 bytes), and the whole payload is zlib-compressed.
Decoded content is a tree of tagged records: 4-byte tag, u32 header length, u32 total length.
  'itma' track: persistent ID (u64 LE @16), followed by 'boma' fields
  'boma' field: u32 total length @8, u32 subtype @12; strings have byte length @24 and data @36
      0x02 title  0x03 album  0x04 artist  0x05 genre  0x06 kind  0x0b location (UTF-8 URL)
      0x0c album artist  (other strings are UTF-16LE)
  'lpma' playlist: 'boma' 0xc8 name (UTF-16LE), 'boma' 0xda items, each an 'IPfa' with the
      track's persistent ID at +16. The first playlist ('####!####') is the master library.
Tracks that are not in the master playlist are 'ghosts': records Music keeps (for example,
deleted tracks it hasn't finished syncing with iCloud) but never shows.
"""
import os, sys, struct, subprocess, zlib, shutil, tempfile, urllib.parse, unicodedata, datetime

KEY = b'BHUILuilfghuila3'   # same scheme as the old iTunes .itl files
STRINGS = {0x02: 'title', 0x03: 'album', 0x04: 'artist', 0x05: 'genre', 0x06: 'kind', 0x0c: 'album_artist'}
OPENSSL = next((p for p in ('/opt/homebrew/bin/openssl', '/usr/local/bin/openssl', '/usr/bin/openssl') if os.path.exists(p)), 'openssl')

def default_path():
    for p in ('~/Music/Music/Music Library.musiclibrary', '~/Music/iTunes/iTunes Library.musiclibrary'):
        p = os.path.expanduser(p)
        if os.path.exists(os.path.join(p, 'Library.musicdb')): return os.path.join(p, 'Library.musicdb')
    sys.exit('Library.musicdb not found')

def decode(path=None):
    """Return (decoded bytes, file mtime). Copies the file first so a concurrent save can't tear it."""
    path = path or default_path()
    with tempfile.TemporaryDirectory() as td:
        for attempt in range(3):
            tmp = os.path.join(td, 'Library.musicdb'); shutil.copy2(path, tmp)
            d = open(tmp, 'rb').read()
            if d[:4] != b'hfma': raise ValueError('not a musicdb file (no hfma header)')
            hl, flen = struct.unpack_from('<II', d, 4)
            if flen == len(d): break
        else:
            raise ValueError('file length in header does not match file size (being written?)')
    crypt = struct.unpack_from('<I', d, 0x54)[0]
    pay = d[hl:]
    n = min(len(pay), crypt); n -= n % 16
    r = subprocess.run([OPENSSL, 'enc', '-d', '-aes-128-ecb', '-K', KEY.hex(), '-nopad'],
                       input=pay[:n], capture_output=True)
    if r.returncode != 0: raise RuntimeError('openssl failed: ' + r.stderr.decode()[:200])
    return zlib.decompress(r.stdout + pay[n:]), os.path.getmtime(path)

def _fields(b, start, end):
    j = start
    while j < end and b[j:j+4] == b'boma':
        t, st = struct.unpack_from('<II', b, j + 8)
        if t < 20: break
        yield j, t, st
        j += t

def parse(b):
    """Return (tracks: {pid: dict}, playlists: [(name, [pids])])."""
    tracks = {}
    i = b.find(b'ltma')
    if i < 0: raise ValueError("no 'ltma' track list")
    while True:
        i = b.find(b'itma', i)
        if i < 0: break
        hl, tl = struct.unpack_from('<II', b, i + 4)
        if tl < hl or i + tl > len(b): i += 4; continue
        pid = '%016X' % struct.unpack_from('<Q', b, i + 16)[0]
        t = {'pid': pid}
        for j, ln_, st in _fields(b, i + hl, i + tl):
            if st == 0x0b:
                ln = struct.unpack_from('<I', b, j + 24)[0]; t['url'] = b[j+36:j+36+ln].decode('utf-8', 'replace')
            elif st in STRINGS:
                ln = struct.unpack_from('<I', b, j + 24)[0]; t[STRINGS[st]] = b[j+36:j+36+ln].decode('utf-16-le', 'replace')
        tracks[pid] = t
        i += tl
    pls = []
    i = 0
    while True:
        i = b.find(b'lpma', i)
        if i < 0: break
        hl, tl = struct.unpack_from('<II', b, i + 4)
        if tl < hl or i + tl > len(b): i += 4; continue
        name, items = None, []
        for j, ln_, st in _fields(b, i + hl, i + tl):
            if st == 0xc8:
                ln = struct.unpack_from('<I', b, j + 24)[0]; name = b[j+36:j+36+ln].decode('utf-16-le', 'replace')
            elif st == 0xda and b[j+20:j+24] == b'IPfa':
                items.append('%016X' % struct.unpack_from('<Q', b, j + 36)[0])
        pls.append((name, items))
        i += tl
    if not tracks or not pls: raise ValueError('no tracks or playlists found — format changed?')
    master = set(pls[0][1])
    for pid, t in tracks.items():
        t['visible'] = pid in master
        u = t.get('url', '')
        t['path'] = unicodedata.normalize('NFC', urllib.parse.unquote(urllib.parse.urlparse(u).path)) if u.startswith('file://') else ''
    return tracks, pls

import re
LOCAL_KIND = re.compile(r'^(AAC audio|MPEG audio|Purchased AAC|Matched AAC|Protected AAC|Apple Lossless|WAV|AIFF)')

HEADER = ('path', 'size', 'modified', 'pid', 'location_type', 'cloud', 'drm', 'media_kind', 'kind',
          'artist', 'album', 'title', 'visible')

def rows(tracks):
    clean = lambda v: (v or '').replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    for t in tracks.values():
        kind = t.get('kind', '')
        if t['path']: ltype = 'file'
        elif t.get('url', '').startswith('http'): ltype = 'url'
        else: ltype = 'remote'
        # No local file: Apple Music items (incl. 'HLS media' downloads, music videos, booklets and
        # blank-kind catalog entries) stream; a track whose kind says it was your own file is lost.
        cloud = '0' if LOCAL_KIND.match(kind) else '1'
        yield (t['path'], '', '', t['pid'], ltype, cloud, '1' if kind.startswith('Protected') else '0', '',
               clean(kind), clean(t.get('artist')), clean(t.get('album')), clean(t.get('title')),
               '1' if t['visible'] else '0')

def watch(new_pids):
    import json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mlt_config as C
    state_f = os.path.join(C.SNAPS, 'watch.json'); log_f = os.path.join(C.SNAPS, 'watch.log')
    try: state = json.load(open(state_f))
    except (OSError, ValueError): state = {}
    b, mtime = decode(); tracks, _ = parse(b)
    for p in new_pids: state.setdefault(p.upper(), None)
    saved = datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
    lines, changed = [], []
    for p, prev in state.items():
        t = tracks.get(p)
        now = 'missing' if not t else ('visible' if t['visible'] else 'ghost')
        desc = f"{t.get('artist','')} — {t.get('title','')}" if t else p
        lines.append(f'{p} {now:8} {desc}')
        if prev is not None and prev != now: changed.append(f'{desc}: {prev} -> {now}')
        state[p] = now
    json.dump(state, open(state_f, 'w'), indent=1)
    with open(log_f, 'a') as f:
        f.write(f'--- {datetime.datetime.now():%Y-%m-%d %H:%M} (database saved {saved})\n' + '\n'.join(lines) + '\n')
        for c in changed: f.write('CHANGED ' + c + '\n')
    print('\n'.join(lines)); [print('CHANGED', c) for c in changed]
    if changed:
        msg = '; '.join(changed)[:200]
        subprocess.run(['osascript', '-e', f'display notification {json.dumps(msg)} with title "Music: watched tracks changed"'])

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'watch': watch(a[1:]); sys.exit(0)
    if not a or a[0] not in ('tracks', 'summary', 'playlists'): sys.exit(__doc__)
    b, mtime = decode()
    tracks, pls = parse(b)
    if a[0] == 'summary':
        vis = sum(t['visible'] for t in tracks.values())
        print(f"Library.musicdb saved {datetime.datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}: "
              f"{len(tracks)} track records, {vis} in the library, {len(tracks) - vis} ghosts, {len(pls)} playlists")
    elif a[0] == 'playlists':
        for name, items in pls: print(f'{len(items):6}  {name}')
    else:
        out = open(a[1], 'w', encoding='utf-8') if len(a) > 1 else sys.stdout
        out.write('\t'.join(HEADER) + '\n')
        for r in rows(tracks): out.write('\t'.join(r) + '\n')
