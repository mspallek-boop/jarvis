#!/bin/zsh
# JARVIS self-repair: hand a bounded task to a coding agent, then report back.
#
# JARVIS (the Hermes agent) calls this through its terminal tool when the user
# reports that JARVIS itself is broken. It is the trust boundary: the agent
# supplies a task description, this script decides what the coding agent is
# allowed to touch.
#
#   scripts/jarvis-selffix.sh "Die Bridge liefert 500 auf /files"
#   BACKEND=claude scripts/jarvis-selffix.sh "..."
#
# Deliberately NOT done here: commit, push, sudo, service restarts, or anything
# outside the repo. A human reviews the diff. Self-repair that can also ship
# itself is how a small bug becomes an unrecoverable one.
set -euo pipefail

REPO=/Users/marlon/Documents/JARVIS
LOG_DIR="${REPO}/server/logs/selffix"
BACKEND="${BACKEND:-codex}"
MAX_MIN="${MAX_MIN:-15}"

TASK="${*:-}"
if [[ -z "${TASK}" ]]; then
  print -u2 "usage: jarvis-selffix.sh <task description>"
  exit 2
fi

# One job at a time. Two agents editing the same worktree corrupts it.
LOCK="/tmp/jarvis-selffix.lock"
if ! mkdir "${LOCK}" 2>/dev/null; then
  print "Ein Self-Fix läuft bereits. Bitte warte, bis er fertig ist."
  exit 3
fi
trap 'rmdir "${LOCK}" 2>/dev/null || true' EXIT

mkdir -p "${LOG_DIR}"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="${LOG_DIR}/${STAMP}.log"

cd "${REPO}"

# Record the pre-state so the report can name exactly what changed.
BEFORE=$(git status --porcelain | sort)
HEAD_BEFORE=$(git rev-parse HEAD)

BRIEF="Du arbeitest im JARVIS-Repository ${REPO}.

AUFGABE: ${TASK}

Regeln:
- Ändere nur Dateien in diesem Repository.
- Committe nicht, pushe nicht, wechsle den Branch nicht.
- Kein sudo, keine Systemeinstellungen, keine Dienste neu starten,
  keine launchctl-Aufrufe, nichts löschen außerhalb des Repos.
- Fasse ~/.hermes/.env nicht an und gib keine Tokens oder Schlüssel aus.
- apple/ gehört Codex-Sessions des Nutzers: nur anfassen, wenn die Aufgabe
  es ausdrücklich verlangt.
- Führe nach der Änderung die Tests aus:
    PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache .venv/bin/python -m pytest -q
- Wenn du die Ursache nicht sicher findest, ändere nichts und sage das.
  Eine falsche Vermutung umzusetzen ist schlimmer als keine Änderung.

Antworte am Ende in drei kurzen Sätzen: was war kaputt, was hast du geändert,
was sagen die Tests."

{
  print "=== jarvis-selffix ${STAMP} ==="
  print "backend: ${BACKEND}"
  print "task:    ${TASK}"
  print "head:    ${HEAD_BEFORE}"
  print "---"
} | tee "${LOG}"

set +e
case "${BACKEND}" in
  codex)
    # Workspace-write keeps the agent inside the repo; no network, no escalation.
    /opt/homebrew/bin/codex exec \
      --cd "${REPO}" \
      --sandbox workspace-write \
      "${BRIEF}" 2>&1 | tee -a "${LOG}"
    RC=${pipestatus[1]}
    ;;
  claude)
    # Requires a one-time interactive `claude` + /login on this machine.
    "${HOME}/.local/bin/claude" -p "${BRIEF}" \
      --permission-mode acceptEdits \
      --add-dir "${REPO}" \
      --disallowedTools "Bash(git push:*)" "Bash(git commit:*)" "Bash(sudo:*)" \
                        "Bash(launchctl:*)" "Bash(rm -rf:*)" \
      --max-turns 40 2>&1 | tee -a "${LOG}"
    RC=${pipestatus[1]}
    ;;
  *)
    print -u2 "unbekanntes BACKEND: ${BACKEND} (erlaubt: codex, claude)"
    exit 2
    ;;
esac
set -e

AFTER=$(git status --porcelain | sort)
HEAD_AFTER=$(git rev-parse HEAD)

print "\n=== Ergebnis ===" | tee -a "${LOG}"
if [[ "${HEAD_BEFORE}" != "${HEAD_AFTER}" ]]; then
  print "WARNUNG: HEAD hat sich bewegt (${HEAD_BEFORE} -> ${HEAD_AFTER}) — es wurde entgegen der Vorgabe committet." | tee -a "${LOG}"
fi
if [[ "${BEFORE}" == "${AFTER}" ]]; then
  print "Keine Dateien geändert." | tee -a "${LOG}"
else
  print "Geänderte Dateien:" | tee -a "${LOG}"
  git status --porcelain | tee -a "${LOG}"
  print "\nDiff-Umfang:" | tee -a "${LOG}"
  git diff --stat | tail -20 | tee -a "${LOG}"
fi
print "\nExit ${RC}. Vollständiges Log: ${LOG}" | tee -a "${LOG}"
print "Die Änderungen sind NICHT committet — bitte prüfen." | tee -a "${LOG}"
exit "${RC}"
