#!/bin/zsh
# Read from and act on whatever program is in front of the user.
#
#   scripts/jarvis-mac.sh clip              # print the clipboard
#   scripts/jarvis-mac.sh clip "neuer text" # put text on the clipboard
#   scripts/jarvis-mac.sh app               # name of the frontmost program
#   scripts/jarvis-mac.sh copy              # press Cmd+C there, print the result
#   scripts/jarvis-mac.sh check             # which of the three actually work
#
# The three commands sit on three different permission levels, and that is the
# whole point of this script:
#
#   clip   pbpaste/pbcopy. No TCC entry, no consent dialog, works everywhere.
#   app    Apple Events to System Events (kTCCServiceAppleEvents).
#   copy   Accessibility (kTCCServiceAccessibility) — synthesising a keystroke
#          into a foreign program is the one thing macOS guards hardest.
#
# Whoever runs this needs the grant, and "whoever" is the Hermes agent's
# interpreter (~/.hermes/hermes-agent/venv/bin/python3), not Terminal and not
# this file. A launchd-started interpreter usually never gets shown the consent
# dialog at all, so `check` reports the truth instead of letting `copy` fail
# silently and look like "nothing was selected".
set -euo pipefail

die() { print -u2 -- "$@"; exit 1; }

GRANT_HINT='Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen,
dort ~/.hermes/hermes-agent/venv/bin/python3 hinzufügen und einschalten.'

case "${1:-clip}" in

  clip)
    if [[ $# -gt 1 ]]; then
      shift
      print -rn -- "$*" | /usr/bin/pbcopy
      print "In der Zwischenablage."
    else
      OUT=$(/usr/bin/pbpaste)
      [[ -n "${OUT}" ]] || die "Die Zwischenablage ist leer."
      print -r -- "${OUT}"
    fi
    ;;

  app)
    /usr/bin/osascript -e 'tell application "System Events" to get name of first process whose frontmost is true' 2>/dev/null \
      || die "Kein Zugriff auf System Events. ${GRANT_HINT}"
    ;;

  copy)
    BEFORE=$(/usr/bin/pbpaste || true)
    # The frontmost process is the target; keystroke goes wherever focus is.
    ERR=$(/usr/bin/osascript -e 'tell application "System Events" to keystroke "c" using command down' 2>&1) || {
      case "${ERR}" in
        *1719*|*ssistive*|*erlaub*|*llowed*)
          die "Darf keine Tasten senden — Bedienungshilfen fehlen.
${GRANT_HINT}" ;;
        *) die "Kopieren fehlgeschlagen: ${ERR}" ;;
      esac
    }
    # The clipboard is filled asynchronously by the target program. Poll rather
    # than sleep a fixed amount: fast apps answer in 50 ms, Electron ones don't.
    for _ in {1..30}; do
      AFTER=$(/usr/bin/pbpaste || true)
      [[ "${AFTER}" != "${BEFORE}" ]] && { print -r -- "${AFTER}"; exit 0; }
      /bin/sleep 0.05
    done
    # Unchanged means either nothing was selected or the selection was already
    # on the clipboard. Both are possible, so say so instead of guessing.
    [[ -n "${BEFORE}" ]] || die "Nichts kopiert — vermutlich war nichts ausgewählt."
    print -r -- "${BEFORE}"
    print -u2 "Hinweis: Die Zwischenablage hat sich nicht geändert. Entweder war nichts ausgewählt, oder es stand schon drin."
    ;;

  check)
    print -n "Zwischenablage: "
    /usr/bin/pbpaste >/dev/null 2>&1 && print "ok" || print "kaputt (sollte nie passieren)"

    print -n "Vordergrund-App: "
    if /usr/bin/osascript -e 'tell application "System Events" to get name of first process whose frontmost is true' >/dev/null 2>&1; then
      print "ok"
    else
      print "fehlt (Automation/Apple Events)"
    fi

    print -n "Tasten senden:   "
    # `key code 63` is the Fn key: a real keystroke for TCC's purposes, but one
    # that does nothing on its own, so the check cannot disturb the user's work.
    if /usr/bin/osascript -e 'tell application "System Events" to key code 63' >/dev/null 2>&1; then
      print "ok"
    else
      print "fehlt (Bedienungshilfen)
${GRANT_HINT}"
    fi
    ;;

  -h|--help|help)
    /usr/bin/sed -n '2,8p' "$0" | /usr/bin/sed 's/^# \{0,1\}//'
    ;;

  *)
    die "Unbekannt: ${1}. Bekannt sind: clip, app, copy, check."
    ;;
esac
