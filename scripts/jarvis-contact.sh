#!/bin/zsh
# Resolve a contact name to WhatsApp chat ids, from the macOS Contacts store.
#
#   scripts/jarvis-contact.sh rici
#
# JARVIS calls this when the user names a person ("schreib rici") instead of a
# number. Prints one line per matching phone number:
#
#   Riccardo Mayer | +43 660 1234567 | 436601234567@s.whatsapp.net
#
# Read-only. Opens the databases immutable so a running Contacts.app is never
# disturbed. Prints nothing but matches — it is a lookup, not a dump, so a typo
# cannot page through the address book.
set -euo pipefail

QUERY="${*:-}"
if [[ -z "${QUERY}" ]]; then
  print -u2 "usage: jarvis-contact.sh <name>"
  exit 2
fi
if [[ ${#QUERY} -lt 2 ]]; then
  print -u2 "Suchbegriff zu kurz — bitte mindestens zwei Zeichen."
  exit 2
fi

BASE="${HOME}/Library/Application Support/AddressBook"
typeset -a DBS
DBS=("${BASE}/AddressBook-v22.abcddb" ${BASE}/Sources/*/AddressBook-v22.abcddb(N))

# SQL-escape single quotes in the needle.
NEEDLE="${QUERY//\'/\'\'}"

FOUND=0
READABLE=0
UNREADABLE=0
for DB in "${DBS[@]}"; do
  [[ -f "${DB}" ]] || continue
  # Probe first. Without this, a TCC denial looks identical to "no such contact",
  # which sends the caller hunting for spelling mistakes that do not exist.
  if ! /usr/bin/sqlite3 "file://${DB}?immutable=1" 'SELECT 1 FROM ZABCDRECORD LIMIT 1;' >/dev/null 2>&1; then
    UNREADABLE=$((UNREADABLE + 1))
    continue
  fi
  READABLE=$((READABLE + 1))
  OUT=$(/usr/bin/sqlite3 -separator '|' "file://${DB}?immutable=1" "
    SELECT
      TRIM(COALESCE(r.ZFIRSTNAME,'') || ' ' || COALESCE(r.ZLASTNAME,'')),
      p.ZFULLNUMBER
    FROM ZABCDPHONENUMBER p
    JOIN ZABCDRECORD r ON r.Z_PK = p.ZOWNER
    WHERE p.ZFULLNUMBER IS NOT NULL
      AND (
        LOWER(COALESCE(r.ZFIRSTNAME,''))    LIKE LOWER('%${NEEDLE}%') OR
        LOWER(COALESCE(r.ZLASTNAME,''))     LIKE LOWER('%${NEEDLE}%') OR
        LOWER(COALESCE(r.ZNICKNAME,''))     LIKE LOWER('%${NEEDLE}%') OR
        LOWER(COALESCE(r.ZORGANIZATION,'')) LIKE LOWER('%${NEEDLE}%')
      )
    LIMIT 40;
  " 2>/dev/null) || continue

  [[ -z "${OUT}" ]] && continue
  while IFS='|' read -r NAME NUMBER; do
    [[ -z "${NUMBER}" ]] && continue
    # Strip everything but digits; turn a leading 00 or a national 0 into E.164.
    DIGITS="${NUMBER//[^0-9+]/}"
    case "${DIGITS}" in
      +*)   DIGITS="${DIGITS#+}" ;;
      00*)  DIGITS="${DIGITS#00}" ;;
      0*)   DIGITS="43${DIGITS#0}" ;;   # local number: assume Austria (+43)
    esac
    printf '%s | %s | %s@s.whatsapp.net\n' "${NAME:-(ohne Namen)}" "${NUMBER}" "${DIGITS}"
    FOUND=1
  done <<< "${OUT}"
done

if [[ ${FOUND} -eq 0 ]]; then
  if [[ ${READABLE} -eq 0 ]]; then
    print -u2 "KEIN ZUGRIFF auf die Kontakte (${UNREADABLE} Datenbank(en) gesperrt)."
    print -u2 "Das ist eine macOS-Freigabe, kein Tippfehler: der aufrufende Prozess"
    print -u2 "braucht Zugriff auf 'Kontakte' bzw. Festplattenvollzugriff."
    exit 3
  fi
  print "Kein Kontakt gefunden für: ${QUERY}"
  exit 1
fi
