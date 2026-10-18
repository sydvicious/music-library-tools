#!/usr/bin/env python3
"""Search one backup drive for missing tracks, and for files not in the library at all.

Run in Terminal (needs Full Disk Access for Time Machine), from any folder:
  recover_from_backup.py /Volumes/<Drive> [--dry-run] [--all] [--skip-orphans] [--rescan] [--dest=PATH]
  recover_from_backup.py /                       this Mac's live ~/Music (never Time Machine)
  recover_from_backup.py --tm                    this Mac's own Time Machine backups, wherever they live
  recover_from_backup.py /path/Users/<user>/Music   a Music folder directly

Working files (Still Missing.out, the library XML, find_missing_tracks.py,
results, and cached drive listings) live in the configured recovery_dir (mlt_config.py).

- Finds Users/<user>/Music on the drive: rsync/clone copies (up to two folders
  deep, e.g. Archive/Ravel), old HFS Backups.backupdb, or APFS Time Machine via
  tmutil (only if the drive really is a Time Machine destination).
- By default searches up to 6 Time Machine backups spread oldest..newest; --all for every one.
- Walks each Music folder ONCE and saves the listing under .listings/, so a dry run
  followed by a real run (or any rerun) doesn't re-walk a slow drive. --rescan forces a fresh walk.
- Pass 1: tracks in 'Still Missing.out', matched by artist/album/file path (exact size preferred).
  Copied to <dest>/<Artist folder>/<Album folder>/<file>, logged in <dest>/recovered.tsv,
  and removed from 'Still Missing.out'.
- Pass 2 (--skip-orphans to skip): media files in the iTunes/Music media folder that match
  nothing in the library export (by path, or by title + exact size). Copied to
  <dest>/Not in Library/<Artist folder>/<Album folder>/<file>; one copy per file even if
  in several backups (newest wins); files recovered earlier are skipped.
- <dest> is <data> on the primary Mac (config primary_mac), <recovery_dir>/From <Mac> elsewhere.
- Read-only on the backup drive.
"""
import os, sys, re, glob, shutil, subprocess, datetime, hashlib, plistlib, urllib.parse, collections, importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mlt_config as C
HERE = C.RECOVERY_DIR
USER_MUSIC = f'Users/{C.USER}/Music'
BIN = os.path.dirname(os.path.abspath(__file__))
FINDER = next(p for p in (os.path.join(BIN, 'find_missing_tracks.py'), os.path.join(HERE, 'find_missing_tracks.py')) if os.path.exists(p))
spec = importlib.util.spec_from_file_location('fmt', FINDER); fmt = importlib.util.module_from_spec(spec); spec.loader.exec_module(fmt)

args = sys.argv[1:]
vol = next((a for a in args if not a.startswith('--')), None)
if '--tm' in args: vol = vol or '/Time Machine'
if not vol: sys.exit(__doc__)
dry, every, rescan = '--dry-run' in args, '--all' in args, '--rescan' in args
vol = vol.rstrip('/')
MISSING = os.path.join(HERE, 'Still Missing.out')
LIBRARY = os.path.join(HERE, '2026-10-13 Music Library.xml')
LISTINGS = os.path.join(HERE, '.listings')
COMPUTER = subprocess.run(['scutil', '--get', 'ComputerName'], capture_output=True, text=True).stdout.strip() or os.uname().nodename
DEST = next((a.split('=', 1)[1] for a in args if a.startswith('--dest=')), None) or (
    C.DATA if COMPUTER == C.PRIMARY_MAC else os.path.join(HERE, f'From {COMPUTER}'))
DEST = os.path.expanduser(DEST)
name = os.path.basename(vol) or COMPUTER
if '--tm' in args: name = f'{COMPUTER} Time Machine'
if vol.endswith('/' + USER_MUSIC):
    _p = vol.split('/'); name = '-'.join(x for x in _p[2:-3] if x) or name
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
RESULT = os.path.join(HERE, f'Backup Results - {name} - {stamp}.out')
OUT2 = os.path.join(HERE, f'Not in Library - {name} - {stamp}.out')
TM = lambda b: '.backup' in b or 'Backups.backupdb' in b

