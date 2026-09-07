#!/bin/zsh
# Resolve a contact name to WhatsApp chat ids, from the macOS Contacts store.
#
#   scripts/jarvis-contact.sh rici
#   scripts/jarvis-contact.sh +49 170 1234567     # a number the user dictated
#
# JARVIS calls this when the user names a person ("schreib rici") instead of a
# number. Prints one line per matching phone number:
#
#   Riccardo Mayer | +43 660 1234567 | 436601234567@s.whatsapp.net
#
# Given a number rather than a name it converts that number to a chat id and
# reverse-looks-up whoever it is stored as, so JARVIS can name the recipient in
# its confirmation instead of reading digits back.
#
# Read-only. Opens the databases immutable so a running Contacts.app is never
# disturbed. Prints nothing but matches — it is a lookup, not a dump, so a typo
# cannot page through the address book.
set -euo pipefail

CACHE="${HOME}/.hermes/contacts.cache.tsv"

# Country code for numbers stored without one ("0170..."). Only 37 of ~855
# stored numbers are in that form, so this is a tie-break, not a policy: it
# defaults to the country of the owner's own WhatsApp account (+49) and any
# line resolved this way says so, because a wrong guess sends a message to a
# stranger. Override with JARVIS_DEFAULT_COUNTRY=43.
DEFAULT_COUNTRY="${JARVIS_DEFAULT_COUNTRY:-49}"

QUERY="${*:-}"
if [[ -z "${QUERY}" ]]; then
  print -u2 "usage: jarvis-contact.sh <name>            # Kontakt suchen"
  print -u2 "       jarvis-contact.sh +49 170 1234567   # Nummer -> Chat-ID"
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
    0*)  d="${DEFAULT_COUNTRY}${d#0}" ;;   # no country code stored
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

# A number, not a name. "+49 170 123 45 67", "0049...", "0170..." and a bare
# "49170..." all mean the same chat. Resolve it directly instead of hunting the
# address book for a contact called "+49" — that lookup can only ever fail, and
# failing sent JARVIS back to the user for a number they had just given it.
DIGITS_ONLY="${QUERY//[^0-9]/}"
if [[ "${QUERY}" == [+0-9]* && "${QUERY//[0-9 +\/()·.-]/}" == "" && ${#DIGITS_ONLY} -ge 6 ]]; then
  NUM=$(normalise "${QUERY//[ \/()·.-]/}")
  if [[ ${#NUM} -lt 8 || ${#NUM} -gt 15 ]]; then
    print -u2 "Das sieht nicht nach einer vollständigen Telefonnummer aus: ${QUERY}"
    exit 2
  fi
  # Name the recipient if we know them. Confirming "an Riccardo Mayer" is a far
  # better check against a mistyped digit than reading the number back.
  NAME=""
  if [[ -r "${CACHE}" ]]; then
    # A stored-but-unnamed number is not an unknown one — say which it is.
    NAME=$(/usr/bin/awk -F'\t' -v n="${NUM}" '$4 == n {
      name = ($1 != "" ? $1 : $2); print (name != "" ? name : "(gespeichert, ohne Namen)"); exit }' "${CACHE}")
  fi
  ASSUMED=""
  [[ "${QUERY}" == 0* && "${QUERY}" != 00* ]] && ASSUMED=" (Ländervorwahl +${DEFAULT_COUNTRY} angenommen)"
  printf '%s | +%s | %s@s.whatsapp.net%s\n' "${NAME:-(nicht in Kontakten)}" "${NUM}" "${NUM}" "${ASSUMED}"
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
      0*)   DIGITS="${DEFAULT_COUNTRY}${DIGITS#0}" ;;   # no country code stored
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
