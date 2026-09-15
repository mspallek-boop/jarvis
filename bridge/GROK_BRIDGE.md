# Grok Bot Bridge (File Queue)

Jarvis und Grok Bot tauschen Aufträge **ohne Webhook** über eine lokale
File-Queue auf dem Mac aus. Keine Secrets, kein Routine-Panel.

## Ordner

Unter `~/.hermes/grok-queue/`:

| Ordner | Wer schreibt | Inhalt |
|---|---|---|
| `inbox/` | Jarvis | Task `{id,task,target,priority,dry_run}` |
| `processing/` | optional | In-flight |
| `outbox/` | Grok/Admin | Ergebnis `{id,status,summary,result}` |

Atomare Writes: zuerst `*.tmp`, dann Rename auf `*.json`.

## Client

```bash
# Ordner sicherstellen
python3 bridge/grok_queue.py init

# Task einstellen (dry_run schreibt sofort ACK in outbox/)
python3 bridge/grok_queue.py enqueue "Testauftrag" --target Admin --dry-run
python3 bridge/grok_queue.py enqueue "…" --target "Botschaft Jarvis" --dry-run

# Ergebnis lesen
python3 bridge/grok_queue.py result <id>

# Inbox listen
python3 bridge/grok_queue.py inbox
```

Python-API: `enqueue_task`, `read_result`, `write_result`, `list_inbox`
in `bridge/grok_queue.py`.

## dry_run

`dry_run: true` → Client legt Task an und schreibt sofort

```json
{"id":"…","status":"ok","summary":"dry_run ack","result":{"dry_run":true,"accepted":true}}
```

in `outbox/`, ohne Admin/Webhook. Damit ist die Pipe lokal prüfbar.

## Live

1. Jarvis: `enqueue` ohne `--dry-run` → Datei in `inbox/`
2. Admin/Grok-Bot: Datei lesen, Auftrag ausführen, `write_result` / outbox-JSON
3. Jarvis: `read_result(id)` pollen

## Tests

```bash
cd bridge && python3 -m unittest test_grok_queue -v
```

## Hermes / Jarvis App

Plugin `hermes-plugin/jarvis_grok` (installed under `~/.hermes/plugins/jarvis_grok`) exposes:

- `grok_delegate` — enqueue; default target `Botschaft Jarvis`
- `grok_delegate_status` — read outbox by id

In Jarvis, ask to delegate to Botschaft Jarvis; the agent should call those tools (not the human CLI).
