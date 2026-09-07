# App-UI: Multitasking und Benachrichtigungen

Auftrag an Codex. Backend steht und ist verifiziert; `apple/` gehört dir, ich
habe nichts darin angefasst.

Die Vorgabe des Users ist kurz und bindend: **es muss clean bleiben.** Das ist
keine Geschmacksfrage, sondern die Abnahmebedingung. Der Rest dieses Dokuments
ist der Versuch, sie in Entscheidungen zu übersetzen, die man prüfen kann.

---

## 1. Warum das Interface überhaupt angefasst wird

Zwei neue Tatsachen passen nicht in die heutige Oberfläche:

1. **Es kann mehr als eine Aufgabe gleichzeitig laufen.** `AppModel` kennt genau
   einen Zustand: `isWorking: Bool` plus `activityLabel: String`. Zwei parallele
   Turns sind damit nicht darstellbar — der zweite überschreibt das Label des
   ersten.
2. **JARVIS kann von sich aus etwas mitzuteilen haben.** Bisher spricht er nur
   als Antwort. Eine WhatsApp-Antwort, die eintrifft, während der User etwas
   anderes tut, hat keinen Ort.

Der erste Entwurf lieferte die Benachrichtigung als macOS-Mitteilung. Der User
hat das zurückgewiesen, und zu Recht: **„das muss ja JARVIS intern kommen."**
Eine System-Mitteilung ist das Betriebssystem, das spricht. JARVIS spricht in
seiner App.

---

## 2. Der Rahmen: was „clean" hier heißt

Vier Regeln. Wenn ein Entwurf gegen eine verstößt, ist er der falsche Entwurf.

**Nichts Dauerhaftes für etwas Vorübergehendes.** Eine Glocke im Header ist für
immer da, damit sie zweimal im Monat einen Punkt tragen kann. Kein Glocken-Icon,
keine Badge-Zahl, kein Notification-Center, keine Tab-Leiste, keine Sidebar.

**Eine Statuszeile bleibt eine Statuszeile.** Die App hat heute genau einen Ort,
der sagt, was gerade passiert. Multitasking macht diese Zeile aussagekräftiger —
es vervielfacht sie nicht.

**Ein Orb.** Nie zwei. Der Orb ist JARVIS, und es gibt einen JARVIS. Er zeigt,
dass gearbeitet wird, nicht wie viel.

**Der Verlauf ist der Posteingang.** Eine Benachrichtigung ist JARVIS, der dem
User etwas sagt. Das gehört dorthin, wo er immer redet: in den Chat. Damit
entfällt jede zweite Liste, die man synchron halten müsste — und die Frage
„was habe ich verpasst?" beantwortet Hochscrollen.

---

## 3. Multitasking

### Datenquelle

```
GET /runs        (App-Bearer wie /chat)

{"count": 2,
 "runs": [{"client_run_id": "…", "phase": "tool", "tool": "web_search",
           "conversation": "jarvis-apple", "seconds": 41.2},
          {"client_run_id": "…", "phase": "queued", "tool": "",
           "conversation": "recherche-2", "seconds": 3.1}]}
```

`phase` ist `queued | thinking | answering | tool | stopping`, längster Turn
zuerst. Enthält nie Prompt-, Antwort- oder Argumenttext.

### Parallel laufen lassen

`POST /chat` und `/chat/stream` nehmen `"parallel": true`. Damit startet ein
zweiter Turn sofort, statt hinter dem ersten zu warten — die App muss dafür
**keine** eigenen Conversations vergeben.

Die Antwort nennt die Conversation, in der der Turn tatsächlich gelaufen ist:

```json
{"text": "…", "conversation": "jarvis-apple#2", "run_id": "…"}
```

Am laufenden Dienst gemessen: drei Aufgaben unter einem Namen, 1,8 / 1,9 /
2,1 s, Gesamtdauer 3 s statt 6 s. `/runs` zeigt sie als drei Einträge, alle
gleichzeitig in `answering`.

**Der Preis, und er ist unvermeidbar:** eine Nebenspur trägt die Historie der
Hauptunterhaltung nicht. Hermes hält eine Turn-Lease pro Session
(`session_turn_leases`, Schlüssel ist die Conversation), zwei Turns in einer
Session können also gar nicht überlappen — und zwei Turns, die sich ein
Transkript teilen, würden ineinander laufen. Deshalb:

