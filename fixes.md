# JARVIS — Fixes und offene Punkte

Stand: 2026-09-07. Bridge auf `127.0.0.1:8770` neu deployt und verifiziert.

## Erledigt

### 1. ElevenLabs-Guthaben aufgebraucht → lokale Stimme
Der Account läuft auf dem Free-Tier und ist bei 10.000/10.000 Zeichen.
ElevenLabs antwortet seither auf **jede** Anfrage mit HTTP 401, die Bridge
machte daraus 503 — JARVIS war schlicht stumm. Beide Sprachwege fallen jetzt
auf die eingebaute macOS-Stimme zurück (`bridge/jarvis_bridge.py` für die App,
`server/server.py` für HUD und Voice-Pipeline), bei 401/402/429, fehlendem
Schlüssel und auch wenn der neuronale Worker auf `:8788` nicht läuft.
Das Audioformat bleibt identisch, die App braucht keine Änderung.
Abschaltbar mit `JARVIS_TTS_FALLBACK=""`, Stimme wählbar mit
`JARVIS_TTS_MACOS_VOICE`.

*Besser wird es sofort mit einer Premium-Stimme:* Systemeinstellungen →
Bedienungshilfen → Gesprochene Inhalte → Systemstimme → Stimmen verwalten →
eine deutsche Premium-Stimme laden, dann deren Namen in
`JARVIS_TTS_MACOS_VOICE` eintragen. Aktuell installiert ist nur die
Standardauswahl, JARVIS spricht daher mit "Anna".

### 2. WhatsApp-Nummer im internationalen Format
`scripts/jarvis-contact.sh` nahm nur Namen. Eine diktierte Nummer lief in die
Namenssuche und konnte nur scheitern. Die Nummer geht jetzt direkt an dasselbe
Skript, in jedem Format (`+49 170 …`, `0049…`, `0170…`), und das Skript sagt
zusätzlich, unter welchem Namen die Nummer gespeichert ist — eine verhörte
Ziffer fällt als "an Riccardo?" auf, als dreizehn vorgelesene Ziffern nicht.
Die Ländervorwahl für Nummern ohne eigene (`0170…`) ist jetzt konfigurierbar
und steht auf +49 statt bisher +43: das eigene WhatsApp-Konto ist deutsch und
das Adressbuch enthält 638 deutsche gegenüber 167 österreichischen Nummern.
Betroffen sind nur 37 von 855 Einträgen, und jede so aufgelöste Zeile sagt
dazu, dass die Vorwahl angenommen wurde.

### 3. HomeKit-Licht
Die Diagnose in der alten Notiz stimmt: Home.app hat auf macOS 26.5.2 kein
Scripting-Dictionary und kein `NSAppleScriptEnabled`, das `home`-CLI ist weg.
AppleScript ist endgültig tot. Neu ist `scripts/jarvis-home.sh`: es listet und
startet Kurzbefehle mit dem Präfix `Home: ` und rührt nichts anderes in der
Kurzbefehle-Bibliothek an. Bei mehreren Treffern fragt es nach, statt zu raten.

**Einmalig von Hand nötig:** pro Aktion ein Kurzbefehl in der Kurzbefehle-App
("Steuere <Gerät>"), benannt `Home: Wohnzimmer an`. Die Home-Aktionen von
Shortcuts sind fest an ein Gerät gebunden, ein Gerätename lässt sich nicht als
Argument übergeben — deshalb ein Kurzbefehl je Aktion und keine generische
Lösung. Noch ist keiner angelegt, JARVIS meldet das ehrlich statt zu behaupten,
HomeKit sei nicht erreichbar.

### 4. Multitasking und Benachrichtigungen — Backend-Seite
Zwei neue Endpoints in der Bridge:

- `GET /runs` — alle laufenden Turns mit Phase, Tool, Conversation und Alter,
  längster zuerst, ohne Prompt- oder Antworttext.
- `POST /chat` mit `"parallel": true` — Aufgaben laufen jetzt **wirklich**
  nebeneinander, ohne dass die App eigene Conversations vergeben muss. Drei
  Aufgaben: 3 s statt 6 s, gemessen. Eine Nebenspur trägt die Historie der
  Hauptunterhaltung nicht — das Flag ist für "mach beides", nicht für eine
  Rückfrage.
- `GET /notifications`, `POST /notify`, `POST /notifications/read` — der Kanal,
  über den JARVIS von sich aus etwas melden kann, **in der App** statt als
  macOS-Mitteilung. Pull-Warteschlange, überlebt einen Bridge-Neustart, auf 50
  Einträge begrenzt.

Die WhatsApp-Antwort geht jetzt diesen Weg. Die System-Mitteilung ist nur noch
Rückfallebene für den Fall, dass die Bridge nicht läuft.

Die Oberfläche gehört Codex. Die Vorgabe dafür steht in
`docs/APP_UI_MULTITASKING_NOTIFICATIONS.md` — mit dem einen Prüfstein, der
"clean" überprüfbar macht: **bei null Aufgaben und null Benachrichtigungen muss
die App pixelgleich aussehen wie heute.**

### 5. Bild-Anhänge im Chat
Die `MEDIA:`- und Inline-Bild-Verarbeitung war im Repository bereits fertig und
getestet, aber nie nach `~/.hermes/services/` kopiert worden — die laufende
Bridge war noch auf dem Stand des letzten Commits. Mit dem Deploy ist sie jetzt
live. Dateien, die keine Bilder sind, bleiben Text: dafür gibt es im
Antwortformat keinen Anhangstyp.

## WhatsApp

