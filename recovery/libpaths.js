// Writes the file location of every library track to /tmp/libpaths.txt (one POSIX path per line).
// Slow (one Apple event per track, ~10+ min for 37k tracks) because Music's bulk location get
// fails with -1741 when any track's file is missing.
// Run: osascript -l JavaScript libpaths.js
function run(){
  const ft=Application("Music").libraryPlaylists[0].fileTracks; const n=ft.length; const out=[];
  for(let j=0;j<n;j++){ try{ const x=ft[j].location(); if(x) out.push(x.toString()); }catch(e){} }
  $.NSString.alloc.initWithUTF8String(out.join("\n"))
    .writeToFileAtomicallyEncodingError("/tmp/libpaths.txt",true,$.NSUTF8StringEncoding,null);
  return out.length+" of "+n;
}
