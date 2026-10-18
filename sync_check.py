#!/usr/bin/env python3
"""Compare three sources of truth for a music folder with one sorted merge.

  sync_check.py snapshot-disk  <folder>  [out.tsv]   walk the folder
  sync_check.py snapshot-db    <source>  [out.tsv]   export the audio-hash database rows for a source
  sync_check.py snapshot-music-xml <Library.xml> [out.tsv]   Music's exported library XML
  sync_check.py merge <folder> disk.tsv db.tsv [music.tsv]
  sync_check.py check <folder> <source> [music.tsv]  snapshot disk + db, then merge
  sync_check.py paths                                print the configured paths as JSON
  sync_check.py library-check (--export | --xml Library.xml) [--notify]
        the whole check for the Music library: lite hash, Music XML (exported by GUI scripting
        with --export), disk + db snapshots, merge, summary (+ macOS notification), log in
        <data>/snapshots/library-check.log

Every snapshot is a TSV whose first column is the path (Unicode NFC), sorted by path
(UTF-8 byte order, which is also what music-dump produces). The merge walks the sorted
files together (heapq.merge), so each path is seen once with a presence mask:

  disk db music   class
   D    B   M     ok | changed (size/date differs from db -> needs hashing)
   D    B   -     orphan          (hashed, but no Music track points to it)
   D    -   M     unhashed        (track's file isn't in the database yet)
   D    -   -     orphan-unhashed
   -    B   M     missing         (Music and database both expect it; file is gone)
   -    B   -     stale-row       (database row for a file that is gone)
   -    -   M     missing         (Music points to a file that doesn't exist)
  A missing 'HLS media' item (an Apple Music download whose cache file is gone) is 'cache-gone'.
  Music paths outside <folder> are classed 'outside'; Music items with no file at all are
  'no-file' (remote/cloud items are counted, not listed). Without music.tsv, the music
  column is ignored and only disk vs db is checked.

Writes "<date> Sync Check.tsv" (every non-ok path) to the reports folder and prints a summary.
Paths (library, data, reports) come from mlt_config.py.
"""
import os, sys, sqlite3, heapq, datetime, unicodedata, csv, subprocess, json
import mlt_config as C
from collections import Counter

EXT = {'.m4a', '.mp3', '.m4p', '.m4v', '.mp4', '.wav', '.aif', '.aiff', '.aac', '.mov', '.caf', '.flac', '.m4b'}
DB = C.DB
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPS = C.SNAPS
REPORTS = C.REPORTS
nfc = lambda s: unicodedata.normalize('NFC', s)
# APFS is case-insensitive and Music keeps whatever case a path had when the track was added,
# so paths are compared (and sorted) by a case-folded NFC key.
pkey = lambda s: nfc(s).casefold().encode('utf-8')
stamp = lambda: datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

def write_sorted(rows, header, out):
    rows.sort(key=lambda r: pkey(r[0]))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\t'.join(header) + '\n')
        for r in rows: f.write('\t'.join(str(x) for x in r) + '\n')
    print(f'{len(rows)} rows -> {out}', file=sys.stderr)
    return out

def snapshot_disk(folder, out=None):
    folder = os.path.abspath(os.path.expanduser(folder))
    rows = []
    for dp, dns, fns in os.walk(folder):
        dns[:] = [d for d in dns if not d.startswith('.')]
        for f in fns:
            if f.startswith('.') or os.path.splitext(f)[1].lower() not in EXT: continue
            p = os.path.join(dp, f)
            try: st = os.stat(p)
            except OSError: continue
            rows.append((nfc(p), st.st_size, int(st.st_mtime)))
    return write_sorted(rows, ('path', 'size', 'mtime'), out or os.path.join(SNAPS, f'disk-{stamp()}.tsv'))

def snapshot_db(source, out=None):
    db = sqlite3.connect(DB)
    rows = [(nfc(p), s, int(m or 0), h or '', (e or '').replace('\t', ' '))
            for p, s, m, h, e in db.execute('select path, size, mtime, audio_md5, error from files where source=?', (source,))]
    return write_sorted(rows, ('path', 'size', 'mtime', 'audio_md5', 'error'), out or os.path.join(SNAPS, f'db-{source}-{stamp()}.tsv'))

