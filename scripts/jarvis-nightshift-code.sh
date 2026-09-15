#!/bin/zsh
# JARVIS night shift, code part: one bounded task, worked in a throwaway git
# worktree so neither Marlon's checkout nor a running Codex session ever sees a
# half-done edit. What survives is a patch plus a log in
# "Jarvis Output/Nachtschicht/", reviewed in the morning briefing.
#
#   scripts/jarvis-nightshift-code.sh "<task>"
#   BACKEND=claude|qwen|none scripts/jarvis-nightshift-code.sh "<task>"
#
# BACKEND=none runs the pipeline without an agent (worktree, tests, patch) so
# the plumbing can be checked without spending any subscription quota.
#
# Deliberately NOT done here: commit, push, branch changes, service restarts,
# or edits to the main checkout. The worktree is detached and removed at exit.
set -euo pipefail

REPO="${JARVIS_REPO:-/Users/marlon/Developer/JARVIS}"
OUT_DIR="${OUT_DIR:-${REPO}/Jarvis Output/Nachtschicht}"
BACKEND="${BACKEND:-codex}"
CODEX_BIN="${CODEX_BIN:-/opt/homebrew/bin/codex}"

TASK="${*:-}"
if [[ -z "${TASK}" ]]; then
  print -u2 "usage: jarvis-nightshift-code.sh <task description>"
  exit 2
fi
case "${BACKEND}" in
  codex|claude|qwen|none) ;;
  *) print -u2 "unbekanntes BACKEND: ${BACKEND} (erlaubt: codex, claude, qwen, none)"; exit 2 ;;
esac

# One run at a time; the night shift has no reason to run two agents at once.
LOCK="/tmp/jarvis-nightshift-code.lock"
if ! mkdir "${LOCK}" 2>/dev/null; then
  print "Die Code-Arbeit der Nachtschicht läuft bereits."
  exit 3
fi

STAMP=$(date +%Y-%m-%d_%H%M%S)
WT="/tmp/jarvis-nightshift-${STAMP}"
cleanup() {
  git -C "${REPO}" worktree remove --force "${WT}" >/dev/null 2>&1 || true
  rmdir "${LOCK}" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "${OUT_DIR}"
LOG="${OUT_DIR}/${STAMP}-code.log"
PATCH="${OUT_DIR}/${STAMP}-code.patch"

git -C "${REPO}" worktree add --detach "${WT}" HEAD >/dev/null 2>&1
BASE=$(git -C "${WT}" rev-parse --short HEAD)
# Nearly every test imports the voice server, which reads this Git-ignored
# local config (no secrets). Without it a fresh worktree is all red.
if [[ -f "${REPO}/server/config/server.yaml" ]]; then
  cp "${REPO}/server/config/server.yaml" "${WT}/server/config/server.yaml"
fi

BRIEF="Du arbeitest in ${WT}, einer Wegwerf-Kopie (git worktree) des
JARVIS-Repositorys. Dein Ergebnis wird als Patch gespeichert und morgens von
Marlon geprüft.

AUFGABE: ${TASK}

Regeln:
- Ändere nur Dateien in ${WT}.
- Committe nicht, pushe nicht, wechsle den Branch nicht.
- Kein sudo, keine Systemeinstellungen, keine Dienste neu starten,
  keine launchctl-Aufrufe, nichts löschen außerhalb von ${WT}.
- Fasse ~/.hermes nicht an und gib keine Tokens oder Schlüssel aus.
- Sende keine Nachrichten, rufe niemanden an, veröffentliche nichts.
- Tests laufen so (aus ${WT}):
    PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache ${REPO}/.venv/bin/python -m pytest -q -p no:cacheprovider
- Wenn du die Ursache nicht sicher findest, ändere nichts und sage das.
  Eine falsche Vermutung umzusetzen ist schlimmer als keine Änderung.

Antworte am Ende in drei kurzen Sätzen: was war das Problem, was hast du
geändert, was sagen die Tests."

{
  print "=== jarvis-nightshift-code ${STAMP} ==="
  print "backend:  ${BACKEND}"
  print "task:     ${TASK}"
  print "base:     ${BASE}"
  print "worktree: ${WT}"
  print "---"
} | tee "${LOG}"

set +e
case "${BACKEND}" in
  codex)
    "${CODEX_BIN}" exec --cd "${WT}" --sandbox workspace-write "${BRIEF}" 2>&1 | tee -a "${LOG}"
    RC=${pipestatus[1]}
    ;;
  claude)
    (cd "${WT}" && "${HOME}/.local/bin/claude" -p "${BRIEF}" \
      --permission-mode acceptEdits \
      --disallowedTools "Bash(git push:*)" "Bash(git commit:*)" "Bash(sudo:*)" \
                        "Bash(launchctl:*)" "Bash(rm -rf:*)" \
      --max-turns 40) 2>&1 | tee -a "${LOG}"
    RC=${pipestatus[1]}
    ;;
  qwen)
    (cd "${WT}" && "${HOME}/.local/bin/qwen" "${BRIEF}" --approval-mode auto-edit) 2>&1 | tee -a "${LOG}"
    RC=${pipestatus[1]}
    ;;
  none)
    print "(kein Agent — nur die Pipeline)" | tee -a "${LOG}"
    RC=0
    ;;
esac

# The agent's own test claim is not the result; this run is.
print "\n=== Tests ===" | tee -a "${LOG}"
(cd "${WT}" && PYTHONPYCACHEPREFIX=/tmp/jarvis-pycache "${REPO}/.venv/bin/python" -m pytest -q -p no:cacheprovider) \
  > "${LOG}.tests" 2>&1
TEST_RC=$?
tail -5 "${LOG}.tests" | tee -a "${LOG}"
rm -f "${LOG}.tests"
set -e

git -C "${WT}" add -A
print "\n=== Ergebnis ===" | tee -a "${LOG}"
if git -C "${WT}" diff --cached --quiet; then
  print "Keine Dateien geändert." | tee -a "${LOG}"
  PATCH_NOTE="kein Patch"
else
  git -C "${WT}" diff --cached --binary > "${PATCH}"
  git -C "${WT}" diff --cached --stat | tail -20 | tee -a "${LOG}"
  PATCH_NOTE="${PATCH}"
fi
print "Agent-Exit: ${RC}. Tests: $([[ ${TEST_RC} -eq 0 ]] && print grün || print "rot (Exit ${TEST_RC})")." | tee -a "${LOG}"
print "Patch: ${PATCH_NOTE}" | tee -a "${LOG}"
print "Log:   ${LOG}" | tee -a "${LOG}"
print "Nichts ist committet oder im Haupt-Checkout geändert." | tee -a "${LOG}"
exit "${RC}"
