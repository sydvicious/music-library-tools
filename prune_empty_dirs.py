#!/usr/bin/env python3
"""Remove directories that are empty or contain only .DS_Store, depth-first.

  prune_empty_dirs.py [ROOT] [--dry-run]      (ROOT defaults to the configured library folder)

Bottom-up walk, so a folder whose only contents are empty folders is removed too.
Never removes ROOT itself or Music's "Automatically Add to ..." drop folders.
Writes every removed path to <ROOT>/../pruned-dirs-<timestamp>.txt.
"""
import os, sys, datetime

args = [a for a in sys.argv[1:] if not a.startswith('--')]
import mlt_config as C
ROOT = os.path.abspath(os.path.expanduser(args[0] if args else C.LIBRARY))
dry = '--dry-run' in sys.argv
KEEP = ('automatically add to',)
JUNK = {'.DS_Store'}

removed, removed_set = [], set()
for dp, dns, fns in os.walk(ROOT, topdown=False):
    if dp == ROOT or any(k in os.path.basename(dp).casefold() for k in KEEP): continue
    try: entries = os.listdir(dp)
    except OSError: continue
    entries = [e for e in entries if os.path.join(dp, e) not in removed_set]   # dry run: children counted as gone
    if all(e in JUNK for e in entries):
        if not dry:
            for e in entries:
                os.remove(os.path.join(dp, e))
            os.rmdir(dp)
        removed.append(dp); removed_set.add(dp)

stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
log = os.path.join(os.path.dirname(ROOT), f'pruned-dirs-{stamp}{"-dryrun" if dry else ""}.txt')
open(log, 'w', encoding='utf-8').write('\n'.join(removed) + ('\n' if removed else ''))
print(f'{"Would remove" if dry else "Removed"} {len(removed)} directories under {ROOT}\nLog: {log}')
