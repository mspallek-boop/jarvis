# Zielarchitektur: JARVIS überall

```text
iPhone JARVIS App
        │
        │ Tailscale (privat, verschlüsselt)
        ▼
Always-on Relay / JARVIS Core
(Raspberry Pi, NAS oder Mini-PC)
        │
        ├── JARVIS bleibt erreichbar
        ├── Wake-on-LAN ins Heimnetz
        └── Aufträge an den Mac
                         │
                         ▼
                 Mac Bridge + Hermes
                 Apps · Tools · Dateien
```

## Was in welchem Zustand möglich ist

| Zustand | Chat mit JARVIS | Mac steuern | lokale Mac-Dateien |
|---|---:|---:|---:|
| Mac online | ja | ja | ja |
| Mac schläft | Relay weckt ihn, dann ja | nach Wake | nach Wake |
| Mac vollständig aus | nur mit separatem Hermes-Core | nein | nur synchronisierte Dateien |

Ein iPhone darf iOS-bedingt keinen dauerhaften Server im Hintergrund hosten.
Ein ausgeschalteter Mac führt ebenfalls keinen Dienst aus. Deshalb ist ein
Always-on-Knoten keine optionale Softwareentscheidung, sondern eine physische
Voraussetzung für echte 24/7-Erreichbarkeit.

## Dateien

Die Mac-Bridge stellt freigegebene Verzeichnisse der nativen App bereit. Der
Standard ist der Benutzerordner; Schlüssel, `.hermes`, `.ssh`, Zertifikate und
versteckte Dateien sind gesperrt. Wenn Dateien auch bei ausgeschaltetem Mac
verfügbar sein müssen, gehören die betreffenden Ordner zusätzlich nach iCloud
Drive oder auf den Always-on-NAS. Ein nicht laufender Mac kann seine interne SSD
nicht ausliefern.

## Sicherheitsregeln

- Kein Port-Forwarding am Router.
- Tailscale zwischen iPhone, Relay und Mac.
- Getrennter App-Token; der Hermes-API-Key verlässt nie den Host.
- Dateizugriff nur über konfigurierte Roots.
- Ruhezustand statt Ausschalten für zuverlässiges Aufwecken.
