import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

private struct TestBytes: AsyncSequence, AsyncIteratorProtocol {
    typealias Element = UInt8
    let data: Data
    var index = 0
    func makeAsyncIterator() -> Self { self }
    mutating func next() async -> UInt8? {
        guard index < data.count else { return nil }
        defer { index += 1 }
        return data[index]
    }
}

@main struct InlineImageTests {
    static var checks = 0
    static func check(_ value: Bool, _ description: String) {
        precondition(value, description)
        checks += 1
    }

    static func raster(_ type: UTType, width: Int = 2, height: Int = 2) -> Data {
        let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        context.setFillColor(CGColor(red: 1, green: 0, blue: 0, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let output = NSMutableData()
        let destination = CGImageDestinationCreateWithData(output, type.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(destination, context.makeImage()!, nil)
        precondition(CGImageDestinationFinalize(destination))
        return output as Data
    }

    static func response(_ text: String, attachments: [[String: String]] = []) throws -> JarvisAPIClient.ChatResponse {
        let data = try JSONSerialization.data(withJSONObject: ["text": text, "tools": [], "attachments": attachments])
        return try JSONDecoder().decode(JarvisAPIClient.ChatResponse.self, from: data)
    }

    static func main() async throws {
        let png = raster(.png)
        let url = "data:image/png;base64," + png.base64EncodedString()
        check(InlineImageData.decode(url) == png, "PNG data URL must round-trip")
        for bad in ["file:///etc/passwd", "MEDIA:/tmp/jarvis-media/knoblauch.jpg",
                    "data:image/svg+xml;base64,PHN2Zy8+", "data:text/html;base64,SGk=",
                    "data:image/png;base64,%%%", "data:image/png;base64,"] {
            check(InlineImageData.decode(bad) == nil, "Unsafe data reference accepted")
            check(!MessageAttachment(kind: .image, url: bad, title: "").isDisplayable,
                  "Device-local or unsupported URL accepted")
        }
        check(!MessageAttachment(kind: .source, url: url, title: "").isDisplayable, "Data URL became a navigation link")
        check(PlatformImage.inlinePreview(from: Data("<svg/>".utf8)) == nil, "SVG accepted")
        check(PlatformImage.inlinePreview(from: png.prefix(20)) == nil, "Truncated PNG accepted")
        check(PlatformImage.inlinePreview(from: raster(.tiff)) == nil, "Disallowed TIFF accepted")
        for type in [UTType.png, .jpeg, .gif, .bmp] {
            check(PlatformImage.inlinePreview(from: raster(type))?.width == 2, "Raster failed: \(type)")
        }
        check(PlatformImage.inlinePreview(from: raster(.jpeg, width: 2000, height: 100))?.width == 1600,
              "Preview was not downsampled")

        // A complete PNG container with an oversized IHDR, without allocating
        // those pixels. Recompute CRC so the dimensions, not a broken header,
        // cause rejection before decompression.
        for (width, height) in [(16_385, 1), (8000, 6000)] {
            var bomb = png
            let dimensions = [UInt32(width).bigEndian, UInt32(height).bigEndian]
            let bytes = dimensions.withUnsafeBytes { Data($0) }
            bomb.replaceSubrange(16..<24, with: bytes)
            var crc: UInt32 = 0xffffffff
            for byte in bomb[12..<29] {
                crc ^= UInt32(byte)
                for _ in 0..<8 { crc = (crc >> 1) ^ (crc & 1 == 1 ? 0xedb88320 : 0) }
            }
            var finalCRC = (crc ^ 0xffffffff).bigEndian
            bomb.replaceSubrange(29..<33, with: withUnsafeBytes(of: &finalCRC) { Data($0) })
            check(PlatformImage.inlinePreview(from: bomb) == nil, "Pixel bomb accepted")
        }

        let oversized = "data:image/png;base64," + Data(repeating: 0, count: InlineImageData.maxBytes + 1).base64EncodedString()
        check(InlineImageData.decode(oversized) == nil, "Oversized data URL accepted")
        let raw = "Knoblauch: ![image](\(url)) Quelle: https://example.com"
        let answer = try response(raw)
        check(answer.text == "Knoblauch: [Bild] Quelle: https://example.com", "Raw base64 remains visible")
        check(answer.messageAttachments.count == 1, "Actual Hermes format lost")
        check(PlatformImage.inlinePreview(from: InlineImageData.decode(answer.messageAttachments[0].url)!) != nil,
              "Response attachment does not reach image decoder")
        let duplicated = try response(raw, attachments: [["kind": "image", "url": url, "title": "image"]])
        check(duplicated.messageAttachments.count == 1, "Duplicate image")
        let archived = ChatMessage(role: .jarvis, text: answer.text, attachments: answer.messageAttachments)
        let restored = try JSONDecoder().decode(ChatMessage.self, from: JSONEncoder().encode(archived))
        check(restored == archived, "Inline attachment lost in history")
        check(PlatformImage.inlinePreview(from: InlineImageData.decode(restored.attachments[0].url)!) != nil,
              "Archived image no longer decodes")
        check(!SpeechText.withoutLinks(raw).contains("base64"), "Base64 is spoken")
        check(!SpeechText.withoutLinks("Bild. MEDIA:/tmp/jarvis-media/knoblauch.jpg").contains("/tmp"), "Path is spoken")

        // A realistic image frame larger than the previous 800 kB limit passes
        // the production byte-stream parser, including UTF-8 and CRLF.
        let large = "data:image/png;base64," + (png + Data(repeating: 0, count: 700_000)).base64EncodedString()
        var frame = try JSONSerialization.data(withJSONObject: ["type": "done", "response": [
            "text": "Grüße: [Bild]", "tools": [],
            "attachments": [["kind": "image", "url": large, "title": "image"]]]])
        check(frame.count > 800_000, "Fixture does not cover previous limit")
        frame.append(contentsOf: [13, 10])
        let streamed = try await JarvisAPIClient.consumeChatStream(TestBytes(data: frame)) { _ in }
        check(streamed.messageAttachments.count == 1 && streamed.text == "Grüße: [Bild]", "Large done frame failed")
        let rejected = [Data(repeating: 120, count: JarvisAPIClient.maxChatFrameBytes + 1),
                        Data("{\"type\":\"done\"".utf8)]
        for data in rejected {
            do {
                _ = try await JarvisAPIClient.consumeChatStream(TestBytes(data: data)) { _ in }
                preconditionFailure("Oversized/unfinished frame accepted")
            } catch { checks += 1 }
        }
        print("\(checks) inline image checks passed")
    }
}
