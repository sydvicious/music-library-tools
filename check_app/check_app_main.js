// "Music Library Check.app": run by launchd (via `open -a`) for the nightly library check.
// build_check_app.sh compiles this file with @@REPO@@ replaced by the repository path.
// The export code is read from the repository at run time (export_library.js), so script changes
// don't need a rebuild — and because it runs inside this app, the Accessibility permission
// ("Device Control and Data Access") belongs to this app alone. Paths come from mlt_config.py.
ObjC.import("Foundation");
const REPO = "@@REPO@@";

function run() {
  const app = Application.currentApplication(); app.includeStandardAdditions = true;
  const q = s => "'" + String(s).replace(/'/g, "'\\''") + "'";
  const sh = s => app.doShellScript("export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; cd " + q(REPO) + " && " + s);
  let LOG = null;
  const log = m => { if (LOG) app.doShellScript("echo " + q(new Date().toISOString() + " app: " + m) + " >> " + q(LOG)); };
  try {
    const P = JSON.parse(sh("./sync_check.py paths"));
    const XML = P.snaps + "/Library-export.xml"; LOG = P.snaps + "/library-check.log";
    const se = Application("System Events");
    if (!se.processes.byName("Music").exists()) {
      log("Music not running; opening it and waiting 15 minutes");
      Application("Music").launch();
      delay(900);
    }
    const src = $.NSString.stringWithContentsOfFileEncodingError(REPO + "/export_library.js", $.NSUTF8StringEncoding, null).js;
    (0, eval)(src.replace(/^function run\(argv\)/m, "function exportLibrary(argv)"));
    log("exporting library XML");
    log(exportLibrary([XML]));
    sh("./sync_check.py library-check --xml " + q(XML) + " --notify >> " + q(LOG) + " 2>&1");
    log("done");
  } catch (e) {
    log("FAILED: " + e.message);
    app.displayNotification(String(e.message).slice(0, 200), { withTitle: "Music library check FAILED" });
  }
}
