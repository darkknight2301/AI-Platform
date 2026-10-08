# Reminders & configuration guide

## Reminder fields (`data/reminders.json`)

```json
{"version": 1, "reminders": [
  {"id": "water", "message": "Drink Water 💧", "time": "10:30", "repeat": "daily",
   "snooze_minutes": 10, "sound_enabled": true, "character": "", "enabled": true}
]}
```

| Field | Notes |
|---|---|
| `message` | 1–200 characters; emoji are fine |
| `time` | `HH:MM` 24h (`"10:30 AM"` is also accepted when hand-editing), local time |
| `repeat` | `once`, `daily`, `weekly`, `interval` |
| `date` | `YYYY-MM-DD`, for `once` (filled in automatically if omitted) |
| `weekdays` | for `weekly`: `0`=Mon … `6`=Sun, at least one |
| `interval_minutes` | for `interval`: first fire at `time`, then every N minutes (1–10080) |
| `snooze_minutes` | 1–1440 (UI presets 5, 10, 15, 30, 60, or custom) |
| `sound_enabled` | per reminder; also needs the global switch |
| `character` | character id, or `""` for the default |
| `enabled` | disabled reminders never fire |
| `status`, `next_due`, `last_triggered` | managed by the app; leave alone |

Duplicates (same message, time and schedule) are rejected. A one-time reminder in the past is rejected.
Invalid entries in the file are skipped with a log warning; the rest still load.
`data/history.json` keeps the last 500 events (fired / completed / snoozed / missed).

## Repeat behaviour

* **Daily** – every day at `time`. **Weekly** – on the selected weekdays at `time`.
* **Custom interval** – `time`, `time+N`, `time+2N`, … (pins to that grid; slots missed while closed are skipped).
* **Once** – disables itself after *Done*; re-enable it to arm it for the next occurrence.
* **Snooze** – returns `snooze_minutes` after you clicked it, then continues the normal schedule after *Done*.

## `config/config.yaml`

| Key | Default | Meaning |
|---|---|---|
| `application.character_position` | `bottom_right` | `bottom_right`, `bottom_left`, `bottom_center` |
| `application.default_character` | `default_character` | used when a reminder has no character |
| `application.monitor` | `cursor` | `cursor` (screen with the mouse) or `primary` |
| `application.start_with_windows` | `false` | mirrors the Settings checkbox (registry is the source of truth) |
| `application.sound_enabled` | `true` | global sound switch |
| `animation.enter_duration` / `exit_duration` | `1.5` | seconds to walk in / out |
| `animation.reaction_duration` | `1.8` | happy / angry animation length |
| `reminder.default_snooze_minutes` | `10` | pre-selected snooze for new reminders |
| `reminder.missed_grace_minutes` | `30` | older than this ⇒ logged as *missed*, not shown |
| `reminder.auto_snooze_after_seconds` | `0` | `0` waits for you; N auto-snoozes an unanswered reminder |

Invalid values are ignored with a log warning and replaced by defaults.

## Sounds

`assets/sounds/{enter,reminder,happy,angry,exit}.wav` (WAV only). A character may override any of them in
its own `sounds/` folder. A missing file is skipped (warned once).

## Start with Windows

Settings → checkbox. Writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DesktopReminder`
(no admin rights) pointing at `pythonw.exe run.py`. Unticking removes it. If you move the project folder,
untick and tick again.
