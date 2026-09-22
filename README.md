# Numpad Soundboard

A Windows desktop soundboard that plays sounds instantly from the numeric
keypad - globally, even while a game or another app has focus. Ten
assignable slots (Numpad 0–9), instant volume control, a panic/stop-all
key, and playlists for switching your whole sound set between games or
voice channels in one click.

- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [Special keys](#special-keys)
- [How it works](#how-it-works)
- [Where your data lives](#where-your-data-lives)
- [Configuration (advanced)](#configuration-advanced)
- [Troubleshooting](#troubleshooting)
- [Scope decisions & limitations](#scope-decisions--limitations)
- [How this was verified](#how-this-was-verified)

## Quick start

Requires **Windows 10/11** and **Python 3.9+** ([python.org](https://www.python.org/downloads/) - tick "Add python.exe to PATH" during install).

```bat
cd numpad-soundboard
pip install -r requirements.txt
python main.py
```

That's it - the window opens, a tray icon appears, and the numpad is live.
Click any slot's card to get started.

## Using the app

**Adding/changing a sound:** click anywhere on a slot's card (its name
text works too) and pick an `.mp3`, `.wav`, or `.ogg` file. It's copied
into the app's own sounds folder (see
[Where your data lives](#where-your-data-lives)) and decoded immediately,
so the very next key press is instant - nothing is decoded on the fly
when a hotkey fires.

**Testing / removing:** the circular **▶** button on each card plays it
right from the GUI, no keyboard needed (it's disabled until a sound is
assigned). **Right-click** a card to clear it - the file itself stays in
your sounds pool in case another slot or playlist still uses it. A card
stays the same size whether it's empty, filled, or showing a missing-file
warning.

**Per-slot and master volume:** every card has its own volume slider,
always visible; the final loudness is that slider × the master volume
card at the bottom. Numpad `+`/`-` nudge master volume by 5% at a time,
live, from anywhere.

**Playlists:** the bar at the top switches, creates, duplicates, renames,
and deletes playlists, plus `<`/`>` buttons next to the dropdown for
cycling one at a time (same thing Numpad `*`/`/` do). Each playlist is
its own independent set of 9 slot assignments (Numpad 1–9) - think
"Valorant," "Discord," "Just Chatting." **The numpad keys themselves
never change** (Numpad 5 is always "slot 5"); only *which sound* Numpad 5
plays changes when you switch playlists. Switching never stops whatever's
currently playing - it only changes what *future* key presses do.
Playlist names are kept unique automatically so the picker is never
ambiguous.

**Numpad 0 is common to every playlist.** Unlike 1–9, its card sits
below the 3×3 grid and holds a single sound that's the same no matter
which playlist is active - for something you want available everywhere
(an air horn, a "brb" clip) without assigning it in every playlist
separately.

**Panic key:** by default this is the dedicated **Delete** key (see
[why](#the-ce-key-problem) below) - instantly stops every sound, no
matter which playlist it came from. Click **Rebind** next to it in the
footer and press any key to use that instead; the app refuses to bind a
key that's already doing something else and tells you so.

## Special keys

| Key(s) | Action |
|---|---|
| Numpad 0 | Play the common sound (same in every playlist) |
| Numpad 1–9 | Play that slot's sound from the active playlist (new, independent instance - presses overlap freely) |
| Numpad `+` | Master volume **+5%** |
| Numpad `-` | Master volume **−5%** |
| Numpad `*` | **Next playlist** |
| Numpad `/` | **Previous playlist** |
| Numpad `.` | Stop the most recently triggered sound |
| Delete *(dedicated key, default, rebindable)* | **Panic - stop everything, instantly** |
| Numpad Enter | Intentionally does nothing |

Every key works **regardless of whether Num Lock is on or off** - see
below for why that's a deliberate design choice, not an accident.

## How it works

### The hotkey problem, and why it's harder than it looks

A naive implementation would listen for "the numpad 5 key" by name or by
virtual key code. That breaks in two ways on Windows:

1. **Num Lock changes what a numpad key *reports itself as*.** With Num
   Lock on, Numpad 5 sends a "5" key code. With it off, that exact same
   physical key sends `VK_CLEAR` (no navigation meaning) - Numpad 2 sends
   "Down arrow," Numpad 8 sends "Up arrow," and so on. Code that matches
   on "the 5 key" or "the Down key" will silently stop working the moment
   Num Lock is toggled, or will fire from the wrong key entirely.
2. **Those Num-Lock-off codes collide with the separate, dedicated
   Home/End/arrow-key cluster.** Numpad 2 (Num Lock off) and the actual
   Down arrow key both claim to be "Down" - matching by virtual key alone
   can't tell them apart.

What *doesn't* change is the keyboard's raw hardware **scan code**, plus
one **extended-key flag** - together they identify a specific physical
key, permanently, independent of Num Lock. This app hooks at exactly
that level (`core/hotkeys.py`) instead of matching key names, which is
why it keeps working correctly no matter what state Num Lock is in.

The scan codes used aren't guessed - they were cross-checked directly
against the installed `keyboard` package's own Windows backend
(`keyboard/_winkeyboard.py`, its `keypad_keys` table), which independently
confirms the exact same (scan code, extended-flag) pairing for every
numpad key. That table is reproduced with citations in
`core/hotkeys.py`'s module docstring.

### The "CE" key problem

The build spec called for a dedicated "CE" (Clear Entry) panic key, as
seen on some calculator-style keypads. There's no such thing on a
standard Windows 104/105-key scan code table - it doesn't exist as a
universal key, so hard-coding a guess risked silently binding the wrong
physical key on hardware that doesn't have one. Instead:

- Panic defaults to the dedicated **Delete** key - the one in the
  Insert/Home/PgUp/Delete/End/PgDn cluster, deliberately *not* the
  numpad's own `.`/Delete key, since that's already Stop Last.
- The **Rebind** button in the footer captures the *next physical key you
  press*, using that same scan-code mechanism, so if your keypad really
  does have a dedicated CE key, you can bind it directly with one click.
  No code changes needed.

### Audio engine

Sounds are decoded once - when you add them, or when a playlist loads -
into an in-memory `pygame.mixer.Sound`, so **a hotkey press never touches
the filesystem or a codec.** Playback uses a pool of `pygame.mixer`
channels (32 by default): every trigger claims its own channel, so
presses overlap freely rather than cutting each other off. If you spam a
key harder than the pool size, the oldest-claimed channel is reclaimed
automatically - never blocks, never crashes, never grows unbounded.

Each channel claim is stamped with a unique, incrementing token. "Stop
last" and cleanup both check that token before touching a channel, which
is what makes stopping the *right* instance reliable even when the same
sound has been triggered dozens of times in a row and channels are being
recycled (an early version of this used channel/sound *identity* instead
of tokens, which looks reasonable but breaks specifically under repeated
same-sound spam - worth knowing if you extend this code).

### Threading

The keyboard hook runs on its own background thread(s) inside the
`keyboard` package; Tkinter/CustomTkinter widgets can only safely be
touched from the main thread. Hotkey callbacks either call straight into
the (thread-safe) audio engine, or post a message onto a `queue.Queue`
that the GUI drains on a `self.after(...)` loop. Nothing from a
background thread ever calls a widget method directly. See the docstring
at the top of `gui/app.py` for the full rundown.

### Project layout

```
main.py                    entry point - wires everything together
core/
  paths.py                 %APPDATA% resolution
  models.py                data classes + JSON (de)serialization
  config_manager.py        config.json (volume, panic key, etc.)
  sound_library.py         shared, deduplicated sound-file pool
  playlist_manager.py      playlist CRUD, slot assignments
  audio_engine.py          pygame.mixer wrapper (see above)
  hotkeys.py                scan-code hook + numpad key table (see above)
gui/
  app.py                   main window, wiring, threading bridge
  slot_card.py               one slot's card (click body = change, right-click = remove, always-visible slider)
  rebind_dialog.py          "press a key" capture dialog
  tray.py                   optional system tray icon
```

## Where your data lives

Nothing is stored next to the script - the app never assumes its own
folder is writable (that'd break under Program Files, or once packaged
as an .exe). Everything lives under your Windows user profile:

```
%APPDATA%\NumpadSoundboard\
  config\
    config.json           master volume, panic key, the common Numpad 0 sound, hotkey/tray settings
    playlists.json         every playlist and its Numpad 1-9 slot assignments
    sound_library.json     metadata for every imported sound file
  sounds\
    <your imported audio files>
```

**Sounds are stored once, referenced by every playlist that uses them.**
Importing the same file twice (even under a different name) is detected
by content hash and reuses the existing copy rather than duplicating it.
Right-clicking a card clears that one assignment only - the file stays in
the pool in case another slot or playlist references it.

If a sound's underlying file goes missing or won't decode, its card shows
**[MISSING]** - click it to replace the file, same as assigning a new one.

## Configuration (advanced)

Two options exist in `config.json` but aren't exposed as GUI controls,
by design - they're advanced/rare enough that a GUI toggle would just be
clutter for the 95% of people who'll never touch them:

- **`max_simultaneous_sounds`** (default `32`) - the channel pool size.
  32 comfortably covers even aggressive spam across all 10 keys; raise it
  if you genuinely need more overlap headroom.
- **`suppress_passthrough`** (default `false`) - if `true`, numpad
  presses handled by this app are *also* blocked from reaching whatever
  app has focus. Off by default so the soundboard only ever *observes*
  input, never intercepts it, matching the "don't inject or interfere
  with other applications" requirement it was built to. The underlying
  hook (`core/hotkeys.py`) already supports per-key selective suppression
  correctly if you do turn this on - only the numpad keys this app
  recognizes are ever affected, nothing else on the keyboard.

Edit `config.json` directly (with the app closed) to change either.

## Troubleshooting

**`pip install -r requirements.txt` fails while building pygame, mentioning
`distutils.msvccompiler` or "Failed to build 'pygame'".** This means pip
couldn't find a prebuilt Windows wheel for your Python version and tried
(and failed) to compile from source - most common on very new Python
versions (3.13+) that upstream `pygame` hasn't published wheels for yet.
This project already pins `pygame-ce` for exactly this reason; if you're
seeing this, either your `requirements.txt` still says `pygame` instead of
`pygame-ce`, or pip has a stale/cached resolution - run
`pip uninstall pygame -y` then `pip install -r requirements.txt` again.

**Hotkeys don't register at all / a "Global hotkeys unavailable" dialog
appears on launch.** The app still runs - the GUI and each card's ▶
button work - but the global hook itself failed. Most often: security
software blocking low-level keyboard hooks. Try running as Administrator.

**Hotkeys work, but not while a specific game has focus.** Some games run
elevated (as Administrator) or use exclusive input capture. Windows'
UIPI can prevent a non-elevated process from hooking into an elevated
one - run the soundboard as Administrator too and it should start
working for that game.

**A specific key isn't triggering the slot you expect.** Open the
**Rebind** dialog (it captures any key press) to confirm what scan code
your hardware is actually sending - some non-standard or third-party
numpads report keys differently than a stock keyboard.

**A sound won't play / MP3 seems silent.** Try re-exporting it as a
standard 44.1kHz/16-bit WAV; a small number of unusual MP3 encodings can
trip up the bundled decoder. The slot will show **[MISSING]** rather than
fail silently if this happens.

**Nothing plays and no error appears.** Check the master volume isn't at
0%, and that the slot isn't showing **[MISSING]**.

## Scope decisions & limitations

Being upfront about a few things that were deliberately left out or
simplified, rather than silently dropped:

- **No drag-and-drop file import.** The spec listed this as "ideally, if
  practical." Real OS-level drag-and-drop in Tkinter needs an extra
  native-extension dependency (`tkinterdnd2`) with its own installation
  quirks, for a feature the file-picker button already fully covers.
  Deferred rather than added at that cost - the picker is one click.
- **No suppress-passthrough toggle in the GUI** (see
  [Configuration](#configuration-advanced) above) - implemented and
  correct, just not surfaced as a control since it's a rare/advanced need.
- **System tray requires `pystray` + Pillow to succeed on your machine.**
  If either can't initialize, the app logs a warning and keeps running
  normally without a tray icon rather than failing to start.
- **Very long filenames** are truncated to keep well under Windows path
  limits when copied into the sounds folder; the original name is still
  preserved as the *display* name in the UI.
- **Removing a sound is right-click, not a button.** The layout has no
  room for a fourth control without breaking the fixed card size or the
  clean look - right-click was the closest thing to "no visible button"
  that still exposes the action somewhere.
- **No small per-card key label once a sound is assigned.** The
  filename fully replaces "NUM 1" as asked; the grid position is what
  tells slots apart after that. Worth revisiting if that gets confusing
  once several cards have similarly long names.

## How this was verified

This was built and tested inside a Linux sandbox, which can't register a
real Windows low-level keyboard hook or open a real audio device - so
verification leaned on three things instead of guesswork:

1. **Reading the actual `keyboard` package source** installed via pip
   (not relying on memory) to confirm every numpad scan code and the
   extended-flag/`is_keypad` behavior described above, including catching
   that Num Lock itself is an *extended* scan code - a detail easy to get
   wrong from recollection alone.
2. **A real, running audio engine** - `pygame.mixer` initialized against
   SDL's dummy audio driver, which exercises the actual channel/volume/
   decode code paths against real generated WAV/MP3/OGG files (via
   `ffmpeg`), just without real speaker output. This is how the
   channel-reclaim bug described in `audio_engine.py`'s docstring was
   actually caught: an early version used channel/sound *identity* to
   detect stale playback instances, which passed lighter tests but broke
   under 200 rapid presses of the *same* sound against a 32-channel pool
   (the exact spam scenario the spec calls out) - fixed with the
   per-channel token scheme described above, then re-verified against
   the same stress test.
3. **A full headless GUI run** (Xvfb + the real CustomTkinter window),
   re-run after every round of changes, driving real widget construction,
   slot assignment, hotkey dispatch, playlist switching, and the
   rebind-with-conflict flow end-to-end - plus actual screenshots (via
   `import`/ImageMagick against the Xvfb display) to visually sanity-check
   layout changes rather than just trusting that the code "should" render
   correctly.

The redesign to a card-based layout with a shared Numpad-0 slot and
playlist-cycling hotkeys (see the rest of this README) went through the
same process and caught three more real bugs before Akito ever saw them:
a card's fixed height only *looked* correct when tested against siblings
in the same grid row (grid auto-sizes a row to its tallest member) and
actually broke across different rows until pinned with
`grid_propagate(False)`; an empty slot's volume slider sat at whatever
arbitrary position `CTkSlider` defaults to instead of a meaningful one,
caught by actually looking at a rendered screenshot rather than just
checking that the code ran without error; and an early version of the
new playlist-cycling code applied the same debounced-save path to the
dropdown selector as the `*`/`/` hotkeys, which turned out to be
unnecessary for the dropdown specifically - a single deliberate click on
the GUI thread has no thread-safety or spam-related reason to defer its
save, so that path was reverted to save immediately.

What could **not** be verified here, and is worth trying first on a real
Windows machine: the low-level hook actually intercepting keys while a
fullscreen game has focus, and real speaker output/timing feel. The
architecture is built specifically around Windows' documented hook and
scan-code behavior, but that's the one gap between "verified in sandbox"
and "verified on Windows."
