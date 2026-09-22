"""
Plain data models persisted to JSON. Each model has explicit to_dict /
from_dict methods (rather than relying on generic dataclass introspection)
so the on-disk schema is easy to read, easy to hand-edit, and stable
across refactors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

COMMON_SLOT_KEY = "0"
# Numpad 1-9 belong to whichever playlist is active. Numpad 0 does not -
# it's a single, playlist-independent "common" sound (see AppConfig.common_slot
# below), so it's deliberately excluded from SLOT_KEYS/Playlist.slots.
SLOT_KEYS: Tuple[str, ...] = tuple(str(i) for i in range(1, 10))  # "1".."9"
ALL_SLOT_KEYS: Tuple[str, ...] = (COMMON_SLOT_KEY,) + SLOT_KEYS  # "0".."9", for GUI iteration
DEFAULT_SLOT_VOLUME = 100


@dataclass
class SoundEntry:
    """One physical file in the shared, deduplicated sounds pool."""
    id: str
    display_name: str
    filename: str  # filename within the managed sounds directory
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "filename": self.filename,
            "content_hash": self.content_hash,
        }

    @staticmethod
    def from_dict(d: dict) -> "SoundEntry":
        return SoundEntry(
            id=d["id"],
            display_name=d["display_name"],
            filename=d["filename"],
            content_hash=d.get("content_hash", ""),
        )


@dataclass
class SlotAssignment:
    sound_id: Optional[str] = None
    volume: int = DEFAULT_SLOT_VOLUME  # 0-100

    def to_dict(self) -> dict:
        return {"sound_id": self.sound_id, "volume": self.volume}

    @staticmethod
    def from_dict(d: dict) -> "SlotAssignment":
        return SlotAssignment(
            sound_id=d.get("sound_id"),
            volume=int(d.get("volume", DEFAULT_SLOT_VOLUME)),
        )


@dataclass
class Playlist:
    id: str
    name: str
    slots: Dict[str, SlotAssignment] = field(default_factory=dict)

    def __post_init__(self):
        # Guarantee slots 1-9 always exist, even for hand-edited JSON.
        # (Slot 0 is intentionally not a playlist concern - see SLOT_KEYS.)
        for key in SLOT_KEYS:
            self.slots.setdefault(key, SlotAssignment())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slots": {k: v.to_dict() for k, v in self.slots.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "Playlist":
        slots = {k: SlotAssignment.from_dict(v) for k, v in d.get("slots", {}).items()}
        return Playlist(id=d["id"], name=d["name"], slots=slots)


@dataclass
class PanicKeyBinding:
    """
    Identifies a physical key by (scan_code, is_keypad) - the same pair
    core/hotkeys.py uses to recognise every numpad key, independent of
    Num Lock state. `label` is just a human-readable name for the GUI.
    """
    scan_code: int
    is_keypad: bool
    label: str = "Delete"

    def to_dict(self) -> dict:
        return {"scan_code": self.scan_code, "is_keypad": self.is_keypad, "label": self.label}

    @staticmethod
    def from_dict(d: dict) -> "PanicKeyBinding":
        return PanicKeyBinding(
            scan_code=int(d.get("scan_code", 83)),
            is_keypad=bool(d.get("is_keypad", False)),
            label=d.get("label", "Delete"),
        )


def _default_panic_key() -> PanicKeyBinding:
    # The dedicated Delete key (scan code 83, NOT the numpad one - Numpad
    # "." is already Stop Last). There's no standard "CE" scan code on any
    # keyboard, so this is the closest fixed default; see core/hotkeys.py.
    return PanicKeyBinding(scan_code=83, is_keypad=False, label="Delete")


@dataclass
class AppConfig:
    master_volume: int = 75
    active_playlist_id: Optional[str] = None
    max_simultaneous_sounds: int = 32
    suppress_passthrough: bool = False
    hotkeys_enabled: bool = True
    tray_enabled: bool = True
    panic_key: PanicKeyBinding = field(default_factory=_default_panic_key)
    # Numpad 0's sound - the same across every playlist. Lives here rather
    # than in any Playlist because it explicitly isn't playlist-scoped.
    common_slot: SlotAssignment = field(default_factory=SlotAssignment)

    def to_dict(self) -> dict:
        return {
            "master_volume": self.master_volume,
            "active_playlist_id": self.active_playlist_id,
            "max_simultaneous_sounds": self.max_simultaneous_sounds,
            "suppress_passthrough": self.suppress_passthrough,
            "hotkeys_enabled": self.hotkeys_enabled,
            "tray_enabled": self.tray_enabled,
            "panic_key": self.panic_key.to_dict(),
            "common_slot": self.common_slot.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> "AppConfig":
        return AppConfig(
            master_volume=int(d.get("master_volume", 75)),
            active_playlist_id=d.get("active_playlist_id"),
            max_simultaneous_sounds=int(d.get("max_simultaneous_sounds", 32)),
            suppress_passthrough=bool(d.get("suppress_passthrough", False)),
            hotkeys_enabled=bool(d.get("hotkeys_enabled", True)),
            tray_enabled=bool(d.get("tray_enabled", True)),
            panic_key=(
                PanicKeyBinding.from_dict(d["panic_key"])
                if d.get("panic_key") else _default_panic_key()
            ),
            common_slot=(
                SlotAssignment.from_dict(d["common_slot"])
                if d.get("common_slot") else SlotAssignment()
            ),
        )