- „Mach beides gleichzeitig" → `parallel: true`, zwei unabhängige Aufgaben.
- „Und was war nochmal das von eben?" → **ohne** Flag, in der Hauptunterhaltung.

Die Entscheidung gehört in die App. Mein Vorschlag: `parallel: true` nur, wenn
bereits ein Turn läuft **und** der User eine neue Aufgabe schickt statt einer
Rückfrage — im Zweifel ohne Flag, denn Warten ist reparabel, ein verlorener
Kontext nicht. Vier Spuren sind das Maximum, danach wird gewartet.

### Darstellung — Blobs, nicht eine Liste

**Korrektur vom 2026-09-07.** Die erste Fassung schlug eine aufklappbare
Statuszeile vor. Der User will etwas anderes, und es ist besser: **kleine Blobs,
die zeigen, dass mehrere Aufgaben laufen. Der, den man antippt, wird zentriert.**
Was Codex bereits gebaut hat (`runsExpanded`, ForEach über `model.runs`), hat den
Datenweg — die Darstellung wandert von der Zeile in den Raum um den Orb.

Der Orb bleibt einer. Er ist die Aufgabe, auf die der User gerade schaut. Die
anderen laufenden Aufgaben stehen als kleine Blobs daneben:

```
        ▫  ▫  ▫          ← laufende Aufgaben, klein, antippbar
                          
          ◼◼◼            ← der Orb: die zentrierte Aufgabe
          ◼◼◼
          ◼◼◼
                          
      Ich suche im Web    ← die Statuszeile, unverändert, gilt dem Orb
```

Regeln:

- **Bei 0 oder 1 Aufgabe gibt es keine Blobs.** Die Ansicht ist dann pixelgleich
  mit heute. Der Prüfstein aus Abschnitt 2 gilt unverändert.
- **Ein Blob ist ein kleiner Orb**, gebaut aus derselben `CubeGrid`- und
  `BauhausTileShape`-Formensprache, die `OrbView.swift` schon hat. Keine neuen
  Symbole, keine Icons, keine Farben — die App bekommt kein zweites
  Formenvokabular.
- **Antippen zentriert.** Der Blob wandert auf die Orb-Position, der bisher
  zentrierte Orb wird zum Blob. `matchedGeometryEffect` über den vorhandenen
  `thinkingOrbNamespace` macht genau diese Bewegung — die Maschinerie liegt
  schon da, sie braucht nur eine `id` pro `client_run_id` statt der festen
  `"thinking-orb"`.
- **Zentriert heißt fokussiert.** Statuszeile, gestreamte Antwort und der
  Orb-Tap zum Abbrechen gelten immer der zentrierten Aufgabe. Genau deshalb
  braucht es keine Abbrechen-Knöpfe an den Blobs.
- **Keine Beschriftung an den Blobs.** Kein Text, keine Zahl, kein Tooltip. Was
  eine Aufgabe tut, erfährt man durch Antippen — die Statuszeile sagt es dann.
- **Der Zustand liegt in der Bewegung, nicht in der Farbe.** `thinking`,
  `answering` und `tool` pulsieren wie der Orb, nur kleiner und langsamer;
  `queued` steht still; `stopping` verblasst. Wer die App im Augenwinkel sieht,
  erkennt daran, ob etwas hakt.
- **Blobs verschwinden, wenn ihre Aufgabe fertig ist** — sie schrumpfen weg,
  nicht schlagartig. Fällt der zentrierte Orb weg, rückt der älteste Blob nach.
- **Höchstens vier**, passend zu `MAX_PARALLEL_CONVERSATIONS`. Mehr kann die
  Bridge nicht gleichzeitig laufen lassen, also kann es nie mehr geben.

Größe und Abstand sind deine Entscheidung; als Anhalt: ein Blob etwa ein Viertel
des Orbs, waagerecht über ihm mit gleichmäßigem Abstand, ausreichend Trefferfläche
für den Finger auch wenn er optisch klein ist.

