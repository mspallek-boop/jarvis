# JARVIS — Fixes und offene Punkte

Stand: 2026-09-07. Bridge auf `127.0.0.1:8770` neu deployt und verifiziert.

## Erledigt

### 1. Stimme — Piper statt ElevenLabs
Der ElevenLabs-Account ist Free-Tier und bei 10.000/10.000 Zeichen; er antwortet
auf jede Anfrage mit HTTP 401. Der erste Fix fiel auf die macOS-Stimme "Anna"
zurück — die ist eine der alten Kompakt-Stimmen und klingt zu Recht schrecklich.

Jetzt läuft **Piper** mit der deutschen Stimme "Thorsten": lokales neuronales
TTS, offline, kostenlos, kein Konto, kein Kontingent. Die Bridge streamt es im
identischen Format wie vorher (24 kHz PCM), die App merkt nichts davon.

- Umgebung: `~/.hermes/piper-venv`, Modell in `~/.hermes/piper-voices`
  (109 MB, `de_DE-thorsten-high`).
- Piper läuft mit 22,05 kHz, der Player der App akzeptiert nur 24 kHz — die
  Bridge rechnet um, damit das Wire-Format ein einziger fester Vertrag bleibt
  und eine neue Stimme nie eine Änderung im Swift-Client wird.
- Reihenfolge: ElevenLabs (falls je wieder Guthaben) → Piper → macOS `say`.
  Der Antwort-Header `X-JARVIS-Speech-Provider` sagt, wer geantwortet hat.
- Andere Stimme: `JARVIS_PIPER_MODEL` auf ein anderes Modell zeigen lassen.
  Verfügbar sind u. a. `de_DE-kerstin-low`, `de_DE-ramona-low`,
  `de_DE-eva_k-x_low` und `de_DE-thorsten_emotional-medium`.

Am laufenden Dienst verifiziert: HTTP 200, Provider `piper`, 4,17 s Audio.

### 1b. Mute-Knopf — er machte das Falsche
Kein Bug: der Knopf hing an `speaksReplies` und schaltete JARVIS' *Stimme* stumm.
Gewollt war, das *Mikrofon* stummzuschalten, um mit anderen Menschen zu reden,
ohne dass JARVIS mithört. Umgebaut auf `mic` / `mic.slash.fill`; die Sperre sitzt
in `SpeechController.start()`, dem einen Ort, durch den jeder Weg zum Mikrofon
läuft — Barge-in und Idle-Neustart gelten damit automatisch mit. "Antworten
vorlesen" bleibt in den Einstellungen.

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

### 10. Den Mac bedienen — "kopiere X aus Programm Y und schick es an Z"
**Erledigt, 2026-09-08. Beide Wege, ohne dass du etwas erlauben musstest.**

Neu ist `scripts/jarvis-mac.sh` mit vier Befehlen, die auf drei verschiedenen
Berechtigungsstufen sitzen:

    jarvis-mac.sh clip              # Zwischenablage lesen  (keine Berechtigung)
    jarvis-mac.sh clip "text"       # Zwischenablage setzen (keine Berechtigung)
    jarvis-mac.sh app               # Vordergrund-Programm   (Apple Events)
    jarvis-mac.sh copy              # dort Cmd+C drücken     (Bedienungshilfen)
    jarvis-mac.sh check             # welche Stufen offen sind

**Korrektur meiner ersten Auskunft.** Ich hatte behauptet, für `copy` fehle
Hermes die Berechtigung und du müsstest sie von Hand erteilen. Das war falsch:
ich hatte den Symlink `~/.hermes/hermes-agent/venv/bin/python` gegen die
TCC-Datenbank gehalten statt sein Ziel. Aufgelöst zeigt er auf
`~/.local/share/uv/python/cpython-3.11.16-.../bin/python3.11`, und *der* steht
dort mit `kTCCServiceAccessibility = 2` — erlaubt. Über die Bridge gegengeprüft:
JARVIS selbst meldet alle drei Stufen offen. Es war nie etwas zu tun.

(Nebenbefund aus derselben Abfrage: Vollzugriff auf die Festplatte steht für
denselben Interpreter auf `0`, also ausdrücklich verweigert. Das ist kein
Problem — `JARVIS_FILE_ROOTS` regelt Dateizugriff ohnehin enger — aber es
erklärt, falls einmal ein Ordner wie `~/Library/Mail` unerreichbar ist.)

