// Usage: osascript -l JavaScript readd_tracks.js /path/readd-manifest.json [--dry-run]
function run(argv) {
  ObjC.import('Foundation');
  const dry = argv.includes('--dry-run');
  const app = Application('Music');
  const rows = JSON.parse(ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null)));
  const fm = $.NSFileManager.defaultManager;
  const lib = app.libraryPlaylists[0];
  const out = [];
  for (const r of rows) {
    if (!fm.fileExistsAtPath(r.file)) { out.push('NO FILE  ' + r.file); continue; }
    if (lib.tracks.whose({persistentID: r.pid}).length) { out.push('OLD ENTRY STILL IN LIBRARY, skipped  ' + r.name); continue; }
    if (dry) { out.push('WOULD ADD  ' + r.name + '  plays=' + r.plays + ' rating=' + r.rating + ' loved=' + r.loved + ' playlists=' + r.playlists.map(p => p.name).join(', ')); continue; }
    const t = app.add(Path(r.file));
    if (!t) { out.push('ADD FAILED  ' + r.file); continue; }
    try { if (r.plays) t.playedCount = r.plays; } catch (e) {}
    try { if (r.skips) t.skippedCount = r.skips; } catch (e) {}
    try { if (r.rating) t.rating = r.rating; } catch (e) {}
    try { if (r.loved) t.favorited = true; } catch (e) { try { t.loved = true; } catch (e2) {} }
    for (const p of r.playlists) {
      const pl = app.userPlaylists.whose({persistentID: p.pid});
      if (pl.length) app.duplicate(t, {to: pl[0]}); else out.push('  playlist not found: ' + p.name);
    }
    out.push('ADDED  ' + r.name + '  -> ' + t.persistentID());
  }
  return out.join('\n');
}
