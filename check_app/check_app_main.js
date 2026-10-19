// "Music Library Check.app": run by launchd (via `open -a`) for the nightly library check.
// build_check_app.sh compiles this file with @@REPO@@ replaced by the repository path.
// The check reads Music's database file directly (musicdb.py), so there is no XML export and no
// Accessibility or Automation permission. The app exists only so the file-access permission for
// Music's library folder belongs to it (launchd-run python3 can't get one). Paths come from
// mlt_config.py.
const REPO = "@@REPO@@";

function run() {
  const app = Application.currentApplication(); app.includeStandardAdditions = true;
  const q = s => "'" + String(s).replace(/'/g, "'\\''") + "'";
  const sh = s => app.doShellScript("export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; cd " + q(REPO) + " && " + s);
  let LOG = null;
  const log = m => { if (LOG) app.doShellScript("echo " + q(new Date().toISOString() + " app: " + m) + " >> " + q(LOG)); };
  try {
    const P = JSON.parse(sh("./sync_check.py paths"));
    LOG = P.snaps + "/library-check.log";
    // Give Music a chance to sync with iCloud and save its database before reading it.
    if (sh("pgrep -xq Music && echo yes || echo no") === "no") {
      log("Music not running; opening it in the background and waiting 15 minutes");
      sh("open -g -a Music");
      delay(900);
    }
    sh("./sync_check.py library-check --notify >> " + q(LOG) + " 2>&1");
    log("done");
  } catch (e) {
    log("FAILED: " + e.message);
    app.displayNotification(String(e.message).slice(0, 200), { withTitle: "Music library check FAILED" });
  }
}
