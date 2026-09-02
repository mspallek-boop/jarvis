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

CACHE="${HOME}/.hermes/contacts.cache.tsv"

QUERY="${*:-}"
if [[ -z "${QUERY}" ]]; then
  print -u2 "usage: jarvis-contact.sh <name>            # Kontakt suchen"
  print -u2 "       jarvis-contact.sh --refresh         # Cache neu aufbauen"
  exit 2
fi
if [[ ${#QUERY} -lt 2 ]]; then
  print -u2 "Suchbegriff zu kurz — bitte mindestens zwei Zeichen."
  exit 2
fi

BASE="${HOME}/Library/Application Support/AddressBook"
typeset -a DBS
DBS=("${BASE}/AddressBook-v22.abcddb" ${BASE}/Sources/*/AddressBook-v22.abcddb(N))

# Normalise a stored number to the digits WhatsApp expects.
normalise() {
  local d="${1//[^0-9+]/}"
  case "${d}" in
    +*)  d="${d#+}" ;;
    00*) d="${d#00}" ;;
    0*)  d="43${d#0}" ;;   # local number: assume Austria (+43)
  esac
  print -r -- "${d}"
}

# Dump every contact into a cache the Hermes gateway can read.
#
# The gateway is denied the Contacts database by macOS (TCC), and the grant is
# awkward: it attributes to the resolved uv interpreter, not the venv symlink in
# the LaunchAgent. Run this once from a context that *does* have access — a
# normal Terminal — and lookups work from anywhere afterwards. Re-run it when
# contacts change; the cache does not update itself.
if [[ "${QUERY}" == "--refresh" ]]; then
  TMP=$(mktemp "${TMPDIR:-/tmp}/jarvis-contacts.XXXXXX")
  COUNT=0
  for DB in "${DBS[@]}"; do
    [[ -f "${DB}" ]] || continue
    OUT=$(/usr/bin/sqlite3 -separator '|' "file://${DB}?immutable=1" "
      SELECT TRIM(COALESCE(r.ZFIRSTNAME,'') || ' ' || COALESCE(r.ZLASTNAME,'')),
             COALESCE(r.ZNICKNAME,''), p.ZFULLNUMBER
      FROM ZABCDPHONENUMBER p JOIN ZABCDRECORD r ON r.Z_PK = p.ZOWNER
      WHERE p.ZFULLNUMBER IS NOT NULL;" 2>/dev/null) || continue
    [[ -z "${OUT}" ]] && continue
    while IFS='|' read -r NAME NICK NUMBER; do
      [[ -z "${NUMBER}" ]] && continue
      printf '%s\t%s\t%s\t%s\n' "${NAME}" "${NICK}" "${NUMBER}" "$(normalise "${NUMBER}")" >> "${TMP}"
      COUNT=$((COUNT + 1))
    done <<< "${OUT}"
  done
  if [[ ${COUNT} -eq 0 ]]; then
    rm -f "${TMP}"
    print -u2 "Cache NICHT geschrieben: keine Kontakte lesbar."
    print -u2 "Führe diesen Befehl in einem normalen Terminal aus, nicht über JARVIS."
    exit 3
  fi
  mkdir -p "${HOME}/.hermes"
  sort -u "${TMP}" > "${CACHE}"
  rm -f "${TMP}"
  chmod 600 "${CACHE}"   # private data: owner-readable only
  print "Cache geschrieben: $(wc -l < "${CACHE}" | tr -d ' ') Nummern -> ${CACHE}"
  exit 0
fi

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

# Live databases unreadable (the usual case for the Hermes gateway): fall back
# to the cache written by --refresh from a permitted context.
if [[ ${FOUND} -eq 0 && ${READABLE} -eq 0 && -r "${CACHE}" ]]; then
  while IFS=$'\t' read -r NAME NICK NUMBER DIGITS; do
    if print -r -- "${NAME} ${NICK}" | /usr/bin/grep -qi -- "${QUERY}"; then
      printf '%s | %s | %s@s.whatsapp.net\n' "${NAME:-${NICK:-(ohne Namen)}}" "${NUMBER}" "${DIGITS}"
      FOUND=1
    fi
  done < "${CACHE}"
  if [[ ${FOUND} -eq 1 ]]; then
    AGE_DAYS=$(( ( $(date +%s) - $(/usr/bin/stat -f %m "${CACHE}") ) / 86400 ))
    (( AGE_DAYS >= 30 )) && print -u2 "(Hinweis: Kontakt-Cache ist ${AGE_DAYS} Tage alt — 'jarvis-contact.sh --refresh' im Terminal aktualisiert ihn.)"
    exit 0
  fi
fi

if [[ ${FOUND} -eq 0 ]]; then
  if [[ ${READABLE} -eq 0 ]]; then
    if [[ -r "${CACHE}" ]]; then
      print "Kein Kontakt gefunden für: ${QUERY} (im Cache gesucht, Live-Datenbank gesperrt)"
      exit 1
    fi
    print -u2 "KEIN ZUGRIFF auf die Kontakte (${UNREADABLE} Datenbank(en) gesperrt)"
    print -u2 "und es existiert kein Cache."
    print -u2 "Einmalig in einem normalen Terminal ausführen:"
    print -u2 "  /Users/marlon/Documents/JARVIS/scripts/jarvis-contact.sh --refresh"
    exit 3
  fi
  print "Kein Kontakt gefunden für: ${QUERY}"
  exit 1
fi
