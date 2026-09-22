"""
Global numpad hotkey detection for Windows.

THE CORE PROBLEM
-----------------
Windows keyboards report a *scan code* for every physical key, plus an
"extended" flag for a handful of keys that would otherwise be ambiguous.
The numpad is the biggest source of ambiguity on the whole keyboard:

  - With Num Lock ON, Numpad 0-9/. send number/decimal virtual keys.
  - With Num Lock OFF, the exact same physical keys send navigation
    virtual keys instead (Insert, End, Down, PageDown, Left, Clear,
    Right, Home, Up, PageUp, Delete) - completely different from what
    they'd send with Num Lock on.
  - Those navigation virtual keys are *also* what the separate, dedicated
    Home/End/arrow-key cluster sends.

So neither "the character typed" nor "the virtual key code" is a safe way
to recognise "physical Numpad 5" - both change with Num Lock, and both
can collide with unrelated keys.

What does NOT change is the raw hardware scan code, plus one "extended"
bit: the dedicated Home/End/arrow cluster always sets that bit, while the
numpad's copies of those same scan codes never do. That (scan_code,
extended) pair uniquely and permanently identifies each physical numpad
key, completely independent of Num Lock, and this app hooks at exactly
that level - which also means the soundboard keeps working correctly
regardless of whether Num Lock happens to be on or off.

The `keyboard` package already computes this for us on Windows and
exposes it as `KeyboardEvent.is_keypad` (see the installed package at
keyboard/_winkeyboard.py, function `process_key`, and its hand-built
`keypad_keys` scan-code table). This module keys its lookup table on
(scan_code, is_keypad) instead of key *names*, since names / virtual-key
codes are exactly the part Num Lock is allowed to change.

VERIFIED SCAN CODES
--------------------
Cross-checked directly against keyboard/_winkeyboard.py's keypad_keys
table (not just recalled from memory) - see the accompanying README for
how this was verified:

    key            scan_code   is_keypad   (what it sends w/o Num Lock)
    Numpad 0          82          True     Insert
    Numpad 1          79          True     End
    Numpad 2          80          True     Down
    Numpad 3          81          True     PageDown
    Numpad 4          75          True     Left
    Numpad 5          76          True     (Clear - no nav equivalent)
    Numpad 6          77          True     Right
    Numpad 7          71          True     Home
    Numpad 8          72          True     Up
    Numpad 9          73          True     PageUp
    Numpad +          78          True     -                (volume up)
    Numpad -          74          True     -                (volume down)
    Numpad *          55          True     -                (next playlist)
    Numpad /          53          True     (extended)        (prev playlist)
    Numpad .          83          True     Delete            (stop last)
    Numpad Enter      28          True     (extended; intentionally unbound)
    Num Lock          69          True     (extended)
    Delete (dedicated)83          False    n/a - not numpad  (panic, default)

THE "CE" KEY
------------
A physical "CE" (Clear Entry) key, as seen on some calculator-style
keypads, is not a standard Windows scan code and has no fixed identity -
it simply does not exist on a standard 104/105-key layout, and the
`keyboard` library has no name for it either. Rather than guess and
potentially bind the wrong physical key, this app defaults the
Panic/Stop-All action to the dedicated Delete key (83, False) - the one
in the Insert/Home/PgUp/Delete/End/PgDn cluster, NOT the numpad's own
"." key (83, True), which is already Stop Last - and exposes a "Rebind"
control in the GUI that captures the very next physical key you press,
using this same (scan_code, is_keypad) mechanism. Anyone whose keypad has
a real, dedicated CE key can bind it directly there - no code changes
needed.

PLAYLIST CYCLING
-----------------
Numpad `*` and `/` switch to the next/previous playlist instead of
adjusting volume (that's `+`/`-` now). They share a scan-code table entry
each, same as every other special key here, so rebinding/suppression
logic treats them identically to volume/stop-last.

NUM LOCK AS THE MASTER ARM/DISARM SWITCH
------------------------------------------
Num Lock (scan_code 69, is_keypad True - see the table above) doubles as
a physical enable/disable switch for the whole soundboard, equivalent to
clicking the header's Disable/Enable button: Num Lock ON means the board
is armed (numpad presses trigger sounds); Num Lock OFF means every
numpad press is left completely alone and simply falls through to
whatever Num Lock's own OS-level state makes it do.

This needed two-tier control, not a single "hook on/off" flag:
`HotkeyManager.active` (the low-level hook itself) has to stay
registered at all times so Num Lock presses are still seen even while
disarmed - otherwise there'd be no way to turn the board back on again.
`HotkeyManager.enabled` is the new, separate arm/disarm flag that
actually gates whether a recognised action dispatches; Num Lock and the
GUI's manual toggle both just flip this one flag; the Num Lock keypress
itself always passes through untouched (never suppressed) either way,
since suppressing it would stop Num Lock's own light/state from
toggling normally.

`enabled` starts out matching whatever Num Lock is actually doing at the
OS level right now (see `_query_num_lock_state` below), read fresh every
time the hook (re)starts, rather than persisted - so it can never get
out of sync with the physical indicator across a restart. From then on
it's tracked purely by counting debounced Num Lock key-down events
(matching every other key here), not by re-querying GetKeyState on every
press: WH_KEYBOARD_LL hooks are known to fire before Windows finishes
updating a toggle key's reported state, so reading it live on each press
is unreliable. The one tradeoff is that something that changes Num Lock
without going through this hook (a second keyboard, a remote session,
an on-screen keyboard) can desync the app's notion of "enabled" from the
real LED; there's no fully race-free fix for that on Windows, short of
polling GetKeyState continuously.
"""
from __future__ import annotations

