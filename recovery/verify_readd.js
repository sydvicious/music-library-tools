function run(argv) {
  ObjC.import('Foundation');
  const rd = p => ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(p, $.NSUTF8StringEncoding, null));
  const rows = JSON.parse(rd(argv[0]));
  const ids = rd(argv[1]).split('\n').filter(l => l.startsWith('ADDED')).map(l => l.split('-> ')[1].trim());
  const app = Application('Music'), lib = app.libraryPlaylists[0];
  let s = {found:0, playsOk:0, ratingOk:0, lovedOk:0, plOk:0, plWant:0, inMedia:0, iniCloud:0, other:[]};
  ids.forEach((id, i) => {
    const r = rows[i], t = lib.tracks.whose({persistentID: id});
    if (!t.length) return; const x = t[0]; s.found++;
    if (x.playedCount() == r.plays) s.playsOk++;
    if (!r.rating || x.rating() == r.rating) s.ratingOk++;
    let fav = false; try { fav = x.favorited(); } catch (e) { try { fav = x.loved(); } catch (e2) {} }
    if (!r.loved || fav) s.lovedOk++;
    const loc = String(x.location());
    if (loc.includes('/Music/iTunes/iTunes Media/')) s.inMedia++; else if (loc.includes('com~apple~CloudDocs')) s.iniCloud++; else s.other.push(loc);
    for (const p of r.playlists) { s.plWant++;
      const pl = app.userPlaylists.whose({persistentID: p.pid});
      if (pl.length && pl[0].tracks.whose({persistentID: id}).length) s.plOk++; }
  });
  return JSON.stringify(s);
}
