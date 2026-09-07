#if os(macOS)
import AppKit
import Combine
import Foundation

/// A push-to-talk key that works while another app is in front.
///
/// Two gestures on the same key, which is the whole point: **hold** to talk and
/// let go to send, or **double-tap** to leave it listening hands-free. Holding
/// is for a quick sentence without losing your place in another app;
/// double-tap is for a conversation.
///
/// Watching keys pressed in *other* apps needs Accessibility permission — macOS
/// has no way around that, and a global monitor silently receives nothing
/// without it. `permissionGranted` reflects that so the UI can say so instead
/// of looking broken.
@MainActor
final class HotkeyMonitor: ObservableObject {
    /// A key that can be held. Modifier keys make the best push-to-talk keys:
    /// they type nothing, so holding one in a text field does no damage.
    enum Key: String, CaseIterable, Identifiable {
        case rightOption, rightCommand, rightControl, rightShift, f13, f14, f15

        var id: String { rawValue }

        var label: String {
            switch self {
            case .rightOption: return "Rechte Wahltaste ⌥"
            case .rightCommand: return "Rechte Befehlstaste ⌘"
            case .rightControl: return "Rechte Ctrl-Taste ⌃"
            case .rightShift: return "Rechte Umschalttaste ⇧"
            case .f13: return "F13"
            case .f14: return "F14"
            case .f15: return "F15"
            }
        }

        /// Short enough for the overlay, which has one line for everything.
        var shortLabel: String {
            switch self {
            case .rightOption: return "⌥ halten"
            case .rightCommand: return "⌘ halten"
            case .rightControl: return "⌃ halten"
            case .rightShift: return "⇧ halten"
            case .f13: return "F13 halten"
            case .f14: return "F14 halten"
            case .f15: return "F15 halten"
            }
        }

        var keyCode: UInt16 {
            switch self {
            case .rightOption: return 61
            case .rightCommand: return 54
            case .rightControl: return 62
            case .rightShift: return 60
            case .f13: return 105
            case .f14: return 107
            case .f15: return 113
            }
        }

        /// Modifier keys arrive as flagsChanged, function keys as keyDown/keyUp.
        var isModifier: Bool {
            switch self {
            case .f13, .f14, .f15: return false
            default: return true
            }
        }

        var flag: NSEvent.ModifierFlags {
            switch self {
            case .rightOption: return .option
            case .rightCommand: return .command
            case .rightControl: return .control
            case .rightShift: return .shift
            default: return []
            }
        }
    }

    @Published var enabled: Bool = UserDefaults.standard.object(forKey: "hotkeyEnabled") as? Bool ?? true {
        didSet {
            UserDefaults.standard.set(enabled, forKey: "hotkeyEnabled")
            restart()
        }
    }

    @Published var key: Key = Key(rawValue: UserDefaults.standard.string(forKey: "hotkeyKey") ?? "")
        ?? .rightOption {
        didSet {
            UserDefaults.standard.set(key.rawValue, forKey: "hotkeyKey")
            restart()
        }
    }

    /// True while the key is physically down, so the overlay can show it.
    @Published private(set) var isHeld = false
    /// Set once a double-tap turns listening on until it is turned off again.
    @Published private(set) var handsFree = false
    @Published private(set) var permissionGranted = false

    /// Hold this long and it counts as holding, not as one half of a
    /// double-tap. Below it, a press is a tap and may pair with the next one.
    private let tapThreshold: TimeInterval = 0.35
    /// Two taps closer together than this are a double-tap.
    private let doubleTapWindow: TimeInterval = 0.45

    var onPressAndHold: (() -> Void)?
    var onRelease: (() -> Void)?
    var onHandsFreeChanged: ((Bool) -> Void)?

    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var pressedAt: Date?
    private var lastTapAt: Date?
    private var holdDidStart = false

    init() {
        permissionGranted = AXIsProcessTrusted()
        restart()
    }

    deinit {
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
    }

    /// Ask macOS for the permission, which opens System Settings for the user.
    /// Nothing else can grant it — not the app, and not us.
    func requestPermission() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        permissionGranted = AXIsProcessTrustedWithOptions(options as CFDictionary)
    }

    func refreshPermission() {
        permissionGranted = AXIsProcessTrusted()
    }

    private func restart() {
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor); self.globalMonitor = nil }
        if let localMonitor { NSEvent.removeMonitor(localMonitor); self.localMonitor = nil }
        isHeld = false
        pressedAt = nil
        holdDidStart = false
        guard enabled else { return }

        let mask: NSEvent.EventTypeMask = key.isModifier ? [.flagsChanged] : [.keyDown, .keyUp]
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: mask) { [weak self] event in
            Task { @MainActor in self?.handle(event) }
        }
        // The global monitor does not see events while our own window is key,
        // so the local one covers the app's own windows.
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: mask) { [weak self] event in
            Task { @MainActor in self?.handle(event) }
            return event
        }
    }

    private func handle(_ event: NSEvent) {
        guard event.keyCode == key.keyCode else { return }
        let down: Bool
        if key.isModifier {
            down = event.modifierFlags.contains(key.flag)
        } else {
            down = event.type == .keyDown
        }
        // A held function key repeats keyDown; only the first one is a press.
        if down && pressedAt != nil { return }
        down ? press() : release()
    }

    private func press() {
        pressedAt = Date()
        holdDidStart = false
        isHeld = true
        // Start listening immediately rather than after the tap threshold: a
        // hold that only begins after 350ms clips the first word, and the
        // double-tap path stops it again within the same breath.
        holdDidStart = true
        onPressAndHold?()
    }

    private func release() {
        guard let pressedAt else { return }
        let heldFor = Date().timeIntervalSince(pressedAt)
        self.pressedAt = nil
        isHeld = false

        if heldFor >= tapThreshold {
            // A real hold: talking is over, send it.
            if holdDidStart { onRelease?() }
            lastTapAt = nil
            return
        }

        // A tap. Paired with a recent one it toggles hands-free; alone it just
        // stops the listening the press started.
        let now = Date()
        if let last = lastTapAt, now.timeIntervalSince(last) <= doubleTapWindow {
            lastTapAt = nil
            handsFree.toggle()
            onHandsFreeChanged?(handsFree)
            return
        }
        lastTapAt = now
        if !handsFree, holdDidStart { onRelease?() }
    }

    /// Leave hands-free from somewhere else (the overlay, a finished turn).
    func setHandsFree(_ value: Bool) {
        guard value != handsFree else { return }
        handsFree = value
        onHandsFreeChanged?(value)
    }
}
#endif
