# HealthKit integration (iOS app → local bridge)

HealthKit is an iOS/watchOS-only framework. There is no HealthKit API on
macOS, so `JARVIS-macOS` never requests or reads health data — only the
`at.marlon.jarvis.ios` app does. Apple Watch activity (steps, workouts, active
energy) already syncs into HealthKit on the paired iPhone automatically via
the Health app; the watchOS target does not need its own HealthKit
entitlement or a separate network call for this feature.

This is the contract for the iOS-side implementation (owned by the native app
per this repo's `CLAUDE.md`). The server side of this contract already exists
and is covered by `tests/test_calorie_tracking.py`.

## 1. Entitlement

Add the HealthKit capability to the iOS target's entitlements file,
`apple/Config/JARVIS.entitlements` (used by the `at.marlon.jarvis.ios` Debug
and Release configurations only — leave `apple/Config/JARVIS-macOS.entitlements`
untouched):

```xml
<key>com.apple.developer.healthkit</key>
<true/>
```

Xcode also requires the HealthKit capability to be added in the target's
"Signing & Capabilities" tab so it's registered with the App ID; editing the
entitlements file alone is not sufficient.

## 2. Info.plist usage string

The app only *reads* HealthKit data, so it needs `NSHealthShareUsageDescription`
only (not `NSHealthUpdateUsageDescription`, which is for writing). Add it as a
build setting on the iOS target (Debug and Release) in `apple/JARVIS.xcodeproj/project.pbxproj`,
next to the existing `INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone`
entries (~line 768/789):

```
INFOPLIST_KEY_NSHealthShareUsageDescription = "JARVIS reads your step count, active energy, and dietary sugar to track your daily calorie balance.";
```

Without this string, `requestAuthorization` crashes the app at runtime — this
is not optional.

## 3. HealthKit types to request

Read-only authorization for exactly three quantity types, matching what the
server's `record_activity` accepts:

| HealthKit type | Field sent to the server |
|---|---|
| `HKQuantityTypeIdentifierStepCount` | `steps` |
| `HKQuantityTypeIdentifierActiveEnergyBurned` | `active_energy_kcal` |
| `HKQuantityTypeIdentifierDietarySugar` | `dietary_sugar_g` |

Do not request write access, workouts, heart rate, or sleep — the server has
no fields for them and never asks for more than a daily aggregate.

## 4. Sync flow

1. On app launch/foreground, call `HKHealthStore.isHealthDataAvailable()`; if
   false (e.g. unsupported device), skip silently — never block the rest of
   the app on HealthKit.
2. Request authorization once (`requestAuthorization(toShare: [], read: types)`).
   If denied, do not re-prompt every launch; Apple's system settings own that.
3. For each of the three types, run an `HKStatisticsQuery` with
   `cumulativeSum` over the current calendar day (device-local midnight to
   now).
4. Send one aggregate for today via the existing endpoint, using the same
   request pattern as `JarvisAPIClient`'s other calls (`baseURL.appendingPathComponent`,
   `X-Jarvis-Token` header, JSON body):

   ```
   PUT {baseURL}/activity/days/{yyyy-MM-dd}
   {"steps": 8421, "active_energy_kcal": 320, "dietary_sugar_g": 5}
   ```

   Add this as a new method on `JarvisAPIClient` (e.g. `syncActivity(day:steps:activeEnergyKcal:dietarySugarG:)`)
   following the existing `request(path:method:body:timeout:)` helper — omit
   any field HealthKit didn't return rather than sending `0`, since the server
   treats `null` as "never recorded" and `0` as a real zero.
5. Repeated syncs upsert (the server keys on the calendar day), so calling
   this on every foreground is safe and requires no local dedup logic.

Background delivery (`HKObserverQuery` + `enableBackgroundDelivery`) is
intentionally out of scope for v1 — a foreground/on-launch sync is enough for
a daily calorie balance and avoids taking on the `UIBackgroundModes`
capability and its review/battery tradeoffs. Add it later only if the
foreground sync proves insufficient in practice.

## 5. Where the data goes

The synced aggregate is stored only in the local server's SQLite diary
(`server/logs/calorie_tracking.sqlite3`, see `docs/CALORIE_TRACKING.md`). It
is never forwarded to Hermes, an LLM provider, or any third party by the
server. `GET /api/calories/days/{date}` folds it into `steps`,
`activity_calories`, and `net_calories` in the same response used by the rest
of the app and the `jarvis_calories` Hermes plugin.

## Status

Server-side storage, validation, and the `/api/activity/days/{day}` endpoint
are implemented and tested (`tests/test_calorie_tracking.py`). The iOS-side
HealthKit authorization, queries, and the `JarvisAPIClient` sync call
described above are not yet implemented — that is native-app work under
`apple/` and out of scope for the backend session that wrote this doc.
