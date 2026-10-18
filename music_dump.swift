// music-dump: write Music.app's view of the library as a TSV, sorted by path.
// Uses Apple's read-only iTunesLibrary framework (no scripting, no Music.app round trips).
//
// Build:  swiftc -O music_dump.swift -o music-dump
// Run:    ./music-dump [out.tsv]        (default: stdout)
//
// Columns: path  size  modified(epoch)  pid  location_type  cloud  drm  media_kind  kind  artist  album  title
// path is the POSIX path, Unicode NFC, empty when the item has no file (cloud-only, or missing).
// Rows with a path come first, sorted by path (byte order of UTF-8); rows without follow, sorted by pid.
import Foundation
import iTunesLibrary

func clean(_ s: String?) -> String {
    (s ?? "").replacingOccurrences(of: "\t", with: " ")
             .replacingOccurrences(of: "\n", with: " ")
             .replacingOccurrences(of: "\r", with: " ")
}

let lib: ITLibrary
do { lib = try ITLibrary(apiVersion: "1.1") }
catch { FileHandle.standardError.write("Cannot open the Music library: \(error)\n".data(using: .utf8)!); exit(1) }

let t0 = Date()
var rows: [(key: String, line: String)] = []
for item in lib.allMediaItems {
    let path = item.location.map { $0.path.precomposedStringWithCanonicalMapping } ?? ""
    let pid = String(format: "%016llX", item.persistentID.uint64Value)
    let mod = item.modifiedDate.map { String(Int($0.timeIntervalSince1970)) } ?? ""
    let ltype: String
    switch item.locationType {
    case .file: ltype = "file"; case .URL: ltype = "url"; case .remote: ltype = "remote"; default: ltype = "unknown"
    }
    let fields = [path, String(item.fileSize), mod, pid, ltype,
                  item.isCloud ? "1" : "0", item.isDRMProtected ? "1" : "0",
                  String(item.mediaKind.rawValue), clean(item.kind),
                  clean(item.artist?.name), clean(item.album.title), clean(item.title)]
    rows.append((path.isEmpty ? "\u{10FFFF}" + pid : path, fields.joined(separator: "\t")))
}
rows.sort { $0.key.utf8.lexicographicallyPrecedes($1.key.utf8) }

let header = "path\tsize\tmodified\tpid\tlocation_type\tcloud\tdrm\tmedia_kind\tkind\tartist\talbum\ttitle\n"
let body = header + rows.map { $0.line }.joined(separator: "\n") + "\n"
if CommandLine.arguments.count > 1 {
    try! body.write(toFile: CommandLine.arguments[1], atomically: true, encoding: .utf8)
} else {
    FileHandle.standardOutput.write(body.data(using: .utf8)!)
}
let withPath = rows.filter { !$0.key.hasPrefix("\u{10FFFF}") }.count
FileHandle.standardError.write(String(format: "%d items (%d with a file path) in %.1fs\n",
                                      rows.count, withPath, Date().timeIntervalSince(t0)).data(using: .utf8)!)