### 6. WhatsApp — Antwort-Benachrichtigung und Empfangs-Schalter
**Erledigt, aber anders als zuerst geplant.**

Was du wolltest — JARVIS behält den Chat im Auge und sagt dezent Bescheid, wenn
die Person geantwortet hat — braucht den Bot-Modus gar nicht. Es läuft jetzt:

- `scripts/jarvis-whatsapp-watch.py` beobachtet einen Chat nach dem Senden.
  Kommt eine Antwort, gibt es innerhalb von ~30 s eine macOS-Mitteilung
  ("Rici hat geantwortet.") und, falls ein HUD offen ist, einen gesprochenen
  Satz. Watches laufen nach 48 h von selbst ab.
- Läuft als `com.jarvis.whatsapp-watch` alle 30 Sekunden. Am echten Bridge-Log
  verifiziert: gefeuert nach 15 s, Watch danach abgeräumt.
- Gelesen wird das Bridge-Log, **nicht** `GET /messages` — dieser Endpoint
  *leert* die Queue, ein zweiter Leser würde dem Gateway Nachrichten wegnehmen.
- Es wird **nie** gespeichert oder weitergegeben, *was* jemand geschrieben hat.
  Nur dass geantwortet wurde und von wem. Der Inhalt bleibt in WhatsApp.
- JARVIS setzt den Watch selbst; steht in der SOUL.

**Warum der Bot-Modus nicht einfach an ist:** ich habe ihn mir angesehen,
nachdem du zugestimmt hattest, und dabei drei Dinge gefunden, die meine erste
Auskunft überholt haben.

1. Mit der aktuellen Allowlist (nur deine eigene Nummer) verwirft der Bot-Modus
   fremde Nachrichten weiterhin — er hätte gar nichts empfangen.
2. Im Bot-Modus werden deine *eigenen* Nachrichten verworfen. Dein WhatsApp-Chat
   mit JARVIS wäre tot gewesen.
3. Angenommene Nachrichten werden nicht geloggt — der neue Watcher wäre für
   genau die Kontakte blind geworden, um die es geht.

### 6b. Der Schalter (statt Dauerzustand)

`scripts/jarvis-whatsapp-mode.py` macht den Empfang zu einer bewussten,
befristeten Entscheidung:

```
jarvis-whatsapp-mode.py status
jarvis-whatsapp-mode.py on --contact "+49 170 1234567" --for 2h
jarvis-whatsapp-mode.py off
```

- Setzt die drei Schlüssel, die zusammengehören: `WHATSAPP_MODE=bot`,
  `WHATSAPP_FORWARD_OWNER_MESSAGES` (dein eigener Chat lebt weiter) und
  `WHATSAPP_DEBUG` (der Watcher bleibt sehend). Deshalb ein Skript und keine
  einzelne Zeile in der `.env`.
- `--for` ist optional, aber empfohlen. `com.jarvis.whatsapp-mode` prüft jede
  Minute und schaltet nach Ablauf selbst zurück — sonst heißt "an bis 18 Uhr"
  beim ersten Zuklappen des Laptops "an für immer".
- `off` stellt die `.env` **byte-genau** wieder her, aus dem gespeicherten
  Vorzustand. Vor jeder Änderung wird gesichert, Rechte bleiben 600, fremde
  Schlüssel und Kommentare bleiben unberührt — alles per Test abgesichert.
- Ohne `--contact` verweigert es. `*` wird abgelehnt: ein offener Bot würde
  Fremden antworten.
- **Solange es an ist, antwortet JARVIS diesen Kontakten selbständig.** Die SOUL
  behandelt `on` deshalb wie das Senden einer Nachricht: nachfragen, warten.

Aktuell steht alles auf `self-chat`, also aus.

## Offen

### 7. WhatsApp-Anrufe
Nicht baubar. Die Bridge nutzt Baileys, und Baileys kann Anrufe nur
**ablehnen** (`rejectCall`) — ausgehende Anrufe implementiert es nicht, und die
WhatsApp Business Cloud API bietet sie ebenso wenig. Kein Aufwand, keine
Konfiguration: das Protokoll ist nicht offen.

Naheliegende Alternative, falls gewünscht: ein normaler Telefonanruf über
Continuity (`open tel://+49…` auf dem Mac klingelt über das iPhone). Das wäre
ein kleines Skript in derselben Machart wie `jarvis-contact.sh`.

### 8. Mute-Button
Konnte ich nicht reproduzieren. Der App-Pfad sieht korrekt aus:
`speaksReplies` stoppt die laufende Ausgabe und wird bei jedem Delta erneut
geprüft. Was "funktioniert nicht" genau heißt, entscheidet die Diagnose —
und der Code gehört Codex, nicht mir. Bitte einmal genauer:

- Spricht JARVIS **weiter**, während er gerade spricht, oder erst bei der
  **nächsten** Antwort wieder?
- Mac oder iPhone?
- Ist dabei das HUD im Browser offen? Das spricht über den Voice-Server auf
  Port 8765 und wird vom Mute-Schalter der App gar nicht erfasst — das wäre
  eine echte, getrennte Ursache.

## Betrieb — dringend

**Die Festplatte ist voll.** 1,5 GiB frei von 228 GiB, Datenvolumen bei 100 %.
Das hat schon Schaden angerichtet: die WhatsApp-Bridge ist mit
`ENOSPC: no space left on device` beim Schreiben von `creds.json` abgestürzt.
Eine kaputte `creds.json` kostet die WhatsApp-Kopplung. Das ist unabhängig von
allem oben und sollte zuerst passieren.