Zwei Details, die den Unterschied zwischen "geht" und "brauchbar" machen:

- `copy` **pollt**, bis sich die Zwischenablage ändert (bis 1,5 s), statt fest
  zu warten. Ein natives Programm antwortet in 50 ms, ein Electron-Fenster
  nicht. Ändert sich nichts, sagt das Skript das — es schickt nicht stillschweigend
  den alten Inhalt als neuen weiter. Genau das wäre der Fehler gewesen, der dir
  irgendwann ein Passwort in einen WhatsApp-Chat legt.
- `check` benutzt `key code 63` (die Fn-Taste): für TCC ein echter Tastendruck,
  aber einer, der nichts auslöst. Die Prüfung kann deine Arbeit nicht stören.

End-to-End nachgewiesen: Text in TextEdit ausgewählt, `copy` liefert
`Beweiszeile aus TextEdit.` zurück.

Die SOUL kennt das jetzt (deployt nach `~/.hermes/SOUL.md`, Sicherung
daneben) — mit der Regel, dass Lesen frei ist und **Senden weiterhin
Rückfrage und Vorlesen verlangt**. Eine Zwischenablage kann ein Passwort
enthalten, und JARVIS ist der, der vorher nicht hingesehen hat.

### 11. Das kleine Fenster — drei Sachen, die es falsch machte
**Erledigt, 2026-09-08. Beide Targets bauen, 186 Python-Tests grün.**

