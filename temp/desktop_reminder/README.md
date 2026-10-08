# Desktop Reminder

A lightweight Windows 11 background app where a small animated character **walks onto your
desktop** at reminder time, shows your message ("Drink Water 💧") and reacts to your answer:

* **Done** → character cheers, then walks away.
* **Snooze** → character gets annoyed, walks away, and the reminder comes back after the snooze time.

Python 3.8 · PySide6 · fully local (no browser, no cloud) · JSON storage · character-agnostic engine.

## Quick start (Windows 11)

```powershell
py -3.8 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py            # add --open to show the window, --test to play a test reminder
```

The first run opens the Reminders window (there are none yet) and puts an icon in the system tray.
Use `pythonw run.py` to run without a console window.

### Your first reminder (the MVP flow)

1. **Add Reminder** → message `Drink Water 💧`, time = 2 minutes from now, repeat *Daily* → OK.
2. Wait. At that time the character walks in from the screen edge and shows the message.
3. Click **Done** → happy animation, character leaves. Or **Snooze (10m)** → angry animation,
   character leaves, the reminder returns after 10 minutes.

No need to wait: **Test Reminder** (Reminders tab), **Test character animation** (Settings tab) or
tray ▸ *Test Character* plays the whole sequence immediately.

Want sample data? Copy `data/reminders.example.json` to `data/reminders.json` before first start.

## Tray menu

Open Reminders · Add Reminder · Test Character · Pause Reminders · Settings · Exit

Closing the window keeps the app running in the tray. **Exit** quits it.

## Features

| Area | What you get |
|---|---|
| Reminders | create / edit / delete / enable-disable, message, time, repeat (once, daily, weekly, custom interval), per-reminder snooze, sound on/off, character choice, history + status |
| Characters | placeholder character *Pebble* (drawn with shapes) and a sample PNG-sequence character *Robo*; add your own without touching engine code |
| Desktop | transparent, borderless, always-on-top, non-focus-stealing overlay; multi-monitor aware; configurable position |
| Resilience | corrupt JSON is quarantined, bad entries skipped, missing art/sound degrades gracefully, missed reminders are logged, single-instance lock |
| Startup | optional "Start with Windows" (per-user Run key, no admin rights) |

## Configuration

`config/config.yaml` (also editable from the Settings tab). See [docs/REMINDERS.md](docs/REMINDERS.md).

## Tests

```powershell
python -m unittest discover -s tests -t .          # core engine, storage, characters (no GUI needed)
set QT_QPA_PLATFORM=offscreen & python -m unittest tests.ui.test_ui_smoke   # GUI smoke tests
```

(`pytest` also works: `pip install -r requirements-dev.txt && pytest`.)

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – design, threading model, extension points
* [docs/CHARACTERS.md](docs/CHARACTERS.md) – **how to add a new character**
* [docs/REMINDERS.md](docs/REMINDERS.md) – reminder & configuration guide
* [docs/REVIEW.md](docs/REVIEW.md) – final senior review, risks, known limitations

## Assets

All bundled art and sounds are original/generated (`tools/generate_assets.py`). No third-party or
copyrighted characters are included; use only artwork you own or are licensed to use.
