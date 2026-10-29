"""
MIDI Listener for Gussy Pad Launcher.
Thread-safe implementation using PyQt5 QObject and pyqtSignal.
Listens to incoming MIDI messages directly via Bluetooth LE (native Windows WinRT BLE)
and standard USB MIDI ports.

Right column pads:
- Pad 16 (idx 15): Track Volume UP
- Pad 12 (idx 11): Track Volume DOWN
- Pad 8  (idx 7):  One-Shot Volume UP
- Pad 4  (idx 3):  One-Shot Volume DOWN

Top buttons:
- Play/Pause (Triangle): Track Play / Pause
- Stop (Square): Stop One-Shots
- Record (Circle): Mute All
"""

import time
import os
from datetime import datetime
import threading
import asyncio
from typing import Dict, Optional, List

from PyQt5.QtCore import QObject, pyqtSignal

import mido
try:
    import mido.backends.rtmidi
except Exception:
    pass
try:
    import rtmidi
except Exception:
    pass

from winrt.windows.devices.bluetooth import BluetoothLEDevice
from winrt.windows.devices.enumeration import DeviceInformation
from winrt.windows.devices.bluetooth.genericattributeprofile import GattClientCharacteristicConfigurationDescriptorValue
from winrt.windows.storage.streams import DataReader

# Dedicated right-column control pads (in 0..15 pad grid):
# Row 0 (top-right): Pad 16 (index 15) -> track_vol_up
# Row 1:             Pad 12 (index 11) -> track_vol_down
# Row 2:             Pad 8  (index 7)  -> oneshot_vol_up
# Row 3 (bottom-rt): Pad 4  (index 3)  -> oneshot_vol_down
CONTROL_PAD_MAP = {
    15: 'track_vol_up',
    11: 'track_vol_down',
    7: 'oneshot_vol_up',
    3: 'oneshot_vol_down'
}

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midi_debug.log")

def debug_log(msg: str):
    try:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# Top transport button mappings:
# Triangle (Play/Pause): CC 22, 115, 117, 41, 94; Notes 22, 115
# Square (Stop): CC 23, 114, 116, 42, 93, 20, 21; Notes 23, 114
# Circle (Record / Toggle Preset: One-Shots <-> Tracks): CC 24, 118, 119, 43, 95, 28, 44, 45; Notes 24, 118, 119
TRANSPORT_CC_MAP = {
    # Triangle (Play/Pause)
    22: 'track_play_pause',
    115: 'track_play_pause',
    117: 'track_play_pause',
    94: 'track_play_pause',
    # Square (Stop)
    23: 'stop_oneshots',
    114: 'stop_oneshots',
    116: 'stop_oneshots',
    93: 'stop_oneshots',
    20: 'stop_oneshots',
    21: 'stop_oneshots',
    # Circle (Record -> Toggle Preset)
    24: 'toggle_preset',
    118: 'toggle_preset',
    119: 'toggle_preset',
    95: 'toggle_preset',
    28: 'toggle_preset',
    44: 'toggle_preset',
    45: 'toggle_preset'
}

TRANSPORT_NOTE_MAP = {
    # Triangle (Play/Pause)
    22: 'track_play_pause',
    115: 'track_play_pause',
    117: 'track_play_pause',
    94: 'track_play_pause',
    # Square (Stop)
    23: 'stop_oneshots',
    114: 'stop_oneshots',
    116: 'stop_oneshots',
    93: 'stop_oneshots',
    20: 'stop_oneshots',
    21: 'stop_oneshots',
    # Circle (Record -> Toggle Preset)
    24: 'toggle_preset',
    118: 'toggle_preset',
    119: 'toggle_preset',
    95: 'toggle_preset',
    28: 'toggle_preset',
    44: 'toggle_preset',
    45: 'toggle_preset'
}

SOUND_PADS_ORDER = [0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14]
PAD_TO_SLOT = {pad_idx: slot_idx for slot_idx, pad_idx in enumerate(SOUND_PADS_ORDER)}


