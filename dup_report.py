#!/usr/bin/env python3
"""Write the duplicate-audio report for the Music library from audio-hashes.sqlite.

Run `./audio_hash.py lite library <library folder>` first so the index is current.
Usage: ./dup_report.py [--min-bytes N]   (default 300000; smaller files are treated as stubs)
Writes "<today> Duplicate Audio.txt" and ".tsv" to the reports folder (mlt_config.py).
"""
import sqlite3, sys, os, datetime
from collections import defaultdict

import mlt_config as C
DB = C.DB
HERE = C.REPORTS
MIN = int(sys.argv[sys.argv.index("--min-bytes") + 1]) if "--min-bytes" in sys.argv else 300000

con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT audio_md5, rel, size FROM files WHERE source='library' AND audio_md5 IS NOT NULL AND size>=?",
    (MIN,)).fetchall()
groups = defaultdict(list)
for md5, rel, size in rows:
    groups[md5].append((rel, size))
sets = sorted(((m, sorted(v)) for m, v in groups.items() if len(v) > 1), key=lambda x: x[1][0][0].lower())

redundant = sum(len(v) - 1 for _, v in sets)
waste = sum(sum(s for _, s in v) - max(s for _, s in v) for _, v in sets)
same_album = sum(1 for _, v in sets if len({os.path.dirname(r) for r, _ in v}) < len(v))

today = datetime.date.today().isoformat()
txt = os.path.join(HERE, f"{today} Duplicate Audio.txt")
tsv = os.path.join(HERE, f"{today} Duplicate Audio.tsv")
with open(txt, "w") as f:
    f.write(f"Duplicate audio in the Music library folder (iTunes Media) — {len(sets)} sets, "
            f"{redundant} redundant files, {waste/1e9:.2f} GB\n")
    f.write(f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. Byte-identical audio (tags/artwork ignored); "
            f"files under {MIN//1000} KB excluded as stubs.\n")
    f.write(f"Sets with 2+ copies in the same folder (album): {same_album}. "
            "Paths relative to the library folder.\n\n")
    for m, v in sets:
        f.write(f"{len(v)} copies  [{m[:12]}]\n")
        for r, s in v:
            f.write(f"    {r}    ({s/1e6:.1f} MB)\n")
        f.write("\n")
with open(tsv, "w") as f:
    f.write("audio_md5\tcopies\tpath\tbytes\n")
    for m, v in sets:
        for r, s in v:
            f.write(f"{m}\t{len(v)}\t{r}\t{s}\n")
print(f"{len(sets)} sets, {redundant} redundant, {waste/1e9:.2f} GB, same-folder sets {same_album}\n{txt}")
