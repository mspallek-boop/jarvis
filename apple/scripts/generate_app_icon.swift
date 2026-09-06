import AppKit
import Foundation

guard CommandLine.arguments.count == 4, let pixels = Int(CommandLine.arguments[2]) else {
    fputs("usage: generate_app_icon.swift OUTPUT SIZE dark|light|mac|foreground\n", stderr)
    exit(2)
}

let output = CommandLine.arguments[1]
let mode = CommandLine.arguments[3]
guard ["dark", "light", "mac", "foreground"].contains(mode) else {
    fputs("appearance must be dark, light, mac, or foreground\n", stderr)
    exit(2)
}
let dark = mode == "dark"
let size = CGFloat(pixels)
let image = NSImage(size: NSSize(width: size, height: size))

image.lockFocus()
guard let context = NSGraphicsContext.current?.cgContext else { exit(3) }

context.setAllowsAntialiasing(true)
context.setShouldAntialias(true)

if mode == "foreground" {
    context.clear(CGRect(x: 0, y: 0, width: size, height: size))
} else {
    context.setFillColor((dark ? NSColor.black : NSColor.white).cgColor)
    context.fill(CGRect(x: 0, y: 0, width: size, height: size))
}

let scale = ["mac", "foreground"].contains(mode) ? 1.10 : 1.0
let grid = size * 0.64 * scale
let gap = size * 0.035 * scale
let tile = (grid - gap * 2) / 3
let origin = (size - grid) / 2
context.setFillColor((mode == "dark" ? NSColor.white : NSColor.black).cgColor)

for row in 0..<3 {
    for column in 0..<3 {
        let rect = CGRect(
            x: origin + CGFloat(column) * (tile + gap),
            y: origin + CGFloat(row) * (tile + gap),
            width: tile,
            height: tile
        )
        let path = CGPath(
            roundedRect: rect,
            cornerWidth: tile * 0.19,
            cornerHeight: tile * 0.19,
            transform: nil
        )
        context.addPath(path)
        context.fillPath()
    }
}
image.unlockFocus()

guard
    let tiff = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let png = bitmap.representation(using: .png, properties: [:])
else { exit(4) }

try png.write(to: URL(fileURLWithPath: output), options: .atomic)
