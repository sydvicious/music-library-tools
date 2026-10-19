#!/usr/bin/env python3
"""Copy album folders and append a year to the album title in every track's tags.

usage: retitle_albums.py OUT_DIR "SRC_DIR=New Album Title" ...
Only the album (\xa9alb) and sort-album (soal) atoms change; everything else
(artwork, gapless info, other tags, audio) is left byte-for-byte as is.
"""
import shutil, sys
from pathlib import Path
from mutagen.mp4 import MP4

out = Path(sys.argv[1]).expanduser()
for spec in sys.argv[2:]:
    src, title = spec.split("=", 1)
    src = Path(src).expanduser()
    dst = out / title.replace("/", "_")
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.m4a")):
        g = dst / f.name
        shutil.copy2(f, g)
        m = MP4(g)
        m["\xa9alb"] = [title]
        if "soal" in m:
            m["soal"] = [title]
        m.save()
        print(f"{dst.name}/{g.name}")