Was das ersetzt: die aufklappbare Liste, das `⌄`-Chevron und das `· +1` am Ende
der Statuszeile. Die Statuszeile bleibt einzeilig und gilt der zentrierten
Aufgabe.

---

## 4. Benachrichtigungen

### Datenquelle

```
GET  /notifications?since=<cursor>&unread=1
POST /notifications/read   {"through": <id>}
POST /notify               {"kind","title","text"}     ← Werkzeuge, nicht die App
```

```json
{"notifications": [{"id": 1, "kind": "whatsapp_reply", "title": "Rici",
                    "text": "hat geantwortet", "at": 1788772924.37,
                    "read": false}],
 "unread": 1, "latest": 1}
```

- `kind`: `whatsapp_reply | task | info`. Bei einer unbekannten Art nicht
  abstürzen — als `info` behandeln.
- `title` ≤ 80 Zeichen, `text` ≤ 200, beide bereits auf eine Zeile normalisiert
  (keine Zeilenumbrüche, kein doppelter Leerraum). Du darfst sie direkt setzen.
- Die Warteschlange ist auf 50 begrenzt und überlebt einen Bridge-Neustart.
- `latest` ist der Cursor für das nächste `since`.
- Absender ist heute der WhatsApp-Antwort-Watcher. Er überträgt **nie**
  Nachrichteninhalt — nur, dass jemand geantwortet hat und wer.

### Polling

An den bestehenden Health-Poll hängen, keine zweite Schleife. Im Vordergrund
alle 15–20 s reicht; eine Benachrichtigung ist kein Alarm. Im Hintergrund gar
nicht — beim Zurückkommen einmal `since=<cursor>` holt alles Verpasste nach.
Das ist der Grund, warum es eine Pull-Queue ist und kein Push: ein verpasster
Moment wird zu einer späten Benachrichtigung, nie zu einer verlorenen.

### Darstellung — zwei Orte, beide vorhanden

**1. Der Moment: eine Zeile unter dem Header.**
Dieselbe Position und Machart wie `connectionBanner`, das es schon gibt. Ein
Satz, Tinte auf Hintergrund, keine Farbe, kein Icon, keine Umrandung:

```
Rici hat geantwortet.
```

Nach ~6 s von selbst weg, Tippen schließt sofort. Kommen mehrere gleichzeitig:
`2 Benachrichtigungen`. Der Banner ist nie stapelbar — eine Zeile, immer.

**2. Das Gedächtnis: eine Zeile im Verlauf.**
Als neue `ChatMessage.Role.system`, gerendert ohne Bubble, kleiner Font,
`ink.opacity(0.5)`, mit Uhrzeit. Damit ist es Teil des Verlaufs, wird archiviert
wie alles andere, und die App bekommt eine „was war los?"-Ansicht geschenkt,
ohne dass irgendwer eine gebaut hätte.

War die App zu, taucht das Verpasste beim Öffnen einfach im Verlauf auf. Kein
Badge, das man wegklicken muss.

**Nach dem Anzeigen** `POST /notifications/read {"through": latest}`. Erst
danach, nicht beim Abholen — sonst verschluckt ein Absturz zwischen Poll und
Render die Benachrichtigung still.

### Sprechen

Wenn `speaksReplies` an ist und gerade nichts läuft, darf JARVIS die Zeile
sagen. Wenn er gerade spricht oder arbeitet: **nicht** unterbrechen und **nicht**
nachträglich nachsprechen. Der Banner hat es bereits gesagt; eine
Sprachausgabe, die zwei Minuten zu spät kommt, ist verwirrend, nicht hilfreich.

---

## 5. Was ausdrücklich nicht gebaut wird

- Kein Glocken-Icon, keine Badge-Zahl, kein Notification-Center.
- Keine Tab-Leiste, keine Sidebar. Genau ein zentrierter Orb — die Blobs sind
  die *anderen* Aufgaben, nie ein zweiter gleichrangiger Orb.
- Keine Abbrechen-Knöpfe pro Aufgabe, keine Beschriftung an den Blobs.
- Keine Liste, kein Chevron, kein "· +1" in der Statuszeile. Das war der erste
  Entwurf und ist durch die Blobs ersetzt.
