# Final review (senior architect pass)

## What was verified, and how

| Check | Status |
|---|---|
| Engine, scheduler, storage, config, geometry, controller, character manager, bundled assets | **82 unit tests pass** (`python -m unittest discover -s tests -t .`) |
| Python 3.8 grammar | all files parse with `ast.parse(..., feature_version=(3, 8))`; no 3.9+ APIs used (no `list[int]`, `X | None`, `removeprefix`) |
| Python 3.8 *runtime* | **not executed** on 3.8 (authoring sandbox had 3.12) |
| Qt code (overlay, sprite character, dialogs, tray, main) | **written but not executed** – PySide6 could not be installed in the authoring sandbox. Smoke tests exist in `tests/ui/` and must be run on your machine |

Treat the GUI as "complete, reviewed, unverified" until you run `python run.py --test` once.
If something misbehaves, `logs/desktop_reminder.log` plus the traceback is all that is needed to fix it.

## Requirement conflicts / deviations (and the closest robust alternative)

1. **Python 3.8 vs PySide6** – PySide6 6.8+ dropped 3.8; `requirements.txt` pins `<6.8` (6.7.x).
2. **`message_duration` config key** – a timed message conflicts with "wait for Done/Snooze". Replaced by
   `reaction_duration` (happy/angry length) and `auto_snooze_after_seconds` (0 = wait forever).
3. **Folder layout** – `characters/characters/…` became `characters/builtin/…` (shipped) and
   `assets/characters/…` (yours); docs live in `docs/`.
4. **Optional sleeping animation** – the manifest/fallback chain accepts a `sleep` animation, but no state
   uses it yet (a 7-state machine was requested). Listed under future work.
5. **Never steal focus** – implemented with `WindowDoesNotAcceptFocus` + `WA_ShowWithoutActivating`
   (maps to `WS_EX_NOACTIVATE`); buttons still receive mouse clicks. Not keyboard-operable by design.
6. **Toasts** – none; the character is the only notification (as specified).

## Findings by area

* **UI thread safety** – scheduler thread never touches Qt except emitting a signal on a `QObject` that lives
  on the GUI thread (queued delivery). Manager returns deep copies. A lambda connected directly to a
  cross-thread signal would run on the wrong thread – avoided deliberately and documented.
* **Scheduler reliability** – 1 Hz poll against wall-clock `datetime.now()` (no drift accumulation), claims
  are atomic, exceptions are contained per pass, delivery failure releases the claim, a crashing character
  is replaced by a 1-minute snooze (no 1 Hz failure loop). Sleep/resume and long downtime are handled by
  the missed-grace rule.
* **Transparent window** – `WA_TranslucentBackground` + frameless + tool window (no taskbar button).
  Fully transparent pixels should pass clicks through on Windows layered windows – *verify visually*.
* **Multi-monitor** – screen re-resolved on every reminder (handles hot-plug/resolution change); entry edge
  avoids sides that touch another monitor (unit-tested). Mixed-DPI setups rely on Qt's logical coordinates.
* **Memory** – one overlay + animation set per character, created lazily and reused; frames are decoded
  once; no per-frame allocations beyond QPainter calls; stale timers are neutralised by a generation counter.
* **Clean shutdown** – scheduler thread joined, character hidden, tray removed, lock file released.
* **Restart** – state persisted atomically; `active` is reset to `scheduled` after a crash; overdue
  reminders inside the grace window fire at start-up, older ones are logged as missed.
* **Missing assets** – per-animation fallback chain, placeholder box, sounds skipped with one warning.
* **Extensibility** – new characters and storage backends require no change to scheduler/manager/store.

## Known limitations / risks

* Exclusive-fullscreen games and some video players can draw above topmost windows; the overlay may not show.
* `winsound` plays one sound at a time (async); an `exit` sound can cut off a `happy` sound. Use short WAVs.
* Interval reminders that were snoozed continue from the snoozed time, shifting the grid.
* Settings changes are saved immediately; the default-snooze setting only affects *new* reminders.
* "Start with Windows" stores an absolute path; re-toggle it if the folder is moved.
* Localised `%p` (AM/PM) in the table follows the system locale.

## Future enhancements (out of MVP scope)

Sleeping/bored state after long inaction · drag-to-reposition · Windows toast fallback · SQLite stores ·
per-reminder icons · packaged installer (PyInstaller) · lottie/skeletal `Animation` subclass.
