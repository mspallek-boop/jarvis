# Codex handoff — 2026-09-02

Owner: **Codex**. Scope: `apple/` only.
Backend (`server/`, `bridge/`, `relay/`, `launchd/`, `scripts/`) is frozen. Do not edit it.
Do not commit unless Marlon asks. Do not `sudo`. Do not touch `/Users/marlon/JARVIS`.

Repo: `/Users/marlon/Documents/JARVIS` on `checkpoint/bridge-port-8770`.
HEAD tracks only three app files:

- `apple/Config/JARVIS-iOS-Info.plist`
- `apple/Config/JARVIS-macOS-Info.plist`
- `apple/Sources/Stores/AppModel.swift`

Everything else under `apple/` (xcodeproj, `project.yml`, Views, WatchApp, …) is **untracked local work**. Preserve it. Do not `git clean`. Skip `apple/build/`.

## Do not regress

- `AppModel.defaultServerURL` must stay
  `http://macbook-air-von-marlon.tailfb3c35.ts.net:8770`
- Keep the UserDefaults migration: `jarvis.local`, `:8765`, or `:8766` → that default
- Keep in-progress chat-history / conversation work in `AppModel.swift`
- Do **not** set `NSAllowsArbitraryLoads`
- Do **not** change `PRODUCT_BUNDLE_IDENTIFIER` (`at.marlon.jarvis.ios.watchkitapp` for Watch)

Bridge is live on `127.0.0.1:8770`. Voice owns `8765` / `443` / `8766`. Details: `docs/BRIDGE_CONTRACT.md`. Ignore the URL table in `docs/CODEX_FIX_IOS_BUILD.md` if you still see `jarvis.local:8765` in an old copy — that task is done.

---

## 1. Restore ATS exception for `ts.net` (live regression)

HEAD has this. The working tree **deleted** it from both:

- `apple/Config/JARVIS-iOS-Info.plist`
- `apple/Config/JARVIS-macOS-Info.plist`

Without it, ATS rejects HTTP to `*.ts.net:8770` (`NSAllowsLocalNetworking` does not cover `ts.net`). Restore the exact `NSAppTransportSecurity` block from HEAD:

```xml
<key>NSAppTransportSecurity</key>
<dict>
	<key>NSAllowsLocalNetworking</key>
	<true/>
	<key>NSExceptionDomains</key>
	<dict>
		<key>ts.net</key>
		<dict>
			<key>NSIncludesSubdomains</key>
			<true/>
			<key>NSExceptionAllowsInsecureHTTPLoads</key>
			<true/>
		</dict>
	</dict>
</dict>
```

Copy from `git show HEAD:apple/Config/JARVIS-iOS-Info.plist` (same block on macOS). Keep the comment that explains why. Do not widen to other hosts.

---

## 2. iOS Watch product name — verify, then fix only if broken

Old failure:

```
error: Multiple commands produce
'.../Debug-watchos/JARVIS Watch App.app/JARVIS Watch App'
```

Cause: Watch `PRODUCT_NAME` was `"JARVIS Watch App"` while `productReference` / Embed Watch Content expected `JARVIS-Watch.app`.

**Current untracked tree already has** Watch `PRODUCT_NAME = $(TARGET_NAME)` in `apple/project.yml` and `apple/JARVIS.xcodeproj/project.pbxproj`. Do not churn it if the build is green.

If the error returns: set Watch `PRODUCT_NAME` to `$(TARGET_NAME)` in both configs (or in `project.yml` and regenerate). Display name “JARVIS Watch App” belongs in `CFBundleDisplayName`, not `PRODUCT_NAME`.

---

## Verify

```bash
xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-iOS \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/jarvis-derived-ios \
  CODE_SIGNING_ALLOWED=NO build

xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-macOS \
  -configuration Debug -destination 'platform=macOS' \
  -derivedDataPath /tmp/jarvis-derived-macos \
  CODE_SIGNING_ALLOWED=NO build
```

Both must print `** BUILD SUCCEEDED **`.

Done when: ATS `ts.net` exception is back in both plists, both schemes build, `defaultServerURL` is still `:8770`, conversation work is intact.
