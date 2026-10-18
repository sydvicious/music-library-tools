#!/usr/bin/env python3
"""Use Spotlight to find audio files whose names match missing tracks.

Usage: spotlight_search.py MISSING.out OUTPUT.out [--only TEXT ...]

For each missing track, asks Spotlight for audio files whose name or
title contains the track name. Results are for review: copies stashed
outside iTunes rarely share its folder layout, so nothing here is
treated as a confirmed match. Read-only.

--only TEXT  limit to tracks whose artist/album/name contains TEXT
             (e.g. --only Rice --only Polk). Repeatable.
"""
import os, sys, re, subprocess, socket, unicodedata

AUDIO = {'.m4a', '.mp3', '.m4p', '.wav', '.aif', '.aiff', '.aac', '.caf', '.flac', '.m4b'}
SKIP = ('/Recovered Music/', '/.Trash/', '/Library/Caches/')
norm = lambda s: re.sub(r'[\W_]+', ' ', unicodedata.normalize('NFC', s or '').casefold()).strip()

args = sys.argv[1:]
only = [args[i + 1].casefold() for i, a in enumerate(args) if a == '--only']
pos = [a for i, a in enumerate(args) if not a.startswith('--') and (i == 0 or args[i - 1] != '--only')]
missing_f, out_f = pos[0], pos[1]
host = socket.gethostname()

def spotlight(name):
    q = name.replace('\\', '\\\\').replace('"', '\\"')
    query = f'(kMDItemFSName == "*{q}*"cd || kMDItemTitle == "*{q}*"cd) && kMDItemContentTypeTree == "public.audio"'
    r = subprocess.run(['mdfind', query], capture_output=True, text=True)
    return [p for p in r.stdout.splitlines()
            if os.path.splitext(p)[1].lower() in AUDIO and not any(s in p for s in SKIP)]

rows, found = [], 0
for line in open(missing_f, encoding='utf-8').read().splitlines()[1:]:
    c = line.split('\t')
    artist, album, name, pid = c[1], c[2], c[3], c[7]
    if only and not any(o in f'{artist} {album} {name}'.casefold() for o in only): continue
    if len(norm(name)) < 4 or re.fullmatch(r'track \d+', norm(name)):  # too generic to search
        rows.append('\t'.join(['SKIPPED generic name', host, artist, album, name, pid, ''])); continue
    hits = spotlight(name)
    # Rank: hits whose folder path mentions the album or artist first
    al, ar = norm(album), norm(artist)
    def score(p):
        d = norm(' '.join(p.split('/')[-3:-1]))  # artist + album folder names only
        return -(2 * bool(al and al in d) + bool(ar and ar in d))
    hits.sort(key=score)
    status = 'NOT FOUND' if not hits else ('CANDIDATE album or artist folder' if score(hits[0]) else 'CANDIDATE name only')
    found += bool(hits)
    rows.append('\t'.join([status, host, artist, album, name, pid, ' | '.join(hits[:10])]))
    print(f'{status:34} {name[:60]}', file=sys.stderr)

rows.sort(key=lambda r: (r.startswith(('NOT', 'SKIP')), not r.startswith('CANDIDATE album'), r.split('\t')[2:5]))
with open(out_f, 'w', encoding='utf-8') as fh:
    fh.write('Status\tMachine\tArtist\tAlbum\tName\tPersistent ID\tCandidates\n' + '\n'.join(rows) + '\n')
print(f'{found} of {len(rows)} tracks have candidates on {host}', file=sys.stderr)
