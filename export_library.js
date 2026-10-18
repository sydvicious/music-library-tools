// Export Music's library as XML via File > Library > Export Library… — without keystrokes.
// Every step is an Accessibility action on Music's own menu/dialog (click, set value), so it
// works whether or not Music is frontmost and never types into another app.
// Usage: osascript -l JavaScript export_library.js /full/path/to/Library.xml
// Needs Accessibility ("Device Control and Data Access") for whatever runs it.
// The save panel saves into whatever folder it last used; the script finds the new file by its
// unique name and moves it to the requested path.
ObjC.import("Foundation");
function run(argv) {
  if (!argv || !argv[0]) throw new Error("usage: osascript -l JavaScript export_library.js /full/path/Library.xml");
  const out = argv[0];
  const fm = $.NSFileManager.defaultManager;
  const unique = "Library-export-" + Date.now() + ".xml";

  const se = Application("System Events"), p = se.processes.byName("Music");
  if (!p.exists()) { Application("Music").launch(); delay(10); }
  const lib = p.menuBars[0].menuBarItems.byName("File").menus[0].menuItems.byName("Library");
  const items = lib.menus[0].menuItems().filter(i => /^Export Library/.test(i.name() || ""));
  if (!items.length) throw new Error("No 'Export Library…' menu item");
  items[0].click();

  // The save panel is a separate "Save" dialog window.
  let panel = null;
  for (let i = 0; i < 60 && !panel; i++) {
    delay(0.25);
    for (const w of p.windows()) { try { if (w.name() === "Save" || w.subrole() === "AXDialog") { panel = w; break; } } catch (e) {} }
  }
  if (!panel) throw new Error("Save panel did not appear");
  const parts = panel.entireContents();
  const field = parts.find(e => { try { return e.role() === "AXTextField" && e.name() === "Save As:"; } catch (x) { return false; } });
  const save = parts.find(e => { try { return e.role() === "AXButton" && e.name() === "Save"; } catch (x) { return false; } });
  const cancel = parts.find(e => { try { return e.role() === "AXButton" && e.name() === "Cancel"; } catch (x) { return false; } });
  if (!field || !save) { if (cancel) cancel.click(); throw new Error("Could not find the Save As field or Save button"); }
  field.value = unique; delay(0.5);
  if (field.value() !== unique) { if (cancel) cancel.click(); throw new Error("Could not set the file name"); }
  save.click();

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
