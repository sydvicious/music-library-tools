#!/bin/zsh
# Build ~/Applications/Music Library Check.app and install the 3:00 AM launchd agent.
#   ./build_check_app.sh            build + (re)load the agent
#   ./build_check_app.sh --uninstall
# The app runs the Python scripts from this repository, so only changes to check_app_main.js need a
# rebuild. After a rebuild macOS treats the app as new and asks again for access to Music's files.
set -e
REPO=${0:A:h:h}
APP=~/Applications/"Music Library Check.app"
LABEL=local.music-library-tools.check
PLIST=~/Library/LaunchAgents/$LABEL.plist

if [[ $1 == --uninstall ]]; then
  launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"; echo "Agent removed (app left at $APP)"; exit 0
fi

SNAPS=$(cd "$REPO" && ./sync_check.py paths | python3 -c "import json,sys;print(json.load(sys.stdin)['snaps'])")
mkdir -p ~/Applications ~/Library/LaunchAgents "$SNAPS"
TMP=$(mktemp -d)
sed "s|@@REPO@@|$REPO|" "$REPO/check_app/check_app_main.js" > "$TMP/main.js"
rm -rf "$APP"
osacompile -l JavaScript -o "$APP" "$TMP/main.js"
# Run without a Dock icon, and identify the app for permission prompts.
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
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardErrorPath</key><string>$SNAPS/launchd.err</string>
</dict></plist>
EOF
launchctl bootout gui/$(id -u) "$PLIST" 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PLIST"
echo "Built $APP; agent $LABEL runs daily at 3:00 AM."
echo "Run it now with:  open -a \"$APP\""
