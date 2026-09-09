# Incident: WhatsApp stand-in, watch, and gateway instability — 2026-09-09

## Scope and method

Read-only investigation performed on 2026-09-09 (Europe/Vienna). No application
code, deployed service, LaunchAgent, state file, or user configuration was
changed. This report is the only created file. Contact identifiers, credentials,
and message text were deliberately neither copied nor recorded.

Evidence commands included `git log`, `git diff`, checksums/stat metadata for
repo versus deployed files, `launchctl print`, `lsof` listener snapshots,
redacted state summaries, and structured summaries of
`/Users/marlon/.hermes/logs/*`. The direct command
`hermes gateway status` was read-only.

## Executive finding

There are three separate conditions, not one Sofia/Maurice automation:

1. The Maurice stand-in feature is implemented and deployed, but the active
   Hermes instructions contain no command or policy for invoking it. The two
   recorded stand-in *offers* (2026-09-08 23:57:42 and 2026-09-09 09:20:09)
   never became durable stand-ins. The current state has zero stand-ins; the
   stand-in stdout/stderr logs are empty. This supports “not started”/“not
   invoked,” but cannot prove which prior spoken request was Maurice without
   exposing personal state.
2. Sofia is a currently pending, non-mutating reply watch created at
   2026-09-09 09:46:41. It is not a stand-in and cannot reply to Sofia. It is
   live until its 48-hour TTL expires, unless cleared; the always-loaded 30s
   LaunchAgent is just its poller. Current WhatsApp mode is `self-chat`, not
   `bot`, so automatic replying is off.
3. Hermes has genuine transport/service instability, but the ledger evidence
   does **not** indicate data corruption or a program-lock crash. Its most
   frequent `SystemExit(75)` records are intentional supervisor-restart
   requests. The concrete failure is restart overlap on the API listener
   (`EADDRINUSE` on port 8642, seven occurrences), with recurrent WhatsApp
   disconnect/reconnect events. A Hermes status-command bug compounds the
   diagnosis by declaring the running GUI-domain LaunchAgent “not loaded.”

## Evidence and root-cause assessment

### Maurice stand-in: implementation exists, invocation path is missing

The stand-in's actual start path is generic: it first calls WhatsApp mode,
then requires an explicit `--announce` or `--no-announce`, writes durable state
only after those steps, and is polled by launchd.

- `scripts/jarvis-chat-standin.py:410-455` validates, switches receiving on,
  requires disclosure choice, sends any required disclosure, then records the
  stand-in.
- `scripts/jarvis-chat-standin.py:507-523` expires/reports active stand-ins
  and reconciles receive mode.
- `launchd/com.jarvis.chat-standin.plist:7-21` runs that deployed script at
  load and every 60 seconds.
- The deployed stand-in and mode scripts checksum-identically match the repo.

However, `hermes-plugin/SOUL.installed.md:191-210` tells Hermes to register a
generic reply watch after a send and grants one specific Morris exception;
`SOUL.installed.md:229-238` documents manual receive mode. There is no
`jarvis-chat-standin.py`, “stand-in,” or `--announce` instruction anywhere in
either SOUL file. Commit `5177327` (2026-09-09 11:24:55+02:00) added the script,
LaunchAgent, bridge display, and tests, but did not add Hermes instructions.

**Root cause (high confidence):** the agent has no installed workflow that
translates a user's request into the required stand-in command. The available
evidence cannot establish a successful Maurice run; it establishes that none
is active now and no completion/error was emitted by its LaunchAgent.

**Secondary operational risk:** starting or ending a stand-in triggers the
mode script, which unconditionally asks Hermes to restart the gateway
(`scripts/jarvis-whatsapp-mode.py:133-139`, `248-258`, `288-296`). During the
observed gateway instability that can make a start fail before state is saved
(`scripts/jarvis-chat-standin.py:422-450`). This is a plausible contributing
failure mode, not proof of the particular Maurice attempt.

### Sofia: active reply watch, not active stand-in or bot

The current `/Users/marlon/.hermes/jarvis-whatsapp-watch.json` contains exactly
one watch named Sofia, created 2026-09-09 09:46:41+02:00, TTL 48 hours, with two
identity aliases. It contains no active bot-mode ownership field. The current
stand-in state has `standin_count=0`, and current mode state is `{}`. The
managed runtime setting is `WHATSAPP_MODE=self-chat`; the allowlist has one
entry but is inactive in self-chat mode.

This is active *state*, not a stale process:

- `scripts/jarvis-whatsapp-watch.py:200-220` creates/replaces a watch only
  when its `watch` command is invoked, then starts scanning at the end of the
  bridge log.
- `scripts/jarvis-whatsapp-watch.py:289-342` polls, only notifies on a matching
  reply, then removes the watch. It does not send WhatsApp messages.
- `launchd/com.jarvis.whatsapp-watch.plist:10-21` runs `poll` at load and every
  30 seconds. Its loaded job has run successfully (last exit 0) 3,513 times.

This is consistent with the existing SOUL instruction to create a watch after
a successful send, rather than with a user starting a Sofia stand-in. The
watch will remain until about 2026-09-11 09:46+02:00 if no matching reply is
observed. It should be cleared deliberately if that notification is no longer
wanted; this report did not clear it.

