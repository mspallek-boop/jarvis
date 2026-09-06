# Runde Watch-Komplikationen — Build 9

Drei zusätzliche auswählbare WidgetKit-Komplikationen:

| Name | Gestaltung | Plätze |
|---|---|---|
| JARVIS · Orbit | Drei Ringsegmente und ein Mittelpunkt | Rund, Ecke |
| JARVIS · Stimme | Sprachwelle im dünnen Kreis | Rund, Ecke |
| JARVIS · Minimal | Schlichtes J mit feiner Kreislinie | Rund, Ecke |

Die bisherige Komplikation und ihre Kennung bleiben erhalten. Insgesamt sind
vier Widget-Konfigurationen im Bundle. Die neuen Formen sind skalierbare
SwiftUI-Vektoren, ohne eckigen Hintergrund, mit übernehmbarer Akzentfarbe.
`widgetLabel` lässt watchOS den Text an die jeweilige Eckkrümmung anpassen;
kreisförmige Plätze zeigen den Zusatztext nur auf unterstützten Zifferblättern.
Jede Variante öffnet die vorhandene Watch-App. Keine neuen Netzwerkdienste,
Berechtigungen oder Einstellungen erforderlich.

Quelle für die Familien und gekrümmten Labels:
[Apple: Go further with Complications in WidgetKit](https://developer.apple.com/videos/play/wwdc2022/10051/).

## Geänderte Dateien

- `apple/WatchComplication/JARVISComplication.swift`: drei neue Widgets,
  gekrümmte Labels, eindeutige Widget-Kennungen und Xcode-Vorschauen.
- `apple/WatchComplication/RoundComplicationGlyph.swift`: neue Vektorsymbole.
- `apple/project.yml`: gemeinsame Buildnummer 9; daraus Xcode-Projekt und
  Versionsmetadaten regeneriert. Mac-App bleibt installiert auf Build 8.
- `apple/README.md`: Auswahl und unterstützte Plätze dokumentiert.
- Dieser Bericht.

## Verifikation

- iOS-Scheme einschließlich Watch und WidgetKit-Erweiterung: **BUILD SUCCEEDED**.
- Signaturen, ausführbare Watch-Einbettung und Version 9 von App/Erweiterung
  geprüft. Alle vier Widget-Kennungen in der kompilierten Erweiterung gefunden.
  Die erste binäre Inventur berücksichtigte nur das Startprogramm; nach
  Einbeziehen von Xcodes signierter Debug-Dylib war die vollständige Prüfung grün.
- Originale SwiftUI-Symbole bei 24, 42 und 84 Punkten gerendert und visuell
  geprüft. Vorschau unter `LocalData/Runtime/previews/watch-round-complications.png`.
  Das ist eine Symbolvorschau, keine Aufnahme eines tatsächlichen Zifferblatts.
- `git diff --check`: fehlerfrei.
- Keine neuen Unit-Tests für diese reine Darstellungsänderung; native Builds,
  Paketprüfung und Sichtkontrolle decken den geänderten Umfang ab.
- iPhone und Watch: Build 9 jeweils erfolgreich per `devicectl` installiert.
- Abschließender Watch-App-Start wegen gesperrtem Gerät abgewiesen
  (`FBSOpenApplicationErrorDomain 7`). Installation erfolgreich, Bedienprüfung offen.

## Auswahl

Auf der Watch: Zifferblatt gedrückt halten → **Bearbeiten** →
**Komplikationen** → runden oder Eckplatz wählen → **JARVIS** → gewünschtes
Design. Das Zifferblatt bestimmt die verfügbaren Plätze. Die sichtbare
Auswahl und gekrümmte Darstellung auf dem konkreten Nutzer-Zifferblatt sind
noch nicht direkt geprüft; kein Zifferblatt wurde automatisch verändert.

Bestehende Änderungen erhalten; keine Commits/Pushes. Die frühere ausstehende
Freigabe für dauerhafte Sprach-/Wachhaltedienste ist davon unabhängig und
wurde durch dieses Update nicht umgangen.
