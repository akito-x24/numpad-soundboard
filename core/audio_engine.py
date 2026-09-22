from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pygame

logger = logging.getLogger(__name__)


@dataclass
class _PlaybackInstance:
    channel_index: int
    token: int
    slot_key: str
    sound_id: str
    triggered_at: float


class AudioEngine:
    def __init__(self, max_simultaneous_sounds: int = 32, sample_rate: int = 44100, buffer_size: int = 512):
        self._lock = threading.RLock()
        self._cache: Dict[str, "pygame.mixer.Sound"] = {}
        self._active: List[_PlaybackInstance] = []
        self._max_channels = max(1, int(max_simultaneous_sounds))
        self._master_volume = 0.75  # 0.0-1.0
        self._initialized = False
        self._sample_rate = sample_rate
        self._buffer_size = buffer_size

        self._channels: List["pygame.mixer.Channel"] = []
        self._channel_token: List[int] = []
        self._next_channel_idx = 0
        self._token_counter = 0

    # ---- lifecycle ----

    def initialize(self) -> None:
        if self._initialized:
            return
        pygame.mixer.pre_init(frequency=self._sample_rate, size=-16, channels=2, buffer=self._buffer_size)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(self._max_channels)
        # Own the channel objects directly (constructed once, kept forever)
        # instead of calling pygame.mixer.find_channel() per trigger, so
        # "which channel" is always an unambiguous plain integer index -
        # see the module docstring for why that matters for correctness.
        self._channels = [pygame.mixer.Channel(i) for i in range(self._max_channels)]
        self._channel_token = [0] * self._max_channels
        self._initialized = True
        logger.info("Audio engine initialized: %s, %d channels", pygame.mixer.get_init(), self._max_channels)

    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            pygame.mixer.stop()
            pygame.mixer.quit()
        finally:
            self._initialized = False

    def set_max_channels(self, count: int) -> None:
        with self._lock:
            self._max_channels = max(1, int(count))
            if self._initialized:
                pygame.mixer.set_num_channels(self._max_channels)
                self._channels = [pygame.mixer.Channel(i) for i in range(self._max_channels)]
                self._channel_token = [0] * self._max_channels
                self._active.clear()
                self._next_channel_idx = 0

    # ---- volume ----

    def set_master_volume_percent(self, percent: int) -> int:
        percent = max(0, min(100, int(percent)))
        with self._lock:
            self._master_volume = percent / 100.0
        return percent

    def get_master_volume_percent(self) -> int:
        with self._lock:
            return round(self._master_volume * 100)

    # ---- preloading (ahead-of-time decode; the hotkey path never decodes) ----

    def preload(self, sound_id: str, file_path: Optional[Path]) -> bool:
        """Decode a sound file once and cache it. Never raises."""
        if file_path is None:
            return False
        with self._lock:
            if sound_id in self._cache:
                return True
            try:
                sound = pygame.mixer.Sound(str(file_path))
                self._cache[sound_id] = sound
                return True
            except Exception as e:
                logger.warning("Failed to decode sound %s (%s): %s", sound_id, file_path, e)
                return False

    def evict(self, sound_id: str) -> None:
        with self._lock:
            self._cache.pop(sound_id, None)

    def is_cached(self, sound_id: str) -> bool:
        with self._lock:
            return sound_id in self._cache

    # ---- playback (the hot path - keep this fast) ----

    def _acquire_channel_locked(self) -> int:
        """
        Returns a channel index to play on: a genuinely free one if any
        exist, otherwise the next one in round-robin order (a simple,
        predictable voice-stealing policy - "reclaim whichever channel
        was assigned longest ago").
        """
        n = len(self._channels)
        for offset in range(n):
            idx = (self._next_channel_idx + offset) % n
            if not self._channels[idx].get_busy():
                self._next_channel_idx = (idx + 1) % n
                return idx
        idx = self._next_channel_idx
        self._next_channel_idx = (idx + 1) % n
        return idx

    def trigger(self, slot_key: str, sound_id: str, slot_volume_percent: int) -> bool:
        """
        Play a brand new, independent instance immediately. No file I/O,
        no decoding, no GUI calls - just a dict lookup, a channel grab,
        and a play() call. Safe to call from the keyboard hook thread.
        """
        with self._lock:
            sound = self._cache.get(sound_id)
            if sound is None:
                logger.warning("trigger() called for uncached sound_id=%s", sound_id)
                return False

            idx = self._acquire_channel_locked()
            self._token_counter += 1
            token = self._token_counter
            self._channel_token[idx] = token

            individual = max(0, min(100, int(slot_volume_percent))) / 100.0
            channel = self._channels[idx]
            channel.set_volume(individual * self._master_volume)
            channel.play(sound)

            self._active.append(_PlaybackInstance(
                channel_index=idx, token=token, slot_key=slot_key,
                sound_id=sound_id, triggered_at=time.monotonic(),
            ))
            self._prune_locked()
            return True

    def _is_live_locked(self, inst: _PlaybackInstance) -> bool:
        # "Live" = no later trigger has reclaimed this channel, and it's
        # still actually producing sound right now.
        return (
            self._channel_token[inst.channel_index] == inst.token
            and self._channels[inst.channel_index].get_busy()
        )

    def stop_last(self) -> bool:
        """
        Stop the most recently triggered instance that's still actually
        playing, walking backward past any that already finished (or
        whose channel got reclaimed for a newer trigger) so this stays
        correct under heavy overlap - including many repeats of the same
        sound. No-ops safely if nothing is active.
        """
        with self._lock:
            while self._active:
                instance = self._active.pop()
                if self._is_live_locked(instance):
                    self._channels[instance.channel_index].stop()
                    return True
            return False

    def stop_all(self) -> None:
        """PANIC: immediately stop every currently playing instance."""
        with self._lock:
            pygame.mixer.stop()
            self._active.clear()

    def _prune_locked(self) -> None:
        self._active = [inst for inst in self._active if self._is_live_locked(inst)]

    def prune(self) -> None:
        with self._lock:
            self._prune_locked()

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
