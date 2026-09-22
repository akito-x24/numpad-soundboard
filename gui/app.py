"""
Main application window: wires together config, the sound library,
playlists, the audio engine, and global hotkeys, and renders the GUI.

THREADING MODEL
----------------
customtkinter (like all Tkinter) is not thread-safe: widgets must only be
touched from the main/GUI thread. The global keyboard hook calls back on
its own background thread(s) (see core/hotkeys.py). To bridge this
safely, every hotkey-triggered callback here either:

  (a) only touches thread-safe objects - AudioEngine's public methods are
      safe to call from any thread, and simple attribute reads/writes on
      plain Python objects are safe enough under the GIL for the kind of
      infrequent, single-value updates used here, or

  (b) pushes a small message onto `self._queue` (a stdlib queue.Queue,
      which IS thread-safe), which `_poll_queue` - running on the GUI
      thread via `self.after(...)` - drains and applies to widgets.

Nothing from a background thread ever calls a CTk widget method, or
`self.after(...)`, directly.
"""
from __future__ import annotations

import logging
import queue
from tkinter import filedialog, messagebox
from typing import Dict, Optional

import customtkinter as ctk

from core.audio_engine import AudioEngine
from core.config_manager import ConfigManager
from core.hotkeys import DEFAULT_PANIC_LABEL, HotkeyManager, KeyId, is_reserved
from core.models import ALL_SLOT_KEYS, COMMON_SLOT_KEY, SLOT_KEYS, SlotAssignment
from core.playlist_manager import PlaylistManager
from core.sound_library import SoundLibrary

from .rebind_dialog import RebindDialog
from .slot_card import SlotCard

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SLOT_DISPLAY_LABELS = {str(i): f"NUM {i}" for i in range(10)}
AUTOSAVE_DEBOUNCE_MS = 1500


