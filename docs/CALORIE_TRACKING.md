# Persistent calorie tracking

The JARVIS server now owns a local SQLite calorie diary. It works while no
ChatGPT conversation is open: entries are committed to
`server/logs/calorie_tracking.sqlite3` by default and remain after server or
client restarts. That file is ignored by Git. Back it up with the rest of the
user's encrypted local data if the history matters.

All routes use the existing `/api/*` token gate. When `JARVIS_HUD_TOKEN` is
configured, send it as `X-Jarvis-Token`; do not put it in a command history.

```bash
# Set a goal, then log an entry (both operate only on the local JARVIS server).
curl -X PUT http://127.0.0.1:8765/api/calories/goal \
  -H 'Content-Type: application/json' \
  -d '{"daily_calories":2200}'
curl -X POST http://127.0.0.1:8765/api/calories/entries \
  -H 'Content-Type: application/json' \
  -d '{"calories":540,"description":"vegetable pasta","meal":"dinner"}'
curl http://127.0.0.1:8765/api/calories/days/2026-09-09
curl 'http://127.0.0.1:8765/api/calories/progress?weeks=8'
```

`occurred_at` is optional ISO-8601 input; omitted means the server's local
time. Each daily record reports entries, total calories, configured target and
remaining calories. A weekly report always covers Monday through Sunday. The
multi-week report is the durable progress history; weekly check-ins can add an
optional measured `weight_kg` and a reflection note:

```json
POST /api/calories/checkins
{"week_start":"2026-09-07", "weight_kg":76.4, "note":"Four tracked days; meal prep helped."}
```

To use natural language through Hermes, install/copy the sibling
`hermes-plugin/jarvis_calories` plugin using the same plugin mechanism as
`hud_display`. It exposes `calories_log`, daily/weekly summaries, multi-week
progress, target changes and weekly check-ins. It calls the local API only.

The HUD (`server/hud/index.html`) also has a CALORIES panel: it shows today's
total, target, remaining calories and step count, lists today's entries with
a one-click delete, and has a quick `kcal` + description field to log an
entry without talking to Hermes at all. It refreshes every 60s and calls the
same `/api/calories/*` routes above.

## Sugar

Any food entry may carry an optional `sugar_g` (grams, 0–2000):

```json
POST /api/calories/entries
{"calories":540,"description":"vegetable pasta","sugar_g":6.5}
```

A day summary's `total_sugar_g` adds logged entries' `sugar_g` to whatever
`dietary_sugar_g` HealthKit synced for that day (see below), so `null` means
nothing was ever recorded — not zero grams.

## Activity (steps and calorie balance from Apple Health)

The iPhone/Watch app — not the Mac, which has no HealthKit — reads today's
step count, active energy burned and dietary sugar total from Apple Health and
pushes one daily aggregate to the local server:

```bash
curl -X PUT http://127.0.0.1:8765/api/activity/days/2026-09-09 \
  -H 'Content-Type: application/json' \
  -d '{"steps":8421,"active_energy_kcal":320,"dietary_sugar_g":5}'
```

All three fields are optional but at least one is required; repeated syncs for
the same day upsert rather than duplicate. `GET /api/calories/days/{day}`
folds the synced `steps` and `activity_calories` (active energy) into the
existing daily summary and adds `net_calories` (`total_calories -
activity_calories`) — a realistic calorie balance, not a BMR/TDEE estimate,
since JARVIS does not model basal metabolism. See
`docs/HEALTHKIT_INTEGRATION.md` for the entitlement, the Info.plist usage
strings and exactly which HealthKit types the app is allowed to read.

No food-recognition service, cloud backup, or nutrition database is assumed or
configured. Those can be added later as explicit integrations; the durable
local API remains the source of truth and avoids invented credentials or
third-party data sharing.
