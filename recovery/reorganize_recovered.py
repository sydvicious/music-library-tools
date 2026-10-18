#!/usr/bin/env python3
"""Sort ~/Music/Recovered into Missing/, Renamed/ and Audiobooks/ using audio-hashes.sqlite.

  reorganize_recovered.py [--dry-run]

Missing/    files whose audio isn't in the library: missing-track copies, gaps in albums
            you still have, and albums not in the library at all
Renamed/    identical audio already in the library, or the same album+title in another encoding
Audiobooks/ anything that came from an Audiobooks folder

Keeps <Artist folder>/<Album folder>/<file>. Never overwrites (adds ' (n)' on a clash).
Updates paths in audio-hashes.sqlite and recovered.tsv, and appends every move to moves.tsv
(old<TAB>new) so it can be undone. Run `audio_hash.py add library ...` first so the library
side of the comparison is current.
"""
import os, re, sys, sqlite3, shutil, collections, unicodedata, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mlt_config as C
ROOT = C.DATA
DB = os.path.join(ROOT, 'audio-hashes.sqlite')
TOP = {'Missing', 'Renamed', 'Audiobooks'}
dry = '--dry-run' in sys.argv

clean = lambda s: re.sub(r'[\W_]+', ' ', unicodedata.normalize('NFC', s).casefold()).strip()
title = lambda f: re.sub(r' \d+$', '', clean(re.sub(r'^\d+(-\d+)? ', '', os.path.splitext(f)[0])))

db = sqlite3.connect(DB)
lib_md5 = {m for (m,) in db.execute("select audio_md5 from files where source='library' and audio_md5 is not null")}
lib = collections.defaultdict(set)
for (rel,) in db.execute("select rel from files where source='library'"):
    p = rel.split('/')
    if len(p) >= 3: lib[clean(p[-2])].add(title(p[-1]))

plan, counts = [], collections.Counter()
for path, rel, md5 in db.execute("select path, rel, audio_md5 from files where source='recovered'").fetchall():
    if rel.split('/')[0] in TOP: continue                      # already sorted
    p = rel.split('/')
    sub = '/'.join(p[1:]) if p[0] == 'Not in Library' else rel  # drop the 'Not in Library/' level
    al = clean(p[-2]) if len(p) >= 3 else ''
    if rel.startswith('Not in Library/Audiobooks/'):
        dest = 'Audiobooks'; sub = '/'.join(p[2:])
    elif md5 and md5 in lib_md5:
        dest = 'Renamed'
    elif p[0] == 'Not in Library' and al and al != 'unknown album' and title(p[-1]) in lib.get(al, ()):
        dest = 'Renamed'
    else:
        dest = 'Missing'
    counts[dest] += 1
    plan.append((path, rel, os.path.join(dest, sub)))

for k in ('Missing', 'Renamed', 'Audiobooks'): print(f'{counts[k]:6d}  -> {k}/')
if dry:
    for path, rel, new in plan[:5]: print(f'  e.g. {rel}\n    -> {new}')
    sys.exit(0)

log = open(os.path.join(ROOT, 'moves.tsv'), 'a', encoding='utf-8')
remap, moved = {}, 0
for path, rel, new in plan:
    if not os.path.exists(path): continue
    dst = os.path.join(ROOT, new)
    base, ext = os.path.splitext(dst); n = 1
    while os.path.exists(dst): dst = f'{base} ({n}){ext}'; n += 1
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(path, dst)
    db.execute('update files set path=?, rel=? where path=?', (dst, os.path.relpath(dst, ROOT), path))
    log.write(f'{path}\t{dst}\n'); remap[path] = dst; moved += 1
db.commit(); log.close()

tsv = os.path.join(ROOT, 'recovered.tsv')
if os.path.exists(tsv):
    lines = open(tsv, encoding='utf-8').read().splitlines()
    out = []
    for l in lines:
        c = l.split('\t')
        if len(c) >= 7 and c[6] in remap: c[6] = remap[c[6]]
        out.append('\t'.join(c))
    open(tsv, 'w', encoding='utf-8').write('\n'.join(out) + '\n')

# remove now-empty folders (but never ROOT or the three targets)
for dp, dns, fns in os.walk(ROOT, topdown=False):
    if dp != ROOT and os.path.relpath(dp, ROOT) not in TOP and not os.listdir(dp):
        os.rmdir(dp)
print(f'Moved {moved} files. Log: {os.path.join(ROOT, "moves.tsv")}')
