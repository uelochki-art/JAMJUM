"""
Automated unit tests for JAMJUM Pad Launcher components.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import mido
from audio_engine import AudioEngine
from midi_listener import MidiListener, CONTROL_PAD_MAP, PAD_TO_SLOT, SOUND_PADS_ORDER, TRANSPORT_CC_MAP
from config_manager import ConfigManager

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


class TestJamjumPadLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audio = AudioEngine()
        cls.config = ConfigManager()
        cls.kick_path = os.path.join(SAMPLE_DIR, "Kick.wav")
        cls.track_path = os.path.join(SAMPLE_DIR, "Backing_Track_120BPM.wav")

    def test_audio_engine_retrigger_and_stop_oneshots_without_track(self):
        loaded = self.audio.load_oneshot(0, self.kick_path)
        self.assertTrue(loaded, "Kick.wav should load into slot 0")

        # 1. Ensure NO track is playing
        self.assertIsNone(self.audio.active_track_slot)

        # 2. Trigger oneshot
        self.audio.trigger_oneshot(0)
        ch1 = pygame.mixer.Channel(1)
        self.assertTrue(ch1.get_busy(), "Channel 1 should be busy playing slot 0")

        # 3. Retrigger test: trigger again should restart channel 1 without error
        self.audio.trigger_oneshot(0)
        self.assertTrue(ch1.get_busy(), "Channel 1 should be playing on retrigger")

        # 4. Stop oneshots: MUST STOP Channel 1 even when no track is running!
        self.audio.stop_oneshots()
        self.assertFalse(ch1.get_busy(), "Channel 1 MUST stop when stop_oneshots() is called!")

    def test_audio_engine_track_exclusive_and_toggle(self):
        loaded = self.audio.load_track(0, self.track_path)
        self.assertTrue(loaded, "Track should load into slot 0")

        # 1. Trigger track -> should play
        self.audio.trigger_track(0)
        self.assertEqual(self.audio.active_track_slot, 0)
        self.assertFalse(self.audio.is_track_paused)

        # 2. Toggle play/pause
        self.audio.toggle_play_pause_track()
        self.assertTrue(self.audio.is_track_paused)
        self.audio.toggle_play_pause_track()
        self.assertFalse(self.audio.is_track_paused)

        # 3. Trigger same track again -> should stop
        self.audio.trigger_track(0)
        self.assertIsNone(self.audio.active_track_slot)

    def test_independent_volume_controls(self):
        self.audio.set_track_volume(0.50)
        self.audio.set_oneshot_volume(0.80)
        self.audio.volume_step = 0.05

        # Track Volume Up (+5%)
        t_vol = self.audio.track_vol_up()
        self.assertAlmostEqual(t_vol, 0.55, places=2)

        # One-Shot Volume Down (-5%)
        os_vol = self.audio.oneshot_vol_down()
        self.assertAlmostEqual(os_vol, 0.75, places=2)

        # Global Mute toggle
        is_muted = self.audio.toggle_mute()
        self.assertTrue(is_muted)
        is_muted = self.audio.toggle_mute()
        self.assertFalse(is_muted)
        self.assertAlmostEqual(self.audio.track_volume, 0.55, places=2)
        self.assertAlmostEqual(self.audio.oneshot_volume, 0.75, places=2)

    def test_midi_listener_controls_and_transport(self):
        listener = MidiListener()
        received_controls = []
        received_pads = []

        listener.sig_control_hit.connect(lambda action: received_controls.append(action))
        listener.sig_pad_hit.connect(lambda preset, slot, vel: received_pads.append((preset, slot, vel)))

        # Check Right Column Control Mapping:
        # Pad 15 (Pad 16) -> track_vol_up
        # Pad 11 (Pad 12) -> track_vol_down
        # Pad 7  (Pad 8)  -> oneshot_vol_up
        # Pad 3  (Pad 4)  -> oneshot_vol_down
        self.assertEqual(CONTROL_PAD_MAP[15], 'track_vol_up')
        self.assertEqual(CONTROL_PAD_MAP[11], 'track_vol_down')
        self.assertEqual(CONTROL_PAD_MAP[7], 'oneshot_vol_up')
        self.assertEqual(CONTROL_PAD_MAP[3], 'oneshot_vol_down')

        # Test Preset 1 note 51 (Pad 15 in Preset 1: 36 + 15 = 51)
        msg_track_vol_up = mido.Message('note_on', note=51, velocity=100)
        listener._handle_message(msg_track_vol_up)
        self.assertIn('track_vol_up', received_controls)

        # Test Top Transport Buttons via CC:
        # CC 22 / CC 115 / CC 117 / CC 94 -> track_play_pause
        for cc in (22, 115, 117, 94):
            received_controls.clear()
            msg_cc = mido.Message('control_change', control=cc, value=127)
            listener._handle_message(msg_cc)
            self.assertIn('track_play_pause', received_controls, f"CC {cc} should trigger track_play_pause")

        # CC 23 / CC 116 / CC 93 -> stop_oneshots
        for cc in (23, 116, 93):
            received_controls.clear()
            msg_cc = mido.Message('control_change', control=cc, value=127)
            listener._handle_message(msg_cc)
            self.assertIn('stop_oneshots', received_controls, f"CC {cc} should trigger stop_oneshots")

        # CC 24 / CC 118 / CC 119 / CC 95 -> toggle_preset (REC button)
        for cc in (24, 118, 119, 95):
            received_controls.clear()
            msg_cc = mido.Message('control_change', control=cc, value=127)
            listener._handle_message(msg_cc)
            self.assertIn('toggle_preset', received_controls, f"CC {cc} should trigger toggle_preset")

        # Test Real-Time Start/Stop (0xFA / 0xFC)
        received_controls.clear()
        listener._on_direct_ble_event(0xFA, 0, 0)
        self.assertIn('track_play_pause', received_controls)

        received_controls.clear()
        listener._on_direct_ble_event(0xFC, 0, 0)
        self.assertIn('stop_oneshots', received_controls)

    def test_config_named_presets(self):
        cfg = ConfigManager()
        test_preset = "ТестПресет2"
        created = cfg.create_preset(test_preset)
        self.assertTrue(created)
        self.assertIn(test_preset, cfg.list_presets())

        cfg.set_oneshot_file(0, self.kick_path)
        self.assertEqual(cfg.get_oneshot_file(0), self.kick_path)

        deleted = cfg.delete_preset(test_preset)
        self.assertTrue(deleted)
        self.assertNotIn(test_preset, cfg.list_presets())


if __name__ == "__main__":
    unittest.main()
