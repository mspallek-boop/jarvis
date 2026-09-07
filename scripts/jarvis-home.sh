#!/bin/zsh
# Run HomeKit actions through the Shortcuts app.
#
#   scripts/jarvis-home.sh --list          # what JARVIS can switch
#   scripts/jarvis-home.sh wohnzimmer an   # run the matching shortcut
#
# Why not AppleScript: Home.app on macOS 26 ships no scripting dictionary and
# no NSAppleScriptEnabled (verified on 26.5.2), and the old `home` CLI is gone.
# Shortcuts is the only remaining automation surface for HomeKit, and its Home
# actions bind to a fixed accessory — a device name cannot be passed as an
# argument. So each action is one shortcut, created once by hand:
#
#   Shortcuts.app -> new shortcut -> "Steuere <Gerät>" -> name it
#   "Home: Wohnzimmer an"
#
# Every shortcut whose name starts with the prefix below is then callable here,
# and nothing else in the Shortcuts library is reachable — this cannot be talked
# into running "Alles löschen".
set -euo pipefail

PREFIX="${JARVIS_HOME_PREFIX:-Home: }"

# Anchored at the start of the name, so "Home: " selects only the shortcuts
# meant for JARVIS and never one that merely mentions the word somewhere.
names() {
  shortcuts list 2>/dev/null | while IFS= read -r LINE; do
    [[ "${LINE}" == "${PREFIX}"* ]] && print -r -- "${LINE}"
  done
  return 0
}

if [[ $# -eq 0 || "${1}" == "--list" ]]; then
  OUT=$(names)
  if [[ -z "${OUT}" ]]; then
    print "Keine Home-Kurzbefehle eingerichtet."
    print "Lege in der Kurzbefehle-App einen an, z. B. \"${PREFIX}Wohnzimmer an\"."
    exit 1
  fi
  print -r -- "${OUT}" | /usr/bin/sed "s/^${PREFIX}//"
  exit 0
fi

QUERY="$*"
typeset -a MATCHES
MATCHES=()
# Every word of the query must appear, so "wohnzimmer aus" cannot fire "an".
while IFS= read -r LINE; do
  OK=1
  for WORD in ${=QUERY}; do
    print -r -- "${LINE}" | /usr/bin/grep -qi -- "${WORD}" || OK=0
  done
  (( OK )) && MATCHES+=("${LINE}")
done < <(names)

if [[ ${#MATCHES} -eq 0 ]]; then
  print -u2 "Kein Home-Kurzbefehl für: ${QUERY}"
  print -u2 "Vorhanden: $(names | /usr/bin/sed "s/^${PREFIX}//" | /usr/bin/paste -sd, - | /usr/bin/sed 's/,/, /g')"
  exit 1
fi
if [[ ${#MATCHES} -gt 1 ]]; then
  # Ambiguity switches the wrong light. Ask instead of picking.
  print -u2 "Mehrdeutig — welcher?"
  print -rl -u2 -- ${MATCHES}
  exit 2
fi

shortcuts run "${MATCHES[1]}"
print "Ausgeführt: ${MATCHES[1]#${PREFIX}}"
