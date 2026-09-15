# Nachtschicht

JARVIS arbeitet nachts allein und legt morgens am Mac-HUD vor, was er getan hat.
Vorgaben von Marlon (15.09.2026): Nachts entstehen nur Entwürfe, nichts geht ohne
Freigabe nach außen; Werkzeuge nach Aufgabenart; Briefing am Mac-HUD.

## Ablauf

1. **03:00** — Hermes-Cron-Job „JARVIS Nachtschicht" (`hermes cron list`) mit dem
   Skill `jarvis-nightshift` (`hermes-plugin/skills/jarvis-nightshift/SKILL.md`,
   installiert unter `~/.hermes/skills/productivity/jarvis-nightshift/`).
   Kalender, Gmail und WhatsApp sichten, recherchieren, Entwürfe schreiben, einen
   Code-Punkt als Patch vorbereiten.
2. **Bericht** — `Jarvis Output/Nachtschicht/<JJJJ-MM-TT>.md` (Git-ignoriert),
   Entwürfe nummeriert E1, E2, … mit `Status: offen`.
3. **Ab 07:30** — der Voice-Server spricht das Briefing, sobald ein HUD offen ist,
   spätestens bis 12:00 (`proactive.schedule` mit `until` in `server.yaml`).
4. **Freigabe** — „schick E2" im HUD sendet genau diesen Entwurf und setzt ihn im
   Bericht auf `gesendet` (Regel in `~/.hermes/SOUL.md`, Abschnitt
   „Nachtschicht-Entwürfe freigeben").

## Sicherungen

- Der Cron-Job hat nur die Toolsets `terminal, file, web, skills, todo, memory,
  session_search, gmail, health` — kein Telefon, kein Browser, keine
  Mac-Steuerung, keine Cron-Verwaltung. Ausgabe `local`, also keine Meldung per
  WhatsApp.
- Der Terminal bleibt, weil Codex und Claude darüber laufen. Damit könnte der
  Agent technisch `hermes send` aufrufen; das Senden verbieten Skill und SOUL.
  Das ist eine Anweisung, keine technische Sperre.
- Gmail ist nur lesend; Mail-Entwürfe muss Marlon selbst abschicken.
- Code-Arbeit läuft über `scripts/jarvis-nightshift-code.sh` in einem
  Wegwerf-Worktree unter `/tmp`: kein Commit, kein Eingriff in den Haupt-Checkout,
  am Ende nur Patch und Log im Nachtschicht-Ordner.

## Werkzeuge

| Aufgabe | Agent |
|---|---|
| Code | Codex (`BACKEND=codex`, Standard) |
| Codex-Kontingent leer | Qwen Code (`BACKEND=qwen`, nur wenn angemeldet), dann Claude |
| Planung, Review, lange Texte | Claude Code, `--permission-mode plan` |
| Aktuelles aus dem Web | Hermes' Websuche |

Botschaft Jarvis (Grok) ist nicht eingeplant: Die Queue unter
`~/.hermes/grok-queue` hat derzeit keinen Abnehmer.

## Bedienung

```bash
hermes cron list                          # Status und nächster Lauf
hermes cron run <id>                      # beim nächsten Tick einmal ausführen
hermes cron pause <id>                    # aussetzen
BACKEND=none scripts/jarvis-nightshift-code.sh "Probe"   # Code-Pipeline ohne Agent prüfen
```

Qwen Code anmelden (einmalig, selbst im Terminal, mit Browser):
`qwen --auth-type qwen-oauth` starten und im Browser mit dem qwen.ai-Konto
einloggen. Danach funktioniert auch `qwen "<Auftrag>"` ohne Terminal-Dialog.
