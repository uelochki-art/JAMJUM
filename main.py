"""
Main entry point for JAMJUM Pad Launcher.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mido
try:
    import mido.backends.rtmidi
except Exception:
    pass
try:
    import rtmidi
except Exception:
    pass

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from audio_engine import AudioEngine
from midi_listener import MidiListener
from config_manager import ConfigManager
from gui import MainWindow


def main():
    # Single instance check
    import ctypes
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, "Global\\JAMJUM_PAD_LAUNCHER_MUTEX")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("[Main] An instance of JAMJUM Pad Launcher is already running. Exiting.")
        sys.exit(0)

    # Enable high DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("JAMJUM Pad Launcher")
    app.setQuitOnLastWindowClosed(False)  # Keep running in system tray

    # Components
    config_manager = ConfigManager()
    audio_engine = AudioEngine()
    midi_listener = MidiListener()

    # Load custom MIDI maps if saved
    p1_map = config_manager.get_midi_map("preset1_midi_map")
    if p1_map:
        try:
            custom_p1 = {int(k): int(v) for k, v in p1_map.items()}
            midi_listener.preset1_map.update(custom_p1)
        except Exception as e:
            print(f"[Main] Error loading preset1 MIDI map: {e}")

    p2_map = config_manager.get_midi_map("preset2_midi_map")
    if p2_map:
        try:
            custom_p2 = {int(k): int(v) for k, v in p2_map.items()}
            midi_listener.preset2_map.update(custom_p2)
        except Exception as e:
            print(f"[Main] Error loading preset2 MIDI map: {e}")

    # Save learned notes automatically
    def save_learned(preset: str, pad_idx: int, note: int):
        key = "preset1_midi_map" if preset == 'preset1' else "preset2_midi_map"
        config_manager.set_midi_map_note(key, note, pad_idx)

    midi_listener.sig_learn_complete.connect(save_learned)

    # Start MIDI listener thread (BLE & USB)
    midi_listener.start()

    # Window
    window = MainWindow(audio_engine, midi_listener, config_manager)
    window.show()

    # Clean exit
    ret = app.exec_()
    midi_listener.stop()
    audio_engine.stop_all()
    sys.exit(ret)


if __name__ == "__main__":
    main()
