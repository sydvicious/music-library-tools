#!/usr/bin/env python3
"""Search backup folders for tracks listed in a Missing Tracks .out file.

Usage: find_missing_tracks.py MISSING.out LIBRARY.xml OUTPUT.out ROOT [ROOT ...]

A candidate only counts when its path under the library matches:
  <artist folder>/<album folder>/<file name>
compared case-, Unicode- and punctuation-insensitively, ignoring the
extension. Tracks with a Location use that path; cloud-only tracks use
the path iTunes would have given them (album artist/album/[d-]NN name).
Read-only: reports candidates, copies nothing.
"""
import os, sys, re, plistlib, unicodedata, collections

AUDIO = {'.m4a', '.mp3', '.m4p', '.m4v', '.mp4', '.wav', '.aif', '.aiff', '.aac', '.mov', '.caf', '.flac'}

def clean(s):  # what survives iTunes' filename sanitising, normalised
    s = unicodedata.normalize('NFC', s or '').casefold()
    return re.sub(r'[\W_]+', ' ', s).strip()

def key(artist_dir, album_dir, filename):
    return (clean(artist_dir), clean(album_dir), clean(os.path.splitext(filename)[0]))

def derived_keys(t):
    """Paths iTunes would have used for this track's metadata."""
    artists = ['Compilations'] if t.get('Compilation') else []
    artists += [a for a in (t.get('Album Artist'), t.get('Artist')) if a] or ['Unknown Artist']
    album = t.get('Album') or 'Unknown Album'
    name, tn, dn = t.get('Name', ''), t.get('Track Number'), t.get('Disc Number')
    files = [name]
    if tn:
        files += [f'{tn:02d} {name}']
        if dn: files += [f'{dn}-{tn:02d} {name}']
    return {key(a, album, f + ".ext") for a in artists for f in files}

if __name__ == '__main__':
    missing_f, library_f, out_f, roots = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    lib = plistlib.load(open(library_f, 'rb'))
    by_pid = {t.get('Persistent ID'): t for t in lib['Tracks'].values()}

    print('Indexing', *roots, file=sys.stderr)
    index, n = collections.defaultdict(list), 0
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not d.startswith('.')]
            parts = dp.split(os.sep)
            if len(parts) < 2: continue
            for f in fns:
                if os.path.splitext(f)[1].lower() not in AUDIO: continue
                k = key(parts[-2], parts[-1], f); full = os.path.join(dp, f); n += 1
                index[k].append(full)
                base = re.sub(r' \d+$', '', k[2])  # iTunes duplicate suffix: "Cheryl 1.m4a"
                if base != k[2]: index[(k[0], k[1], base)].append(full)
    print(f'Indexed {n} audio files', file=sys.stderr)

    def size(p):
        try: return os.path.getsize(p)
        except OSError: return None

    rows, stats = [], collections.Counter()
    for line in open(missing_f, encoding='utf-8').read().splitlines()[1:]:
        c = line.split('\t')
        src, artist, album, name, pid, path = c[0], c[1], c[2], c[3], c[7], c[8]
        t = by_pid.get(pid, {})
        if path.startswith('/'):
            p = path.split('/'); keys, how = {key(p[-3], p[-2], p[-1])}, 'library path'
        else:
            keys, how = derived_keys(t), 'derived path'
        cands = sorted({h for k in keys for h in index.get(k, [])})
        want = t.get('Size')
        exact = [h for h in cands if want and size(h) == want]
        if exact: status, cands = f'MATCH {how}+size', exact
        elif cands: status = f'MATCH {how}'
        else: status = 'NOT FOUND'
        stats[status] += 1
        rows.append('\t'.join([status, src, artist, album, name, pid, path, ' | '.join(cands)]))

    rows.sort(key=lambda r: (r.startswith('NOT'), r.split('\t')[2:5]))
    with open(out_f, 'w', encoding='utf-8') as fh:
        fh.write('Status\tSource\tArtist\tAlbum\tName\tPersistent ID\tOriginal Path\tCandidates\n')
        fh.write('\n'.join(rows) + '\n')
    for k, v in sorted(stats.items()): print(f'{v:5d}  {k}', file=sys.stderr)
