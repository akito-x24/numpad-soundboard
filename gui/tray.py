from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import pystray
from PIL import Image

from core.paths import get_icon_png_path

logger = logging.getLogger(__name__)


def _build_icon_image() -> "Image.Image":
    try:
        return Image.open(get_icon_png_path())
    except Exception as e:
        logger.warning("Failed to load tray icon %s: %s", get_icon_png_path(), e)
        return Image.new("RGBA", (64, 64), (37, 99, 235, 255))


class TrayIcon:
    def __init__(
        self,
        on_show: Callable[[], None],
        on_enable: Callable[[], None],
        on_disable: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self._icon = pystray.Icon(
            "numpad_soundboard",
            _build_icon_image(),
            "Numpad Soundboard",
            menu=pystray.Menu(
                pystray.MenuItem("Show Soundboard", lambda icon, item: on_show()),
                pystray.MenuItem("Enable Hotkeys", lambda icon, item: on_enable()),
                pystray.MenuItem("Disable Hotkeys", lambda icon, item: on_disable()),
                pystray.MenuItem("Exit", lambda icon, item: on_exit()),
            ),
        )
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
