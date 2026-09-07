import AppKit
import Foundation

@main
struct PlatformImageTests {
    @MainActor
    static func main() throws {
        // A private pasteboard: never replace the user's copied content.
        let pasteboard = NSPasteboard.withUniqueName()
        defer { pasteboard.releaseGlobally() }
        pasteboard.setString("Normaler Text", forType: .string)
        precondition(PlatformImage.clipboardPNG(from: pasteboard) == nil)
        precondition(pasteboard.string(forType: .string) == "Normaler Text")

        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 3, pixelsHigh: 2,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        for x in 0..<3 {
            for y in 0..<2 { bitmap.setColor(NSColor(deviceRed: 1, green: 0, blue: 0, alpha: 1), atX: x, y: y) }
        }
        for (format, type): (NSBitmapImageRep.FileType, NSPasteboard.PasteboardType) in [(.tiff, .tiff), (.png, .png)] {
            pasteboard.clearContents()
            pasteboard.setData(bitmap.representation(using: format, properties: [:])!, forType: type)
            try verify(PlatformImage.clipboardPNG(from: pasteboard))
        }

        let file = FileManager.default.temporaryDirectory.appendingPathComponent("jarvis-paste-\(UUID()).png")
        defer { try? FileManager.default.removeItem(at: file) }
        try bitmap.representation(using: .png, properties: [:])!.write(to: file)
        pasteboard.clearContents()
        pasteboard.writeObjects([file as NSURL])
        try verify(PlatformImage.clipboardPNG(from: pasteboard))

        pasteboard.clearContents()
        pasteboard.setData(Data("invalid image".utf8), forType: .png)
        precondition(PlatformImage.clipboardPNG(from: pasteboard) == nil)
        print("Clipboard: text preserved, TIFF screenshot, PNG, Finder file URL and invalid image passed")
    }

    private static func verify(_ data: Data?) throws {
        let data = data!
        precondition(Array(data.prefix(8)) == [137, 80, 78, 71, 13, 10, 26, 10])
        let decoded = NSBitmapImageRep(data: data)!
        precondition(decoded.pixelsWide == 3 && decoded.pixelsHigh == 2)
        precondition(decoded.colorAt(x: 1, y: 1)!.redComponent > 0.9)
    }
}
