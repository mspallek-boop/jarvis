# JARVIS für iPhone und Mac

Eine gemeinsame SwiftUI-Codebasis erzeugt zwei native Apps. Beide sprechen mit
der kleinen Bridge auf dem Mac; Hermes- und Modellschlüssel werden niemals in
der App gespeichert.

## Sprechtempo

Das Tempo lässt sich auch direkt oben im Chat über **1×** ändern, zum Beispiel
auf **1,25×** oder **1,5×**. Daneben schaltet der **Lautsprecher-Button** die
Sprachausgabe stumm: Die laufende Antwort stoppt sofort, neue Antworten bleiben
stumm, bis der Ton wieder eingeschaltet wird. Die Auswahl bleibt nach einem
Neustart erhalten; das Mikrofon wird separat über den Sprachmodus gesteuert.

Unter **Einstellungen → Sprache → Sprechtempo** stehen auf Mac und iPhone
**Langsam (0,75×)**, **Normal (1×)**, **Schnell (1,25×)** und
**Sehr schnell (1,5×)** zur Auswahl. Standard ist **Normal**; die Auswahl wird
pro Gerät gespeichert. **Stimme testen** verwendet dieselbe Einstellung.

Bei der natürlichen Stimme wirkt die Änderung sofort auf die laufende
Wiedergabe, ohne die Tonhöhe zu ändern. Die Systemstimme (auch beim Ausfall
der natürlichen Stimme) übernimmt das Tempo ab dem nächsten Satz bzw. beim
nächsten Vorlesen. Ihre genaue Geschwindigkeit hängt von der Apple-Stimme ab.
Die Einstellung ändert weder die Spracherkennung noch die Redepause bis zum
Senden und benötigt keine Änderung an der Bridge.

Die eigenständigen Swift-Tests einschließlich Offline-Audiorendering lassen
sich auf dem Mac ohne Server, Mikrofon oder Lautsprecherausgabe ausführen:

```bash
bash apple/scripts/test_speech.sh
```

Die Testprogramme werden unter `/tmp` abgelegt. Die Audiotests prüfen Dauer,
Tonhöhe, Tempoänderungen während der Wiedergabe und Stoppen am tatsächlichen
Audio-Graphen des Players.
Falls die Ausführungsumgebung keine Core-Audio-Komponenten bereitstellt,
führt `bash apple/scripts/test_speech.sh --skip-audio` nur die Tests ohne
Audio-Rendering aus und meldet die ausgelassenen Audiotests ausdrücklich.
Testpräferenzen bleiben im Arbeitsspeicher.

## Projekt erzeugen

```bash
cd apple
xcodegen generate
open JARVIS.xcodeproj
```

Die Generierung korrigiert den Einbettungspfad der modernen SwiftUI-Watch-App
automatisch auf `Watch/`. Dadurch erscheint JARVIS in der Watch-App auf dem
iPhone unter „Verfügbare Apps“. Ist dort „Automatische App-Installation“
aktiviert, wird die Watch-App beim Installieren der iPhone-App mitinstalliert.

In Xcode das eigene Apple-Team wählen. Für das iPhone das Gerät auswählen und
`JARVIS-iOS` starten; für den Mac `JARVIS-macOS`.

Für das macOS-Target muss unter **Signing & Capabilities** ein gültiges
**Apple Development**-Zertifikat verwendet werden. **Sign to Run Locally** ist
nur eine Ad-hoc-Signatur, deren Identität sich bei jedem Build ändert; dadurch
fragt macOS nach Änderungen immer wieder nach Mikrofon- und anderen
Datenschutzfreigaben. Fehlt das Zertifikat, lässt es sich unter **Xcode →
Settings → Accounts → Manage Certificates** anlegen.

Beim ersten Start unter Einstellungen:

- Bridge über Tailscale: `https://macbook-air-von-marlon.tailfb3c35.ts.net:8443`
- App-Token: `JARVIS_APP_TOKEN` aus `~/.hermes/.env`

Wenn ein Always-on-Relay eingerichtet ist, wird statt der Mac-Adresse die
Tailscale-Adresse des Relays eingetragen. Die App zeigt dann den Schlafzustand
des Macs und bietet „Mac wecken“ an. Über das Ordnersymbol können freigegebene
Mac-Dateien durchsucht, geladen und an andere iPhone-/Mac-Apps übergeben werden.

