# Claude Code workplan: supervise Hermes for JARVIS

## Mission

Act as the backend integration lead and supervisor for Hermes while Codex owns
the native SwiftUI application in `apple/` for macOS and iPhone.

The product goal is a private, voice-first JARVIS that is usable from Mac and
iPhone, uses Hermes as its agent brain, exposes only narrowly authenticated
bridge APIs, retains the existing HUD/voice experience, and can later remain
reachable through a private always-on relay and Tailscale.

## Source of truth

- The only authoritative repository is `/Users/marlon/Documents/JARVIS`.
- `/Users/marlon/JARVIS` is a separate, non-Git prototype accidentally created
  by an earlier Hermes session. Do not edit, merge, move, or delete it without
  explicit user approval.
- Always confirm `pwd` and `git rev-parse --show-toplevel` before assigning work
  to Hermes or changing files.
- The worktree already contains user-owned changes. Preserve them. Do not
  reset, clean, discard, or overwrite unrelated work.

## Ownership and concurrency contract

### Claude Code owns

- Supervising Hermes sessions and reviewing every Hermes-produced diff.
- Backend integration in `server/`, `bridge/`, `relay/`, `launchd/`, `scripts/`,
  and related documentation when a task is explicitly assigned.
- Python tests, service health checks, security checks, and API-contract review.
- Keeping Hermes in the authoritative repository and stopping it from widening
  scope, using sudo, changing system settings, or touching credentials.

### Codex owns

- All implementation and design work under `apple/`.
- macOS/iPhone UI, Swift models, networking client, speech behavior, settings,
  signing/build guidance, and native-app tests.
- Any change to the native app's expected bridge API contract.

### Shared boundary

- `bridge/` is the contract boundary. Before changing endpoints, payloads,
  authentication, error semantics, or the bridge port, document the proposed
  contract and ensure the Swift client can be updated coherently.
- Do not edit `apple/` while Codex is working there. Report a required app-side
  change instead.
- Do not run two agents against the same files concurrently.

## Verified handoff state (2026-08-31)

- `JARVIS-macOS` builds successfully with signing disabled and DerivedData in
  `/tmp`.
- Generic-device `JARVIS-iOS` builds successfully with signing disabled and
  DerivedData in `/tmp`.
- `server/config/server.yaml` was created locally from
  `server/config/server.example.yaml`; it is intentionally Git-ignored and
  contains no secrets. Runtime secrets remain in `~/.hermes/.env`.
- The Python suite reaches 108 passing tests with two remaining failures:
  1. `tests/test_backdoor_scan.py::test_no_unexpected_outbound_hosts` needs the
     intentionally used `api.open-meteo.com` host reviewed and allow-listed.
  2. `test_default_posture_exposes_privileged_surfaces` performs a real request
     to the dashboard backend on `127.0.0.1:9119`; make it deterministic and
     offline by stubbing the backend response without weakening the auth-gate
     assertion.
- A confirmed runtime port collision exists: the voice server uses `8765`, and
  the new native bridge also defaults to `8765`. Preserve the established voice
  server port and move the bridge to one documented, unused port consistently
  across bridge code, launchd, setup scripts/docs, and app-facing guidance.
  Coordinate the final native-app default with Codex rather than editing
  `apple/` directly.
- Hermes gateway has been observed on `127.0.0.1:8642`. A bridge process has
  been observed on `127.0.0.1:8765`, while the HUD/voice/dashboard services were
  not healthy during the sandboxed check. Re-verify outside the sandbox.
- A headless Hermes assignment failed after three model connection retries and
  made no changes. Treat provider availability as an operational issue, not a
  reason to invent progress.

## Immediate execution plan

### 1. Establish a clean supervisory baseline

Run read-only checks first:

```bash
cd /Users/marlon/Documents/JARVIS
pwd
git rev-parse --show-toplevel
git status --short
hermes gateway status
hermes sessions list
lsof -nP -iTCP -sTCP:LISTEN | egrep ':(8642|8765|8766|8767|8768|9119|9443|443)\\b'
```