class DirectBleMidiReceiver:
    def __init__(self, on_midi_event_cb, on_status_cb):
        self.on_midi_event_cb = on_midi_event_cb
        self.on_status_cb = on_status_cb
        self.is_connected = False
        self.device_name = ""
        self._running = False
        self._thread = None
        self._loop = None

        self._ble_device = None
        self._services = None
        self._subscribed_chars = []
        self._writable_chars = []
        self._midi_char = None
        self._event_tokens = []
        self._conn_token = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._disconnect_cleanup()
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass

    def _run_async_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._worker())
        except Exception:
            pass
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _worker(self):
        while self._running:
            if not self.is_connected:
                success = await self._try_connect()
                if not success:
                    await asyncio.sleep(2.0)
                    continue
            else:
                # Connection watchdog check
                try:
                    if self._ble_device is None or self._ble_device.connection_status == 0:
                        self._disconnect_cleanup()
                except Exception:
                    self._disconnect_cleanup()
            await asyncio.sleep(1.0)

    async def _try_connect(self):
        try:
            selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
            devices = await DeviceInformation.find_all_async_aqs_filter(selector)
            target = None
            for d in devices:
                if "jp" in d.name.lower() or "mini" in d.name.lower():
                    target = d
                    break
            if not target:
                return False

            dev = await BluetoothLEDevice.from_id_async(target.id)
            if not dev:
                return False

            if dev.connection_status == 0:
                try:
                    dev.close()
                except Exception:
                    pass
                return False

            services_res = await dev.get_gatt_services_async()
            if services_res.status != 0 or not services_res.services:
                try:
                    dev.close()
                except Exception:
                    pass
                return False

            self._ble_device = dev
            self._services = services_res.services
            self._conn_token = self._ble_device.add_connection_status_changed(self._on_conn_status_changed)
            subscribed = False

            for s in self._services:
                chars_res = await s.get_characteristics_async()
                if chars_res.status != 0:
                    continue
                for c in chars_res.characteristics:
                    props = c.characteristic_properties
                    uuid_str = str(c.uuid).lower()
                    if "7772e5db" in uuid_str:
                        self._midi_char = c
                        if c not in self._writable_chars:
                            self._writable_chars.append(c)
                    elif (props & 4) or (props & 8):
                        if c not in self._writable_chars:
                            self._writable_chars.append(c)
                    if (props & 16) or ("7772e5db" in uuid_str):
                        try:
                            st = await c.write_client_characteristic_configuration_descriptor_async(
                                GattClientCharacteristicConfigurationDescriptorValue.NOTIFY
                            )
                            if st == 0:
                                token = c.add_value_changed(self._on_gatt_notification)
                                self._subscribed_chars.append(c)
                                self._event_tokens.append((c, token))
                                subscribed = True
                        except Exception:
                            pass

            if subscribed:
                self.is_connected = True
                self.device_name = f"Bluetooth: {target.name}"
                if self.on_status_cb:
                    self.on_status_cb(True, self.device_name)
                return True
            else:
                self._disconnect_cleanup()
                return False
        except Exception:
            self._disconnect_cleanup()
            return False

    def _on_conn_status_changed(self, sender, args):
        try:
            if sender.connection_status == 0:
                self._disconnect_cleanup()
        except Exception:
            pass

    def _disconnect_cleanup(self):
        if not self.is_connected and self._ble_device is None:
            return
        self.is_connected = False
        try:
            if self._conn_token is not None and self._ble_device is not None:
                try:
                    self._ble_device.remove_connection_status_changed(self._conn_token)
                except Exception:
                    pass
                self._conn_token = None
        except Exception:
            pass

        for char, token in self._event_tokens:
            try:
                char.remove_value_changed(token)
            except Exception:
                pass
        self._event_tokens.clear()
        self._subscribed_chars.clear()
        self._writable_chars.clear()
        self._midi_char = None
        if self._ble_device is not None:
            try:
                self._ble_device.close()
            except Exception:
                pass
            self._ble_device = None
        self._services = None

        if self.on_status_cb:
            self.on_status_cb(False, "Bluetooth: Отключено (Поиск...)")

    def _on_gatt_notification(self, sender, args):
        try:
            dr = DataReader.from_buffer(args.characteristic_value)
            length = dr.unconsumed_buffer_length
            data = bytearray(length)
            dr.read_bytes(data)
            events = self._parse_packet(data)
            for ev in events:
                status, d1, d2 = ev
                self.on_midi_event_cb(status, d1, d2)
        except Exception:
            pass

    def send_led_feedback(self, status: int, note: int, velocity: int):
        """Sends MIDI Note On/Off back to JP-Mini over BLE to light up the hardware RGB pad."""
        self.send_midi_sequence([[status, note, velocity]])

    def send_midi_sequence(self, messages: list):
        """Sends a list of MIDI message byte lists [[status, d1, d2], ...] with spacing."""
        target_char = self._midi_char or (self._writable_chars[0] if self._writable_chars else None)
        if not target_char or not self._loop or not self._loop.is_running() or not messages:
            return
        try:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._async_send_sequence(target_char, messages))
            )
        except Exception:
            pass

    async def _async_send_sequence(self, char_ref, messages: list):
        try:
            from winrt.windows.storage.streams import DataWriter
            from winrt.windows.devices.bluetooth.genericattributeprofile import GattWriteOption

            for msg in messages:
                dw = DataWriter()
                dw.write_byte(0x80)  # BLE MIDI Header Timestamp
                dw.write_byte(0x80)  # BLE MIDI Event Timestamp
                for b in msg:
                    dw.write_byte(b & 0xFF)
                buf = dw.detach_buffer()

                props = char_ref.characteristic_properties
                try:
                    if props & 4:  # WriteWithoutResponse
                        await char_ref.write_value_with_result_async(buf, GattWriteOption.WRITE_WITHOUT_RESPONSE)
                    elif props & 8:  # Write
                        await char_ref.write_value_with_result_async(buf, GattWriteOption.WRITE_WITH_RESPONSE)
                    else:
                        await char_ref.write_value_async(buf)
                except Exception as err:
                    debug_log(f"[BLE WRITE ERR] {err}")
                await asyncio.sleep(0.003)
        except Exception as e:
            debug_log(f"[ASYNC SEND MIDI ERR] {e}")

    def _parse_packet(self, data: bytearray):
        events = []
        if len(data) < 2:
            return events

        i = 1
        last_status = None
        while i < len(data):
            b = data[i]
            # BLE MIDI timestamp skip
            if (b & 0x80) and (i + 1 < len(data)) and (0x80 <= data[i+1] <= 0xFF):
                i += 1
                b = data[i]

            # Real-Time single-byte messages (0xF8..0xFF)
            if b in (0xFA, 0xFB):  # Start / Continue
                events.append((b, 0, 0))
                i += 1
                continue
            elif b == 0xFC:        # Stop
                events.append((b, 0, 0))
                i += 1
                continue
            elif 0xF8 <= b <= 0xFF:
                i += 1
                continue

            if 0x80 <= b <= 0xF7:
                last_status = b
                i += 1
            elif last_status is not None:
                pass
            else:
                i += 1
                continue

            if last_status is None:
                break

            msg_type = last_status & 0xF0
            if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                if i + 1 < len(data):
                    events.append((last_status, data[i], data[i+1]))
                    i += 2
                else:
                    break
            elif last_status == 0xF0:  # SysEx MMC
                # Look for MMC command byte inside SysEx
                sysex_bytes = []
                while i < len(data) and data[i] != 0xF7:
                    sysex_bytes.append(data[i])
                    i += 1
                if i < len(data) and data[i] == 0xF7:
                    i += 1
                # Check for standard MMC: 7F [dev] 06 [cmd]
                if len(sysex_bytes) >= 3 and sysex_bytes[0] == 0x7F and sysex_bytes[2] == 0x06:
                    cmd = sysex_bytes[3] if len(sysex_bytes) > 3 else 0
                    events.append((0xF0, 0x06, cmd))
            else:
                i += 1
        return events


