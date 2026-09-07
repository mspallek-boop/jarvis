import SwiftUI
import UniformTypeIdentifiers
import ImageIO

#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// The clipboard is the one place where Mac and iPhone genuinely differ, so the
/// difference is kept here instead of spreading `#if os` through the views.
enum PlatformImage {
    /// Inspect dimensions before decoding pixels, then downsample the first
    /// frame. Animated images cannot allocate an unbounded frame sequence.
    static func inlinePreview(from data: Data) -> CGImage? {
        guard !data.isEmpty, data.count <= InlineImageData.maxBytes,
              let source = CGImageSourceCreateWithData(data as CFData,
                [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetStatus(source) == .statusComplete,
              let type = CGImageSourceGetType(source) as String?,
              [UTType.png.identifier, UTType.jpeg.identifier, UTType.gif.identifier,
               UTType.webP.identifier, UTType.bmp.identifier].contains(type),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              width > 0, height > 0, width <= 16_384, height <= 16_384,
              width * height <= 40_000_000 else { return nil }
        return CGImageSourceCreateThumbnailAtIndex(source, 0, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: 1600,
            kCGImageSourceShouldCacheImmediately: true
        ] as CFDictionary)
    }

    #if os(macOS)
    static func clipboardPNG(from pasteboard: NSPasteboard = .general) -> Data? {
        let pastedImage = NSImage(pasteboard: pasteboard)
        let fileURLs = pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]
        let image = pastedImage ?? fileURLs?.lazy.compactMap { NSImage(contentsOf: $0) }.first
        guard let image,
              let tiff = image.tiffRepresentation else { return nil }
        return pngData(from: tiff)
    }
    #endif
    /// What a pasted picture may be. Kept narrow on purpose: the bridge sniffs
    /// the bytes anyway and refuses anything that is not really an image.
    static let pasteTypes: [UTType] = [.png, .jpeg, .gif, .heic, .tiff, .image]

    /// iOS has no paste command for a view, so the composer shows a button
    /// only when there is actually a picture to take.
    #if os(iOS)
    static var clipboardHasImage: Bool { UIPasteboard.general.hasImages }

    static func clipboardPNG() -> Data? {
        UIPasteboard.general.image?.pngData()
    }
    #endif

    static func from(_ data: Data) -> Image? {
        #if os(macOS)
        guard let native = NSImage(data: data) else { return nil }
        return Image(nsImage: native)
        #else
        guard let native = UIImage(data: data) else { return nil }
        return Image(uiImage: native)
        #endif
    }

    /// PNG bytes for whatever the clipboard holds, so the bridge always
    /// receives a format it recognises — a screenshot arrives as TIFF on macOS.
    static func pngData(from data: Data) -> Data? {
        #if os(macOS)
        guard let native = NSImage(data: data),
              let tiff = native.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff) else { return nil }
        return bitmap.representation(using: .png, properties: [:])
        #else
        return UIImage(data: data)?.pngData()
        #endif
    }
}

#if os(macOS)
/// Catch image paste before the text field's field editor consumes it. Ordinary
/// text and shortcuts in other windows/sheets keep their normal responder path.
struct ClipboardImagePasteHandler: NSViewRepresentable {
    var enabled: Bool
    var onPaste: (Data) -> Void

    func makeNSView(context: Context) -> PasteView {
        let view = PasteView()
        view.installMonitor()
        return view
    }

    func updateNSView(_ view: PasteView, context: Context) {
        view.pasteEnabled = enabled
        view.onPaste = onPaste
    }

    static func dismantleNSView(_ view: PasteView, coordinator: ()) {
        view.removeMonitor()
    }

    final class PasteView: NSView {
        var pasteEnabled = false
        var onPaste: ((Data) -> Void)?
        private var monitor: Any?

        func installMonitor() {
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, self.pasteEnabled,
                      let window = self.window, window.isKeyWindow,
                      event.window === window, window.attachedSheet == nil,
                      event.modifierFlags.intersection([.command, .control, .option, .shift]) == .command,
                      event.charactersIgnoringModifiers?.lowercased() == "v",
                      let png = PlatformImage.clipboardPNG() else { return event }
                self.onPaste?(png)
                return nil
            }
        }

        func removeMonitor() {
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
        }

        deinit {
            if let monitor { NSEvent.removeMonitor(monitor) }
        }
    }
}
#endif