Unterhaltungen werden lokal auf dem jeweiligen Gerät archiviert. Über das
Verlaufssymbol lassen sie sich erneut öffnen und löschen oder ein neuer Chat
starten. Gespeichert werden höchstens 30 Unterhaltungen mit jeweils 250
Nachrichten; Zugangsdaten bleiben davon getrennt im Schlüsselbund.

Während JARVIS arbeitet, bleibt die Quadrat-Animation sichtbar: Wird der große
Orb beim Lesen nach oben aus dem Bild gescrollt, erscheint er verkleinert direkt
am Eingabefeld und wandert beim Zurückscrollen wieder an seine Ausgangsposition.

Die App verweigert unverschlüsseltes HTTP zu öffentlichen Adressen. Die
konfigurierte `.ts.net`-Adresse ist ausschließlich im privaten Tailnet
erreichbar; Tailscale muss auf dem jeweiligen Gerät aktiv sein.

## Version 0.3.0 — Voice zuerst

Mac und iPhone starten im Sprachmodus. Eine kurze Sprechpause sendet den
transkribierten Satz; nach der gesprochenen Antwort hört JARVIS wieder zu.
Der Orb unterbricht die Sprachausgabe oder bricht den laufenden Hermes-Auftrag
über `client_run_id` ab. Die dezente Linie am unteren Rand öffnet die
Texteingabe und pausiert das Mikrofon. Beim Hintergrundwechsel pausiert Audio.

Berechtigungen werden pro Prozess zentral einmal angefragt. Nach einer
Ablehnung gibt es keine automatische Wiederholung. Alle Mac-Updates müssen
mit derselben Apple-Development-Identität signiert bleiben. Die bisher
installierte App hatte eine Ad-hoc-Signatur; beim Wechsel zur stabilen Signatur
kann einmalig eine erneute Freigabe nötig sein.

Für einen Geräte-Build einschließlich Watch benötigt Xcode die watchOS-Plattform.
Die Uhr muss für die direkte Entwicklungsinstallation im Entwicklermodus sein.
Die Watch-App ist unter `JARVIS.app/Watch/JARVIS-Watch.app` eingebettet und kann
zusätzlich direkt mit `devicectl device install app` auf die gepaarte Uhr
installiert werden. Sie leitet Anfragen über das iPhone weiter und liest
Antworten auf der Uhr vor; das iPhone muss dafür erreichbar sein.

### Runde Watch-Komplikationen (Build 9)

Neben dem bisherigen JARVIS-Symbol gibt es drei weitere auswählbare Varianten:

- **JARVIS · Orbit:** segmentierter Reaktorring mit Mittelpunkt.
- **JARVIS · Stimme:** Sprachwelle im feinen Kreis.
- **JARVIS · Minimal:** dezentes J mit dünner Kreislinie.

Alle drei unterstützen `accessoryCircular` und `accessoryCorner`. Eckplätze
bekommen über WidgetKit eine gekrümmte Beschriftung; bei runden Plätzen zeigt
watchOS sie nur an, wenn das Zifferblatt den äußeren Text unterstützt. Die
Symbole übernehmen die Akzentfarbe des Zifferblatts und öffnen die Watch-App.
Sie zeigen keine erfundenen Live-Statuswerte oder Fortschrittsanzeigen.

Auf der Watch das Zifferblatt gedrückt halten → Bearbeiten → Komplikationen →
einen runden oder Eckplatz auswählen → JARVIS → gewünschte Variante. Welche
Plätze angeboten werden, bestimmt das gewählte Apple-Zifferblatt. Die bestehende
Komplikation behält ihre Kennung und bleibt auswählbar.

### Die Uhr spricht satzweise mit (Build 10)

Bisher blieb die Watch stumm, bis Hermes die ganze Antwort fertig hatte. Jetzt
schickt das iPhone jeden fertigen Satz sofort weiter: Die Uhr liest ihn vor,
während die Antwort noch entsteht.

Jeder Satz trägt eine laufende Nummer. Kommen zwei Nachrichten in falscher
Reihenfolge an, hält die Uhr den späteren zurück, bis der frühere da ist, und
spricht nichts doppelt. Der abschließende Funkspruch enthält zusätzlich die
vollständige Satzliste; fehlt der Uhr ein Satz, holt sie ihn daraus nach. War
die Uhr währenddessen gar nicht erreichbar, liest sie wie bisher die komplette
Antwort am Stück vor.

Die Satzgrenze erkennt gängige deutsche Abkürzungen (`Dr.`, `bzw.`, `z. B.`)
und Dezimalzahlen, damit kein Halbsatz vorgelesen wird. Ersetzt Hermes den
gestreamten Wortlaut am Ende durch eine andere Endfassung, bleibt der
maßgebliche Text auf dem Bildschirm stehen; vorgelesen wird er nicht erneut.

