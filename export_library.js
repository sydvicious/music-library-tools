// Export Music's library as XML via File > Library > Export Library… — without keystrokes.
// Every step is an Accessibility action on Music's own menu/dialog (click, set value), so it
// works whether or not Music is frontmost and never types into another app.
// Usage: osascript -l JavaScript export_library.js /full/path/to/Library.xml
// Needs Accessibility ("Device Control and Data Access") for whatever runs it.
// The save panel saves into whatever folder it last used; the script finds the new file by its
// unique name and moves it to the requested path. It tries twice (up to 90 s each for the dialog);
// if both fail it cancels any open dialog, keeps watching 5 more minutes to cancel a panel that
// appears late, and, when a previous export exists at the output path, returns "FALLBACK: …"
// instead of failing so the check can still run. With the display asleep or the screen locked
// it doesn't try at all and returns "SKIPPED: …".
ObjC.import("Foundation");
ObjC.import("CoreGraphics");

// Returns why the screen can't be used for the export ("display asleep", "screen locked",
// "not the console session"), or "" when it is awake and unlocked.
function screenUnavailable() {
  try {
    if ($.CGDisplayIsAsleep($.CGMainDisplayID())) return "display asleep";
    const d = ObjC.castRefToObject($.CGSessionCopyCurrentDictionary());
    if (!d.js) return "no login session on the console";
    const locked = d.objectForKey("CGSSessionScreenIsLocked");
    if (locked && locked.js) return "screen locked";
    const onConsole = d.objectForKey("kCGSSessionOnConsoleKey");
    if (onConsole && onConsole.js === false) return "not the console session";
  } catch (e) { return ""; }   // can't tell: try the export as before
  return "";
}

function run(argv) {
  if (!argv || !argv[0]) throw new Error("usage: osascript -l JavaScript export_library.js /full/path/Library.xml");
  const out = argv[0];
  const fm = $.NSFileManager.defaultManager;
  const unique = "Library-export-" + Date.now() + ".xml";
  const previous = () => fm.fileExistsAtPath(out)
    ? "using previous XML from " + fm.attributesOfItemAtPathError(out, null).objectForKey("NSFileModificationDate").js.toISOString()
    : "no previous XML";

  // With the display asleep or the screen locked, Music's Save panel shows up late or never
  // reports itself, and then sits open until someone dismisses it. Don't try.
  const why = screenUnavailable();
  if (why) return "SKIPPED: " + why + "; " + previous();

  const se = Application("System Events"), p = se.processes.byName("Music");
  if (!p.exists()) { Application("Music").launch(); delay(10); }

  const findPanel = () => {
    for (const w of p.windows()) {
      try { if (w.name() === "Save" || w.subrole() === "AXDialog") return w; } catch (e) {}
      try { if (w.sheets.length) return w.sheets[0]; } catch (e) {}
    }
    return null;
  };
  const buttonIn = (panel, name) => panel.entireContents().find(e => { try { return e.role() === "AXButton" && e.name() === name; } catch (x) { return false; } });
  const cancelAny = () => { try { const pn = findPanel(); if (pn) { const c = buttonIn(pn, "Cancel"); if (c) c.click(); } } catch (e) {} };
  const windowList = () => { try { return p.windows().map(w => { let s = ""; try { s = w.subrole(); } catch (e) {} return w.name() + "/" + s; }).join(", ") || "(none)"; } catch (e) { return "(unreadable: " + e.message + ")"; } };

  // One attempt: open the panel (or reuse one left open), name the file, click Save.
  const attempt = () => {
    try { Application("Music").activate(); } catch (e) {}
    delay(2);
    let panel = findPanel();
    if (!panel) {
      const lib = p.menuBars[0].menuBarItems.byName("File").menus[0].menuItems.byName("Library");
      const items = lib.menus[0].menuItems().filter(i => /^Export Library/.test(i.name() || ""));
      if (!items.length) throw new Error("No 'Export Library…' menu item");
      items[0].click();
      for (let i = 0; i < 90 && !panel; i++) { delay(1); panel = findPanel(); }   // up to 90 s
    }
    if (!panel) throw new Error("Save panel did not appear within 90 s (Music windows: " + windowList() + ")");
    delay(1);
    const parts = panel.entireContents();
    const field = parts.find(e => { try { return e.role() === "AXTextField" && e.name() === "Save As:"; } catch (x) { return false; } });
    const save = parts.find(e => { try { return e.role() === "AXButton" && e.name() === "Save"; } catch (x) { return false; } });
    if (!field || !save) throw new Error("Could not find the Save As field or Save button");
    field.value = unique; delay(0.5);
    if (field.value() !== unique) throw new Error("Could not set the file name");
    save.click();
  };

  let lastErr = null;
  for (let tries = 0; tries < 2; tries++) {
    try { attempt(); lastErr = null; break; }
    catch (e) { lastErr = e; cancelAny(); delay(5); }
  }
  if (lastErr) {
    // Don't leave a dialog open: the panel can appear minutes after the menu click, so keep
    // watching for 5 minutes and cancel it if it shows up. Then fall back to the previous export.
    cancelAny();
    let lateCancelled = 0;
    for (let i = 0; i < 20; i++) {
      delay(15);
      const pn = findPanel();
      if (pn) { try { const c = buttonIn(pn, "Cancel"); if (c) { c.click(); lateCancelled++; } } catch (e) {} }
    }
    if (fm.fileExistsAtPath(out))
      return "FALLBACK: export failed (" + lastErr.message + ")" +
        (lateCancelled ? "; cancelled a late Save panel" : "") + "; " + previous();
    throw lastErr;
  }

  // Find the new file (the panel's last-used folder) and move it into place.
  const home = $.NSHomeDirectory().js;
  const outDir = out.replace(/\/[^\/]+$/, "");
  const roots = [outDir].concat(["Desktop", "Documents", "Downloads", "Music", ""].map(r => home + (r ? "/" + r : "")));
  let found = null;
  for (let i = 0; i < 240 && !found; i++) {           // up to 2 minutes
    delay(0.5);
    for (const r of roots) { const c = r + "/" + unique; if (fm.fileExistsAtPath(c)) { found = c; break; } }
    if (!found && i % 20 === 19) {                     // every 10 s, ask Spotlight too
      const app = Application.currentApplication(); app.includeStandardAdditions = true;
      try { const s = app.doShellScript("mdfind -name " + unique + " | head -1"); if (s) found = s; } catch (e) {}
    }
  }
  if (!found) throw new Error("Export did not produce " + unique);
  let last = -1;                                       // wait for the write to finish
  for (let j = 0; j < 120; j++) {
    const sz = fm.attributesOfItemAtPathError(found, null).objectForKey("NSFileSize").intValue;
    if (sz > 0 && sz === last) break;
    last = sz; delay(1);
  }
  if (fm.fileExistsAtPath(out)) fm.removeItemAtPathError(out, null);
  if (!fm.moveItemAtPathToPathError(found, out, null)) throw new Error("Could not move " + found + " to " + out);
  return out + " (saved via " + found.replace(/\/[^\/]+$/, "") + ")";
}
