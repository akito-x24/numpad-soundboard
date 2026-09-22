from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import AppConfig
from .paths import get_config_dir

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.json"


class ConfigManager:
    def __init__(self):
        self._path: Path = get_config_dir() / CONFIG_FILENAME
        self.config: AppConfig = AppConfig()

    def load(self) -> AppConfig:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self.config = AppConfig.from_dict(data)
            except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError) as e:
                logger.warning("Could not read config.json (%s); using defaults.", e)
                self.config = AppConfig()
        else:
            self.config = AppConfig()
        return self.config

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(self.config.to_dict(), indent=2), encoding="utf-8")
            tmp_path.replace(self._path)  # atomic on the same volume
        except OSError as e:
            logger.error("Failed to save config.json: %s", e)
