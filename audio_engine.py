"""
Audio Engine for Gussy Pad Launcher.
Handles low-latency playback of one-shot samples, exclusive track playback,
independent volume controls (Track Volume vs One-Shot Volume),
mute/panic, and top transport controls (Play/Pause, Stop One-shots, Mute All).
"""

import os
import pygame
from typing import Dict, Optional, Callable


class AudioEngine:
    def __init__(self, frequency: int = 44100, buffer_size: int = 512):
        self.frequency = frequency
        self.buffer_size = buffer_size
        self._initialized = False

        # Independent volume controls (0.0 to 1.0)
        self.oneshot_volume: float = 1.0
        self.track_volume: float = 1.0
        self.volume_step: float = 0.05  # 5%

        # Global Mute state
        self.is_muted: bool = False
        self._pre_mute_oneshot_vol: float = 1.0
        self._pre_mute_track_vol: float = 1.0

        # One-shot sound cache: {slot_index: pygame.mixer.Sound}
        self.oneshot_sounds: Dict[int, pygame.mixer.Sound] = {}
        # Track sound cache: {slot_index: pygame.mixer.Sound}
        self.track_sounds: Dict[int, pygame.mixer.Sound] = {}
        self.track_paths: Dict[int, str] = {}

        # Active playing track
        self.active_track_slot: Optional[int] = None
        self.is_track_paused: bool = False
        self.track_channel: Optional[pygame.mixer.Channel] = None

        # Callbacks for UI updates
        # (track_vol, oneshot_vol, is_muted)
        self.on_volume_changed: Optional[Callable[[float, float, bool], None]] = None
        # (active_slot, is_paused)
        self.on_track_state_changed: Optional[Callable[[Optional[int], bool], None]] = None

        self._init_mixer()

    def _init_mixer(self):
        try:
            pygame.mixer.pre_init(frequency=self.frequency, size=-16, channels=2, buffer=self.buffer_size)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(64)
            # Dedicated channel for exclusive backing tracks (channel 0)
            self.track_channel = pygame.mixer.Channel(0)
            self._initialized = True
        except Exception as e:
            print(f"[AudioEngine] Error initializing mixer: {e}")

    def load_oneshot(self, slot: int, file_path: str) -> bool:
        if not os.path.exists(file_path):
            return False
        try:
            sound = pygame.mixer.Sound(file_path)
            sound.set_volume(0.0 if self.is_muted else self.oneshot_volume)
            self.oneshot_sounds[slot] = sound
            return True
        except Exception as e:
            print(f"[AudioEngine] Failed to load oneshot {file_path}: {e}")
            return False

    def load_track(self, slot: int, file_path: str) -> bool:
        if not os.path.exists(file_path):
            return False
        try:
            sound = pygame.mixer.Sound(file_path)
            sound.set_volume(0.0 if self.is_muted else self.track_volume)
            self.track_sounds[slot] = sound
            self.track_paths[slot] = file_path
            return True
        except Exception as e:
            print(f"[AudioEngine] Failed to load track {file_path}: {e}")
            return False

    def clear_slot(self, is_track: bool, slot: int):
        if is_track:
            if self.active_track_slot == slot:
                self.stop_track()
            self.track_sounds.pop(slot, None)
            self.track_paths.pop(slot, None)
        else:
            ch_idx = 1 + (slot % 12)
            try:
                pygame.mixer.Channel(ch_idx).stop()
            except Exception:
                pass
            self.oneshot_sounds.pop(slot, None)

    # ==========================
    # One-Shot Trigger & Stop
    # ==========================
    def trigger_oneshot(self, slot: int):
        """
        Triggers one-shot on a dedicated channel (Channels 1..12).
        Retrigger logic: if the slot is already playing, stops it and restarts immediately.
        """
        sound = self.oneshot_sounds.get(slot)
        if not sound:
            return
        effective_vol = 0.0 if self.is_muted else self.oneshot_volume
        sound.set_volume(effective_vol)

        channel_idx = 1 + (slot % 12)
        channel = pygame.mixer.Channel(channel_idx)
        if channel.get_busy():
            channel.stop()  # Stop previous playback before retriggering
        channel.set_volume(effective_vol)
        channel.play(sound)

    def stop_oneshots(self):
        """Top STOP button: stops all one-shot channels without affecting the active track."""
        for c in range(1, 13):
            try:
                ch = pygame.mixer.Channel(c)
                if ch.get_busy():
                    ch.stop()
            except Exception:
                pass

    # ==========================
    # Exclusive Track Trigger & Transport
    # ==========================
    def trigger_track(self, slot: int):
        if not self.track_channel:
            return

        sound = self.track_sounds.get(slot)
        if not sound:
            return

        effective_vol = 0.0 if self.is_muted else self.track_volume
        sound.set_volume(effective_vol)

        if self.active_track_slot == slot and (self.track_channel.get_busy() or self.is_track_paused):
            self.stop_track()
            return

        if self.track_channel.get_busy():
            self.track_channel.stop()

        self.is_track_paused = False
        self.active_track_slot = slot
        self.track_channel.play(sound, loops=0)

        if self.on_track_state_changed:
            self.on_track_state_changed(self.active_track_slot, False)

    def stop_track(self):
        if self.track_channel and self.track_channel.get_busy():
            self.track_channel.stop()
        self.active_track_slot = None
        self.is_track_paused = False
        if self.on_track_state_changed:
            self.on_track_state_changed(None, False)

    def toggle_play_pause_track(self):
        """Top PLAY/PAUSE button: toggles pause/resume on the active track."""
        if not self.track_channel:
            return
        if self.active_track_slot is None:
            # If no track is currently active, start first available track
            for slot in sorted(self.track_sounds.keys()):
                self.trigger_track(slot)
                return
            return

        if self.is_track_paused:
            self.track_channel.unpause()
            self.is_track_paused = False
        else:
            self.track_channel.pause()
            self.is_track_paused = True

        if self.on_track_state_changed:
            self.on_track_state_changed(self.active_track_slot, self.is_track_paused)

    # ==========================
    # Independent Volume Controls
    # ==========================
    def track_vol_up(self) -> float:
        if self.is_muted:
            self.is_muted = False
        self.track_volume = min(1.0, self.track_volume + self.volume_step)
        self._apply_volumes()
        return self.track_volume

    def track_vol_down(self) -> float:
        if self.is_muted:
            self.is_muted = False
        self.track_volume = max(0.0, self.track_volume - self.volume_step)
        self._apply_volumes()
        return self.track_volume

    def oneshot_vol_up(self) -> float:
        if self.is_muted:
            self.is_muted = False
        self.oneshot_volume = min(1.0, self.oneshot_volume + self.volume_step)
        self._apply_volumes()
        return self.oneshot_volume

    def oneshot_vol_down(self) -> float:
        if self.is_muted:
            self.is_muted = False
        self.oneshot_volume = max(0.0, self.oneshot_volume - self.volume_step)
        self._apply_volumes()
        return self.oneshot_volume

    def set_track_volume(self, vol: float):
        self.track_volume = max(0.0, min(1.0, vol))
        self._apply_volumes()

    def set_oneshot_volume(self, vol: float):
        self.oneshot_volume = max(0.0, min(1.0, vol))
        self._apply_volumes()

    def toggle_mute(self) -> bool:
        """Top REC button: mutes/unmutes all sounds (both tracks and oneshots)."""
        if self.is_muted:
            self.is_muted = False
            self.oneshot_volume = self._pre_mute_oneshot_vol if self._pre_mute_oneshot_vol > 0 else 0.5
            self.track_volume = self._pre_mute_track_vol if self._pre_mute_track_vol > 0 else 0.5
        else:
            self._pre_mute_oneshot_vol = self.oneshot_volume
            self._pre_mute_track_vol = self.track_volume
            self.is_muted = True
        self._apply_volumes()
        return self.is_muted

    def _apply_volumes(self):
        eff_track = 0.0 if self.is_muted else self.track_volume
        eff_oneshot = 0.0 if self.is_muted else self.oneshot_volume

        if self.track_channel:
            self.track_channel.set_volume(eff_track)
        for s in self.track_sounds.values():
            s.set_volume(eff_track)
        for s in self.oneshot_sounds.values():
            s.set_volume(eff_oneshot)
        for c in range(1, 13):
            try:
                pygame.mixer.Channel(c).set_volume(eff_oneshot)
            except Exception:
                pass

        if self.on_volume_changed:
            self.on_volume_changed(self.track_volume, self.oneshot_volume, self.is_muted)

    def stop_all(self):
        """Panic button: immediately stops everything."""
        pygame.mixer.stop()
        self.active_track_slot = None
        self.is_track_paused = False
        if self.on_track_state_changed:
            self.on_track_state_changed(None, False)
