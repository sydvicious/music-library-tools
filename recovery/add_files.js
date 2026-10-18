// Usage: osascript -l JavaScript add_files.js files.json   (JSON array of paths)
function run(argv) {
  ObjC.import('Foundation');
  const files = JSON.parse(ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null)));
  const app = Application('Music'), out = [];
  for (const f of files) {
    try { const t = app.add(Path(f)); out.push((t ? 'ADDED\t' + t.persistentID() : 'NO TRACK\t') + '\t' + f); }
    catch (e) { out.push('FAILED\t' + e + '\t' + f); }
  }
  return out.join('\n');
}
