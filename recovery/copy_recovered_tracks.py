#!/usr/bin/env python3
"""Copy files found by find_missing_tracks.py into an iCloud Drive folder.

Usage: copy_recovered_tracks.py CANDIDATES.out [--include-likely] [--include-possible] [--dry-run]

Copies the first candidate for each track into
  <recovery_dir>/<Artist>/<Album>/<filename>
and writes a manifest there (Recovered Manifest.tsv) mapping each
Persistent ID to the copied file, for relinking in Music later.
Never overwrites; skips files already present with the same size.
"""
import os, sys, shutil

args = sys.argv[1:]
src_file = next(a for a in args if not a.startswith('--'))
ok = {'MATCH'} | ({'LIKELY'} if '--include-likely' in args else set()) \
               | ({'LIKELY', 'POSSIBLE'} if '--include-possible' in args else set())
dry = '--dry-run' in args

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mlt_config as C
dest = C.RECOVERY_DIR
safe = lambda s: (s or 'Unknown').replace('/', '-').replace(':', '-').strip() or 'Unknown'

manifest, copied, skipped, failed = [], 0, 0, 0
for line in open(src_file, encoding='utf-8').read().splitlines()[1:]:
    c = line.split('\t')
    status, artist, album, name, pid, cands = c[0], c[2], c[3], c[4], c[5], c[7] if len(c) > 7 else ''
    if status.split()[0] not in ok or not cands: continue
    src = cands.split(' | ')[0]
    out = os.path.join(dest, safe(artist), safe(album), os.path.basename(src))
    try:
        if os.path.exists(out) and os.path.getsize(out) == os.path.getsize(src):
            skipped += 1
        elif os.path.exists(out):
            base, ext = os.path.splitext(out); out = f'{base} ({pid}){ext}'
        if not os.path.exists(out):
            print(('WOULD COPY ' if dry else 'COPY ') + src)
            if not dry:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copy2(src, out)
            copied += 1
        manifest.append('\t'.join([pid, status, artist, album, name, src, out]))
    except OSError as e:
        print(f'FAILED {src}: {e}', file=sys.stderr); failed += 1

if not dry and manifest:
    with open(os.path.join(dest, 'Recovered Manifest.tsv'), 'a', encoding='utf-8') as fh:
        fh.write('\n'.join(manifest) + '\n')
print(f'{"Would copy" if dry else "Copied"} {copied}, already there {skipped}, failed {failed}')
