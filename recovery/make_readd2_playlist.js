function run(argv) {
  const app = Application('Music');
  const ObjC_ = ObjC; ObjC_.import('Foundation');
  const rows = JSON.parse(ObjC_.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null)));
  let pl = app.userPlaylists.whose({name: 'Recovery – Re-add 2'});
  pl = pl.length ? pl[0] : app.make({new: 'playlist', withProperties: {name: 'Recovery – Re-add 2'}});
  const lib = app.libraryPlaylists[0];
  let ok = 0, missing = [];
  for (const r of rows) {
    const t = lib.tracks.whose({persistentID: r.pid});
    if (t.length) { app.duplicate(t[0], {to: pl}); ok++; } else missing.push(r.pid + ' ' + r.name);
  }
  return `added ${ok}, not found ${missing.length}\n` + missing.join('\n');
}
