# Architecture

```
ReminderManager ──(owns state)──► ReminderStore (JSON now, SQLite later)
      ▲  claim_due()
Scheduler thread (1 Hz, GUI-free)
      │ list of Reminder
      ▼  queued Qt signal  (scheduler thread ➜ GUI thread)
CharacterController ──► CharacterManager ──► BaseCharacter implementation
      │  applies Done/Snooze to the manager, plays sounds
      ▼
SpriteCharacter ──► Animation objects ──► DesktopOverlay (transparent Qt window)
```

## Layers and what they may know

| Layer | Module | Knows about | Must not know about |
|---|---|---|---|
| Model | `reminders/reminder.py` | itself | Qt, storage, characters |
| Rules | `reminders/scheduler.py` (`next_occurrence`, `advance_after_fire`, `snooze_until`) | Reminder | Qt, storage |
| Engine | `reminders/reminder_manager.py` | store interface, rules | Qt, characters |
| Storage | `storage/reminder_store.py` | model | engine |
| Contract | `characters/base_character.py` | model, config | Qt |
| Controller | `characters/character_controller.py` | manager, character contract, sound | Qt, concrete characters |
| Rendering | `characters/sprite_character.py`, `animation*.py`, `ui/desktop_overlay.py` | Qt | engine internals |
| App shell | `main.py`, `ui/*` | everything | – |

Result: the engine and controller are unit-tested with no GUI (`tests/`), and adding a character or a
storage backend changes **none** of `scheduler.py`, `reminder_manager.py`, `reminder_store.py`.

## Reminder lifecycle

`scheduled → active → completed | snoozed → active …` (`missed` when overdue past the grace period;
`disabled` when switched off). Every transition is written to the history.

* `claim_due(now)` atomically marks due reminders *active* (so they cannot fire twice) and returns copies.
* Done → `advance_after_fire`: next daily/weekly/interval slot; one-time reminders disable themselves.
* Snooze → `next_due = now + snooze_minutes`.
* Overdue by more than `missed_grace_minutes` (app was closed, PC asleep) → recorded as *missed* and
  rescheduled instead of popping up hours late. Within the grace period it fires on start-up.

## Character state machine

```
HIDDEN → ENTERING → IDLE → REMINDER → HAPPY ┐
                              └────→ ANGRY ─┴→ EXITING → HIDDEN
```
Defined in `base_character.py` (`ALLOWED_TRANSITIONS`). Characters call `_set_state()`; the controller is
notified of every change (that is how sounds are triggered, independent of the character).

Contract used by the controller: `show_reminder(reminder)`, `react("completed"|"snoozed")`,
`hide(immediate=False)`; the character reports button presses via `_emit_action()`.

## Animation system

Anything with `render(painter, rect, t_ms)` is an `Animation`:

* `FrameAnimation` – PNG sequences, GIF/WebP (decoded to frames), sprite sheets
* `ProceduralAnimation` – QPainter drawing (placeholder character; vector art)
* `PlaceholderAnimation` – automatic fallback when art is missing
* Skeletal/Lottie/etc. later = another `Animation` subclass; no other code changes.

Missing animations fall back `reminder/happy/angry/sleep → idle → walk → placeholder box`.

## Threading model

* Scheduler: one daemon thread; it only calls `manager.claim_due()` and emits a Qt signal.
* All widgets/animations live on the GUI thread. The signal is delivered through a queued connection to a
  `QObject` slot on the GUI thread (`UiBridge`). **Never connect scheduler callbacks to bare lambdas.**
* `ReminderManager` is guarded by an `RLock`; it returns deep copies, never live objects.

## Storage

`ReminderStore` / `HistoryStore` are abstract. JSON implementation writes atomically (temp file +
`os.replace`), quarantines unreadable files as `*.corrupt-<timestamp>`, and skips individual bad entries.
For SQLite: implement the two interfaces and pass them to `ReminderManager` in `main.py`.

## Extension points

1. **New character** – see CHARACTERS.md (no engine changes).
2. **New storage backend** – implement `ReminderStore`/`HistoryStore`.
3. **New animation type** – subclass `Animation`, register in `animation_loader._BUILDERS`.
4. **New repeat rule** – add a branch in `next_occurrence` / `advance_after_fire` and a constant in `reminder.py`.
5. **Windows toast fallback** – add a listener in `main.py`; the engine is unaffected.