Do not claim a service is healthy from `lsof` alone; verify its authenticated
health endpoint where applicable. Never print API keys or tokens.

### 2. Put Hermes on the correct project

- Do not continue the Hermes session whose working directory is
  `/Users/marlon` or whose changes target `/Users/marlon/JARVIS`.
- Start or resume a workspace-scoped session with the correct directory.
- `-c` means continue a session; it is not a prompt flag. Use `--oneshot` for a
  headless prompt, or the TUI for supervised work.
- Give Hermes one bounded task at a time. Require it to inspect the dirty
  worktree, state intended files before editing, run focused tests, and stop for
  review after the task.

Suggested first Hermes assignment:

```text
Work only in /Users/marlon/Documents/JARVIS. Preserve all existing changes and
do not touch /Users/marlon/JARVIS. Resolve the native-bridge versus voice-server
port collision while preserving voice port 8765. Do not edit apple/. Update the
bridge backend, launchd/setup material, and backend documentation consistently.
Run focused bridge tests and report the exact API/port contract for Codex. Do
not use sudo, change system settings, delete files, or commit.
```

Review the diff before giving Hermes another task.

### 3. Restore a deterministic Python test suite

- Add `api.open-meteo.com` to the reviewed outbound-host allow-list with a
  concise comment explaining its HUD weather use.
- Stub the dashboard backend response inside the security test so the test
  proves whether the auth middleware allowed the request without depending on
  a live server or local networking.
- Do not change the production security posture merely to satisfy the tests.
- Run the complete suite from the repository root.

```bash
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements-test.txt
PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q
```

Expected result after the two fixes: all tests pass with no network dependency.

### 4. Prove backend integration

After the bridge-port change and green tests:

- Run `bridge/test_bridge.py` and `relay/test_relay.py` explicitly.
- Validate plist syntax with `plutil -lint`.
- Run the repository health/smoke scripts without exposing secrets.
- Confirm that Hermes API, bridge, voice server, dashboard, and dashboard proxy
  have distinct ports and a documented startup order.
- Report any credential, Tailscale, signing, or system-setting requirement as a
  blocker; do not bypass it.

### 5. Prepare the relay milestone

Once local Mac/iPhone-to-bridge integration is proven, assess `relay/` against
`docs/TARGET_ARCHITECTURE.md`. The target is private Tailscale connectivity and
an always-on node that can report Mac state and issue authenticated Wake-on-LAN
requests. No router port-forwarding and no Hermes API key on the phone or relay.

## Verification commands

Python:

```bash
PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q
```

macOS compile proof (Codex-owned app; read-only verification is allowed):

```bash
xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-macOS \
  -configuration Debug -destination 'platform=macOS' \
  -derivedDataPath /tmp/jarvis-derived-macos \
  CODE_SIGNING_ALLOWED=NO build
```

iOS generic-device compile proof:

```bash
xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-iOS \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/jarvis-derived-ios \
  CODE_SIGNING_ALLOWED=NO build
```

## Safety and review gates

- No `sudo`, system-setting changes, token creation, credential output, public
  network exposure, router changes, or destructive commands without explicit
  user approval at the moment they are needed.
- No commits, pushes, branch changes, or pull requests unless the user asks.
- Do not modify or remove the accidental `/Users/marlon/JARVIS` prototype.
- Treat all Hermes changes as untrusted until the diff and tests are reviewed.
- If Hermes repeats a failed model call three times, stop and report the exact
  failure rather than looping.

## Reporting cadence

After each bounded Hermes task, report:

1. Files changed and why.
2. Exact tests/checks run and their results.
3. Any API-contract impact for Codex's Swift client.
4. Remaining blockers requiring user input.
5. The single recommended next Hermes task.

## Definition of the next milestone

The handoff milestone is complete when:

- Hermes is operating only inside the authoritative repository.
- The bridge/voice port collision is resolved and documented.
- The Python suite is fully green and offline-deterministic.
- Both Apple targets still compile.
- Claude has produced a reviewed bridge contract for Codex.
- Local authenticated app-to-bridge-to-Hermes chat and health checks are proven,
  or the exact external blocker is documented.
