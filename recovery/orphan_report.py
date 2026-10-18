#!/usr/bin/env python3
"""Find orphans: media files in iTunes Media that no library entry points to.

Needs:
  - audio-hashes.sqlite up to date:  ./audio_hash.py add library ~/Music/iTunes/"iTunes Media"
  - a list of library file locations, one POSIX path per line (default /tmp/libpaths.txt,
    made by:  osascript -l JavaScript libpaths.js)

Each orphan is classified:
  dup-in-library   same audio as a file the library uses  -> safe to trash
  dup-orphans-only same audio as other orphans only        -> keep one, add it back
  true-orphan      audio not found anywhere in the library -> add back
  stub             under 300 KB (likely broken)            -> review

Usage: ./orphan_report.py [--paths FILE] [--copy]
  --copy  copies one file per add-back audio into ~/Music/Recovered/Orphans/<relative path>
Writes "<today> Orphans.tsv" and "<today> Orphans.txt" next to this script.
"""
import sqlite3, sys, os, shutil, datetime, unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mlt_config as C
DB = C.DB
MEDIA = C.LIBRARY
DEST = os.path.join(C.DATA, "Orphans")
HERE = C.REPORTS
STUB = 300_000
args = sys.argv[1:]
PATHS = args[args.index("--paths") + 1] if "--paths" in args else "/tmp/libpaths.txt"
COPY = "--copy" in args

nfc = lambda s: unicodedata.normalize("NFC", s)
prefix = MEDIA.rstrip("/") + "/"
inlib = set()
for line in open(PATHS, encoding="utf-8"):
    p = nfc(line.rstrip("\n"))
    if p.startswith(prefix):
        inlib.add(p[len(prefix):])
if len(inlib) < 1000:
    sys.exit(f"Only {len(inlib)} library paths under iTunes Media in {PATHS}; is the list complete?")

con = sqlite3.connect(DB)
rows = con.execute("SELECT rel, size, audio_md5, error FROM files WHERE source='library'").fetchall()
lib_md5 = defaultdict(list)
orph = []
for rel, size, md5, err in rows:
    r = nfc(rel)
    if r in inlib:
        if md5: lib_md5[md5].append(r)
    else:
        orph.append((r, size, md5, err))
orph_md5 = defaultdict(list)
for r, s, m, e in orph:
    if m: orph_md5[m].append(r)

# Same album folder + file name as a library file (e.g. moved to Compilations, or an
# iTunes Match re-encode replaced the original): different bytes, same recording.
def akey(r):
    parts = r.split("/")
    return (parts[-2].lower(), parts[-1].lower()) if len(parts) >= 2 else ("", r.lower())
lib_akey = {akey(r): r for r in inlib}

out, counts = [], defaultdict(int)
seen_addback = set()
for r, s, m, e in sorted(orph, key=lambda x: x[0].lower()):
    top = r.split("/")[0]
    if ".ite/" in r or ".itlp/" in r or "iTunes LP (" in r: status, ref = "itunes-extras", ""
    elif top in ("Movies", "TV Shows", "Home Videos"): status, ref = "tv-app", ""
    elif s < STUB:                     status, ref = "stub", ""
    elif m and m in lib_md5:           status, ref = "dup-in-library", lib_md5[m][0]
    elif akey(r) in lib_akey:          status, ref = "same-name-in-library", lib_akey[akey(r)]
    elif m and len(orph_md5[m]) > 1:   status, ref = "dup-orphans-only", ""
    elif not m:                        status, ref = "no-audio-hash", e or ""
    else:                              status, ref = "true-orphan", ""
    addback = status in ("true-orphan", "dup-orphans-only") and m not in seen_addback
    if addback: seen_addback.add(m)
    counts[status] += 1
    out.append((status, "yes" if addback else "", r, s, m or "", ref))

today = datetime.date.today().isoformat()
with open(os.path.join(HERE, f"{today} Orphans.tsv"), "w") as f:
    f.write("status\tadd_back\tpath\tbytes\taudio_md5\tlibrary_copy_or_error\n")
    for row in out: f.write("\t".join(map(str, row)) + "\n")
with open(os.path.join(HERE, f"{today} Orphans.txt"), "w") as f:
    f.write(f"Orphan files in iTunes Media (on disk, not referenced by any library entry) — {len(out)} files\n")
    f.write(f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. Library entries checked: {len(inlib)}\n")
    for k in ("true-orphan", "dup-orphans-only", "same-name-in-library", "dup-in-library", "stub", "tv-app", "itunes-extras", "no-audio-hash"):
        f.write(f"  {k:22} {counts[k]}\n")
    f.write(f"  files to add back  {len(seen_addback)}\n\n")
    for k in ("true-orphan", "dup-orphans-only", "stub", "no-audio-hash", "same-name-in-library", "dup-in-library", "tv-app", "itunes-extras"):
        sel = [o for o in out if o[0] == k]
        if not sel: continue
        f.write(f"== {k} ({len(sel)}) ==\n")
        for st, ab, r, s, m, ref in sel:
            f.write(f"  {'+' if ab else ' '} {r}  ({s/1e6:.1f} MB)" + (f"\n      = {ref}" if ref else "") + "\n")
        f.write("\n")

copied = 0
if COPY:
    for st, ab, r, s, m, ref in out:
        if not ab: continue
        dst = os.path.join(DEST, r)
        if os.path.exists(dst) and os.path.getsize(dst) == s: continue
        src = os.path.join(MEDIA, r)
        if not os.path.exists(src): print("gone:", r); continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst); copied += 1
print(dict(counts), "add back:", len(seen_addback), "copied:", copied)
