# Fix für Codex: iOS-Build ist gebrochen

Stand 2026-09-02. Das iOS-Target baut nicht mehr. macOS baut weiterhin fehlerfrei.
Die Ursache liegt vollständig in `apple/JARVIS.xcodeproj/project.pbxproj`, also im
Zuständigkeitsbereich von Codex. Backend und Bridge sind nicht betroffen.

## Fehler

```
error: Multiple commands produce
'/tmp/jarvis-derived-ios/Build/Products/Debug-watchos/JARVIS Watch App.app/JARVIS Watch App'
```

Reproduzierbar mit:

```bash
xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-iOS \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/jarvis-derived-ios \
  CODE_SIGNING_ALLOWED=NO build
```

## Ursache

Das Target `JARVIS-Watch` widerspricht sich selbst: Die Projektstruktur erwartet ein
anderes Produkt, als die Build-Settings erzeugen.

| Ort | Wert |
|---|---|
| `productReference` des Targets (Zeile 83, `PBXFileReference`) | `JARVIS-Watch.app` |
| `PRODUCT_NAME` in Debug-Config `611F90F354171437432F3B72` (Zeile ~432) | `JARVIS Watch App` |
| `PRODUCT_NAME` in Release-Config `7375F648A40047681D9D25B8` (Zeile ~447) | `JARVIS Watch App` |

Die Build-Phase `Embed Watch Content` des iOS-Targets kopiert `JARVIS-Watch.app`.
Weil die Settings zugleich `JARVIS Watch App.app` erzeugen, registriert das
Build-System zwei Produzenten für denselben Ausgabepfad und bricht ab.

Es gibt nur drei Native-Targets (`JARVIS-Watch`, `JARVIS-macOS`, `JARVIS-iOS`);
ein doppeltes Target ist also *nicht* die Ursache. Es ist reine Namensinkonsistenz.

## Empfohlener Fix

`PRODUCT_NAME` an die Produktreferenz angleichen. Zwei Zeilen, beide
Build-Konfigurationen des Watch-Targets:

```
PRODUCT_NAME = "JARVIS Watch App";     →     PRODUCT_NAME = "$(TARGET_NAME)";
```

`$(TARGET_NAME)` ergibt `JARVIS-Watch` und passt damit zu `productReference` und
zur Embed-Phase.

**Nicht ändern:** `PRODUCT_BUNDLE_IDENTIFIER = at.marlon.jarvis.ios.watchkitapp`.
Die Kopplung zwischen iPhone- und Watch-App läuft über die Bundle-ID, nicht über
den Produktnamen. Sie muss `<iOS-Bundle-ID>.watchkitapp` bleiben.

Falls stattdessen der Anzeigename „JARVIS Watch App" erhalten bleiben soll: nicht
über `PRODUCT_NAME` lösen, sondern über `CFBundleDisplayName` in
`Config/JARVIS-Watch-Info.plist`. Die Alternative wäre, die `productReference` auf
`JARVIS Watch App.app` umzustellen — das ist aber der invasivere Weg, weil auch die
Embed-Phase und die Datei-Referenz mitgezogen werden müssen.

## Verifikation nach dem Fix

Beide Targets müssen bauen:

```bash
xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-iOS \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/jarvis-derived-ios \
  CODE_SIGNING_ALLOWED=NO build

xcodebuild -project apple/JARVIS.xcodeproj -scheme JARVIS-macOS \
  -configuration Debug -destination 'platform=macOS' \
  -derivedDataPath /tmp/jarvis-derived-macos \
  CODE_SIGNING_ALLOWED=NO build
```

Erwartet: zweimal `** BUILD SUCCEEDED **`.

## Zweite Aufgabe im selben Zug: Bridge-Adresse

**Erledigt (Stand 2026-09-02). Nicht zurückändern.**

Die Bridge läuft auf Port **8770**. Der Voice-Server behält `8765` (plain `ws://`)
und `tls_ports: [443, 8766]`. `8766` ist Voice-TLS, nicht die Bridge.

Committed `AppModel.defaultServerURL` ist bereits:

```
http://macbook-air-von-marlon.tailfb3c35.ts.net:8770
```

`SettingsView` nutzt `AppModel.defaultServerURL` als TextField-Platzhalter — dort
steht kein eigener URL-String.

Die UserDefaults-Migration in `AppModel` ist ebenfalls schon da: ein gespeicherter
`serverURL` mit `jarvis.local`, Suffix `:8765` oder `:8766` wird auf den Default
überschrieben. Nicht entfernen, und **nicht** auf `jarvis.local:8765` oder `:8766`
zurücksetzen.

Offen bleibt nur der Watch-`PRODUCT_NAME`-Fix oben.

## Bridge-Vertrag (Stand jetzt, getestet)

```
Base URL : http://macbook-air-von-marlon.tailfb3c35.ts.net:8770
Auth     : Authorization: Bearer <JARVIS_APP_TOKEN>   (alternativ X-Jarvis-Token)

GET  /                        offen, Service-Banner
GET  /health                  auth
GET  /files?path=             auth
GET  /files/download?path=    auth
POST /chat  {message, conversation}   auth
POST /stop  {run_id}                  auth
POST /wake  {}                        auth

Fehler: 401 / 400 / 403 / 404 / 502, immer JSON {"error": …}
```

`POST /wake` existiert seit heute und liefert ohne konfiguriertes Relay
`{"awake": true, "relay": false}`. Der frühere 404 auf diesem Pfad ist behoben —
der Client muss dafür nicht angepasst werden.

Die Bridge ist nur im Tailnet erreichbar. Ohne aktives Tailscale auf dem iPhone
gibt es keine Verbindung; das ist beabsichtigt.