class MidiListener(QObject):
    sig_pad_hit = pyqtSignal(str, int, int)       # (preset, slot_idx, velocity)
    sig_control_hit = pyqtSignal(str)             # (action_name)
    sig_preset_switched = pyqtSignal(str)         # (preset_name)
    sig_status_changed = pyqtSignal(bool, str)    # (is_connected, port_name)
    sig_learn_complete = pyqtSignal(str, int, int)# (preset, pad_idx, note)
    sig_midi_activity = pyqtSignal(str)           # (activity_description_for_ui)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_port_name: Optional[str] = None
        self.inports: List[mido.ports.BaseInput] = []
        self.opened_port_names: List[str] = []
        self.user_preferred_port: Optional[str] = None
        self._port_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self.ble_receiver = DirectBleMidiReceiver(self._on_direct_ble_event, self._on_direct_ble_status)

        # Active Preset: 'preset1' (oneshot) or 'preset2' (track)
        self.active_preset: str = 'preset1'

        self.pad_map: Dict[int, int] = {}
        self.preset1_map: Dict[int, int] = {}
        self.preset2_map: Dict[int, int] = {}
        self._init_default_mappings()

        self.learning_slot: Optional[int] = None
        self.learning_preset: Optional[str] = None

    def _init_default_mappings(self):
        # 16-pad hardware mapping covering standard drum notes across multiple banks:
        # Bank 1 (GM standard 36..51)
        # Bank 2 (52..67)
        # Bank 3 (68..83)
        # Bank 4 (84..99)
        # Octave 2 (48..63)
        # Low range (0..15)
        self.pad_map = {}
        for b_start in (36, 52, 68, 84, 48, 0):
            for i in range(16):
                self.pad_map.setdefault(b_start + i, i)
        self.preset1_map = {}
        self.preset2_map = {}

    def start(self):
        self._running = True
        self.ble_receiver.start()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.ble_receiver.stop()
        with self._port_lock:
            for inp in self.inports:
                try:
                    inp.close()
                except Exception:
                    pass
            self.inports.clear()
            self.opened_port_names.clear()

    def get_available_ports(self) -> List[str]:
        ports = []
        if self.ble_receiver.is_connected:
            ports.append(self.ble_receiver.device_name)
        else:
            ports.append("Bluetooth JP-Mini (Поиск...)")
        try:
            for p in mido.get_input_names():
                usb_p = f"USB: {p}"
                if usb_p not in ports:
                    ports.append(usb_p)
        except Exception:
            pass
        return ports

    def force_reconnect(self):
        threading.Thread(target=self._do_force_reconnect, daemon=True).start()

    def _do_force_reconnect(self):
        self._refresh_usb_ports(force=True)
        self.ble_receiver._disconnect_cleanup()

    @staticmethod
    def _select_primary_endpoint(available: List[str]) -> Optional[str]:
        if not available:
            return None

        # 1. Prefer primary endpoint 'JP-Mini 0' (or endpoint ending with ' 0')
        for p in available:
            low = p.lower()
            if 'jp-mini' in low and ('jp-mini 0' in low or ' 0' in low):
                return p

        # 2. Fallback to any JP-Mini endpoint (single primary)
        for p in available:
            if 'jp-mini' in p.lower():
                return p

        # 3. Known virtual / hardware MIDI devices
        for p in available:
            if any(k in p.lower() for k in ('midi-01', 'loopmidi')):
                return p

        # 4. Fallback to the first matching device
        return available[0]

    def _refresh_usb_ports(self, force: bool = False):
        try:
            available = mido.get_input_names()
        except Exception:
            available = []

        if not available:
            with self._port_lock:
                for inp in self.inports:
                    try:
                        inp.close()
                    except Exception:
                        pass
                self.inports.clear()
                self.opened_port_names.clear()
                self.current_port_name = None
            if not self.ble_receiver.is_connected:
                self.sig_status_changed.emit(False, "USB/BLE: Поиск устройства...")
            return

        target_port = None
        if self.user_preferred_port and self.user_preferred_port in available:
            target_port = self.user_preferred_port
        else:
            # Auto-detect single primary endpoint
            target_port = self._select_primary_endpoint(available)

        with self._port_lock:
            # If target_port is already successfully opened and no force, do nothing
            if not force and target_port and self.opened_port_names == [target_port] and len(self.inports) == 1:
                return

            # Close obsolete or dead ports
            for inp in self.inports:
                try:
                    inp.close()
                except Exception:
                    pass
            self.inports.clear()
            self.opened_port_names.clear()

            # Open ONLY the single primary endpoint to prevent driver deadlock
            if target_port:
                try:
                    inp = mido.open_input(target_port)
                    self.inports.append(inp)
                    self.opened_port_names.append(target_port)
                except Exception:
                    pass

            if self.inports:
                main_name = f"USB: {self.opened_port_names[0]}"
                self.current_port_name = main_name
                if not self.ble_receiver.is_connected:
                    self.sig_status_changed.emit(True, main_name)
            else:
                if not self.ble_receiver.is_connected:
                    self.current_port_name = None
                    self.sig_status_changed.emit(False, "USB/BLE: Поиск устройства...")

    def _run_loop(self):
        last_check = 0.0
        while self._running:
            now = time.time()
            if now - last_check > 2.0:
                last_check = now
                self._refresh_usb_ports()

            with self._port_lock:
                active_inports = list(self.inports)

            if not active_inports:
                time.sleep(0.3)
                continue

            for inp in active_inports:
                try:
                    for msg in inp.iter_pending():
                        self._handle_mido_message(msg)
                except Exception:
                    with self._port_lock:
                        try:
                            inp.close()
                        except Exception:
                            pass
                        if inp in self.inports:
                            self.inports.remove(inp)
                        if inp.name in self.opened_port_names:
                            self.opened_port_names.remove(inp.name)
                    last_check = 0.0
            time.sleep(0.002)

    def _on_direct_ble_status(self, is_connected: bool, name: str):
        if is_connected:
            self.current_port_name = name
            self.sig_status_changed.emit(True, name)
            self.update_hardware_leds()
        else:
            if self.inports and self.current_port_name and "USB:" in self.current_port_name:
                self.sig_status_changed.emit(True, self.current_port_name)
            else:
                self.current_port_name = None
                self.sig_status_changed.emit(False, name)

    def _on_direct_ble_event(self, status: int, d1: int, d2: int):
        debug_log(f"[BLE RAW] status=0x{status:02X}, d1={d1} (0x{d1:02X}), d2={d2}")
        # 1. Real-Time Transport messages
        if status in (0xFA, 0xFB):
            debug_log("[BLE] Real-Time START -> track_play_pause")
            self.sig_midi_activity.emit("▶ PLAY / PAUSE")
            self.sig_control_hit.emit('track_play_pause')
            return
        if status == 0xFC:
            debug_log("[BLE] Real-Time STOP -> stop_oneshots")
            self.sig_midi_activity.emit("⏹ СТОП ВАНШОТЫ")
            self.sig_control_hit.emit('stop_oneshots')
            return
        if status == 0xF0 and d1 == 0x06:  # MMC
            if d2 in (0x02, 0x09):
                debug_log("[BLE] MMC PLAY -> track_play_pause")
                self.sig_midi_activity.emit("▶ PLAY / PAUSE")
                self.sig_control_hit.emit('track_play_pause')
            elif d2 == 0x01:
                debug_log("[BLE] MMC STOP -> stop_oneshots")
                self.sig_midi_activity.emit("⏹ СТОП ВАНШОТЫ")
                self.sig_control_hit.emit('stop_oneshots')
            elif d2 == 0x06:
                debug_log("[BLE] MMC REC -> toggle_preset")
                self.sig_midi_activity.emit("⏺ ПРЕСЕТ")
                self.sig_control_hit.emit('toggle_preset')
            return

        msg_type = status & 0xF0
        # 2. Check Control Change (CC) for top transport buttons
        if msg_type == 0xB0:
            cc_num = d1
            val = d2
            debug_log(f"[BLE CC] CC={cc_num}, Val={val}")
            if cc_num in TRANSPORT_CC_MAP and val > 0:
                action = TRANSPORT_CC_MAP[cc_num]
                debug_log(f"[BLE CC] -> action={action}")
                label = "▶ PLAY / PAUSE" if action == 'track_play_pause' else ("⏹ СТОП ВАНШОТЫ" if action == 'stop_oneshots' else "⏺ ПРЕСЕТ")
                self.sig_midi_activity.emit(label)
                self.sig_control_hit.emit(action)
                return

        # 3. Check Note On / Note Off
        if msg_type == 0x90:
            note = d1
            velocity = d2
            # Hardware LED Feedback
            if velocity > 0:
                self.ble_receiver.send_led_feedback(status, note, 127)
            else:
                pad_idx = self.pad_map.get(note, 0)
                col = self._get_pad_default_color(pad_idx)
                self.ble_receiver.send_led_feedback(0x90 | (status & 0x0F), note, col)

            if velocity == 0:
                return

            # Check top transport buttons if sent as notes
            if note in TRANSPORT_NOTE_MAP:
                action = TRANSPORT_NOTE_MAP[note]
                debug_log(f"[BLE NOTE] Transport Note {note} -> {action}")
                label = "▶ PLAY / PAUSE" if action == 'track_play_pause' else ("⏹ СТОП ВАНШОТЫ" if action == 'stop_oneshots' else "⏺ ПРЕСЕТ")
                self.sig_midi_activity.emit(label)
                self.sig_control_hit.emit(action)
                return

            self._dispatch_note_press(note, velocity)

        elif msg_type == 0x80:
            note = d1
            pad_idx = self.pad_map.get(note, 0)
            col = self._get_pad_default_color(pad_idx)
            self.ble_receiver.send_led_feedback(0x90 | (status & 0x0F), note, col)

    def _handle_mido_message(self, msg: mido.Message):
        debug_log(f"[USB RAW] {msg}")
        if msg.type in ('start', 'continue'):
            self.sig_midi_activity.emit("▶ PLAY / PAUSE")
            self.sig_control_hit.emit('track_play_pause')
            return
        if msg.type == 'stop':
            self.sig_midi_activity.emit("⏹ СТОП ВАНШОТЫ")
            self.sig_control_hit.emit('stop_oneshots')
            return

        if msg.type == 'control_change' and msg.value > 0:
            if msg.control in TRANSPORT_CC_MAP:
                action = TRANSPORT_CC_MAP[msg.control]
                debug_log(f"[USB CC] CC={msg.control} -> {action}")
                label = "▶ PLAY / PAUSE" if action == 'track_play_pause' else ("⏹ СТОП ВАНШОТЫ" if action == 'stop_oneshots' else "⏺ ПРЕСЕТ")
                self.sig_midi_activity.emit(label)
                self.sig_control_hit.emit(action)
                return

        if msg.type not in ('note_on', 'note_off'):
            return

        is_press = (msg.type == 'note_on' and msg.velocity > 0)
        if not is_press:
            return

        if msg.note in TRANSPORT_NOTE_MAP:
            action = TRANSPORT_NOTE_MAP[msg.note]
            debug_log(f"[USB NOTE] Transport Note {msg.note} -> {action}")
            label = "▶ PLAY / PAUSE" if action == 'track_play_pause' else ("⏹ СТОП ВАНШОТЫ" if action == 'stop_oneshots' else "⏺ ПРЕСЕТ")
            self.sig_midi_activity.emit(label)
            self.sig_control_hit.emit(action)
            return

        self._dispatch_note_press(msg.note, msg.velocity)

    _handle_message = _handle_mido_message

    def _dispatch_note_press(self, note: int, velocity: int):
        debug_log(f"[NOTE PRESS] note={note}, vel={velocity}, preset={self.active_preset}")
        if self.learning_slot is not None and self.learning_preset is not None:
            pad_idx = self.learning_slot
            preset = self.learning_preset
            if preset == 'preset1':
                self.preset1_map[note] = pad_idx
            else:
                self.preset2_map[note] = pad_idx
            learned_slot = self.learning_slot
            learned_preset = self.learning_preset
            self.learning_slot = None
            self.learning_preset = None
            debug_log(f"[LEARN COMPLETE] preset={learned_preset}, slot={learned_slot}, note={note}")
            self.sig_midi_activity.emit(f"✓ Привязана нота {note} к PAD {learned_slot + 1}")
            self.sig_learn_complete.emit(learned_preset, learned_slot, note)
            return

        # Check custom learned map for active preset first
        custom_map = self.preset1_map if self.active_preset == 'preset1' else self.preset2_map
        pad_idx = custom_map.get(note)

        # Hardware Bank Routing based on JP-Mini banks:
        # 1) Bank 1: Blue / Cyan (notes 36..51) -> PRESET 1: ONE-SHOTS
        if 36 <= note <= 51:
            if self.active_preset != 'preset1':
                debug_log(f"[BANK SYNC] 🔵 Голубой банк (нота {note}) -> Пресет 1 (Ваншоты)")
                self.set_active_preset('preset1')
            if pad_idx is None:
                pad_idx = note - 36

        # 2) Bank 2: Red (notes 52..67) -> PRESET 2: TRACKS
        elif 52 <= note <= 67:
            if self.active_preset != 'preset2':
                debug_log(f"[BANK SYNC] 🔴 Красный банк (нота {note}) -> Пресет 2 (Треки)")
                self.set_active_preset('preset2')
            if pad_idx is None:
                pad_idx = note - 52

        # 3) Bank 3: Green (notes 68..83) -> ПУСТОЙ (Резерв)
        elif 68 <= note <= 83:
            pad_idx = note - 68
            hw_num = pad_idx + 1
            debug_log(f"[BANK SYNC] 🟢 Зелёный банк (нота {note}) -> Пустой банк")
            self.sig_midi_activity.emit(f"🟢 Зелёный банк: PAD {hw_num} (Пустой)")
            # Green bank is intentionally unassigned / silent
            return

        # 4) Any other notes
        else:
            if pad_idx is None:
                debug_log(f"[UNMAPPED NOTE] note={note}")
                self.sig_midi_activity.emit(f"Нота {note} (не назначена)")
                return

        hw_num = pad_idx + 1
        debug_log(f"[DISPATCH] note={note} -> pad_idx={pad_idx} (PAD {hw_num}), preset={self.active_preset}")

        # Right column controls (Volume UP/DOWN)
        if pad_idx in CONTROL_PAD_MAP:
            action = CONTROL_PAD_MAP[pad_idx]
            self.sig_midi_activity.emit(f"PAD {hw_num} ({action})")
            self.sig_control_hit.emit(action)
            return

        # Sound pads (0..11)
        if pad_idx in PAD_TO_SLOT:
            slot_idx = PAD_TO_SLOT[pad_idx]
            tag = "🔵 Ваншот" if self.active_preset == 'preset1' else "🔴 Трек"
            self.sig_midi_activity.emit(f"{tag}: PAD {hw_num} (Vel {velocity})")
            self.sig_pad_hit.emit(self.active_preset, slot_idx, velocity)

    def set_active_preset(self, preset: str):
        if self.active_preset != preset:
            self.active_preset = preset
            self.sig_preset_switched.emit(preset)
        self.update_hardware_leds()

    def toggle_preset(self):
        new_preset = 'preset2' if self.active_preset == 'preset1' else 'preset1'
        self.set_active_preset(new_preset)

    def update_hardware_leds(self):
        debug_log(f"[UPDATE HARDWARE LEDS] active_preset={self.active_preset}")
        msgs = []
        # 1. Program Change to sync hardware bank
        prog = 0 if self.active_preset == 'preset1' else 1
        msgs.append([0xC9, prog])
        msgs.append([0xC0, prog])

        # 2. Update colors on Bank 1 (36..51) and Bank 2 (52..67)
        for bank_base in (36, 52):
            for i in range(16):
                note = bank_base + i
                pad_idx = i
                col = self._get_pad_default_color(pad_idx)
                msgs.append([0x99, note, col])
                msgs.append([0x90, note, col])

        self.ble_receiver.send_midi_sequence(msgs)

    def _get_pad_default_color(self, pad_idx: int) -> int:
        if pad_idx in (15, 11):      # Track Volume UP / DOWN
            return 21  # Green
        elif pad_idx in (7, 3):      # One-Shot Volume UP / DOWN
            return 37  # Cyan (голубой)
        else:                        # Sound pads (0..11)
            # Preset 1 (One-Shots) = Cyan (37 - голубой); Preset 2 (Tracks) = Green (21 - зеленый)
            return 37 if self.active_preset == 'preset1' else 21

    def start_learn(self, preset: str, pad_idx: int):
        self.learning_preset = preset
        self.learning_slot = pad_idx

    def cancel_learn(self):
        self.learning_slot = None
        self.learning_preset = None

    def switch_port(self, port_name: str):
        threading.Thread(target=self._do_switch_port, args=(port_name,), daemon=True).start()

    def _do_switch_port(self, port_name: str):
        if "Bluetooth" in port_name:
            with self._port_lock:
                self.user_preferred_port = None
                for inp in self.inports:
                    try:
                        inp.close()
                    except Exception:
                        pass
                self.inports.clear()
                self.opened_port_names.clear()
            self.ble_receiver._disconnect_cleanup()
        else:
            clean_name = port_name.replace("USB: ", "").strip()
            self.user_preferred_port = clean_name
            with self._port_lock:
                for inp in self.inports:
                    try:
                        inp.close()
                    except Exception:
                        pass
                self.inports.clear()
                self.opened_port_names.clear()
                try:
                    inp = mido.open_input(clean_name)
                    self.inports.append(inp)
                    self.opened_port_names.append(clean_name)
                    self.current_port_name = f"USB: {clean_name}"
                    self.sig_status_changed.emit(True, self.current_port_name)
                except Exception:
                    self.sig_status_changed.emit(False, f"Ошибка {clean_name}")