- Kein Wischen zum Verwerfen, keine Benachrichtigungs-Einstellungen. Wer keine
  Benachrichtigungen will, lässt JARVIS keinen Watch setzen.
- Keine Ungelesen-Zahl irgendwo. Der Verlauf ist der Posteingang.

Der Prüfstein: **mit null laufenden Aufgaben und null Benachrichtigungen muss
die App pixelgleich aussehen wie heute.** Ist das nicht so, ist etwas
Dauerhaftes für etwas Vorübergehendes eingebaut worden.

---

## 6. Nötige Änderungen in `apple/`

Zur Orientierung, nicht als Vorschrift — die Datei- und Typentscheidungen sind
deine:

- `ChatMessage.Role` um `system` erweitern (Persistenz-Migration beachten: alte
  Archive kennen den Fall nicht).
- `AppModel`: `runs: [RunStatus]` statt `isWorking`/`activityLabel` allein; die
  Einzelaufgabe bleibt der Sonderfall `runs.count == 1`.
- `AppModel`: `notificationCursor` (persistiert) + der Poll an `checkConnection`.
- `JarvisAPIClient`: `runs()`, `notifications(since:)`, `markRead(through:)`.
- `ContentView`: Blobs um den Orb, `matchedGeometryEffect` mit einer id je
  `client_run_id` statt der festen `"thinking-orb"`; Banner neben
  `connectionBanner`.
- `OrbView`: eine kleine Variante derselben `CubeGrid`-Formensprache als Blob.
- `MessageBubble`: `system`-Zweig ohne Bubble.

Wenn dir eine dieser Grenzen im Weg steht oder du die Bridge anders brauchst —
etwa `/runs` mit Conversation-Titeln statt IDs — sag es, das ist meine Seite und
schnell geändert. Änderungen an `bridge/` bitte nicht selbst vornehmen.

---

## 7. Verifiziert am laufenden Dienst (2026-09-07)

- `GET /runs` leer `{"runs":[],"count":0}`, ohne Token 401, echter Turn
  erschien mit `thinking` → `answering` und verschwand beim Abschluss.
- Ganze Kette: WhatsApp-Antwort → Watcher → `POST /notify` → `GET
  /notifications` liefert `{"id":1,"kind":"whatsapp_reply","title":"Rici"}`,
  `unread: 1`; `POST /notifications/read {"through":1}` → `unread: 0`.
- 105 Bridge-Tests grün, davon 11 neu für die Benachrichtigungen.


---

## 8. Nachtrag vom 2026-09-07 — bereits erledigt, nicht doppelt bauen

Zwei Dinge habe ich auf ausdrückliche Anweisung des Users direkt in `apple/`
geändert, obwohl der Ordner dir gehört. Beides ist einzeilig und gebaut:

**Der Mute-Knopf mutet jetzt das Mikrofon, nicht JARVIS.** Er hing an
`speaksReplies`, schaltete also die Sprachausgabe stumm — der User erwartet, sein
*Mikrofon* stummzuschalten, um mit anderen Menschen zu reden, ohne dass JARVIS
mithört. Das war kein Bug, sondern die falsche Funktion hinter dem Symbol.
`SpeechController.microphoneMuted` (persistiert) sperrt jetzt
`start(stoppingSpeech:)` — der eine Ort, durch den jeder Weg zum Mikrofon läuft,
also gelten Barge-in, Idle-Neustart und `listenThrough()` automatisch mit. Das
Symbol ist `mic` / `mic.slash.fill`, die Orb-Zeile sagt "Mikrofon stumm".
`speaksReplies` bleibt unverändert in den Einstellungen als "Antworten vorlesen".

**"Ich prüfe das" ist raus.** Der gesprochene Füller beim Tool-Start sagte im
generischen Fall "Ich prüfe das" — das teilt nichts mit, kostet einen
gesprochenen Satz und verzögert die Antwort. Jetzt wird nur noch bei einer
Websuche etwas gesagt, weil die Wartezeit sonst unerklärt bleibt. Die Regel steht
zusätzlich in der SOUL, damit auch das Modell die Formulierung nicht selbst
produziert.

Beides ist für macOS und iOS gebaut, signiert und auf Mac, iPhone und Watch
installiert.