import logging
import sys
import threading
from typing import Callable, Dict, Optional, Set, Tuple

import keyboard

logger = logging.getLogger(__name__)

KeyId = Tuple[int, bool]  # (scan_code, is_keypad)

SLOT_KEYMAP: Dict[KeyId, str] = {
    (82, True): "0",
    (79, True): "1",
    (80, True): "2",
    (81, True): "3",
    (75, True): "4",
    (76, True): "5",
    (77, True): "6",
    (71, True): "7",
    (72, True): "8",
    (73, True): "9",
}

VOLUME_UP_KEYS: Set[KeyId] = {(78, True)}       # Numpad +
VOLUME_DOWN_KEYS: Set[KeyId] = {(74, True)}     # Numpad -
STOP_LAST_KEYS: Set[KeyId] = {(83, True)}       # Numpad .
NEXT_PLAYLIST_KEYS: Set[KeyId] = {(55, True)}   # Numpad *
PREV_PLAYLIST_KEYS: Set[KeyId] = {(53, True)}   # Numpad /
NUM_LOCK_KEY: KeyId = (69, True)                # Num Lock - arms/disarms the board

DEFAULT_PANIC_KEY: KeyId = (83, False)  # dedicated Delete key (not the numpad one)
DEFAULT_PANIC_LABEL = "Delete"

_RESERVED_KEYS: Set[KeyId] = (
    set(SLOT_KEYMAP) | VOLUME_UP_KEYS | VOLUME_DOWN_KEYS | STOP_LAST_KEYS
    | NEXT_PLAYLIST_KEYS | PREV_PLAYLIST_KEYS | {NUM_LOCK_KEY}
)


