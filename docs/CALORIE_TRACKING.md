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

## Soll from the goal

The goal is two numbers: the daily calories and, optionally, the goal body
weight. Every nutrient's Soll is derived from them — nothing is set by hand:

| Nährwert | Soll | Art |
|---|---|---|
| Kalorien | `daily_calories` | Obergrenze |
| Eiweiß | 2 g × goal weight (without one: 25 % of the calories) | Mindestwert |
| Fett | 30 % of the calories ÷ 9 | Obergrenze |
| Kohlenhydrate | the remaining calories ÷ 4 | Obergrenze |
| Zucker | 10 % of the calories ÷ 4 (WHO ceiling) | Obergrenze |

```json
PUT /api/calories/goal
{"daily_calories": 2000, "goal_weight_kg": 70}
```

Omitting `goal_weight_kg` keeps the weight already set. A day summary carries
`targets` and a `nutrients` list with `actual`, `target`, `limit` (`max`/`min`)
and `status`: `ok`, `over`, `under`, or `incomplete` when some entries of the
day lack that value, so the Ist is only a lower bound. The evening balance and
the HUD panel both render that list as Ist / Soll.

## Sugar

Any food entry may carry optional nutrition values in grams (0–2000):

```json
POST /api/calories/entries
{"calories":540,"description":"vegetable pasta","protein_g":22,"fat_g":14,"carbohydrates_g":75,"sugar_g":6.5}
```

A day summary's `total_sugar_g` adds logged entries' `sugar_g` to whatever
`dietary_sugar_g` HealthKit synced for that day (see below), so `null` means
nothing was ever recorded — not zero grams.

## Daily WhatsApp balance

`calories_daily_report` is the versioned report generator for the evening
balance. It uses the existing daily-summary data and returns a message ready to
send unchanged: a dated heading, every nutrient as Ist / Soll with a verdict,
the activity block, then every recorded food and drink. Values that
were never logged are shown as `nicht erfasst`, never as invented zeroes.

It goes out every evening at 22:00 to the WhatsApp group "Nährwerte Jarvis"
(members: the user only). `scripts/jarvis-calorie-balance.py`, started by
`launchd/com.jarvis.calorie-balance.plist` from `~/.hermes/services`, fetches
the day summary, formats it with the plugin's own `report.py` and sends it with
`hermes send` — no model in between, so a rate-limited free model can neither
delay nor reword it. It sends at most once per day and only until midnight, so
a Mac that sleeps through 22:00 catches up that evening but never sends last
night's balance the next morning. The group's chat id lives in `~/.hermes/.env`
as `JARVIS_CALORIE_REPORT_CHAT`; a failed send is reported in the JARVIS app.

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
