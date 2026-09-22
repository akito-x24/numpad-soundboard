from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw


def _build_icon_image() -> "Image.Image":
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((3, 3, size - 3, size - 3), fill=(37, 99, 235, 255))
    # Simple speaker glyph so the icon reads clearly even at small sizes.
    draw.polygon([(18, 24), (28, 24), (39, 14), (39, 50), (28, 40), (18, 40)], fill=(255, 255, 255, 255))
    draw.arc((34, 19, 50, 45), start=300, end=60, fill=(255, 255, 255, 255), width=3)
    return img


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
