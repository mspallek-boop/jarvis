import SwiftUI
import UniformTypeIdentifiers

#if os(macOS)
import AppKit
#else
import UIKit
#endif

/// The clipboard is the one place where Mac and iPhone genuinely differ, so the
/// difference is kept here instead of spreading `#if os` through the views.
enum PlatformImage {
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
