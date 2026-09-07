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

PICK=""
if [[ "${1:-}" == "--pick" ]]; then
  PICK="${2:-}"
  if [[ ! "${PICK}" =~ ^[0-9]+$ ]]; then
    print -u2 "usage: jarvis-contact.sh --pick <Nummer> <Suchbegriff>"
    exit 2
  fi
  shift 2
fi

QUERY="${*:-}"
if [[ -z "${QUERY}" ]]; then
  print -u2 "usage: jarvis-contact.sh <name>            # Kontakt suchen"
  print -u2 "       jarvis-contact.sh +49 170 1234567   # Nummer -> Chat-ID"
  print -u2 "       jarvis-contact.sh --pick 2 rici      # aus der Trefferliste waehlen"
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


# ---------------------------------------------------------------- Auswahl
#
# Ambiguity is the dangerous case, not the rare one: "rici" matches two people
# and "mar" matches forty. The old version printed them all and exited 0, which
# reads as success — and a caller that treats it as success picks one and sends
# a message to a stranger. A message sent to the wrong person cannot be taken
# back, so more than one match is now its own exit code, and choosing is a
# separate, explicit step.
#
#   exit 0   exactly one match, safe to use
#   exit 10  several matches, numbered — the caller must ask which
#   exit 1   nothing found
#   exit 3   no access to the contacts and no cache

MATCHES=()

collect() {
  local NAME="$1" NUMBER="$2"
  [[ -z "${NUMBER}" ]] && return
  local DIGITS="${NUMBER//[^0-9+]/}"
  case "${DIGITS}" in
    +*)   DIGITS="${DIGITS#+}" ;;
    00*)  DIGITS="${DIGITS#00}" ;;
    0*)   DIGITS="${DEFAULT_COUNTRY}${DIGITS#0}" ;;
  esac
  MATCHES+=("${NAME:-(ohne Namen)}|${NUMBER}|${DIGITS}")
}

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
  # The full name is matched as well as the parts: "Marcel Richter" is a first
  # and a last name and matches neither column on its own, so without it the
  # most precise query a caller can make is the one that fails.
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
        LOWER(COALESCE(r.ZORGANIZATION,'')) LIKE LOWER('%${NEEDLE}%') OR
        LOWER(TRIM(COALESCE(r.ZFIRSTNAME,'') || ' ' || COALESCE(r.ZLASTNAME,''))) LIKE LOWER('%${NEEDLE}%')
      )
    LIMIT 60;
  " 2>/dev/null) || continue
  [[ -z "${OUT}" ]] && continue
  while IFS='|' read -r NAME NUMBER; do collect "${NAME}" "${NUMBER}"; done <<< "${OUT}"
done

# Live databases unreadable (the usual case for the Hermes gateway): fall back
# to the cache written by --refresh from a permitted context.
if [[ ${#MATCHES} -eq 0 && ${READABLE} -eq 0 && -r "${CACHE}" ]]; then
  # Parsed with awk, not `read`. Tab is a whitespace character, so `read` folds
  # two consecutive tabs into one separator — and a contact with no nickname
  # has exactly that. The fields then shift by one and the chat id comes out
  # empty or wrong, which on the gateway (where the cache is the only path)
  # means a message addressed to nobody, or worse, to someone else.
  while IFS='|' read -r NAME NUMBER DIGITS; do
    [[ -z "${DIGITS}" ]] && continue
    MATCHES+=("${NAME:-(ohne Namen)}|${NUMBER}|${DIGITS}")
  done < <(/usr/bin/awk -F'\t' -v q="${(L)QUERY}" '
    { haystack = tolower($1 " " $2) }
    index(haystack, q) > 0 && $4 != "" {
      name = ($1 != "" ? $1 : $2)
      print name "|" $3 "|" $4
    }' "${CACHE}")
fi

if [[ ${#MATCHES} -eq 0 ]]; then
  if [[ ${READABLE} -eq 0 && ! -r "${CACHE}" ]]; then
    print -u2 "KEIN ZUGRIFF auf die Kontakte (${UNREADABLE} Datenbank(en) gesperrt)"
    print -u2 "und es existiert kein Cache. Einmalig in einem normalen Terminal:"
    print -u2 "  /Users/marlon/Documents/JARVIS/scripts/jarvis-contact.sh --refresh"
    exit 3
  fi
  print "Kein Kontakt gefunden für: ${QUERY}"
  exit 1
fi

# An exact name match beats a substring one, so "Rici" wins over "Riccardo" —
# but only when it is the ONLY exact match. Two people really called Rici stay
# ambiguous, because they are.
typeset -a EXACT
EXACT=()
for ENTRY in "${MATCHES[@]}"; do
  NAME="${ENTRY%%|*}"
  [[ "${(L)NAME}" == "${(L)QUERY}" ]] && EXACT+=("${ENTRY}")
done
(( ${#EXACT} == 1 )) && MATCHES=("${EXACT[@]}")

# De-duplicate: one person with the same number in two address books is one
# person, and counting them twice would invent an ambiguity.
typeset -a UNIQUE
UNIQUE=()
for ENTRY in "${MATCHES[@]}"; do
  SEEN=0
  for KEPT in "${UNIQUE[@]}"; do
    [[ "${ENTRY##*|}" == "${KEPT##*|}" ]] && SEEN=1 && break
  done
  (( SEEN )) || UNIQUE+=("${ENTRY}")
done
MATCHES=("${UNIQUE[@]}")

show() {
  local ENTRY="$1"
  printf '%s | %s | %s@s.whatsapp.net\n' "${ENTRY%%|*}" \
    "$(print -r -- "${ENTRY}" | cut -d'|' -f2)" "${ENTRY##*|}"
}

# --pick chooses from exactly the list the caller was just shown.
if [[ -n "${PICK}" ]]; then
  if (( PICK < 1 || PICK > ${#MATCHES} )); then
    print -u2 "Es gibt nur ${#MATCHES} Treffer für \"${QUERY}\"."
    exit 2
  fi
  show "${MATCHES[PICK]}"
  exit 0
fi

if (( ${#MATCHES} == 1 )); then
  show "${MATCHES[1]}"
  exit 0
fi

print "MEHRDEUTIG: ${#MATCHES} Treffer für \"${QUERY}\" — frag nach, welcher gemeint ist."
INDEX=1
for ENTRY in "${MATCHES[@]}"; do
  printf '%2d) %s\n' "${INDEX}" "$(show "${ENTRY}")"
  INDEX=$((INDEX + 1))
done
print "Auswahl danach mit: jarvis-contact.sh --pick <Nummer> ${QUERY}"
exit 10