**Die Glyphe zappelte im Schlaf.** In `OverlayView` stand
`thinking: model.isWorking || !listening` — das `|| !listening` heißt wörtlich
"animiere immer, wenn du gerade nicht zuhörst", also gerade im Ruhezustand. Der
Kommentar daneben begründete es auch noch ("eine stehende Glyphe wirkt wie ein
totes Standbild"). Das war die falsche Abwägung: Bewegung bedeutet Arbeit, und
eine Pille, die im Leerlauf weitermorpht, behauptet beschäftigt zu sein,
während sie schläft. Jetzt bewegt sie sich, während JARVIS zuhört oder denkt,
und steht sonst still.

**Der Dock-Klick öffnete ein zweites Fenster.** Die App hatte gar keinen
`NSApplicationDelegate`, also beantwortete SwiftUI den Klick mit seinem
Standardverhalten: kein *sichtbares* Fenster → baue ein neues aus der
`WindowGroup`. Ein zusammengefaltetes Fenster ist genau dieser Fall — es ist
`orderOut`, lebt aber weiter und hält die Unterhaltung. Ergebnis: ein leeres
Duplikat vorn, das echte Fenster weiter zugeklappt.

Neu ist `apple/Sources/Services/AppDelegate.swift` mit
`applicationShouldHandleReopen`. `false` heißt "erledigt, bau nichts". Die
Reihenfolge: ist die Pille oben, klappt der Klick sie auf (die Pille *ist* das
Fenster); sonst wird das vorhandene Fenster nach vorn geholt. Nur wenn es
wirklich keines gibt, darf SwiftUI eines bauen.

Dazu ein zweiter Befund: `⌘M` legt das Fenster ins Dock statt es auszublenden,
und ein ins Dock gelegtes Fenster ignoriert jedes `makeKeyAndOrderFront`. Ohne
`deminiaturize` hätte der Klick auch mit Delegate nichts sichtbar getan.
Steht jetzt an beiden Stellen, im Delegate und in `WindowTransition.expand`.

**Minimieren schnitt JARVIS mitten im Satz ab.** Jeder Weg, der das Fenster
versteckt — `⌘H`, `⌘M`, das Zuklappen, `onDisappear`, die Szene im Hintergrund —
landet in `setVoiceForeground(false)`, und das ruft `speech.suspend()` →
`stopSpeaking()`: Satzschlange weg, laufende Ausgabe abgewürgt. Schlimmer noch,
die Antwort auf eine schon laufende Aufgabe wurde danach überhaupt nicht mehr
vorgelesen, weil `voiceForeground` in der Bedingung dafür steht.

Die Pille ist der eine Fall, in dem "das Fenster ist weg" nicht "hör auf"
heißen darf: JARVIS ist weiter auf dem Schirm und weiter am Arbeiten. Der
Wächter sitzt deshalb in `setVoiceForeground` selbst, dem einen Punkt, durch
den alle diese Wege laufen. Weil `⌘M` ihn über zwei Benachrichtigungen
erreicht, deren Reihenfolge nicht uns gehört, setzt `collapseToOverlay` den
Zustand danach noch einmal ausdrücklich — sonst entscheidet ein Rennen darüber,
ob dein Satz zu Ende gesprochen wird. Laufende Aufgaben waren nie betroffen;
`chatTasks` wird nur beim Abschluss abgebrochen.

### 12. WhatsApp lesen — ungelesene Nachrichten zusammenfassen
**Erledigt, 2026-09-08.**

Die alte Notiz sagte, JARVIS dürfe nur wissen *dass* jemand geantwortet hat,
nicht *was*. Das stimmte für den Weg, den ich damals genommen hatte, und
dieser Weg war die Sackgasse.

**Warum die Bridge es nie konnte.** Sie läuft auf Baileys mit
`syncFullHistory: false`, und im Code steht wörtlich "We don't maintain a
message store". Ihre Warteschlange wird von `GET /messages` *geleert* — wer
liest, nimmt sie dem Gateway weg. Im `self-chat`-Modus verwirft sie fremde
Nachrichten, bevor irgendetwas sie sieht. "Was ist ungelesen" hat dort keine
Datenquelle, aus der es beantwortet werden könnte. Sie zu erweitern hätte
außerdem fremden Code in `~/.hermes/hermes-agent/` geändert, den das nächste
Hermes-Update überschreibt.

**Was stattdessen da war.** WhatsApp Desktop legt jeden Chat in einer
**unverschlüsselten SQLite-Datei** im eigenen Gruppen-Container ab
(`ChatStorage.sqlite`, 34 MB, live aktualisiert). Kein Protokoll, kein
zweites gekoppeltes Gerät, kein QR-Code. Neu ist
`scripts/jarvis-whatsapp-read.py`:

    jarvis-whatsapp-read.py unread          # wer wartet, wie viele, seit wann
    jarvis-whatsapp-read.py unread --full   # und was sie geschrieben haben
    jarvis-whatsapp-read.py chat Andi       # ein Gespräch der Reihe nach

Vier Dinge, die den Unterschied zwischen "läuft" und "stimmt" machen:

- **`mode=ro`, nicht `immutable=1`.** Der naheliegende `immutable`-Schalter
  ignoriert die `-wal`-Datei, und dort stehen die neuesten Stunden. Auf diesem
  Mac gemessen: die immutable-Sicht war zweieinhalb Stunden hinterher.
- **Gruppen-Absender.** `ZWAMESSAGE.ZPUSHNAME` sieht nach dem Namen aus und ist
  eine Falle — in Gruppen steht dort ein base64-Block. Die Namen liegen in
  `ZWAPROFILEPUSHNAME`, adressiert über die `@lid`-Kennung des Mitglieds statt
  über eine Telefonnummer. Ohne diesen Join hieß jeder Absender "jemand".
- **Nichts wird geschrieben.** Die Verbindung ist schreibgeschützt geöffnet und
  im Code steht kein INSERT, UPDATE oder DELETE. Deine Chats bleiben in
  WhatsApp ungelesen — sonst hätte "fass mir den Morgen zusammen" nebenbei alle
  Badges gelöscht. Ein Test prüft das byte-genau.
- **Deckelung je Chat.** Andi hat 172 ungelesene. Ungedeckelt ist das keine
  Zusammenfassung, sondern eine Wand.

**Voreinstellung sind die letzten 24 Stunden.** Der erste Wurf zeigte alle 486
ungelesenen aus 25 Chats — das ist kein Eingang, das ist ein Archiv. Gefiltert
wird auf Nachrichtenebene, nicht auf Chatebene: Andi hat 172 ungelesene, keine
davon von heute, also taucht er nicht auf; Silvia Horand hat 107, davon 16 von
heute, also steht dort "16 (von 107 insgesamt)". Übrig bleiben 4 Chats mit 24
Nachrichten. Was wegfiel, sagt eine Schlusszeile — sonst liest sich "nichts
Neues" wie ein leerer Posteingang, während 370 Nachrichten daneben liegen.
`--days 7` oder `--days 0` holen den Rest.

**Ein Fund am Rande, der eine halbe Stunde gekostet hat.** Der Aufruf über den
direkten Pfad wurde vom Hermes-Gateway blockiert: "command or referenced script
cannot restart, stop, or uninstall the gateway". Im Skript steht kein einziges
solches Wort. Die Ursache: der Wächter zerlegt ein referenziertes Skript in
Tokens und behandelt einen Pfad am Zeilenanfang als Befehl, den er nachlesen
muss. Der Datenbankpfad stand als Fortsetzungszeile da, wurde damit zum ersten
Token, der Wächter expandierte die Tilde, fand die echte 34-MB-Datei und
scannte **deinen Chatinhalt** nach Gateway-Befehlen — bei 34 MB fremder Sätze
trifft er zwangsläufig einen. Der Pfad steht jetzt auf der Zeile seiner
Zuweisung, mit einem Kommentar, der erklärt, warum man ihn nicht umbrechen darf.

Am laufenden Dienst nachgewiesen: auf "Fasse meine ungelesenen WhatsApp-
Nachrichten zusammen, wer braucht eine Antwort?" findet JARVIS das Skript
selbst über die SOUL und antwortet mit drei konkreten Chats, die eine Antwort
brauchen. 7 neue Tests.

Die SOUL sagt dazu: lesen ist frei, **weitergeben nicht**. Etwas aus einem Chat
in einen anderen Chat, eine Mail oder eine Datei zu zitieren ist eine eigene
Handlung und braucht die übliche Rückfrage.

### 7. WhatsApp-Anrufe
Nicht baubar. Die Bridge nutzt Baileys, und Baileys kann Anrufe nur
**ablehnen** (`rejectCall`) — ausgehende Anrufe implementiert es nicht, und die
WhatsApp Business Cloud API bietet sie ebenso wenig. Kein Aufwand, keine
Konfiguration: das Protokoll ist nicht offen.

Naheliegende Alternative, falls gewünscht: ein normaler Telefonanruf über
Continuity (`open tel://+49…` auf dem Mac klingelt über das iPhone). Das wäre
ein kleines Skript in derselben Machart wie `jarvis-contact.sh`.

### 8. Mute-Button — erledigt
Er war nicht kaputt, er machte das Falsche: er hing an `speaksReplies` und
schaltete JARVIS' Stimme stumm statt des Mikrofons. Umgebaut, siehe 1b.

Der ursprüngliche Befund lautete: Der App-Pfad sieht korrekt aus:
`speaksReplies` stoppt die laufende Ausgabe und wird bei jedem Delta erneut
geprüft. Was "funktioniert nicht" genau heißt, entscheidet die Diagnose —
und der Code gehört Codex, nicht mir. Bitte einmal genauer:

- Spricht JARVIS **weiter**, während er gerade spricht, oder erst bei der
  **nächsten** Antwort wieder?
- Mac oder iPhone?
- Ist dabei das HUD im Browser offen? Das spricht über den Voice-Server auf
  Port 8765 und wird vom Mute-Schalter der App gar nicht erfasst — das wäre
  eine echte, getrennte Ursache.

### 9. Bilder direkt im Chat anzeigen — erledigt
Kein Render-Fehler. Die Bridge macht aus `MEDIA:` nur dann einen Anhang, wenn
die Datei in `/tmp/jarvis-media` liegt — jeder andere Ort wird bewusst
abgelehnt, sonst könnte `MEDIA:` jede Datei der Platte in den Chat ziehen. Die
SOUL erwähnte dieses Verzeichnis **kein einziges Mal**, also legte JARVIS Bilder
woanders ab und die Bridge lehnte korrekt ab.

Nachgewiesen: derselbe Satz mit einem Bild aus `/tmp/jarvis-media` ergibt einen
Anhang, mit einem Bild aus `~/Downloads` keinen. Die Regel steht jetzt in der
SOUL, samt der Kopierzeile und dem Hinweis, dass PDFs und Videos Pfade bleiben.

## Betrieb — erledigt

**Die Festplatte war voll** (inzwischen wieder ~12 GiB frei). 1,5 GiB von 228,
Datenvolumen bei 100 %.
Das hat schon Schaden angerichtet: die WhatsApp-Bridge ist mit
`ENOSPC: no space left on device` beim Schreiben von `creds.json` abgestürzt.
Eine kaputte `creds.json` kostet die WhatsApp-Kopplung. Das ist unabhängig von
allem oben und sollte zuerst passieren.