def _query_num_lock_state() -> Optional[bool]:
    """
    Best-effort, one-shot read of the real OS-level Num Lock toggle (the
    keyboard's own LED state) via user32's GetKeyState. Used only to seed
    HotkeyManager.enabled when the hook (re)starts - see the "NUM LOCK AS
    THE MASTER ARM/DISARM SWITCH" note in this module's docstring for why
    it's not re-queried on every keypress. Returns None on any platform
    or environment where this isn't available; callers treat that as
    "assume ON", matching today's default-enabled behaviour.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        VK_NUMLOCK = 0x90
        return bool(ctypes.windll.user32.GetKeyState(VK_NUMLOCK) & 1)
    except Exception:
        logger.debug("Could not query Num Lock state", exc_info=True)
        return None


class HotkeyManager:
    """
    Owns exactly one global low-level keyboard hook (via the `keyboard`
    package) and dispatches recognised numpad events to the callbacks
    supplied at construction. Anything not in this app's key set always
    passes through untouched, regardless of the suppress setting.

    Threading: callbacks fire on a `keyboard`-managed background thread
    (see the README's architecture section for exactly which one, and
    why it's safe). They must stay fast and must never touch GUI widgets
    directly.
    """

    def __init__(
        self,
        on_slot: Callable[[str], None],
        on_volume_up: Callable[[], None],
        on_volume_down: Callable[[], None],
        on_stop_last: Callable[[], None],
        on_panic: Callable[[], None],
        on_next_playlist: Callable[[], None],
        on_prev_playlist: Callable[[], None],
        on_numlock_toggle: Callable[[bool], None],
        panic_key: KeyId = DEFAULT_PANIC_KEY,
        suppress: bool = False,
    ):
        self._on_slot = on_slot
        self._on_volume_up = on_volume_up
        self._on_volume_down = on_volume_down
        self._on_stop_last = on_stop_last
        self._on_panic = on_panic
        self._on_next_playlist = on_next_playlist
        self._on_prev_playlist = on_prev_playlist
        self._on_numlock_toggle = on_numlock_toggle
        self.panic_key: KeyId = panic_key
        self.suppress = suppress

        self._held: Set[KeyId] = set()
        self._held_lock = threading.Lock()
        self._remove_hook: Optional[Callable[[], None]] = None
        self._capture_callback: Optional[Callable[[KeyId, str], None]] = None
        self.active = False  # is the OS-level hook registered at all?
        self.enabled = True  # is the board currently armed? (Num Lock / GUI toggle)

    # ---- lifecycle ----

    def start(self) -> Tuple[bool, Optional[str]]:
        """Registers the global hook. Returns (success, error_message)."""
        if self.active:
            return True, None
        try:
            self._remove_hook = keyboard.hook(self._handle_event, suppress=self.suppress)
            self.active = True
            # Sync "armed or not" to whatever Num Lock is actually doing
            # right now, rather than remembering our own past value - see
            # the module docstring's Num Lock section for why.
            state = _query_num_lock_state()
            # self.enabled = True if state is None else state
            self.enabled = True if state is None else (not state)
            return True, None
        except Exception as e:
            logger.error("Failed to register global keyboard hook: %s", e)
            self.active = False
            return False, str(e)

    def stop(self) -> None:
        if self._remove_hook is not None:
            try:
                self._remove_hook()
            except Exception as e:
                logger.warning("Error while unhooking keyboard: %s", e)
            self._remove_hook = None
        self.active = False
        with self._held_lock:
            self._held.clear()

    def set_suppress(self, suppress: bool) -> Tuple[bool, Optional[str]]:
        """Re-registers the hook with a new suppress setting."""
        was_active = self.active
        self.stop()
        self.suppress = suppress
        return self.start() if was_active else (True, None)

    # ---- rebinding ----

    def capture_next_key(self, callback: Callable[[KeyId, str], None]) -> None:
        """
        The next physical key pressed anywhere is reported to
        `callback(key_id, display_name)` instead of being dispatched
        normally; capture mode then automatically switches off.
        """
        self._capture_callback = callback

    def cancel_capture(self) -> None:
        self._capture_callback = None

    def set_panic_key(self, key_id: KeyId) -> None:
        self.panic_key = key_id

    def set_enabled(self, enabled: bool) -> None:
        """Arm/disarm the board without touching the OS-level hook
        registration - used by the GUI's manual toggle button and the
        tray menu, so they and Num Lock all converge on one flag."""
        self.enabled = bool(enabled)

    # ---- event handling ----

    def _handle_event(self, event) -> bool:
        if event.scan_code is None:
            return True  # can't identify it - never touch it

        key_id: KeyId = (event.scan_code, bool(event.is_keypad))
        is_down = event.event_type == keyboard.KEY_DOWN

        if self._capture_callback is not None:
            if is_down:
                cb, self._capture_callback = self._capture_callback, None
                try:
                    cb(key_id, event.name or "unknown key")
                except Exception:
                    logger.exception("Error in key-capture callback")
            return True  # never suppress while capturing

        if key_id == NUM_LOCK_KEY:
            # Debounce the same way every other key here does, but never
            # suppress - Num Lock must keep toggling its own OS state (and
            # LED) normally regardless of anything else. Always processed,
            # even while disarmed, since this is the only way to re-arm.
            with self._held_lock:
                already_held = key_id in self._held
                if is_down:
                    self._held.add(key_id)
                else:
                    self._held.discard(key_id)
            if is_down and not already_held:
                self.enabled = not self.enabled
                try:
                    self._on_numlock_toggle(self.enabled)
                except Exception:
                    logger.exception("Error in numlock-toggle callback")
            return True

        action = self._resolve_action(key_id)
        if action is None:
            return True  # not one of ours

        # Debounce OS auto-repeat: fire only on the up -> down transition,
        # so holding a key down can't flood unbounded playback instances.
        with self._held_lock:
            already_held = key_id in self._held
            if is_down:
                self._held.add(key_id)
            else:
                self._held.discard(key_id)

        if not self.enabled:
            # Disarmed (Num Lock off): hands off entirely, regardless of
            # the suppress setting - the numpad falls through untouched.
            return True

        if is_down and not already_held:
            try:
                self._dispatch(action)
            except Exception:
                logger.exception("Error dispatching hotkey action %s", action)

        return not self.suppress

    def _resolve_action(self, key_id: KeyId) -> Optional[str]:
        if key_id in SLOT_KEYMAP:
            return "slot:" + SLOT_KEYMAP[key_id]
        if key_id in VOLUME_UP_KEYS:
            return "volume_up"
        if key_id in VOLUME_DOWN_KEYS:
            return "volume_down"
        if key_id in STOP_LAST_KEYS:
            return "stop_last"
        if key_id in NEXT_PLAYLIST_KEYS:
            return "next_playlist"
        if key_id in PREV_PLAYLIST_KEYS:
            return "prev_playlist"
        if key_id == self.panic_key:
            return "panic"
        return None

    def _dispatch(self, action: str) -> None:
        if action.startswith("slot:"):
            self._on_slot(action.split(":", 1)[1])
        elif action == "volume_up":
            self._on_volume_up()
        elif action == "volume_down":
            self._on_volume_down()
        elif action == "stop_last":
            self._on_stop_last()
        elif action == "next_playlist":
            self._on_next_playlist()
        elif action == "prev_playlist":
            self._on_prev_playlist()
        elif action == "panic":
            self._on_panic()


def is_reserved(key_id: KeyId) -> bool:
    """True if key_id is permanently bound to a slot/volume/stop-last/
    playlist-cycling key (used by the GUI's panic-key rebind conflict check)."""
    return key_id in _RESERVED_KEYS