class SoundboardApp(ctk.CTk):
    def __init__(
        self,
        config_manager: ConfigManager,
        sound_library: SoundLibrary,
        playlist_manager: PlaylistManager,
        audio_engine: AudioEngine,
    ):
        super().__init__()

        self.config_manager = config_manager
        self.config = config_manager.config
        self.sound_library = sound_library
        self.playlist_manager = playlist_manager
        self.audio_engine = audio_engine

        self._queue: "queue.Queue" = queue.Queue()
        self._save_jobs: dict = {}
        self._rebind_dialog: Optional[RebindDialog] = None
        self._slot_cards: Dict[str, SlotCard] = {}
        self._playlist_ids_in_order = []
        self.tray = None

        self._reconcile_active_playlist()
        self._migrate_common_slot_if_needed()
        self._preload_active_playlist()
        self._preload_common_slot()

        self.title("Numpad Soundboard")
        self.geometry("760x820")
        self.minsize(640, 560)

        self._build_widgets()
        self._refresh_playlist_list()
        self._refresh_all_slots()
        self._sync_master_volume_display()

        self.hotkey_manager = HotkeyManager(
            on_slot=self._hk_on_slot,
            on_volume_up=self._hk_on_volume_up,
            on_volume_down=self._hk_on_volume_down,
            on_stop_last=self._hk_on_stop_last,
            on_panic=self._hk_on_panic,
            on_next_playlist=self._hk_on_next_playlist,
            on_prev_playlist=self._hk_on_prev_playlist,
            panic_key=(self.config.panic_key.scan_code, self.config.panic_key.is_keypad),
            suppress=self.config.suppress_passthrough,
        )
        self._start_hotkeys(initial=True)

        if self.config.tray_enabled:
            self._start_tray()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll_queue)

    # ------------------------------------------------------------------
    # Startup helpers
    # ------------------------------------------------------------------

    def _reconcile_active_playlist(self) -> None:
        playlists = self.playlist_manager.list_playlists()
        ids = {p.id for p in playlists}
        if self.config.active_playlist_id not in ids:
            self.config.active_playlist_id = playlists[0].id
            self.config_manager.save()

    def _preload_active_playlist(self) -> None:
        playlist = self.playlist_manager.get(self.config.active_playlist_id)
        if not playlist:
            return
        for slot in playlist.slots.values():
            if slot.sound_id:
                path = self.sound_library.resolve_path(slot.sound_id)
                if path and path.exists():
                    self.audio_engine.preload(slot.sound_id, path)

    def _preload_common_slot(self) -> None:
        sound_id = self.config.common_slot.sound_id
        if sound_id:
            path = self.sound_library.resolve_path(sound_id)
            if path and path.exists():
                self.audio_engine.preload(sound_id, path)

    def _migrate_common_slot_if_needed(self) -> None:
        if self.config.common_slot.sound_id:
            return
        for playlist in self.playlist_manager.list_playlists():
            legacy = playlist.slots.get(COMMON_SLOT_KEY)
            if legacy and legacy.sound_id:
                self.config.common_slot = SlotAssignment(sound_id=legacy.sound_id, volume=legacy.volume)
                self.config_manager.save()
                return

    # ------------------------------------------------------------------
    # Widget construction
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_playlist_bar()
        self._build_slot_list()
        self._build_footer()
        self._build_status_bar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="Numpad Soundboard", font=ctk.CTkFont(size=22, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        # Single button doubles as the status indicator (green/"Disable"
        # when hotkeys are live, red/"Enable" when they're not) rather than
        # a separate status readout next to it.
        self.toggle_hotkeys_btn = ctk.CTkButton(
            header, text="Disable", width=110, command=self._toggle_hotkeys,
            fg_color="#2E7D46", hover_color="#255E38",
        )
        self.toggle_hotkeys_btn.grid(row=0, column=1, sticky="e")

    def _build_playlist_bar(self) -> None:
        bar = ctk.CTkFrame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        bar.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(bar, text="Playlist", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=(14, 8), pady=12)

        ctk.CTkButton(bar, text="<", width=32, command=lambda: self._cycle_playlist(-1)).grid(
            row=0, column=1, padx=(0, 4), pady=12
        )

        self.playlist_combo = ctk.CTkComboBox(bar, values=[], command=self._on_playlist_selected)
        self.playlist_combo.grid(row=0, column=2, sticky="ew", pady=12)

        ctk.CTkButton(bar, text=">", width=32, command=lambda: self._cycle_playlist(+1)).grid(
            row=0, column=3, padx=(4, 10), pady=12
        )

        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.grid(row=0, column=4, padx=10, pady=8)
        ctk.CTkButton(btns, text="New", width=60, command=self._new_playlist).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="Duplicate", width=80, command=self._duplicate_playlist).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="Rename", width=68, command=self._rename_playlist).pack(side="left", padx=2)
        ctk.CTkButton(
            btns, text="Delete", width=64, fg_color="#8B2E2E", hover_color="#6E2424", command=self._delete_playlist
        ).pack(side="left", padx=2)

    def _make_slot_card(self, parent, slot_key: str, empty_label: str) -> SlotCard:
        card = SlotCard(
            parent,
            slot_key=slot_key,
            empty_label=empty_label,
            on_test=self._gui_test_slot,
            on_change=self._gui_change_slot,
            on_remove=self._gui_remove_slot,
            on_volume_change=self._gui_slot_volume_change,
        )
        self._slot_cards[slot_key] = card
        return card

    def _build_slot_list(self) -> None:
        self.slot_scroll = ctk.CTkScrollableFrame(self, label_text="")
        self.slot_scroll.grid(row=2, column=0, sticky="nsew", padx=16, pady=8)
        for col in range(3):
            self.slot_scroll.grid_columnconfigure(col, weight=1, uniform="slotcol")

        # Numpad 1-9 as a 3x3 grid.
        for i, key in enumerate(SLOT_KEYS):
            row, col = divmod(i, 3)
            card = self._make_slot_card(self.slot_scroll, key, SLOT_DISPLAY_LABELS[key])
            card.grid(row=row, column=col, padx=20, pady=20, sticky="nsew")

        # Bottom row: the common Numpad 0 slot (left) + master volume
        # (spans the rest) - Numpad 0 is intentionally NOT part of the 3x3
        # playlist grid above, since it's the same across every playlist.
        bottom = ctk.CTkFrame(self.slot_scroll, fg_color="transparent")
        bottom.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(20, 0))
        bottom.grid_columnconfigure(0, weight=1, uniform="slotcol")
        bottom.grid_columnconfigure(1, weight=2)

        common_card = self._make_slot_card(bottom, COMMON_SLOT_KEY, "NUM 0 (common)")
        common_card.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        volume_card = ctk.CTkFrame(bottom, corner_radius=10)
        volume_card.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        volume_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(volume_card, text="Master Volume", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=14, pady=(14, 4), sticky="w"
        )
        self.master_slider = ctk.CTkSlider(
            volume_card, from_=0, to=100, number_of_steps=100, command=self._on_master_slider_move
        )
        self.master_slider.grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")
        self.master_pct_label = ctk.CTkLabel(volume_card, text="75%")
        self.master_pct_label.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=8)
        footer.grid_columnconfigure(0, weight=1)

        legend = (
            "(.) = STOP LAST   \u2022    (+) OR (-) = VOLUME UP/DOWN   \u2022   "
            "(*) OR (/) = NEXT/PREV PLAYLIST   \u2022   RIGHT CLICK ON CARD TO REMOVE THE SOUND"
        )
        ctk.CTkLabel(footer, text=legend, text_color=("gray35", "gray70")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 2)
        )

        panic_row = ctk.CTkFrame(footer, fg_color="transparent")
        panic_row.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        ctk.CTkLabel(panic_row, text="Panic key (stop all):").pack(side="left")
        self.panic_key_label = ctk.CTkLabel(
            panic_row, text=self.config.panic_key.label, font=ctk.CTkFont(weight="bold")
        )
        self.panic_key_label.pack(side="left", padx=(6, 12))
        ctk.CTkButton(panic_row, text="Rebind", width=70, command=self._open_rebind_dialog).pack(side="left")

    def _build_status_bar(self) -> None:
        self.status_label = ctk.CTkLabel(self, text="Ready.", text_color=("gray45", "gray60"), anchor="w")
        self.status_label.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 10))

    # ------------------------------------------------------------------
    # Cross-thread messaging
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _post(self, kind: str, *payload) -> None:
        self._queue.put((kind, payload))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._handle_message(kind, payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _handle_message(self, kind: str, payload: tuple) -> None:
        if kind == "master_volume":
            (percent,) = payload
            self.master_slider.set(percent)
            self.master_pct_label.configure(text=f"{percent}%")
            self._schedule_save("config")
        elif kind == "status":
            (text,) = payload
            self._set_status(text)
        elif kind == "show_window":
            self.deiconify()
            self.lift()
            self.focus_force()
        elif kind == "tray_enable":
            if not self.hotkey_manager.active:
                self._start_hotkeys()
        elif kind == "tray_disable":
            self._disable_hotkeys()
        elif kind == "tray_exit":
            self._on_close()
        elif kind == "rebind_captured":
            key_id, label = payload
            self._apply_rebind_capture(key_id, label)
        elif kind == "playlist_switched":
            (new_id,) = payload
            self._refresh_playlist_list()
            self._refresh_all_slots()
            self._schedule_save("config")
            pl = self.playlist_manager.get(new_id)
            if pl:
                self._set_status(f"Switched to playlist '{pl.name}'.")

    # ------------------------------------------------------------------
    # Hotkey callbacks - these run on a background thread (see module
    # docstring). Keep them fast; never touch widgets directly here.
    # ------------------------------------------------------------------

    def _resolve_assignment(self, slot_key: str) -> Optional[SlotAssignment]:
        """Numpad 0 reads from the shared common_slot; 1-9 read from
        whichever playlist is currently active. Safe from any thread -
        only reads plain config/playlist state, no widget access."""
        if slot_key == COMMON_SLOT_KEY:
            return self.config.common_slot
        playlist = self.playlist_manager.get(self.config.active_playlist_id)
        return playlist.slots.get(slot_key) if playlist else None

    def _hk_on_slot(self, slot_key: str) -> None:
        assignment = self._resolve_assignment(slot_key)
        if not assignment or not assignment.sound_id:
            return
        self.audio_engine.trigger(slot_key, assignment.sound_id, assignment.volume)

    def _hk_on_volume_up(self) -> None:
        self._adjust_master_volume(+5)

    def _hk_on_volume_down(self) -> None:
        self._adjust_master_volume(-5)

    def _adjust_master_volume(self, delta: int) -> None:
        current = self.audio_engine.get_master_volume_percent()
        new_percent = self.audio_engine.set_master_volume_percent(current + delta)
        self.config.master_volume = new_percent
        self._post("master_volume", new_percent)

    def _hk_on_stop_last(self) -> None:
        self.audio_engine.stop_last()

    def _hk_on_panic(self) -> None:
        self.audio_engine.stop_all()
        self._post("status", "PANIC - all audio stopped.")

    def _hk_on_next_playlist(self) -> None:
        self._cycle_playlist(+1)

    def _hk_on_prev_playlist(self) -> None:
        self._cycle_playlist(-1)

    def _cycle_playlist(self, direction: int) -> None:
        """Handler for the </> buttons AND the */÷ hotkeys - both can
        plausibly fire several times in quick succession (skipping
        through playlists), so this path debounces its save and defers
        its GUI refresh through a queue message, via _switch_active_playlist.
        Contrast with _on_playlist_selected below, which is a one-off
        selection with no reason to delay anything."""
        playlists = self.playlist_manager.list_playlists()
        if len(playlists) <= 1:
            return
        ids = [p.id for p in playlists]
        try:
            idx = ids.index(self.config.active_playlist_id)
        except ValueError:
            idx = 0
        new_id = ids[(idx + direction) % len(ids)]
        self._switch_active_playlist(new_id)

    def _switch_active_playlist(self, new_id: str) -> None:
        if new_id == self.config.active_playlist_id:
            return
        self.config.active_playlist_id = new_id
        # Deliberately NOT stopping currently playing sounds - switching
        # only changes what future key presses do.
        self._preload_active_playlist()
        self._post("playlist_switched", new_id)

    # ------------------------------------------------------------------
    # GUI-initiated slot actions (already on the main thread)
    # ------------------------------------------------------------------

    def _active_playlist(self):
        return self.playlist_manager.get(self.config.active_playlist_id)

    def _gui_test_slot(self, slot_key: str) -> None:
        assignment = self._resolve_assignment(slot_key)
        if assignment and assignment.sound_id:
            self.audio_engine.trigger(slot_key, assignment.sound_id, assignment.volume)

    def _gui_change_slot(self, slot_key: str) -> None:
        filetypes = [("Audio files", "*.mp3 *.wav *.ogg"), ("All files", "*.*")]
        path = filedialog.askopenfilename(title="Choose a sound", filetypes=filetypes)
        if not path:
            return
        try:
            entry = self.sound_library.import_sound(path)
        except (FileNotFoundError, ValueError, OSError) as e:
            messagebox.showerror("Could not add sound", str(e))
            return

        if not self.audio_engine.preload(entry.id, self.sound_library.resolve_path(entry.id)):
            messagebox.showerror(
                "Could not load sound",
                f"'{entry.display_name}' was copied into the sounds folder, but could not be "
                "decoded. It may be corrupted or in an unsupported format.",
            )

        if slot_key == COMMON_SLOT_KEY:
            self.config.common_slot.sound_id = entry.id
            self.config_manager.save()
        else:
            playlist = self._active_playlist()
            if not playlist:
                return
            self.playlist_manager.assign_sound(playlist.id, slot_key, entry.id)
        self._refresh_slot(slot_key)
        self._set_status(f"Assigned '{entry.display_name}' to NUM {slot_key}.")

    def _gui_remove_slot(self, slot_key: str) -> None:
        if slot_key == COMMON_SLOT_KEY:
            self.config.common_slot.sound_id = None
            self.config_manager.save()
        else:
            playlist = self._active_playlist()
            if not playlist:
                return
            self.playlist_manager.assign_sound(playlist.id, slot_key, None)
        self._refresh_slot(slot_key)
        self._set_status(f"Cleared NUM {slot_key}.")

    def _gui_slot_volume_change(self, slot_key: str, value: int) -> None:
        if slot_key == COMMON_SLOT_KEY:
            self.config.common_slot.volume = max(0, min(100, int(value)))
            self._schedule_save("config")
        else:
            playlist = self._active_playlist()
            if not playlist:
                return
            self.playlist_manager.set_slot_volume(playlist.id, slot_key, value)
            self._schedule_save("playlists")

    # ------------------------------------------------------------------
    # Slot rendering
    # ------------------------------------------------------------------

    def _refresh_all_slots(self) -> None:
        for key in ALL_SLOT_KEYS:
            self._refresh_slot(key)

    def _refresh_slot(self, slot_key: str) -> None:
        card = self._slot_cards[slot_key]
        assignment = self._resolve_assignment(slot_key)
        if not assignment or not assignment.sound_id:
            card.set_empty()
            return

        entry = self.sound_library.sounds.get(assignment.sound_id)
        display_name = entry.display_name if entry else "Unknown sound"
        path = self.sound_library.resolve_path(assignment.sound_id)
        if not path or not path.exists():
            card.set_missing(display_name, assignment.volume)
            return
        if not self.audio_engine.is_cached(assignment.sound_id):
            if not self.audio_engine.preload(assignment.sound_id, path):
                card.set_missing(f"{display_name} (corrupted)", assignment.volume)
                return
        card.set_assigned(display_name, assignment.volume)

    # ------------------------------------------------------------------
    # Master volume (GUI-driven path; hotkey-driven path is above)
    # ------------------------------------------------------------------

    def _sync_master_volume_display(self) -> None:
        percent = self.audio_engine.set_master_volume_percent(self.config.master_volume)
        self.master_slider.set(percent)
        self.master_pct_label.configure(text=f"{percent}%")

    def _on_master_slider_move(self, value) -> None:
        percent = int(round(value))
        self.audio_engine.set_master_volume_percent(percent)
        self.config.master_volume = percent
        self.master_pct_label.configure(text=f"{percent}%")
        self._schedule_save("config")

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def _refresh_playlist_list(self) -> None:
        playlists = self.playlist_manager.list_playlists()
        self._playlist_ids_in_order = [p.id for p in playlists]
        self.playlist_combo.configure(values=[p.name for p in playlists])
        active = self._active_playlist()
        if active:
            self.playlist_combo.set(active.name)

    def _on_playlist_selected(self, name: str) -> None:
        names = [p.name for p in self.playlist_manager.list_playlists()]
        if name not in names:
            return
        new_id = self._playlist_ids_in_order[names.index(name)]
        if new_id == self.config.active_playlist_id:
            return
        self.config.active_playlist_id = new_id
        self.config_manager.save()
        self._preload_active_playlist()
        self._refresh_all_slots()
        self._set_status(f"Switched to playlist '{name}'.")

    def _new_playlist(self) -> None:
        name = ctk.CTkInputDialog(text="New playlist name:", title="New Playlist").get_input()
        if not name:
            return
        pl = self.playlist_manager.create_playlist(name.strip())
        self.config.active_playlist_id = pl.id
        self.config_manager.save()
        self._refresh_playlist_list()
        self._refresh_all_slots()
        self._set_status(f"Created playlist '{pl.name}'.")

    def _duplicate_playlist(self) -> None:
        playlist = self._active_playlist()
        if not playlist:
            return
        name = ctk.CTkInputDialog(text="Name for the duplicate:", title="Duplicate Playlist").get_input()
        if not name:
            return
        pl = self.playlist_manager.duplicate_playlist(playlist.id, name.strip())
        self.config.active_playlist_id = pl.id
        self.config_manager.save()
        self._refresh_playlist_list()
        self._preload_active_playlist()
        self._refresh_all_slots()
        self._set_status(f"Duplicated as '{pl.name}'.")

    def _rename_playlist(self) -> None:
        playlist = self._active_playlist()
        if not playlist:
            return
        name = ctk.CTkInputDialog(text="New name:", title="Rename Playlist").get_input()
        if not name:
            return
        self.playlist_manager.rename_playlist(playlist.id, name.strip())
        self._refresh_playlist_list()
        self._set_status("Playlist renamed.")

    def _delete_playlist(self) -> None:
        playlist = self._active_playlist()
        if not playlist:
            return
        if len(self.playlist_manager.playlists) <= 1:
            messagebox.showinfo("Cannot delete", "You need at least one playlist.")
            return
        if not messagebox.askyesno("Delete playlist", f"Delete '{playlist.name}'? This cannot be undone."):
            return
        self.playlist_manager.delete_playlist(playlist.id)
        self.config.active_playlist_id = self.playlist_manager.list_playlists()[0].id
        self.config_manager.save()
        self._refresh_playlist_list()
        self._preload_active_playlist()
        self._refresh_all_slots()
        self._set_status("Playlist deleted.")

    # ------------------------------------------------------------------
    # Hotkey enable/disable + status
    # ------------------------------------------------------------------

    def _start_hotkeys(self, initial: bool = False) -> None:
        success, error = self.hotkey_manager.start()
        self.config.hotkeys_enabled = success
        if not success:
            messagebox.showerror(
                "Global hotkeys unavailable",
                "Could not register the global keyboard hook:\n\n"
                f"{error}\n\n"
                "The soundboard will keep running and the Test buttons will still work, "
                "but Numpad hotkeys won't trigger sounds until this is resolved. Try "
                "running as Administrator, or see Troubleshooting in the README.",
            )
        self._apply_hotkey_status(success)
        if not initial:
            self.config_manager.save()

    def _disable_hotkeys(self) -> None:
        if self.hotkey_manager.active:
            self.hotkey_manager.stop()
            self.config.hotkeys_enabled = False
            self._apply_hotkey_status(False)
            self.config_manager.save()
            self._set_status("Hotkeys disabled.")

    def _apply_hotkey_status(self, active: bool) -> None:
        if active:
            self.toggle_hotkeys_btn.configure(text="Disable", fg_color="#2E7D46", hover_color="#255E38")
        else:
            self.toggle_hotkeys_btn.configure(text="Enable", fg_color="#8B2E2E", hover_color="#6E2424")

    def _toggle_hotkeys(self) -> None:
        if self.hotkey_manager.active:
            self._disable_hotkeys()
        else:
            self._start_hotkeys()
            if self.hotkey_manager.active:
                self._set_status("Hotkeys enabled.")

    # ------------------------------------------------------------------
    # Panic key rebinding
    # ------------------------------------------------------------------

    def _open_rebind_dialog(self) -> None:
        if self._rebind_dialog is not None:
            return
        self._rebind_dialog = RebindDialog(
            self, current_label=self.config.panic_key.label, on_cancel=self._close_rebind_dialog
        )
        self._arm_capture()

    def _arm_capture(self) -> None:
        self.hotkey_manager.capture_next_key(lambda key_id, label: self._post("rebind_captured", key_id, label))

    def _close_rebind_dialog(self) -> None:
        self.hotkey_manager.cancel_capture()
        self._rebind_dialog = None

    def _apply_rebind_capture(self, key_id: KeyId, label: str) -> None:
        if is_reserved(key_id):
            if self._rebind_dialog is not None:
                self._rebind_dialog.show_conflict(
                    f"'{label}' is already used by the soundboard. Press a different key."
                )
                self._arm_capture()
            return

        scan_code, is_keypad = key_id
        self.config.panic_key.scan_code = scan_code
        self.config.panic_key.is_keypad = is_keypad
        self.config.panic_key.label = label.title()
        self.hotkey_manager.set_panic_key(key_id)
        self.panic_key_label.configure(text=self.config.panic_key.label)
        self.config_manager.save()
        self._set_status(f"Panic key set to '{self.config.panic_key.label}'.")
        if self._rebind_dialog is not None:
            self._rebind_dialog.destroy()
            self._rebind_dialog = None

    # ------------------------------------------------------------------
    # Debounced saving (only ever called on the GUI thread)
    # ------------------------------------------------------------------

    def _schedule_save(self, kind: str) -> None:
        job = self._save_jobs.get(kind)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        if kind == "config":
            self._save_jobs[kind] = self.after(AUTOSAVE_DEBOUNCE_MS, self._do_save_config)
        elif kind == "playlists":
            self._save_jobs[kind] = self.after(AUTOSAVE_DEBOUNCE_MS, self._do_save_playlists)

    def _do_save_config(self) -> None:
        self._save_jobs.pop("config", None)
        self.config_manager.save()

    def _do_save_playlists(self) -> None:
        self._save_jobs.pop("playlists", None)
        self.playlist_manager.save()

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _start_tray(self) -> None:
        try:
            from .tray import TrayIcon

            self.tray = TrayIcon(
                on_show=lambda: self._post("show_window"),
                on_enable=lambda: self._post("tray_enable"),
                on_disable=lambda: self._post("tray_disable"),
                on_exit=lambda: self._post("tray_exit"),
            )
            self.tray.start()
        except Exception as e:
            logger.warning("System tray unavailable: %s", e)
            self.tray = None

    # ------------------------------------------------------------------
    # Shutdown (see README's Application Lifecycle section)
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        try:
            self.audio_engine.stop_all()
        except Exception:
            logger.exception("Error stopping audio on close")
        try:
            self.hotkey_manager.stop()
        except Exception:
            logger.exception("Error unregistering hotkeys on close")
        try:
            self.config_manager.save()
            self.playlist_manager.save()
            self.sound_library.save()
        except Exception:
            logger.exception("Error saving state on close")
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.audio_engine.shutdown()
        except Exception:
            logger.exception("Error shutting down audio engine")
        self.destroy()
