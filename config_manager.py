"""
Config Manager for Gussy / JAMJUM Pad Launcher.
Handles multi-preset soundbanks (e.g. "Основной", "Новый год", "День рождения"),
local sample storage inside project folders, volume levels, and MIDI note maps.
"""

import os
import sys
import json
import shutil
from typing import Dict, Any, List, Optional

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PRESETS_DIR = os.path.join(BASE_DIR, "presets")
GLOBAL_CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT_PRESET_NAME = "Основной"

DEFAULT_PRESET_DATA: Dict[str, Any] = {
    "name": DEFAULT_PRESET_NAME,
    "track_volume": 1.0,
    "oneshot_volume": 1.0,
    "volume_step": 0.05,
    "oneshot_files": {},  # "0": "samples/kick.wav", ...
    "track_files": {}     # "0": "samples/track1.mp3", ...
}

DEFAULT_GLOBAL_CONFIG: Dict[str, Any] = {
    "current_preset": DEFAULT_PRESET_NAME,
    "preset1_midi_map": {},
    "preset2_midi_map": {}
}


class ConfigManager:
    def __init__(self, base_dir: str = BASE_DIR):
        self.base_dir = base_dir
        self.presets_dir = os.path.join(self.base_dir, "presets")
        os.makedirs(self.presets_dir, exist_ok=True)

        self.global_config_path = os.path.join(self.base_dir, "config.json")
        self.global_config = self._load_global_config()

        self.current_preset_name = self.global_config.get("current_preset", DEFAULT_PRESET_NAME)
        self.preset_data = self.load_preset(self.current_preset_name)

    def _load_global_config(self) -> Dict[str, Any]:
        if os.path.exists(self.global_config_path):
            try:
                with open(self.global_config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cfg = DEFAULT_GLOBAL_CONFIG.copy()
                    cfg.update(data)
                    return cfg
            except Exception as e:
                print(f"[ConfigManager] Error reading global config: {e}")
        return DEFAULT_GLOBAL_CONFIG.copy()

    def _save_global_config(self):
        try:
            self.global_config["current_preset"] = self.current_preset_name
            with open(self.global_config_path, "w", encoding="utf-8") as f:
                json.dump(self.global_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Error saving global config: {e}")

    def list_presets(self) -> List[str]:
        presets = []
        if os.path.exists(self.presets_dir):
            for entry in os.listdir(self.presets_dir):
                full_path = os.path.join(self.presets_dir, entry)
                if os.path.isdir(full_path):
                    presets.append(entry)
        if not presets:
            presets.append(DEFAULT_PRESET_NAME)
        return sorted(presets)

    def get_preset_dir(self, preset_name: Optional[str] = None) -> str:
        name = preset_name or self.current_preset_name
        pdir = os.path.join(self.presets_dir, name)
        os.makedirs(pdir, exist_ok=True)
        return pdir

    def get_preset_samples_dir(self, preset_name: Optional[str] = None) -> str:
        pdir = self.get_preset_dir(preset_name)
        sdir = os.path.join(pdir, "samples")
        os.makedirs(sdir, exist_ok=True)
        return sdir

    def load_preset(self, preset_name: str) -> Dict[str, Any]:
        self.current_preset_name = preset_name
        pdir = self.get_preset_dir(preset_name)
        config_file = os.path.join(pdir, "preset.json")

        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cfg = DEFAULT_PRESET_DATA.copy()
                    cfg.update(data)
                    cfg["name"] = preset_name
                    self.preset_data = cfg
                    self._save_global_config()
                    return cfg
            except Exception as e:
                print(f"[ConfigManager] Error loading preset '{preset_name}': {e}")

        # Check for legacy root config.json migration
        legacy_file = os.path.join(self.base_dir, "config.json")
        cfg = DEFAULT_PRESET_DATA.copy()
        cfg["name"] = preset_name
        if os.path.exists(legacy_file):
            try:
                with open(legacy_file, "r", encoding="utf-8") as f:
                    leg = json.load(f)
                    if "oneshot_files" in leg:
                        cfg["oneshot_files"] = leg.get("oneshot_files", {})
                    if "track_files" in leg:
                        cfg["track_files"] = leg.get("track_files", {})
                    if "volume_step" in leg:
                        cfg["volume_step"] = leg.get("volume_step", 0.05)
            except Exception:
                pass

        self.preset_data = cfg
        self.save_preset()
        self._save_global_config()
        return cfg

    def save_preset(self):
        pdir = self.get_preset_dir(self.current_preset_name)
        config_file = os.path.join(pdir, "preset.json")
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(self.preset_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Error saving preset '{self.current_preset_name}': {e}")
        self._save_global_config()

    def create_preset(self, new_name: str, copy_current: bool = False) -> bool:
        new_name = new_name.strip()
        if not new_name:
            return False
        pdir = self.get_preset_dir(new_name)
        sdir = self.get_preset_samples_dir(new_name)

        if copy_current:
            new_data = json.loads(json.dumps(self.preset_data))
            new_data["name"] = new_name
            # Copy sample files into new preset samples dir
            for slot, path in list(new_data.get("oneshot_files", {}).items()):
                if path and os.path.exists(path):
                    dst = os.path.join(sdir, os.path.basename(path))
                    if os.path.abspath(path) != os.path.abspath(dst):
                        shutil.copy2(path, dst)
                    new_data["oneshot_files"][slot] = dst
            for slot, path in list(new_data.get("track_files", {}).items()):
                if path and os.path.exists(path):
                    dst = os.path.join(sdir, os.path.basename(path))
                    if os.path.abspath(path) != os.path.abspath(dst):
                        shutil.copy2(path, dst)
                    new_data["track_files"][slot] = dst
        else:
            new_data = DEFAULT_PRESET_DATA.copy()
            new_data["name"] = new_name

        self.current_preset_name = new_name
        self.preset_data = new_data
        self.save_preset()
        return True

    def delete_preset(self, preset_name: str) -> bool:
        presets = self.list_presets()
        if len(presets) <= 1:
            return False  # Cannot delete the only preset
        pdir = os.path.join(self.presets_dir, preset_name)
        if os.path.exists(pdir):
            try:
                shutil.rmtree(pdir)
            except Exception as e:
                print(f"[ConfigManager] Error removing preset folder {pdir}: {e}")
                return False

        remaining = self.list_presets()
        self.load_preset(remaining[0])
        return True

    def import_sample_file(self, src_path: str, is_track: bool, slot: int) -> str:
        """
        Copies sample into preset's dedicated samples directory so project is self-contained.
        """
        if not os.path.exists(src_path):
            return src_path
        samples_dir = self.get_preset_samples_dir()
        base_name = os.path.basename(src_path)
        prefix = f"track_{slot}_" if is_track else f"one_{slot}_"
        target_name = f"{prefix}{base_name}"
        target_path = os.path.join(samples_dir, target_name)

        try:
            if os.path.abspath(src_path) != os.path.abspath(target_path):
                shutil.copy2(src_path, target_path)
            return target_path
        except Exception as e:
            print(f"[ConfigManager] Could not copy sample to {target_path}: {e}")
            return src_path

    # ==========================
    # Slot Accessors
    # ==========================
    def get_oneshot_file(self, slot: int) -> str:
        rel_or_abs = self.preset_data.get("oneshot_files", {}).get(str(slot), "")
        return self._resolve_path(rel_or_abs)

    def set_oneshot_file(self, slot: int, path: str):
        if "oneshot_files" not in self.preset_data:
            self.preset_data["oneshot_files"] = {}
        self.preset_data["oneshot_files"][str(slot)] = path
        self.save_preset()

    def get_track_file(self, slot: int) -> str:
        rel_or_abs = self.preset_data.get("track_files", {}).get(str(slot), "")
        return self._resolve_path(rel_or_abs)

    def set_track_file(self, slot: int, path: str):
        if "track_files" not in self.preset_data:
            self.preset_data["track_files"] = {}
        self.preset_data["track_files"][str(slot)] = path
        self.save_preset()

    def _resolve_path(self, path: str) -> str:
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        # Try relative to preset dir
        preset_rel = os.path.join(self.get_preset_dir(), path)
        if os.path.exists(preset_rel):
            return preset_rel
        # Try relative to base dir
        base_rel = os.path.join(self.base_dir, path)
        if os.path.exists(base_rel):
            return base_rel
        return path

    def get_volume_step(self) -> float:
        return self.preset_data.get("volume_step", 0.05)

    def set_volume_step(self, step: float):
        self.preset_data["volume_step"] = step
        self.save_preset()

    def get_track_volume(self) -> float:
        return self.preset_data.get("track_volume", 1.0)

    def set_track_volume(self, vol: float):
        self.preset_data["track_volume"] = vol
        self.save_preset()

    def get_oneshot_volume(self) -> float:
        return self.preset_data.get("oneshot_volume", 1.0)

    def set_oneshot_volume(self, vol: float):
        self.preset_data["oneshot_volume"] = vol
        self.save_preset()

    # Legacy compat
    @property
    def config(self) -> Dict[str, Any]:
        return self.preset_data

    def get_midi_map(self, preset_key: str) -> Dict[str, int]:
        return self.global_config.get(preset_key, {})

    def set_midi_map_note(self, preset_key: str, note: int, pad_idx: int):
        if preset_key not in self.global_config:
            self.global_config[preset_key] = {}
        self.global_config[preset_key][str(note)] = pad_idx
        self._save_global_config()

    def get_master_volume(self) -> float:
        return self.get_track_volume()

    def set_master_volume(self, vol: float):
        self.set_track_volume(vol)
        self.set_oneshot_volume(vol)