There is a deployment drift worth fixing before relying on reply-close logic:
the installed watcher at
`/Users/marlon/.hermes/services/jarvis-whatsapp-watch.py` is dated
2026-09-07 11:22 and has a different checksum from the repo. It lacks the
fixed Morris accepted-message matching and receive-window-close logic introduced
by commit `f3c81df` (`scripts/jarvis-whatsapp-watch.py:158-170`, `267-286`,
`328-338`). The installed mode script and chat-stand-in script do match the
repo; all three installed LaunchAgent plists match the repo. Thus a future
Morris reply cannot close the receive window through the installed watcher,
although Sofia's generic notification watch is functional.

`scripts/setup-mac.sh:30-39` deploys only the bridge and its plist; it deploys
none of the three WhatsApp scripts or their LaunchAgents. That omission explains
how the watcher remained old despite matching source/plist copies elsewhere.

### Gateway, WhatsApp connection, data, and lock behaviour

Current read-only health snapshot:

- `launchctl print gui/501/ai.hermes.gateway` reports a running LaunchAgent
  (`ai.hermes.gateway`, wrapper PID 58989), configured `KeepAlive=true`,
  `RunAtLoad=true`, `ThrottleInterval=30`, and an external-supervisor gateway
  child. Port 8642 is currently listened to by that child; the WhatsApp bridge
  is currently listening on port 3000; the JARVIS bridge is listening on 8770.
- `hermes gateway status` simultaneously says the service is not loaded and
  calls its child detached. This is a false status result: its own
  `/Users/marlon/.hermes/hermes-agent/hermes_cli/gateway.py:4192-4205` calls
  `launchctl list <label>` without a GUI domain. Here that command exits 1,
  while `launchctl print gui/501/ai.hermes.gateway` shows the active service.
  The resulting false “not loaded” branch is at lines 4218-4223. Do not use
  that status result as evidence that the daemon is manually orphaned.

The structured lifecycle log is the reliable source for exit classification:

- `/Users/marlon/.hermes/logs/gateway-exit-diag.log` has 47
  `asyncio.run.SystemExit` records with code 75, most recently at
  2026-09-09 14:37:24Z (16:37:24+02:00). Hermes defines 75 as
  `GATEWAY_SERVICE_RESTART_EXIT_CODE`—a request for its supervisor to restart—
  in `gateway/restart.py:9-10`, not a data/program-lock failure.
- The same log has 21 `gateway.previous_unclean_exit` records where the state
  database integrity result is `ok`; it has no current corruption result.
  The only recorded `OperationalError` was historical (2026-09-07
  02:51:05Z), with no recurrence in the later incident window. The data store
  is therefore not supported as the root cause.
- “Already running”/program-lock-like text occurs in aggregate logs on
  2026-09-06/07, but no matching lock error code appears in the canonical exit
  ledger. Hermes' lock helper explicitly treats `lock_conflict` or `*_lock` as
  a separate startup conflict (`gateway/restart.py:46-59`). Do not conflate
  those older messages with the 2026-09-09 code-75 restarts.
- `/Users/marlon/.hermes/logs/gateway.error.log` records seven API listener
  address-in-use events on port 8642, including 2026-09-09 15:37:06 and
  16:37:31+02:00. This is direct evidence that a replacement gateway sometimes
  tries to bind before the previous listener releases the port. Concurrent
  WhatsApp disconnect/reconnect entries are repeatedly present; the latest
  cluster is around 16:37–16:39+02:00. The temporal overlap makes restart
  overlap a strong contributor to connection churn, but the logs do not prove
  it is the sole cause of every WhatsApp disconnect.

## Minimal remediation plan (do not apply until approved)

1. Add a precise stand-in section to the *installed* Hermes instruction source:
   require explicit contact, duration, and disclosure choice; invoke
   `jarvis-chat-standin.py start`; state that failure to switch mode means no
   stand-in exists. Add one direct acceptance test that captures the generated
   command for a requested stand-in. This fixes the missing invocation path;
   it must not silently enable bot mode.
2. Make WhatsApp deployment atomic and version-checked: deploy the three
   scripts from `scripts/` to `~/.hermes/services/`, deploy their plists, then
   reload only those three jobs. Extend `scripts/setup-mac.sh` (or a dedicated
   deploy command) to verify hashes afterward. First update the stale watcher.
3. Before any automatic gateway restart, serialize/coalesce restarts and wait
   for the old 8642 listener to leave before considering the operation
   successful. The mode script should verify the supervised gateway by
   `launchctl print gui/$(id -u)/ai.hermes.gateway` plus a health check, not by
   the currently defective unscoped `hermes gateway status`. Add a regression
   test for an exit-75 handoff where the old listener remains briefly bound.
4. Correct Hermes' status implementation upstream: query the GUI-domain job
   (or use the existing supervision predicate) rather than bare
   `launchctl list <label>`. Keep the external-supervisor marker; it is already
   correctly present in the installed plist.
5. Make a deliberate user decision on the current Sofia watch: leave it until
   TTL if a reply notification is desired, otherwise clear that one watch. No
   current state authorizes or requires changing WhatsApp mode.

## Verification results

- Passed: import smoke tests with bytecode writing disabled for
  `jarvis-whatsapp-mode.py`, `jarvis-whatsapp-watch.py`, and
  `jarvis-chat-standin.py`.
- Passed: repo/deployed checksums for stand-in and mode scripts; all three
  WhatsApp LaunchAgent plist checksums match. Failed equality only for the
  watcher, as documented above.
- Passed: `launchctl print` confirms the three JARVIS poll jobs are loaded and
  exit 0; confirms the Hermes gateway LaunchAgent is currently running.
- Not run: pytest is unavailable in both `/Users/marlon/.local/bin/python3.11`
  and the Hermes virtual environment (`No module named pytest`). No dependency
  installation was attempted because it would modify the environment.