# 1. Find the Music folders --------------------------------------------------
backups = []
if '--tm' in args:                                   # this Mac's own Time Machine, wherever it is (network or USB)
    r = subprocess.run(['tmutil', 'listbackups'], capture_output=True, text=True)
    backups = sorted(l.strip() for l in r.stdout.splitlines() if l.strip().startswith('/'))
    if not backups: sys.exit('tmutil listed no backups for this Mac (is the backup disk reachable? Full Disk Access?)')
elif vol == '':
    backups = ['']
elif vol.endswith('/' + USER_MUSIC) and os.path.isdir(vol):
    backups = [vol]
else:
    backups = sorted({os.path.realpath(m[:-len('/' + USER_MUSIC)])
                      for pat in (USER_MUSIC, '*/' + USER_MUSIC, '*/*/' + USER_MUSIC)
                      for m in glob.glob(f'{vol}/{pat}')})
    if not backups:
        backups = [b for b in sorted(glob.glob(f'{vol}/Backups.backupdb/*/[12]*')) if not b.endswith('Latest')]
    if not backups:
        # Only ask tmutil about a disk that really holds Time Machine backups: this Mac's configured
        # destination, or any disk with dated YYYY-MM-DD-HHMMSS.backup/.previous/.inprogress entries.
        # (tmutil -d on anything else silently lists THIS Mac's backups.)
        info = subprocess.run(['tmutil', 'destinationinfo'], capture_output=True, text=True).stdout
        mounts = {os.path.realpath(l.split(':', 1)[1].strip()) for l in info.splitlines() if l.strip().startswith('Mount Point')}
        try: dated = any(re.match(r'\d{4}-\d{2}-\d{2}-\d{6}\.(backup|previous|inprogress)$', e) for e in os.listdir(vol))
        except OSError: dated = False
        if os.path.realpath(vol) in mounts or dated:
            r = subprocess.run(['tmutil', 'listbackups', '-d', vol], capture_output=True, text=True)
            backups = sorted(l.strip() for l in r.stdout.splitlines() if l.strip().startswith('/'))
if not backups:
    sys.exit(f'No Users/<user>/Music copies, Backups.backupdb, or Time Machine backups found on {vol}.\n'
             'If the Music folder is somewhere else, pass its path directly (…/Users/<user>/Music).')

print(f'Recovering into: {DEST}')
if backups == ['']:
    print(f'Searching the live disk on {name} (not Time Machine)')
elif any(TM(b) for b in backups):
    print(f'{len(backups)} backup(s) on {name}: {os.path.basename(backups[0])} .. {os.path.basename(backups[-1])}')
    if not every and len(backups) > 6:
        n = len(backups); backups = [backups[round(i * (n - 1) / 5)] for i in range(6)]
    print('Searching:', *[os.path.basename(b) for b in backups], sep='\n  ')
else:
    print(f'Searching {len(backups)} cop(y/ies) on {name}:', *backups, sep='\n  ')

roots, seen = [], set()
for b in backups:
    if b.endswith('/' + USER_MUSIC): found = [b]
    else: found = glob.glob(f'{b}/*/{USER_MUSIC}') + glob.glob(f'{b}/{USER_MUSIC}')
    found = [f for f in found if os.path.realpath(f) not in seen]
    seen |= {os.path.realpath(f) for f in found}
    if not found: print(f'  (no Users/<user>/Music in {os.path.basename(b) or "/"})')
    roots += found
if not roots: sys.exit('No Music folders found.')

# 2. One walk per Music folder, cached ---------------------------------------
os.makedirs(LISTINGS, exist_ok=True)
def listing(root):
    cache = os.path.join(LISTINGS, hashlib.sha1(os.path.realpath(root).encode()).hexdigest()[:16] + '.txt')
    live = not os.path.realpath(root).startswith('/Volumes/')   # never cache a live disk (/, /System/Volumes/Data, ...)
    if not rescan and not live and os.path.exists(cache):
        lines = open(cache, encoding='utf-8').read().splitlines()
        if lines and lines[0] == root:
            print(f'  using saved listing for {root} ({len(lines) - 1} files)'); return lines[1:]
    print(f'  walking {root} ...', flush=True)
    rel = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith('.')]
        r = os.path.relpath(dp, root)
        for f in fns:
            if not f.startswith('.') and os.path.splitext(f)[1].lower() in fmt.AUDIO:
                rel.append(f if r == '.' else f'{r}/{f}')
    if not live:
        with open(cache, 'w', encoding='utf-8') as fh: fh.write(root + '\n' + '\n'.join(rel) + '\n')
    print(f'    {len(rel)} media files')
    return rel
