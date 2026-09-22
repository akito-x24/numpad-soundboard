"""
Numpad Soundboard - entry point.

Startup sequence (see README for the full lifecycle description):
  1. Load configuration.
  2. Load the sound library and playlists.
  3. Initialize the audio engine.
  4. Build the GUI, which preloads the active playlist's audio and registers global hotkeys as it constructs itself.
  5. Hand control to the GUI's event loop.

Run with:  python main.py
"""
import logging
import sys

from core.audio_engine import AudioEngine
from core.config_manager import ConfigManager
from core.playlist_manager import PlaylistManager
from core.sound_library import SoundLibrary
from gui.app import SoundboardApp


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger("main")

    if not sys.platform.startswith("win"):
        logger.warning(
            "This app targets Windows (global Numpad hotkeys use Windows-specific "
            "scan codes). The GUI and audio engine will still run here for "
            "development, but global hotkeys will not function on this platform."
        )

    config_manager = ConfigManager()
    config_manager.load()

    sound_library = SoundLibrary()
    sound_library.load()

    playlist_manager = PlaylistManager()
    playlist_manager.load()

    audio_engine = AudioEngine(max_simultaneous_sounds=config_manager.config.max_simultaneous_sounds)
    audio_engine.initialize()

    app = SoundboardApp(
        config_manager=config_manager,
        sound_library=sound_library,
        playlist_manager=playlist_manager,
        audio_engine=audio_engine,
    )
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
