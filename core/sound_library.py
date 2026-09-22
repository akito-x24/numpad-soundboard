"""
Owns the single shared pool of imported audio files plus their metadata.

Playlists never store sound files themselves - a slot just references a
sound_id (see models.Playlist). That means the same sound can be used by
any number of playlists/slots while the actual audio only ever exists
once on disk (deduplicated by content hash on import).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional

from .models import SoundEntry
from .paths import get_config_dir, get_sounds_dir

logger = logging.getLogger(__name__)

LIBRARY_FILENAME = "sound_library.json"
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg"}
_MAX_STEM_LENGTH = 100  # keep well under Windows path-length limits


def _hash_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitize_filename(name: str) -> str:
    # Strip characters Windows filenames can't contain.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
    if not name:
        name = "sound"
    stem, dot, ext = name.rpartition(".")
    if dot:
        return f"{stem[:_MAX_STEM_LENGTH]}.{ext}"
    return name[:_MAX_STEM_LENGTH]


class SoundLibrary:
    def __init__(self):
        self._path: Path = get_config_dir() / LIBRARY_FILENAME
        self.sounds: Dict[str, SoundEntry] = {}

    def load(self) -> None:
        self.sounds = {}
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for entry in data.get("sounds", []):
                    sound = SoundEntry.from_dict(entry)
                    self.sounds[sound.id] = sound
            except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
                logger.warning("Could not read sound_library.json (%s); starting empty.", e)
                self.sounds = {}

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"sounds": [s.to_dict() for s in self.sounds.values()]}
            tmp_path = self._path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as e:
            logger.error("Failed to save sound_library.json: %s", e)

    def resolve_path(self, sound_id: Optional[str]) -> Optional[Path]:
        if not sound_id:
            return None
        entry = self.sounds.get(sound_id)
        if entry is None:
            return None
        return get_sounds_dir() / entry.filename

    def import_sound(self, source_path: str) -> SoundEntry:
        """
        Copy an external file into the managed sounds directory and
        register it. If a byte-identical file was already imported, the
        existing entry is reused instead of duplicating it on disk.
        """
        src = Path(source_path)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        if src.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported audio format '{src.suffix}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        file_hash = _hash_file(src)

        # Avoid unnecessary duplicate copies of audio already in the pool.
        for entry in self.sounds.values():
            if entry.content_hash == file_hash:
                existing_path = get_sounds_dir() / entry.filename
                if existing_path.exists():
                    return entry
                break  # metadata says we have it but the file vanished; re-copy below

        sounds_dir = get_sounds_dir()
        safe_name = _sanitize_filename(src.name)
        dest = sounds_dir / safe_name
        if dest.exists():
            # Different source file that happens to share a filename -
            # never silently overwrite an existing sound.
            stem, dot, ext = safe_name.rpartition(".")
            suffix = uuid.uuid4().hex[:8]
            safe_name = f"{stem}_{suffix}.{ext}" if dot else f"{safe_name}_{suffix}"
            dest = sounds_dir / safe_name

        shutil.copy2(src, dest)

        entry = SoundEntry(
            id=str(uuid.uuid4()),
            display_name=src.name,
            filename=dest.name,
            content_hash=file_hash,
        )
        self.sounds[entry.id] = entry
        self.save()
        return entry
