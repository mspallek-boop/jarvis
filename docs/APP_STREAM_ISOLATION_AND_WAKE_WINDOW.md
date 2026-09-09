# Two native-app fixes for the next GUI pass (macOS)

Contract for the native app, owned by Codex per this repo's `CLAUDE.md`. Both
fixes touch files the GUI update will already have open, so they belong in that
pass rather than in a separate round that would conflict with it.

Evidence: `~/Library/Logs/DiagnosticReports/JARVIS-2026-09-08-224638.ips`
(JARVIS 0.3.0 build 19, `EXC_CRASH`/`SIGABRT`, abort out of
`-[NSMenu itemArray]`).

## 1. The streamed answer mutates `@Published` state off the main actor

### What happens

`JarvisAPIClient.chatStreaming` (`apple/Sources/Services/JarvisAPIClient.swift:381`)
and `JarvisAPIClient.consumeChatStream`
(`apple/Sources/Services/JarvisAPIClient.swift:414`) both declare the callback as
a bare, non-isolated, non-`Sendable` function value:

```swift
onFrame: (ChatFrame) -> Void
```

The closure passed at `apple/Sources/Stores/AppModel.swift:976` is written inside
a `@MainActor` context and reads as main-actor code, but handing it to a
`nonisolated` async function erases that isolation. `consumeChatStream` drives
`for try await byte in bytes` on the generic cooperative executor, so `onFrame`
— and with it `AppModel.updateRun`
(`apple/Sources/Stores/AppModel.swift:224`) and the `@Published var localRuns`
mutation behind it — runs on a background thread, once per streamed token.

The crash report confirms the thread: frame 0..n of the faulting thread 12 is
queue `com.apple.root.user-initiated-qos.cooperative`, and the stack runs
`AppModel.updateRun` → `Published.subscript.modify` →
`ObservableObjectPublisher.send()` → `GraphHost.flushTransactions()` →
`AppKitMainMenuItem.updateMainMenu` → `-[NSMenu itemArray]` → assertion → abort.

Commit `249b5a9` removed one trigger by making the Scene hold the model as
`@State` rather than `@StateObject`, so the menu is no longer rebuilt per token.
That is a correct change and should stay. It does not fix this: publishing
SwiftUI state from a background thread is undefined regardless of who observes
it, and the same race also shows up as a hang when the main thread and the
cooperative thread meet on the AttributeGraph lock instead of on the menu.

Reproduction that made it fire reliably: send a message, then open Settings
while the answer is still streaming. Presenting the sheet changes the scene set,
which routes the next graph flush through `scenesDidChange(phaseChanged:)`, and
during streaming the next flush is a delta arriving on the wrong thread.

### The change

Put the isolation back into the type, so the compiler enforces it:

```swift
// apple/Sources/Services/JarvisAPIClient.swift:379
func chatStreaming(message: String, conversation: String, clientRunID: String,
                   imagePath: String = "", parallel: Bool = false,
                   onFrame: @MainActor (ChatFrame) -> Void) async throws -> ChatResponse

// apple/Sources/Services/JarvisAPIClient.swift:413
static func consumeChatStream<Bytes: AsyncSequence>(_ bytes: Bytes,
    onFrame: @MainActor (ChatFrame) -> Void) async throws -> ChatResponse
    where Bytes.Element == UInt8
```

and `await` the call at `apple/Sources/Services/JarvisAPIClient.swift:431`:

```swift
await onFrame(frame)
```

Both call sites (`apple/Sources/Stores/AppModel.swift:976` and `:1095`) are
already main-actor isolated and need no change. The two test call sites
(`apple/Tests/InlineImageTests.swift:108` and `:114`) pass closure literals,
which infer `@MainActor` from the parameter type; they compile unchanged.

Prefer this over wrapping the body in `MainActor.run`: the type change makes the
next person unable to reintroduce the bug, and it keeps the per-token hop
explicit and visible at the call site.

## 2. `jarvis://wake` opens a second window instead of using the open one

### What happens

Saying "Hey JARVIS" runs `open -g jarvis://wake`
(`~/.hermes/services/jarvis-wakeword.py`). With the main window already on
screen — even muted — a second, empty `WindowGroup` window appears.

The overlay is not the cause: `AppModel.wakeAndListen`
(`apple/Sources/Stores/AppModel.swift:329`) only calls `wakeToOverlay()` when
`!mainWindowIsOnScreen`, so with a visible window it does nothing but unmute and
listen. What appears is a genuine second window from the `WindowGroup`.

`apple/project.yml:75` registers the `jarvis` URL scheme, and the `WindowGroup`
at `apple/Sources/JARVISApp.swift:26` declares no `handlesExternalEvents` — the
modifier appears nowhere in the project. When AppKit delivers an external URL
event and no existing window claims it, SwiftUI answers by building a new window
from the group. `AppDelegate.application(_:open:)` still runs, which is why
listening also starts, but a delegate method does not suppress the scene's own
window creation, and `applicationShouldHandleReopen` — which already guards the
Dock-click path (`apple/Sources/Services/AppDelegate.swift:48`) — is not called
for URL opens.

### The change

Let the existing window claim the event, and let the group create a window only
for this one activity:

```swift
// apple/Sources/JARVISApp.swift
WindowGroup {
    ContentView()
        .environmentObject(model)
        .tint(.blue)
        .handlesExternalEvents(preferring: ["wake"], allowing: ["wake"])
        #if os(macOS)
        .onAppear { appDelegate.model = model }
        #endif
}
.handlesExternalEvents(matching: ["wake"])
```

The view modifier is what makes an already-open window take the event; the scene
modifier bounds what the group may open a window for at all. Both are needed.

Keep the existing behaviour for the closed-window case: with no window at all,
the wake word should still bring JARVIS back, which is what the pill in
`wakeAndListen` already does.

### How to check it

1. Open the main window, mute the microphone.
2. Say "Hey JARVIS".
3. Expected: the existing window becomes key and starts listening. No second
   window, and the window count in `NSApp.windows` (excluding `NSPanel`) stays
   at one.
4. Then collapse to the pill and repeat: the pill path must still work.
