#if os(iOS)
import ActivityKit
import Foundation
import SwiftUI

/// What a running JARVIS turn looks like from outside the app.
///
/// The phone locking used to end the conversation as far as the user could
/// tell: the screen went dark, the socket went with it, and the next thing on
/// screen was an error. A Live Activity is the honest answer — the turn keeps
/// running on the Mac, and the lock screen and the Dynamic Island say so.
///
/// This file is compiled into both the app and the widget extension, so the
/// two always agree on the shape of the payload.
struct JarvisActivityAttributes: ActivityAttributes {
    /// The question. Fixed for the life of the activity.
    let prompt: String
    /// `AppBackground.rawValue`, so the lock screen wears the same colour the
    /// app does. The extension is a separate process and cannot read the app's
    /// defaults, so the choice travels with the activity. It is an attribute
    /// rather than state because nobody changes their theme mid-answer.
    var background: String = "black"

    struct ContentState: Codable, Hashable {
        /// What JARVIS is doing right now, already in the app's wording —
        /// "Ich denke nach", "Ich suche im Web", "Ich antworte".
        var phase: String
        /// The answer as far as it has streamed in. Empty until the first
        /// token. Kept short: the lock screen shows a few lines, not an essay.
        var reply: String
        /// Set once the turn is over, so the last update can read as a result
        /// rather than as work still in progress.
        var isFinished: Bool
        /// Only set when the turn ended badly, and only for a real failure —
        /// never for the connection drop that locking the phone itself causes.
        var failure: String?

        /// The trailing slice of the answer that fits a lock screen.
        var replyExcerpt: String {
            let trimmed = reply.trimmingCharacters(in: .whitespacesAndNewlines)
            guard trimmed.count > 240 else { return trimmed }
            return "…" + trimmed.suffix(240)
        }
    }
}

/// The app's background palette, as the extension needs it.
///
/// It deliberately mirrors `AppBackground` rather than sharing it: that enum
/// lives in the app's model layer with everything else the extension has no
/// business linking against. A test keeps the two lists in step.
enum ActivityPalette {
    static func background(_ raw: String) -> Color {
        switch raw {
        case "white": return .white
        case "blue": return .blue
        case "green": return .green
        case "orange": return .orange
        case "red": return .red
        case "purple": return .purple
        default: return .black
        }
    }

    /// Black text on the light grounds, white on the dark ones — the same
    /// pairing the app uses, so the lock screen is legible in both.
    static func foreground(_ raw: String) -> Color {
        switch raw {
        case "white", "green", "orange": return .black
        default: return .white
        }
    }

    /// A tone for the phase line and the prompt: the foreground, stepped back.
    static func secondary(_ raw: String) -> Color {
        foreground(raw).opacity(0.65)
    }
}
#endif
