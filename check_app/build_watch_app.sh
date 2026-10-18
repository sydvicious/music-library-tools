#!/bin/zsh
# Build ~/Applications/Music Library Watch.app and a launchd agent that opens it every 15 minutes
# to run `musicdb.py watch`. The app exists so macOS's permission to read Music's library files
# belongs to this one app (launchd running python3 directly is refused).
#   ./build_watch_app.sh             build + (re)load the agent
#   ./build_watch_app.sh --uninstall
set -e
REPO=${0:A:h:h}
APP=~/Applications/"Music Library Watch.app"
LABEL=local.music-library-tools.watch
PLIST=~/Library/LaunchAgents/$LABEL.plist

if [[ $1 == --uninstall ]]; then
  launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"; echo "Agent removed (app left at $APP)"; exit 0
fi

SNAPS=$(cd "$REPO" && ./sync_check.py paths | python3 -c "import json,sys;print(json.load(sys.stdin)['snaps'])")
TMP=$(mktemp -d)
cat > "$TMP/main.js" <<EOF
function run() {
  const app = Application.currentApplication(); app.includeStandardAdditions = true;
  const q = s => "'" + String(s).replace(/'/g, "'\\\\''") + "'";
  try {
    app.doShellScript("export PATH=/opt/homebrew/bin:/usr/local/bin:\$PATH; cd " + q("$REPO") +
                      " && /usr/bin/python3 musicdb.py watch >/dev/null 2>> " + q("$SNAPS/watch.err"));
  } catch (e) {
    app.displayNotification(String(e.message).slice(0, 200), { withTitle: "Music library watch FAILED" });
  }
}
EOF
rm -rf "$APP"
osacompile -l JavaScript -o "$APP" "$TMP/main.js"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $LABEL" "$APP/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string $LABEL" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"
rm -rf "$TMP"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/open</string><string>-g</string><string>-a</string><string>$APP</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardErrorPath</key><string>$SNAPS/launchd-watch.err</string>
</dict></plist>
EOF
launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PLIST"
echo "Built $APP; agent $LABEL runs every 15 minutes."
echo "Run it once now to grant access:  open -a \"$APP\""