def snapshot_music_xml(xml, out=None):
    """Music's File > Library > Export Library... XML -> the same TSV columns music-dump writes."""
    import plistlib, urllib.parse
    with open(os.path.expanduser(xml), 'rb') as f: pl = plistlib.load(f)
    clean = lambda v: ('' if v is None else str(v)).replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    rows = []
    for t in pl.get('Tracks', {}).values():
        loc = t.get('Location', '')
        path = nfc(urllib.parse.unquote(urllib.parse.urlparse(loc).path)) if loc.startswith('file://') else ''
        ttype = t.get('Track Type', '')
        ltype = {'File': 'file', 'Remote': 'remote', 'URL': 'url'}.get(ttype, ttype.lower())
        mod = t.get('Date Modified'); mod = int(mod.timestamp()) if mod else ''
        rows.append((path, t.get('Size', ''), mod, t.get('Persistent ID', ''), ltype,
                     '1' if t.get('Apple Music') or t.get('Matched') else '0', '1' if t.get('Protected') else '0',
                     '', clean(t.get('Kind')), clean(t.get('Artist')), clean(t.get('Album')), clean(t.get('Name'))))
    header = ('path', 'size', 'modified', 'pid', 'location_type', 'cloud', 'drm', 'media_kind', 'kind', 'artist', 'album', 'title')
    return write_sorted(rows, header, out or os.path.join(SNAPS, f'music-xml-{stamp()}.tsv'))

def read_tsv(path, tag):
    """Yield (key, tag, row) sorted by the case-folded path key; rows with no path come first.
    Snapshots are written in this order already; anything else (e.g. music-dump) is sorted here."""
    with open(path, encoding='utf-8', newline='') as f:
        r = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        header = next(r)
        rows = [dict(zip(header, row)) for row in r if row]
    keyed = [(pkey(d['path']) if d['path'] else None, d) for d in rows]
    for k, d in keyed:
        if k is None: yield (None, tag, d)          # music items with no file
    for k, d in sorted(((k, d) for k, d in keyed if k is not None), key=lambda x: x[0]):
        yield (k, tag, d)

def merge(folder, disk_tsv, db_tsv, music_tsv=None):
    folder = os.path.abspath(os.path.expanduser(folder)); prefix = folder + '/'
    streams = [read_tsv(disk_tsv, 'disk'), read_tsv(db_tsv, 'db')]
    nofile = Counter(); nofile_rows = []
    def music_iter():
        for k, t, d in read_tsv(music_tsv, 'music'):
            if k is None:
                kind = 'remote' if d.get('location_type') == 'remote' else 'no-file'
                nofile[kind] += 1
                if kind == 'no-file': nofile_rows.append(d)
                continue
            yield (k, t, d)
    if music_tsv: streams.append(music_iter())

    counts, report = Counter(), []
    cur_key, group = None, {}
    def flush(key, g):
        if key is None: return
        d, b, m = g.get('disk'), g.get('db'), g.get('music')
        path = (d or b or m)['path']
        if m and not pkey(path).startswith(pkey(prefix)):
            cls = 'outside' if d or os.path.exists(path) else 'missing'
            counts[cls] += 1; report.append((cls, path, 'music', m.get('pid', ''), describe(m))); return
        if music_tsv:
            if d and b and m:   cls = 'ok' if same(d, b) else 'changed'
            elif d and b:       cls = 'orphan'
            elif d and m:       cls = 'unhashed'
            elif d:             cls = 'orphan-unhashed'
            elif b and m:       cls = 'missing'
            elif b:             cls = 'stale-row'
            elif m.get('kind') == 'HLS media': cls = 'cache-gone'   # Apple Music download whose cache file is gone
            else:               cls = 'missing'
        else:
            if d and b:         cls = 'ok' if same(d, b) else 'changed'
            elif d:             cls = 'unhashed'
            else:               cls = 'stale-row'
        counts[cls] += 1
        if cls != 'ok':
            detail = ''
            if cls == 'changed': detail = f"size {b['size']}->{d['size']} mtime {b['mtime']}->{d['mtime']}"
            elif b and b.get('error'): detail = b['error']
            report.append((cls, path, ''.join(x for x, v in (('D', d), ('B', b), ('M', m)) if v),
                           m.get('pid', '') if m else '', describe(m) if m else detail))
    for key, tag, row in heapq.merge(*streams, key=lambda x: x[0]):
        if key != cur_key:
            flush(cur_key, group); cur_key, group = key, {}
        group[tag] = row
    flush(cur_key, group)
    for d in nofile_rows:
        counts['no-file'] += 1; report.append(('no-file', '', 'M', d.get('pid', ''), describe(d)))

    out = os.path.join(REPORTS, f'{datetime.date.today().isoformat()} Sync Check.tsv')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('class\tpath\tpresent\tpid\tdetail\n')
        for r in report: f.write('\t'.join(r) + '\n')
    inputs = f'disk={os.path.basename(disk_tsv)} db={os.path.basename(db_tsv)}' + \
             (f' music={os.path.basename(music_tsv)}' if music_tsv else ' (no music snapshot)')
    print(inputs)
    order = ['ok', 'changed', 'unhashed', 'orphan', 'orphan-unhashed', 'missing', 'cache-gone', 'stale-row', 'outside', 'no-file']
    print('  ' + '  '.join(f'{k} {counts[k]}' for k in order if counts[k]))
    if nofile['remote']: print(f'  (plus {nofile["remote"]} remote/cloud items with no local file)')
    print(f'Report: {out}')
    return counts