files = []   # (root, relpath) in backup order (oldest first)
for root in roots:
    files += [(root, r) for r in listing(root)]

_sizes = {}
def size(p):
    if p not in _sizes:
        try: _sizes[p] = os.path.getsize(p)
        except OSError: _sizes[p] = None
    return _sizes[p]
strip_dup = lambda k: (k[0], k[1], re.sub(r' \d+$', '', k[2]))

print('Loading library export...', flush=True)
lib = plistlib.load(open(LIBRARY, 'rb'))
by_pid = {t.get('Persistent ID'): t for t in lib['Tracks'].values()}

# 3. Pass 1: still-missing tracks ---------------------------------------------
index = collections.defaultdict(list)
for root, r in files:
    parts = (root + '/' + r).split('/')
    k = fmt.key(parts[-3], parts[-2], parts[-1]); full = os.path.join(root, r)
    index[k].append(full)
    if strip_dup(k) != k: index[strip_dup(k)].append(full)

lines = open(MISSING, encoding='utf-8').read().splitlines()
print(f'\nPass 1: looking for {len(lines) - 1} still-missing tracks in {len(files)} files...')
rows, stats = [], collections.Counter()
for line in lines[1:]:
    c = line.split('\t')
    src_, artist, album, nm, pid, path = c[0], c[1], c[2], c[3], c[7], c[8]
    t = by_pid.get(pid, {})
    if path.startswith('/'):
        p = path.split('/'); keys, how = {fmt.key(p[-3], p[-2], p[-1])}, 'library path'
    else:
        keys, how = fmt.derived_keys(t), 'derived path'
    cands = sorted({h for k in keys for h in index.get(k, [])})
    want = t.get('Size')
    if src_ == 'broken-file':                      # library file is a stub: never accept another stub
        stub = os.path.getsize(path) if os.path.exists(path) else (want or 0)
        cands = [h for h in cands if (size(h) or 0) > 2 * stub]
        want = None
    exact = [h for h in cands if want and size(h) == want]
    if exact: status, cands = f'MATCH {how}+size', exact
    elif cands: status = f'MATCH {how}'
    else: status = 'NOT FOUND'
    stats[status] += 1
    rows.append('\t'.join([status, src_, artist, album, nm, pid, path, ' | '.join(cands)]))
rows.sort(key=lambda r: (r.startswith('NOT'), r.split('\t')[2:5]))
with open(RESULT, 'w', encoding='utf-8') as fh:
    fh.write('Status\tSource\tArtist\tAlbum\tName\tPersistent ID\tOriginal Path\tCandidates\n' + '\n'.join(rows) + '\n')
for k, v in sorted(stats.items()): print(f'{v:5d}  {k}')

found_pids, log = set(), []
for row in rows:
    c = row.split('\t')
    if not c[0].startswith('MATCH') or not c[7]: continue
    src = c[7].split(' | ')[-1]          # newest backup's copy
    parts = src.split('/')
    out = os.path.join(DEST, parts[-3], parts[-2], parts[-1])
    if os.path.exists(out) and os.path.getsize(out) != size(src):
        base, ext = os.path.splitext(out); out = f'{base} ({c[5]}){ext}'
    print(('WOULD COPY  ' if dry else 'COPY  ') + f'{c[2]} / {c[3]} / {c[4]}')
    if not dry:
        if not os.path.exists(out):
            os.makedirs(os.path.dirname(out), exist_ok=True); shutil.copy2(src, out)
        log.append('\t'.join([c[5], c[0], c[2], c[3], c[4], src, out]))
    found_pids.add(c[5])
