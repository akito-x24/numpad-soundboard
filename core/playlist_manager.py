from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .models import Playlist, SlotAssignment
from .paths import get_config_dir

logger = logging.getLogger(__name__)

PLAYLISTS_FILENAME = "playlists.json"
DEFAULT_PLAYLIST_NAME = "Default"


class PlaylistManager:
    def __init__(self):
        self._path: Path = get_config_dir() / PLAYLISTS_FILENAME
        self.playlists: Dict[str, Playlist] = {}
        self.order: List[str] = []  # preserves GUI display order

    # ---- persistence ----

    def load(self) -> None:
        self.playlists = {}
        self.order = []
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for entry in data.get("playlists", []):
                    pl = Playlist.from_dict(entry)
                    self.playlists[pl.id] = pl
                    self.order.append(pl.id)
            except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
                logger.warning("Could not read playlists.json (%s); starting fresh.", e)
                self.playlists = {}
                self.order = []

        if not self.playlists:
            self.create_playlist(DEFAULT_PLAYLIST_NAME)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "playlists": [self.playlists[pid].to_dict() for pid in self.order if pid in self.playlists]
            }
            tmp_path = self._path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as e:
            logger.error("Failed to save playlists.json: %s", e)

    # ---- name uniqueness (keeps the GUI's name-based playlist picker unambiguous) ----

    def _unique_name(self, base_name: str, ignore_id: Optional[str] = None) -> str:
        existing = {p.name for pid, p in self.playlists.items() if pid != ignore_id}
        if base_name not in existing:
            return base_name
        i = 2
        while f"{base_name} ({i})" in existing:
            i += 1
        return f"{base_name} ({i})"

    # ---- CRUD ----

    def create_playlist(self, name: str) -> Playlist:
        pl = Playlist(id=str(uuid.uuid4()), name=self._unique_name(name or "Untitled"))
        self.playlists[pl.id] = pl
        self.order.append(pl.id)
        self.save()
        return pl

    def duplicate_playlist(self, playlist_id: str, new_name: Optional[str] = None) -> Playlist:
        src = self.playlists[playlist_id]
        cloned_slots = {k: SlotAssignment(sound_id=v.sound_id, volume=v.volume) for k, v in src.slots.items()}
        name = self._unique_name(new_name or f"{src.name} (copy)")
        pl = Playlist(id=str(uuid.uuid4()), name=name, slots=cloned_slots)
        self.playlists[pl.id] = pl
        self.order.append(pl.id)
        self.save()
        return pl

    def rename_playlist(self, playlist_id: str, new_name: str) -> None:
        new_name = new_name.strip()
        if playlist_id in self.playlists and new_name:
            self.playlists[playlist_id].name = self._unique_name(new_name, ignore_id=playlist_id)
            self.save()

    def delete_playlist(self, playlist_id: str) -> None:
        if len(self.playlists) <= 1:
            raise ValueError("Cannot delete the last remaining playlist.")
        if playlist_id in self.playlists:
            del self.playlists[playlist_id]
            self.order = [pid for pid in self.order if pid != playlist_id]
            self.save()

    def get(self, playlist_id: Optional[str]) -> Optional[Playlist]:
        if playlist_id is None:
            return None
        return self.playlists.get(playlist_id)

    def list_playlists(self) -> List[Playlist]:
        return [self.playlists[pid] for pid in self.order if pid in self.playlists]

    # ---- slot mutation ----
    # Note: these mutate in-memory state only. Callers that fire rapidly
    # (e.g. a GUI volume slider mid-drag) are expected to debounce their
    # own call to save() rather than writing to disk on every change;
    # CRUD operations above save immediately since they're already
    # discrete, low-frequency user actions.

    def assign_sound(self, playlist_id: str, slot_key: str, sound_id: Optional[str]) -> None:
        self.playlists[playlist_id].slots[slot_key].sound_id = sound_id
        self.save()

    def set_slot_volume(self, playlist_id: str, slot_key: str, volume: int) -> None:
        self.playlists[playlist_id].slots[slot_key].volume = max(0, min(100, int(volume)))