LIBRARY = C.LIBRARY
EXPORT_XML = os.path.join(SNAPS, 'Library-export.xml')

def notify(title, msg):
    subprocess.run(['osascript', '-e', f'display notification {json.dumps(msg)} with title {json.dumps(title)}'])

def library_check(xml=None, export=False, do_notify=False):
    """One command: hash new/changed files, get Music's view (exported XML), snapshot disk + db, merge."""
    log = []
    def say(m): print(m, flush=True); log.append(m)
    t0 = datetime.datetime.now()
    r = subprocess.run([os.path.join(HERE, 'audio_hash.py'), 'lite', 'library', LIBRARY], capture_output=True, text=True)
    say('lite: ' + (r.stdout.strip().splitlines() or ['(no output)'])[-1])
    if export:
        r = subprocess.run(['osascript', '-l', 'JavaScript', os.path.join(HERE, 'export_library.js'), EXPORT_XML],
                           capture_output=True, text=True)
        if r.returncode != 0:
            msg = 'Music export failed: ' + (r.stderr.strip() or r.stdout.strip())[:200]
            say(msg)
            if do_notify: notify('Music library check FAILED', msg)
            sys.exit(1)
        xml = EXPORT_XML
    if not xml: sys.exit('library-check needs --xml PATH or --export')
    xml_age = (t0.timestamp() - os.path.getmtime(os.path.expanduser(xml))) / 60
    say(f'Music XML: {xml} ({xml_age:.0f} min old)')
    counts = merge(LIBRARY, snapshot_disk(LIBRARY), snapshot_db('library'), snapshot_music_xml(xml))
    problems = {k: v for k, v in counts.items() if k not in ('ok', 'cache-gone', 'no-file')}
    summary = ', '.join(f'{k} {v}' for k, v in sorted(problems.items())) or 'all in sync'
    say(f'Result: {summary} (ok {counts["ok"]}, Apple Music cache gone {counts["cache-gone"]})')
    with open(os.path.join(SNAPS, 'library-check.log'), 'a') as f:
        f.write(f'--- {t0:%Y-%m-%d %H:%M:%S}\n' + '\n'.join(log) + '\n')
    removed = cleanup()
    if removed: say(f'cleanup: removed {removed} snapshot/report files older than {KEEP_DAYS} days')
    if do_notify: notify('Music library check', summary)
    return problems

KEEP_DAYS = 14
def cleanup(days=KEEP_DAYS):
    """Delete snapshot TSVs and dated Sync Check reports older than `days` days."""
    import glob, time
    cutoff = time.time() - days * 86400
    pats = [os.path.join(SNAPS, x) for x in ('disk-*.tsv', 'db-*.tsv', 'music-xml-*.tsv', 'music-*.tsv')] + \
           [os.path.join(REPORTS, '????-??-?? Sync Check.tsv')]
    n = 0
    for pat in pats:
        for f in glob.glob(pat):
            try:
                if os.path.getmtime(f) < cutoff: os.remove(f); n += 1
            except OSError: pass
    return n

def same(d, b):
    return d['size'] == b['size'] and abs(int(d['mtime']) - int(b['mtime'])) <= 1

def describe(m):
    return ' — '.join(x for x in (m.get('artist', ''), m.get('album', ''), m.get('title', '')) if x) + \
           (f" [{m['kind']}]" if m.get('kind') else '')

if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == 'snapshot-disk': snapshot_disk(a[1], a[2] if len(a) > 2 else None)
    elif len(a) >= 2 and a[0] == 'snapshot-music-xml': snapshot_music_xml(a[1], a[2] if len(a) > 2 else None)
    elif len(a) >= 2 and a[0] == 'snapshot-db': snapshot_db(a[1], a[2] if len(a) > 2 else None)
    elif len(a) in (4, 5) and a[0] == 'merge': merge(a[1], a[2], a[3], a[4] if len(a) > 4 else None)
    elif a and a[0] == 'paths':
        print(json.dumps({'repo': C.REPO, 'library': C.LIBRARY, 'data': C.DATA, 'reports': C.REPORTS, 'snaps': C.SNAPS, 'db': C.DB}))
    elif a and a[0] == 'library-check':
        xml = a[a.index('--xml') + 1] if '--xml' in a else None
        library_check(xml, export='--export' in a, do_notify='--notify' in a)
    elif len(a) in (3, 4) and a[0] == 'check':
        merge(a[1], snapshot_disk(a[1]), snapshot_db(a[2]), a[3] if len(a) > 3 else None)
    else: sys.exit(__doc__)