if not dry and found_pids:
    os.makedirs(DEST, exist_ok=True)
    with open(os.path.join(DEST, 'recovered.tsv'), 'a', encoding='utf-8') as fh: fh.write('\n'.join(log) + '\n')
    keep = [lines[0]] + [l for l in lines[1:] if l.split('\t')[7] not in found_pids]
    open(MISSING, 'w', encoding='utf-8').write('\n'.join(keep) + '\n')
print(f'\n{name}: {"would recover" if dry else "recovered"} {len(found_pids)} track(s); '
      f'{len(lines) - 1 - (0 if dry else len(found_pids))} still missing.\nDetails: {RESULT}')

# 4. Pass 2: files not in the library at all -----------------------------------
if '--skip-orphans' in args: sys.exit(0)
print('\nPass 2: looking for files that are not in the library at all...')
def title(fn): return re.sub(r' \d+$', '', re.sub(r'^(\d+-)?\d+ ', '', fmt.clean(os.path.splitext(fn)[0])))
have_keys, have_title_size = set(), set()
for t in lib['Tracks'].values():
    ks = set()
    if t.get('Location', '').startswith('file://'):
        p_ = urllib.parse.unquote(urllib.parse.urlparse(t['Location']).path).split('/')
        if len(p_) >= 3: ks.add(fmt.key(p_[-3], p_[-2], p_[-1]))
        if t.get('Size'): have_title_size.add((title(p_[-1]), t['Size']))
    ks |= fmt.derived_keys(t)
    have_keys |= ks | {strip_dup(k) for k in ks}
    if t.get('Size'): have_title_size.add((fmt.clean(t.get('Name', '')), t['Size']))
SKIP = {'apple music', 'podcasts', 'mobile applications', 'ringtones', 'tones', 'books',
        'movies', 'tv shows', 'ipod games', 'downloads', 'automatically add to itunes',
        'automatically add to music', 'album artwork', 'previous itunes libraries'}
MEDIA_RE = re.compile(r'(^|/)(iTunes/iTunes (Media|Music)|Music/Media(\.localized)?)/', re.I)
orph, scanned = {}, 0
for root, r in files:
    d = os.path.dirname(r) + '/'
    if not MEDIA_RE.search(d): continue
    if any(fmt.clean(x) in SKIP or 'itunes lp' in x.lower() or x.lower().endswith('.itlp') for x in d.split('/') if x): continue
    scanned += 1
    parts = (root + '/' + r).split('/')
    k = fmt.key(parts[-3], parts[-2], parts[-1])
    if k in have_keys or strip_dup(k) in have_keys: continue
    full = os.path.join(root, r); sz = size(full)
    if sz is None or (title(parts[-1]), sz) in have_title_size: continue
    orph[(parts[-3], parts[-2], parts[-1])] = (full, sz)       # later (newer) backups overwrite
print(f'Checked {scanned} media files; {len(orph)} distinct file(s) not in the library.')
ODEST = os.path.join(DEST, 'Not in Library')
out_rows, copied, skipped, total = [], 0, 0, 0
for (ad, al, f), (src, sz) in sorted(orph.items()):
    out = os.path.join(ODEST, ad, al, f)
    if os.path.exists(out) or os.path.exists(os.path.join(DEST, ad, al, f)):
        skipped += 1; st = 'ALREADY RECOVERED'
    else:
        st = 'WOULD COPY' if dry else 'COPIED'; total += sz; copied += 1
        if not dry:
            os.makedirs(os.path.dirname(out), exist_ok=True); shutil.copy2(src, out)
    out_rows.append('\t'.join([st, ad, al, f, str(sz), src, out]))
with open(OUT2, 'w', encoding='utf-8') as fh:
    fh.write('Status\tArtist Folder\tAlbum Folder\tFile\tBytes\tSource\tDestination\n' + '\n'.join(out_rows) + '\n')
for (ad, al), n in sorted(collections.Counter((r.split('\t')[1], r.split('\t')[2]) for r in out_rows if not r.startswith('ALREADY')).items()):
    print(f'  {n:4d}  {ad} / {al}')
print(f'\n{name}: {"would copy" if dry else "copied"} {copied} file(s) not in the library '
      f'({total / 1e9:.2f} GB); {skipped} already recovered earlier.\nDetails: {OUT2}')
