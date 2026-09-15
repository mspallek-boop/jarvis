# Telefon: JARVIS ruft für den User an

Hermes startet über das Plugin `jarvis_phone` (`phone_call`, `phone_call_status`)
einen Anruf. `call.py` meldet sich bei Fairytel an (SIP über UDP), wählt, und
sobald abgehoben wird, führt OpenAI Realtime (`gpt-realtime-2.1`) das Gespräch
nach dem Auftrag von Hermes. Nach dem Auflegen kommt das Ergebnis per
`jarvis-notify` in die App.

```
Hermes ─phone_call─▶ call.py start ──(detached)──▶ call.py run
                                                    │  SIP/RTP G.711   ▲ WebSocket, audio/pcmu
                                                    ▼                  │
                                              sip.fairytel.at     api.openai.com
```

## Einrichtung

In `~/.hermes/.env` (nie in Argumenten, Logs oder Ergebnissen):

| Variable | Inhalt |
|---|---|
| `FAIRYTEL_SIP_USER` | Nummer im Format `43720…` |
| `FAIRYTEL_SIP_PASSWORD` | SIP-Passwort aus secure.fairytel.at → SIP |
| `OPENAI_API_KEY` | vorhanden; Realtime-Guthaben nötig |

Optional: `PHONE_PRINCIPAL` (Name, in dessen Auftrag angerufen wird; Standard
`Marlon Spallek` — immer der volle Name, so gewünscht), `PHONE_VOICE` (`cedar`), `PHONE_DIAL_FORMAT` (`national`),
`PHONE_MAX_CALLS_PER_DAY` (5), `PHONE_MAX_CALLS_PER_MONTH` (20).

Laufzeit: `LocalData/Runtime/phone-venv` (Python 3.11, `websockets==15.0.1`).
Live-Kopie: `~/.hermes/services/phone/`, Plugin: `~/.hermes/plugins/jarvis_phone/`.
Nach Änderungen beide kopieren; nach Plugin-Änderungen `hermes gateway restart`.

Prüfen ohne Anruf (Anmeldung bei Fairytel + eine Ein-Wort-Antwort von OpenAI):

```sh
LocalData/Runtime/phone-venv/bin/python ~/.hermes/services/phone/call.py check
```

## Regeln im Code

- Nur Österreich und Deutschland; Notruf-/Kurznummern (unter 8 Ziffern),
  Mehrwert-, Service- und Auskunftsnummern werden abgelehnt.
- Ein Anruf gleichzeitig, Tages- und Monatslimit, hartes Zeitlimit (Standard
  6, höchstens 15 Minuten), 45 s Klingeln.
- Die Stimme stellt sich als KI vor (EU-KI-Verordnung, Art. 50) und sagt nur
  zu, was im Auftrag steht.
- Protokolle und Transkripte: `~/.hermes/phone/calls/<id>.json` (Modus 600).

## Netzwerk

- Der A1-Router vergibt Ports je Ziel neu (symmetrisches NAT). Deshalb kein
  STUN im SDP; die Signalisierung nutzt `rport`, der Ton ist symmetrisches RTP
  und startet sofort, damit Fairytels Medienserver den Rückweg lernt.
- IPv6 zu api.openai.com hängt über diesen Anschluss; der WebSocket verbindet
  deshalb mit Happy Eyeballs (`HAPPY_EYEBALLS = 0.25`).

## Kosten (Stand 2026-09)

Fairytel „Easy“ (Tarifblatt 2023-08-29, Taktung 60/60): 0 € Grundgebühr,
3,9 ct/min in österreichische Netze, nach Deutschland 2 ct/min Festnetz und
10 ct/min Mobil. OpenAI Realtime: grob 5–15 ct pro Gesprächsminute. Bei 1–2
Anrufen im Monat also etwa 1–2 € im Monat.
