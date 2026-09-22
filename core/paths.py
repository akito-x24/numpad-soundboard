"""
Resolves where the soundboard stores its persistent data.

The app must not assume the current working directory is the project
directory - it may be launched via a shortcut, a pinned taskbar icon, or
(eventually) a packaged EXE, none of which guarantee a predictable cwd.
Instead everything lives under the standard per-user Windows app-data
folder, which also happens to be exactly the right place for a future
PyInstaller build (the project folder itself may end up read-only, e.g.
under Program Files).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "NumpadSoundboard"


def get_app_data_dir() -> Path:
    """
    Windows: %APPDATA%\\NumpadSoundboard (Roaming app data).
    Non-Windows (development/testing only): a sensible per-user fallback.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / APP_NAME


def get_config_dir() -> Path:
    d = get_app_data_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_sounds_dir() -> Path:
    d = get_app_data_dir() / "sounds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_assets_dir() -> Path:
    """
    Resolves the bundled `assets/` folder - both running from source and
    once frozen into a PyInstaller build (files live next to the exe,
    exposed via sys._MEIPASS).
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "assets"


def get_icon_ico_path() -> Path:
    return get_assets_dir() / "icon.ico"


def get_icon_png_path() -> Path:
    return get_assets_dir() / "icon.png"