Dasselbe Verfahren gilt auf iPhone und Mac: Die Sprachausgabe beginnt beim
ersten fertigen Satz statt am Ende der Antwort.

### Durchgehend zuhören (Build 10)

Das Mikrofon bleibt offen, solange der Sprachmodus läuft — auch während JARVIS
nachdenkt und während er vorliest. Sprichst du dazwischen, hält er an und hört
zu; ein laufender Auftrag wird dabei still beendet, damit deine neuen Worte
nicht verlorengehen.

Damit JARVIS sich nicht selbst hört, aktiviert die App die Echokompensation des
Systems. Zusätzlich ignoriert er Erkennungen, die nur aus den Wörtern bestehen,
die er gerade selbst gesagt hat — auch aus dem Satz davor, dessen Echo in der
Lücke zwischen zwei Sätzen noch eintrifft. Zum Auslösen braucht es mindestens
drei Zeichen und zwei aufeinanderfolgende Teilergebnisse; ein Husten stoppt
nichts. Lässt sich die Echokompensation auf einem Gerät nicht einschalten,
bleibt das Unterbrechen dort aus, statt das Mikrofon zu verlieren.

Abschaltbar unter Einstellungen → Sprache → **Durch Sprechen unterbrechen**.
Die Uhr behält das Antippen zum Unterbrechen.

### Eigene Wörter für die Spracherkennung

Die deutsche Erkennung auf dem Gerät kennt keine Produkt- und Markennamen und
schreibt „Skyr" als „Skar". Unter Einstellungen → Sprache → **Eigene Wörter**
lassen sich solche Namen kommagetrennt hinterlegen; sie werden der Erkennung
als Vorschlag mitgegeben und verlassen das Gerät nicht.

### Bilder, Videos und Quellen (Build 11)

Nennt JARVIS in einer Antwort ein Bild, ein Video oder eine Webseite,
erscheint das unter der Antwort: Bilder als Vorschau, Videos und Quellen als
antippbare Zeilen mit Titel und Domain. Lässt sich ein Bild nicht laden, steht
das dort statt einer Lücke. Vorgelesen werden Links nicht — eine gesprochene
URL ist unerträglich, deshalb entfernt die Sprachausgabe sie und behält bei
Markdown-Links nur den sichtbaren Text.

Nur `http` und `https` werden dargestellt.

### Bilder einfügen (Build 11)

Auf dem Mac mit **⌘V** direkt in der Hauptansicht, auch im Sprachmodus: Die
Texteingabe öffnet sich automatisch. Screenshots, kopierte Bilder und Bilddateien
aus dem Finder werden nach PNG gewandelt. Normales Texteinfügen und Eingaben in
den Einstellungen bleiben unverändert. Ein Bild kann auch ohne Begleittext
gesendet werden; JARVIS beschreibt es dann. Auf dem iPhone
erscheint neben dem Senden-Knopf ein Bildsymbol, sobald ein Bild in der
Zwischenablage liegt. Das angehängte Bild zeigt sich als kleine Vorschau über
dem Eingabefeld und lässt sich dort wieder entfernen.

Das Bild geht an den Mac und liegt in `~/.hermes/jarvis-uploads`. JARVIS sieht
es sich mit `vision_analyze` an. Es gehört nur zur abgeschickten Nachricht;
danach ist das Eingabefeld wieder leer.

`bash apple/scripts/test_clipboard.sh` prüft die Bildkonvertierung, Finder-Dateien
und unveränderten Text auf einer privaten Test-Zwischenablage. Die tatsächliche
Zwischenablage bleibt dabei erhalten.

### Zuhören endet von selbst (Build 12)

Das Mikrofon schaltet nach einer Weile Stille ab, damit es nicht den ganzen
Abend offen bleibt. Voreingestellt sind zehn Sekunden; unter Einstellungen →
Sprache → **Zuhören endet nach** stehen auch 30 Sekunden, 2 Minuten und „Nie".

Stille während einer Antwort zählt nicht als Untätigkeit: solange JARVIS denkt
oder spricht, läuft das Mikrofon weiter — genau dann willst du ja
dazwischengehen können. Erst danach beginnt die Uhr zu laufen.

Ist abgeschaltet, steht unter dem Orb „Tippen zum Sprechen". Ein Tippen startet
das Zuhören wieder.
