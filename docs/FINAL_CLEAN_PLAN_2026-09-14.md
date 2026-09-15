# Jarvis Final Clean Plan — 2026-09-14 (local)

## Scope
- Lokal only, kein Push
- Telefon: geblockt bis Marlon Fairytel auflädt (Admin)

## Known local deliverables (uncommitted)
- bridge/grok_queue.py, GROK_BRIDGE.md, test_grok_queue.py (+ legacy grok_client/callback)
- hermes-plugin/jarvis_grok/
- docs/FINAL_STATUS_2026-09-14.md
- ~/.hermes plugins/config already live for jarvis_grok + queue dirs

## Proposed clean commits (NOT executed — Admin/PR-Wächter)
1. feat(bridge): grok file-queue client + docs + tests
2. feat(hermes): jarvis_grok plugin (delegate to Botschaft Jarvis)
3. docs: FINAL_STATUS + phone blocker note
4. chore: remove ~/.hermes/grok-webhook-fill.env leftover after webhook drop

## Phone blocker
- SIP/OpenAI checks OK
- Last real fail: empty Fairytel balance (2026-09-11)
- No test call tonight

## Morning checklist
1. Fairytel top-up (Marlon)
2. Approve short test call (Admin/Marlon)
3. Review/approve git clean commits or PR
