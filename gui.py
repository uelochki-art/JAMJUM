"""
GUI for Gussy / JAMJUM Pad Launcher.
PyQt5 modern dark neon interface with:
- 4x4 matrix with real-time pad feedback & Drag-and-Drop
- Audio Trimming dialog ("✂") with waveform selection and preview
- Named presets management (e.g. "Основной", "Новый год", "День рождения")
- Dedicated right-column controls:
    Pad 16 (Row 0): ТРЕКИ ГРОМК +
    Pad 12 (Row 1): ТРЕКИ ГРОМК -
    Pad 8  (Row 2): ВАНШОТЫ ГРОМК +
    Pad 4  (Row 3): ВАНШОТЫ ГРОМК -
- Top transport controls:
    ▶/⏸ (Play/Pause): Длинные треки
    ⏹ (Stop): Стоп ваншотов
    ⏺ (Record): Mute All
- Dual independent volume controls (Треки / Ваншоты) + Step setting
- Direct Bluetooth LE / USB MIDI indicator
- Minimization to Windows System Tray
"""

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSlider, QSpinBox, QFileDialog, QTabWidget,
    QFrame, QMessageBox, QComboBox, QInputDialog, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

from audio_engine import AudioEngine
from midi_listener import MidiListener, CONTROL_PAD_MAP, SOUND_PADS_ORDER, PAD_TO_SLOT
from config_manager import ConfigManager
from tray_manager import TrayManager, create_default_icon
from audio_trimmer import AudioTrimmerDialog


HW_PAD_NUMBERS = [1, 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15]


class PadButton(QFrame):
    """Visual pad widget supporting Drag & Drop, MIDI trigger animation, and Trimming."""
    file_dropped = pyqtSignal(int, str)
    browse_clicked = pyqtSignal(int)
    trim_clicked = pyqtSignal(int)
    clear_clicked = pyqtSignal(int)
    learn_clicked = pyqtSignal(int)
    pad_clicked = pyqtSignal(int)

    def __init__(self, slot_idx: int, is_track: bool = False, parent=None):
        super().__init__(parent)
        self.slot_idx = slot_idx
        self.is_track = is_track
        self.file_path = ""
        self.is_active_playing = False
        self.is_paused = False
        self.is_learning = False

        self.setAcceptDrops(True)
        self.setMinimumSize(115, 95)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("PadButton")
        self._init_ui()
        self.update_style()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        # Header row: Pad number matching hardware (PAD 1..16) + actions
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(3)

        hw_num = HW_PAD_NUMBERS[self.slot_idx] if self.slot_idx < len(HW_PAD_NUMBERS) else self.slot_idx + 1
        self.lbl_num = QLabel(f"PAD {hw_num}")
        self.lbl_num.setStyleSheet("font-weight: 900; font-size: 11px; color: #7e8fa6;")
        top_row.addWidget(self.lbl_num)

        top_row.addStretch()

        # Trim Button ✂
        self.btn_trim = QPushButton("✂")
        self.btn_trim.setToolTip("Обрезать / выбрать фрагмент")
        self.btn_trim.setFixedSize(18, 18)
        self.btn_trim.setStyleSheet("""
            QPushButton {
                background: #1a233a; color: #00ffff; border: 1px solid #00ffff;
                border-radius: 9px; font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { background: #00ffff; color: #070913; }
        """)
        self.btn_trim.clicked.connect(lambda: self.trim_clicked.emit(self.slot_idx))
        top_row.addWidget(self.btn_trim)

        # MIDI Learn Button
        self.btn_learn = QPushButton("L")
        self.btn_learn.setToolTip("MIDI Learn (привязать ноту)")
        self.btn_learn.setFixedSize(18, 18)
        self.btn_learn.setStyleSheet("""
            QPushButton {
                background: #1a233a; color: #ffd700; border: 1px solid #ffd700;
                border-radius: 9px; font-size: 9px; font-weight: bold;
            }
            QPushButton:hover { background: #ffd700; color: #070913; }
        """)
        self.btn_learn.clicked.connect(lambda: self.learn_clicked.emit(self.slot_idx))
        top_row.addWidget(self.btn_learn)

        # Browse Button
        self.btn_browse = QPushButton("...")
        self.btn_browse.setToolTip("Выбрать файл")
        self.btn_browse.setFixedSize(18, 18)
        self.btn_browse.setStyleSheet("""
            QPushButton {
                background: #1a233a; color: #39ff14; border: 1px solid #39ff14;
                border-radius: 9px; font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { background: #39ff14; color: #070913; }
        """)
        self.btn_browse.clicked.connect(lambda: self.browse_clicked.emit(self.slot_idx))
        top_row.addWidget(self.btn_browse)

        # Clear Button
        self.btn_clear = QPushButton("✕")
        self.btn_clear.setToolTip("Очистить слот")
        self.btn_clear.setFixedSize(18, 18)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background: #1a233a; color: #ff007f; border: 1px solid #ff007f;
                border-radius: 9px; font-size: 9px; font-weight: bold;
            }
            QPushButton:hover { background: #ff007f; color: #ffffff; }
        """)
        self.btn_clear.clicked.connect(lambda: self.clear_clicked.emit(self.slot_idx))
        top_row.addWidget(self.btn_clear)

        layout.addLayout(top_row)

        # File name label (Ignored horizontal size policy prevents label text from widening pad column)
        self.lbl_name = QLabel("Перетащите файл сюда")
        self.lbl_name.setAlignment(Qt.AlignCenter)
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_name.setStyleSheet("font-size: 11px; color: #7e8fa6; padding: 2px;")
        layout.addWidget(self.lbl_name, 1)

    def set_file(self, path: str):
        self.file_path = path
        if path:
            base = os.path.basename(path)
            name, ext = os.path.splitext(base)
            if len(name) > 14:
                display_name = f"{name[:8]}..{name[-4:]}{ext}"
            else:
                display_name = base
            self.lbl_name.setText(display_name)
            self.lbl_name.setStyleSheet("font-size: 11px; font-weight: bold; color: #f0f4fc;")
            self.setToolTip(f"{base}\n{path}")
        else:
            self.lbl_name.setText("Перетащите файл сюда")
            self.lbl_name.setStyleSheet("font-size: 10px; color: #7e8fa6;")
            self.setToolTip("")
        self.update_style()

    def flash_trigger(self):
        accent = "#00ffff" if not self.is_track else "#39ff14"
        self.setStyleSheet(f"""
            QFrame#PadButton {{
                background-color: {accent};
                border: 2px solid #ffffff;
                border-radius: 8px;
            }}
        """)
        self.lbl_name.setStyleSheet("color: #070913; font-weight: bold;")
        QTimer.singleShot(150, self.update_style)

    def set_playing(self, is_playing: bool, is_paused: bool = False):
        self.is_active_playing = is_playing
        self.is_paused = is_paused
        self.update_style()

    def set_learning(self, is_learning: bool):
        self.is_learning = is_learning
        self.update_style()

    def update_style(self):
        if self.is_learning:
            border = "2px dashed #ffd700"
            bg = "#332a00"
            text_color = "#ffd700"
        elif self.is_active_playing:
            border = "2px solid #39ff14"
            bg = "#103518" if not self.is_paused else "#332d00"
            text_color = "#39ff14" if not self.is_paused else "#ffd700"
        elif bool(self.file_path):
            border = "1px solid rgba(0, 255, 255, 0.45)" if not self.is_track else "1px solid rgba(57, 255, 20, 0.45)"
            bg = "#141c33"
            text_color = "#f0f4fc"
        else:
            border = "1px dashed rgba(255, 255, 255, 0.15)"
            bg = "#0f1424"
            text_color = "#7e8fa6"

        self.setStyleSheet(f"""
            QFrame#PadButton {{
                background-color: {bg};
                border: {border};
                border-radius: 8px;
            }}
            QFrame#PadButton:hover {{
                border-color: #00ffff;
            }}
        """)
        if self.file_path:
            self.lbl_name.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {text_color};")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pad_clicked.emit(self.slot_idx)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ('.wav', '.mp3', '.ogg', '.flac', '.aiff'):
                self.file_dropped.emit(self.slot_idx, file_path)
                event.acceptProposedAction()
                break


class ControlButton(QFrame):
    """Right-column dedicated control pad widget."""
    triggered = pyqtSignal()

    def __init__(self, action_id: str, title: str, subtitle: str, color: str, parent=None):
        super().__init__(parent)
        self.action_id = action_id
        self.title_text = title
        self.subtitle_text = subtitle
        self.base_color = color
        self.setMinimumSize(115, 95)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setObjectName("ControlButton")
        self._init_ui()
        self.update_style()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setAlignment(Qt.AlignCenter)

        self.lbl_title = QLabel(self.title_text)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: 900;")
        layout.addWidget(self.lbl_title)

        self.lbl_sub = QLabel(self.subtitle_text)
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setStyleSheet("font-size: 11px; font-weight: bold;")
        layout.addWidget(self.lbl_sub)

    def set_sub_text(self, text: str):
        self.lbl_sub.setText(text)

    def flash_trigger(self):
        self.setStyleSheet(f"""
            QFrame#ControlButton {{
                background-color: {self.base_color};
                border: 2px solid #ffffff;
                border-radius: 8px;
            }}
        """)
        self.lbl_title.setStyleSheet("color: #070913; font-weight: 900; font-size: 13px;")
        self.lbl_sub.setStyleSheet("color: #070913; font-weight: bold; font-size: 11px;")
        QTimer.singleShot(150, self.update_style)

    def update_style(self):
        self.setStyleSheet(f"""
            QFrame#ControlButton {{
                background-color: #1a162b;
                border: 2px solid {self.base_color};
                border-radius: 8px;
            }}
            QFrame#ControlButton:hover {{
                background-color: #26203d;
            }}
        """)
        self.lbl_title.setStyleSheet(f"color: {self.base_color}; font-size: 13px; font-weight: 900;")
        self.lbl_sub.setStyleSheet("color: #f0f4fc; font-size: 11px; font-weight: bold;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.triggered.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, audio_engine: AudioEngine, midi_listener: MidiListener, config_manager: ConfigManager):
        super().__init__()
        self.audio = audio_engine
        self.midi = midi_listener
        self.cfg = config_manager

        self.setWindowTitle("JAMJUM Pad Launcher — Bluetooth LE MIDI")
        self.setWindowIcon(create_default_icon())
        self.resize(800, 720)

        # Tray manager
        self.tray = TrayManager(self)
        self.tray.restore_requested.connect(self.restore_window)
        self.tray.panic_requested.connect(self.audio.stop_all)
        self.tray.exit_requested.connect(self._force_exit)

        # Pad widgets lists: 12 pads each
        self.oneshot_pads = []
        self.track_pads = []

        # Right column controls references
        self.btn_track_vol_up = None
        self.btn_track_vol_down = None
        self.btn_oneshot_vol_up = None
        self.btn_oneshot_vol_down = None

        self._init_ui()
        self._load_saved_files()
        self._setup_callbacks()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # Global stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #070913;
            }
            QLabel {
                color: #f0f4fc;
                font-family: 'Segoe UI', Montserrat, sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid rgba(0, 255, 255, 0.2);
                background: #0f1424;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #141c33;
                color: #7e8fa6;
                padding: 9px 24px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: bold;
                font-size: 12px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #0f1424;
                color: #00ffff;
                border-bottom: 2px solid #00ffff;
            }
        """)

        # ==========================
        # 1. Header Bar: Title, Device Status, Port selector
        # ==========================
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("JAMJUM PAD LAUNCHER")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 900; color: #00ffff; letter-spacing: 1px;")
        lbl_sub = QLabel("Native Bluetooth LE MIDI • One-Shot & Backing Track Engine")
        lbl_sub.setStyleSheet("font-size: 11px; color: #7e8fa6;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box)

        header.addStretch()

        # Status badge
        self.lbl_status = QLabel("● Поиск BLE...")
        self.lbl_status.setStyleSheet("""
            QLabel {
                background: #141c33; color: #ffd700; border: 1px solid #ffd700;
                border-radius: 12px; padding: 5px 12px; font-weight: bold; font-size: 11px;
            }
        """)
        header.addWidget(self.lbl_status)

        # Live MIDI activity pill
        self.lbl_midi_activity = QLabel("● MIDI готов")
        self.lbl_midi_activity.setStyleSheet("""
            QLabel {
                background: #101726; color: #7e8fa6; border: 1px solid #23314d;
                border-radius: 12px; padding: 5px 12px; font-weight: bold; font-size: 11px;
            }
        """)
        header.addWidget(self.lbl_midi_activity)

        # Port Selector combo box
        self.combo_ports = QComboBox()
        self.combo_ports.setStyleSheet("""
            QComboBox {
                background: #141c33; color: #f0f4fc; border: 1px solid #00ffff;
                border-radius: 6px; padding: 4px 10px; font-weight: bold; font-size: 11px; min-width: 140px;
            }
            QComboBox QAbstractItemView {
                background: #0f1424; color: #f0f4fc; selection-background-color: #1a233a;
                selection-color: #00ffff; border: 1px solid #00ffff;
            }
        """)
        self._refresh_ports_list()
        self.combo_ports.activated.connect(self._on_port_selected)
        header.addWidget(self.combo_ports)

        btn_refresh_ports = QPushButton("🔄")
        btn_refresh_ports.setToolTip("Обновить список подключений и переподключиться")
        btn_refresh_ports.setFixedSize(26, 26)
        btn_refresh_ports.setStyleSheet("""
            QPushButton {
                background: #1a233a; color: #00ffff; border: 1px solid #00ffff;
                border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background: #00ffff; color: #070913; }
        """)
        btn_refresh_ports.clicked.connect(self._on_refresh_clicked)
        header.addWidget(btn_refresh_ports)

        main_layout.addLayout(header)

        # ==========================
        # 2. Preset Management Bar (e.g. Новый Год, День Рождения)
        # ==========================
        preset_bar = QHBoxLayout()
        preset_bar.setContentsMargins(0, 0, 0, 0)
        preset_bar.setSpacing(8)

        lbl_preset = QLabel("📁 Набор сэмплов (Пресет):")
        lbl_preset.setStyleSheet("font-weight: bold; font-size: 12px; color: #f0f4fc;")
        preset_bar.addWidget(lbl_preset)

        self.combo_presets = QComboBox()
        self.combo_presets.setStyleSheet("""
            QComboBox {
                background: #141c33; color: #00ffff; border: 1px solid #00ffff;
                border-radius: 6px; padding: 4px 12px; font-weight: bold; font-size: 12px; min-width: 170px;
            }
            QComboBox QAbstractItemView {
                background: #0f1424; color: #f0f4fc; selection-background-color: #1a233a;
                selection-color: #00ffff; border: 1px solid #00ffff;
            }
        """)
        self._populate_presets_combo()
        self.combo_presets.currentTextChanged.connect(self._on_preset_selected)
        preset_bar.addWidget(self.combo_presets)

        btn_new_preset = QPushButton("➕ Новый набор")
        btn_new_preset.setStyleSheet("""
            QPushButton {
                background: #141c33; color: #39ff14; border: 1px solid #39ff14;
                border-radius: 6px; padding: 4px 10px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #39ff14; color: #070913; }
        """)
        btn_new_preset.clicked.connect(self._on_new_preset_clicked)
        preset_bar.addWidget(btn_new_preset)

        btn_del_preset = QPushButton("🗑 Удалить")
        btn_del_preset.setStyleSheet("""
            QPushButton {
                background: #141c33; color: #ff007f; border: 1px solid #ff007f;
                border-radius: 6px; padding: 4px 10px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #ff007f; color: #ffffff; }
        """)
        btn_del_preset.clicked.connect(self._on_delete_preset_clicked)
        preset_bar.addWidget(btn_del_preset)

        preset_bar.addStretch()

        # Top Buttons Hardware Hints
        lbl_hints = QLabel("Контроллер: ▶/⏸ Трек | ⏹ Стоп ваншоты | PAD BANK: 🔵 Ваншоты | 🔴 Треки | 🟢 Пустой")
        lbl_hints.setStyleSheet("font-size: 11px; color: #ffd700; font-weight: bold;")
        preset_bar.addWidget(lbl_hints)

        main_layout.addLayout(preset_bar)

        # ==========================
        # 3. Tabs: Left = PRESET 1: ONE-SHOTS, Right = PRESET 2: TRACKS
        # ==========================
        self.tabs = QTabWidget()
        tab_oneshot = QWidget()
        tab_track = QWidget()

        tab_oneshot.setLayout(self._create_pad_grid_layout(is_track=False))
        tab_track.setLayout(self._create_pad_grid_layout(is_track=True))

        self.tabs.addTab(tab_oneshot, "PRESET 1: ONE-SHOTS")
        self.tabs.addTab(tab_track, "PRESET 2: TRACKS")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tabs, 1)

        # ==========================
        # 4. Master Controls & Tray Bar
        # ==========================
        bottom_bar = QVBoxLayout()
        bottom_bar.setContentsMargins(4, 4, 4, 4)
        bottom_bar.setSpacing(6)

        # Volumes row (Dual independent sliders)
        vols_row = QHBoxLayout()
        vols_row.setSpacing(12)

        # 1) Track Volume
        lbl_tvol = QLabel("Громкость Треков:")
        lbl_tvol.setStyleSheet("font-weight: bold; color: #39ff14; font-size: 11px;")
        vols_row.addWidget(lbl_tvol)

        self.slider_track_vol = QSlider(Qt.Horizontal)
        self.slider_track_vol.setRange(0, 100)
        self.slider_track_vol.setValue(int(self.audio.track_volume * 100))
        self.slider_track_vol.setStyleSheet("""
            QSlider::groove:horizontal { height: 6px; background: #141c33; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #39ff14; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ffffff; width: 14px; margin-top: -4px; margin-bottom: -4px; border-radius: 7px; }
        """)
        self.slider_track_vol.valueChanged.connect(self._on_track_vol_slider_changed)
        vols_row.addWidget(self.slider_track_vol, 1)

        self.lbl_tvol_val = QLabel(f"{int(self.audio.track_volume * 100)}%")
        self.lbl_tvol_val.setFixedWidth(36)
        self.lbl_tvol_val.setStyleSheet("font-weight: bold; color: #39ff14;")
        vols_row.addWidget(self.lbl_tvol_val)

        vols_row.addSpacing(10)

        # 2) One-Shot Volume
        lbl_osvol = QLabel("Громкость Ваншотов:")
        lbl_osvol.setStyleSheet("font-weight: bold; color: #00ffff; font-size: 11px;")
        vols_row.addWidget(lbl_osvol)

        self.slider_oneshot_vol = QSlider(Qt.Horizontal)
        self.slider_oneshot_vol.setRange(0, 100)
        self.slider_oneshot_vol.setValue(int(self.audio.oneshot_volume * 100))
        self.slider_oneshot_vol.setStyleSheet("""
            QSlider::groove:horizontal { height: 6px; background: #141c33; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #00ffff; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ffffff; width: 14px; margin-top: -4px; margin-bottom: -4px; border-radius: 7px; }
        """)
        self.slider_oneshot_vol.valueChanged.connect(self._on_oneshot_vol_slider_changed)
        vols_row.addWidget(self.slider_oneshot_vol, 1)

        self.lbl_osvol_val = QLabel(f"{int(self.audio.oneshot_volume * 100)}%")
        self.lbl_osvol_val.setFixedWidth(36)
        self.lbl_osvol_val.setStyleSheet("font-weight: bold; color: #00ffff;")
        vols_row.addWidget(self.lbl_osvol_val)

        # Step
        vols_row.addSpacing(10)
        lbl_step = QLabel("Шаг +/-:")
        lbl_step.setStyleSheet("color: #7e8fa6; font-size: 11px;")
        vols_row.addWidget(lbl_step)

        self.spin_step = QSpinBox()
        self.spin_step.setRange(1, 25)
        self.spin_step.setValue(int(self.audio.volume_step * 100))
        self.spin_step.setSuffix("%")
        self.spin_step.setStyleSheet("""
            QSpinBox {
                background: #141c33; color: #f0f4fc; border: 1px solid #7e8fa6;
                border-radius: 4px; padding: 2px 4px; font-weight: bold;
            }
        """)
        self.spin_step.valueChanged.connect(self._on_step_changed)
        vols_row.addWidget(self.spin_step)

        bottom_bar.addLayout(vols_row)

        # Buttons row
        action_row = QHBoxLayout()

        # Stop One-Shots button (⏹)
        self.btn_stop_os = QPushButton("⏹ Стоп ваншоты")
        self.btn_stop_os.setStyleSheet("""
            QPushButton {
                background: #1f1b2b; color: #00ffff; border: 1px solid #00ffff;
                border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #00ffff; color: #070913; }
        """)
        self.btn_stop_os.clicked.connect(self.audio.stop_oneshots)
        action_row.addWidget(self.btn_stop_os)

        # Track Play/Pause button (▶/⏸)
        self.btn_play_pause_track = QPushButton("▶/⏸ Трек")
        self.btn_play_pause_track.setStyleSheet("""
            QPushButton {
                background: #103518; color: #39ff14; border: 1px solid #39ff14;
                border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #39ff14; color: #070913; }
        """)
        self.btn_play_pause_track.clicked.connect(self.audio.toggle_play_pause_track)
        action_row.addWidget(self.btn_play_pause_track)

        # Mute All button (⏺)
        self.btn_mute_toggle = QPushButton("🔇 Mute All")
        self.btn_mute_toggle.setStyleSheet("""
            QPushButton {
                background: #2b121d; color: #ff007f; border: 1px solid #ff007f;
                border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #ff007f; color: #ffffff; }
        """)
        self.btn_mute_toggle.clicked.connect(self.audio.toggle_mute)
        action_row.addWidget(self.btn_mute_toggle)

        # Panic Button
        btn_panic = QPushButton("⏹ Стоп всё")
        btn_panic.setStyleSheet("""
            QPushButton {
                background: #3a1111; color: #ff4444; border: 1px solid #ff4444;
                border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #ff4444; color: #ffffff; }
        """)
        btn_panic.clicked.connect(self.audio.stop_all)
        action_row.addWidget(btn_panic)

        action_row.addStretch()

        # Minimize to Tray Button
        btn_tray = QPushButton(" Свернуть в трей")
        btn_tray.setStyleSheet("""
            QPushButton {
                background: #141c33; color: #00ffff; border: 1px solid #00ffff;
                border-radius: 6px; padding: 6px 16px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #00ffff; color: #070913; }
        """)
        btn_tray.clicked.connect(self.hide_to_tray)
        action_row.addWidget(btn_tray)

        bottom_bar.addLayout(action_row)
        main_layout.addLayout(bottom_bar)

    def _create_pad_grid_layout(self, is_track: bool) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.setContentsMargins(10, 10, 10, 10)

        pads_list = self.track_pads if is_track else self.oneshot_pads

        # Arrange 12 sound pads:
        # Row 0: P9,  P10, P11
        # Row 1: P6,  P7,  P8
        # Row 2: P3,  P4,  P5
        # Row 3: P0,  P1,  P2
        row_pad_indices = [
            (0, [9, 10, 11]),
            (1, [6, 7, 8]),
            (2, [3, 4, 5]),
            (3, [0, 1, 2])
        ]

        for r, slot_ids in row_pad_indices:
            for c, slot_idx in enumerate(slot_ids):
                pad = PadButton(slot_idx, is_track=is_track)
                pad.file_dropped.connect(self._on_file_dropped)
                pad.browse_clicked.connect(self._on_browse_clicked)
                pad.trim_clicked.connect(self._on_trim_clicked)
                pad.clear_clicked.connect(self._on_clear_clicked)
                pad.learn_clicked.connect(self._on_learn_clicked)
                pad.pad_clicked.connect(self._on_pad_clicked)
                pads_list.append(pad)
                grid.addWidget(pad, r, c)

        # Rightmost Column (Pads 16, 12, 8, 4):
        # Row 0 (Pad 16): ТРЕКИ ГРОМК +
        # Row 1 (Pad 12): ТРЕКИ ГРОМК -
        # Row 2 (Pad 8):  ВАНШОТЫ ГРОМК +
        # Row 3 (Pad 4):  ВАНШОТЫ ГРОМК -
        step_pct = int(self.audio.volume_step * 100)
        ctrl_track_up = ControlButton('track_vol_up', "PAD 16", f"ТРЕКИ VOL + (+{step_pct}%)", "#39ff14")
        ctrl_track_up.triggered.connect(lambda: self._handle_control('track_vol_up'))
        grid.addWidget(ctrl_track_up, 0, 3)

        ctrl_track_down = ControlButton('track_vol_down', "PAD 12", f"ТРЕКИ VOL - (-{step_pct}%)", "#39ff14")
        ctrl_track_down.triggered.connect(lambda: self._handle_control('track_vol_down'))
        grid.addWidget(ctrl_track_down, 1, 3)

        ctrl_os_up = ControlButton('oneshot_vol_up', "PAD 8", f"ВАНШОТ VOL + (+{step_pct}%)", "#00ffff")
        ctrl_os_up.triggered.connect(lambda: self._handle_control('oneshot_vol_up'))
        grid.addWidget(ctrl_os_up, 2, 3)

        ctrl_os_down = ControlButton('oneshot_vol_down', "PAD 4", f"ВАНШОТ VOL - (-{step_pct}%)", "#00ffff")
        ctrl_os_down.triggered.connect(lambda: self._handle_control('oneshot_vol_down'))
        grid.addWidget(ctrl_os_down, 3, 3)

        if not is_track:
            self.btn_track_vol_up = ctrl_track_up
            self.btn_track_vol_down = ctrl_track_down
            self.btn_oneshot_vol_up = ctrl_os_up
            self.btn_oneshot_vol_down = ctrl_os_down

        for c in range(4):
            grid.setColumnStretch(c, 1)
        for r in range(4):
            grid.setRowStretch(r, 1)

        return grid

    def _setup_callbacks(self):
        # Audio engine callbacks
        self.audio.on_volume_changed = self._on_volume_updated
        self.audio.on_track_state_changed = self._on_track_state_updated

        # MIDI Qt Signals (Thread-safe QueuedConnection)
        self.midi.sig_pad_hit.connect(self._on_midi_pad_hit)
        self.midi.sig_control_hit.connect(self._handle_control)
        self.midi.sig_preset_switched.connect(self._on_midi_preset_switched)
        self.midi.sig_status_changed.connect(self._on_midi_status_changed)
        self.midi.sig_learn_complete.connect(self._on_midi_learn_complete)
        self.midi.sig_midi_activity.connect(self._on_midi_activity)

        if self.midi.current_port_name:
            self._on_midi_status_changed(True, self.midi.current_port_name)

    # ==========================
    # Preset Management
    # ==========================
    def _populate_presets_combo(self):
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        presets = self.cfg.list_presets()
        for p in presets:
            self.combo_presets.addItem(p)
        current = self.cfg.current_preset_name
        idx = self.combo_presets.findText(current)
        if idx >= 0:
            self.combo_presets.setCurrentIndex(idx)
        self.combo_presets.blockSignals(False)

    def _on_preset_selected(self, preset_name: str):
        if not preset_name or preset_name == self.cfg.current_preset_name:
            return
        self.audio.stop_all()
        self.cfg.load_preset(preset_name)
        self._load_saved_files()

    def _on_new_preset_clicked(self):
        name, ok = QInputDialog.getText(self, "Новый набор", "Введите название пресета (например: Новый год):")
        if ok and name.strip():
            name = name.strip()
            # Ask if want to copy current pad assignments
            reply = QMessageBox.question(
                self, "Копирование",
                f"Скопировать текущие назначенные сэмплы в новый пресет '{name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            copy_curr = (reply == QMessageBox.Yes)
            self.cfg.create_preset(name, copy_current=copy_curr)
            self._populate_presets_combo()
            self._load_saved_files()

    def _on_delete_preset_clicked(self):
        curr = self.cfg.current_preset_name
        presets = self.cfg.list_presets()
        if len(presets) <= 1:
            QMessageBox.warning(self, "Внимание", "Нельзя удалить единственный оставшийся пресет.")
            return

        reply = QMessageBox.question(
            self, "Удаление пресета",
            f"Вы уверены, что хотите удалить пресет '{curr}' вместе со всеми его файлами?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.audio.stop_all()
            self.cfg.delete_preset(curr)
            self._populate_presets_combo()
            self._load_saved_files()

    # ==========================
    # Ports and MIDI
    # ==========================
    def _on_refresh_clicked(self):
        self.midi.force_reconnect()
        self._refresh_ports_list()

    def _refresh_ports_list(self):
        current = self.midi.current_port_name
        self.combo_ports.blockSignals(True)
        self.combo_ports.clear()
        ports = self.midi.get_available_ports()
        if not ports:
            self.combo_ports.addItem("Bluetooth JP-Mini (Поиск...)")
        else:
            for p in ports:
                self.combo_ports.addItem(p)
            if current and current in ports:
                self.combo_ports.setCurrentText(current)
            elif self.midi.opened_port_names:
                preferred = f"USB: {self.midi.opened_port_names[0]}"
                if preferred in ports:
                    self.combo_ports.setCurrentText(preferred)
        self.combo_ports.blockSignals(False)

    def _on_port_selected(self, index: int):
        port_name = self.combo_ports.currentText()
        if port_name:
            self.midi.switch_port(port_name)

    def _load_saved_files(self):
        # Clear existing audio sounds
        for slot in range(12):
            self.audio.clear_slot(is_track=False, slot=slot)
            self.audio.clear_slot(is_track=True, slot=slot)
            p_os = self._find_pad(is_track=False, slot=slot)
            if p_os:
                p_os.set_file("")
            p_tr = self._find_pad(is_track=True, slot=slot)
            if p_tr:
                p_tr.set_file("")

        # Load One-Shots
        for slot in range(12):
            path = self.cfg.get_oneshot_file(slot)
            if path and os.path.exists(path):
                self.audio.load_oneshot(slot, path)
                pad = self._find_pad(is_track=False, slot=slot)
                if pad:
                    pad.set_file(path)

        # Load Tracks
        for slot in range(12):
            path = self.cfg.get_track_file(slot)
            if path and os.path.exists(path):
                self.audio.load_track(slot, path)
                pad = self._find_pad(is_track=True, slot=slot)
                if pad:
                    pad.set_file(path)

        # Restore Volumes
        tvol = self.cfg.get_track_volume()
        osvol = self.cfg.get_oneshot_volume()
        step = self.cfg.get_volume_step()

        self.audio.set_track_volume(tvol)
        self.audio.set_oneshot_volume(osvol)
        self.audio.volume_step = step

        self.slider_track_vol.setValue(int(tvol * 100))
        self.slider_oneshot_vol.setValue(int(osvol * 100))
        self.spin_step.setValue(int(step * 100))

    def _find_pad(self, is_track: bool, slot: int) -> PadButton:
        pads = self.track_pads if is_track else self.oneshot_pads
        for p in pads:
            if p.slot_idx == slot:
                return p
        return None

    # ==========================
    # Pad File Actions & Trimmer
    # ==========================
    def _on_file_dropped(self, slot_idx: int, file_path: str):
        is_track = (self.tabs.currentIndex() == 1)
        self._assign_file_with_copy(is_track, slot_idx, file_path)

    def _on_browse_clicked(self, slot_idx: int):
        is_track = (self.tabs.currentIndex() == 1)
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите аудиофайл", "",
            "Аудиофайлы (*.wav *.mp3 *.ogg *.flac *.aiff);;Все файлы (*.*)"
        )
        if file_path:
            self._assign_file_with_copy(is_track, slot_idx, file_path)

    def _on_trim_clicked(self, slot_idx: int):
        is_track = (self.tabs.currentIndex() == 1)
        current_path = self.cfg.get_track_file(slot_idx) if is_track else self.cfg.get_oneshot_file(slot_idx)

        # If no file assigned yet, open file picker first
        if not current_path or not os.path.exists(current_path):
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Выберите аудиофайл для подрезки", "",
                "Аудиофайлы (*.wav *.mp3 *.ogg *.flac *.aiff);;Все файлы (*.*)"
            )
            if not file_path:
                return
            current_path = file_path

        # Open AudioTrimmerDialog
        samples_dir = self.cfg.get_preset_samples_dir()
        dlg = AudioTrimmerDialog(current_path, samples_dir, self)
        if dlg.exec_() == AudioTrimmerDialog.Accepted and dlg.trimmed_path:
            self._assign_file(is_track, slot_idx, dlg.trimmed_path)

    def _on_clear_clicked(self, slot_idx: int):
        is_track = (self.tabs.currentIndex() == 1)
        self.audio.clear_slot(is_track, slot_idx)
        pad = self._find_pad(is_track, slot_idx)
        if pad:
            pad.set_file("")
        if is_track:
            self.cfg.set_track_file(slot_idx, "")
        else:
            self.cfg.set_oneshot_file(slot_idx, "")

    def _assign_file_with_copy(self, is_track: bool, slot_idx: int, path: str):
        # Automatically copy file into preset's local samples directory
        local_path = self.cfg.import_sample_file(path, is_track, slot_idx)
        self._assign_file(is_track, slot_idx, local_path)

    def _assign_file(self, is_track: bool, slot_idx: int, path: str):
        success = self.audio.load_track(slot_idx, path) if is_track else self.audio.load_oneshot(slot_idx, path)
        if success:
            pad = self._find_pad(is_track, slot_idx)
            if pad:
                pad.set_file(path)
            if is_track:
                self.cfg.set_track_file(slot_idx, path)
            else:
                self.cfg.set_oneshot_file(slot_idx, path)

    def _on_pad_clicked(self, slot_idx: int):
        is_track = (self.tabs.currentIndex() == 1)
        if is_track:
            self.audio.trigger_track(slot_idx)
        else:
            self.audio.trigger_oneshot(slot_idx)
        pad = self._find_pad(is_track, slot_idx)
        if pad:
            pad.flash_trigger()

    # ==========================
    # MIDI Learn
    # ==========================
    def _on_learn_clicked(self, slot_idx: int):
        is_track = (self.tabs.currentIndex() == 1)
        preset = 'preset2' if is_track else 'preset1'
        pad = self._find_pad(is_track, slot_idx)
        if pad:
            pad.set_learning(True)
        pad_idx = SOUND_PADS_ORDER[slot_idx] if slot_idx < len(SOUND_PADS_ORDER) else slot_idx
        self.midi.start_learn(preset, pad_idx)

    def _on_midi_learn_complete(self, preset: str, pad_idx: int, note: int):
        is_track = (preset == 'preset2')
        slot_idx = PAD_TO_SLOT.get(pad_idx, pad_idx)
        pad = self._find_pad(is_track, slot_idx)
        if pad:
            pad.set_learning(False)
            pad.flash_trigger()

    # ==========================
    # MIDI & Audio Event Handlers
    # ==========================
    def _on_midi_pad_hit(self, preset: str, slot_idx: int, velocity: int):
        is_track = (preset == 'preset2')
        if is_track:
            self.audio.trigger_track(slot_idx)
        else:
            self.audio.trigger_oneshot(slot_idx)

        pad = self._find_pad(is_track, slot_idx)
        if pad:
            pad.flash_trigger()

    def _handle_control(self, action: str):
        if action == 'track_vol_up':
            self.audio.track_vol_up()
            if self.btn_track_vol_up:
                self.btn_track_vol_up.flash_trigger()
        elif action == 'track_vol_down':
            self.audio.track_vol_down()
            if self.btn_track_vol_down:
                self.btn_track_vol_down.flash_trigger()
        elif action == 'oneshot_vol_up':
            self.audio.oneshot_vol_up()
            if self.btn_oneshot_vol_up:
                self.btn_oneshot_vol_up.flash_trigger()
        elif action == 'oneshot_vol_down':
            self.audio.oneshot_vol_down()
            if self.btn_oneshot_vol_down:
                self.btn_oneshot_vol_down.flash_trigger()
        elif action in ('track_play_pause', 'play_pause'):
            self.audio.toggle_play_pause_track()
            if hasattr(self, 'btn_play_pause_track') and self.btn_play_pause_track:
                self.btn_play_pause_track.setStyleSheet("background: #39ff14; color: #070913; border: 1px solid #39ff14; border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;")
                QTimer.singleShot(150, lambda: self.btn_play_pause_track.setStyleSheet("background: #103518; color: #39ff14; border: 1px solid #39ff14; border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;"))
        elif action in ('stop_oneshots', 'stop'):
            self.audio.stop_oneshots()
            if hasattr(self, 'btn_stop_os') and self.btn_stop_os:
                self.btn_stop_os.setStyleSheet("background: #00ffff; color: #070913; border: 1px solid #00ffff; border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;")
                QTimer.singleShot(150, lambda: self.btn_stop_os.setStyleSheet("background: #1f1b2b; color: #00ffff; border: 1px solid #00ffff; border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px;"))
        elif action in ('toggle_preset', 'switch_mode'):
            new_idx = 1 if self.tabs.currentIndex() == 0 else 0
            self.tabs.setCurrentIndex(new_idx)
        elif action in ('mute_all', 'mute'):
            self.audio.toggle_mute()

    def _on_midi_activity(self, text: str):
        if hasattr(self, 'lbl_midi_activity') and self.lbl_midi_activity:
            self.lbl_midi_activity.setText(f"● {text}")
            self.lbl_midi_activity.setStyleSheet("""
                QLabel {
                    background: #1a2a47; color: #ffd700; border: 1px solid #ffd700;
                    border-radius: 12px; padding: 5px 12px; font-weight: bold; font-size: 11px;
                }
            """)
            QTimer.singleShot(1500, self._reset_midi_activity_style)

    def _reset_midi_activity_style(self):
        if hasattr(self, 'lbl_midi_activity') and self.lbl_midi_activity:
            self.lbl_midi_activity.setStyleSheet("""
                QLabel {
                    background: #101726; color: #7e8fa6; border: 1px solid #23314d;
                    border-radius: 12px; padding: 5px 12px; font-weight: bold; font-size: 11px;
                }
            """)

    def _on_tab_changed(self, idx: int):
        preset = 'preset1' if idx == 0 else 'preset2'
        self.midi.set_active_preset(preset)
        name = "ВАНШОТЫ (PRESET 1)" if idx == 0 else "ТРЕКИ (PRESET 2)"
        self._on_midi_activity(f"ПРЕСЕТ: {name}")

    def _on_midi_preset_switched(self, preset: str):
        idx = 0 if preset == 'preset1' else 1
        if self.tabs.currentIndex() != idx:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(idx)
            self.tabs.blockSignals(False)
        name = "ВАНШОТЫ (PRESET 1)" if idx == 0 else "ТРЕКИ (PRESET 2)"
        self._on_midi_activity(f"ПРЕСЕТ: {name}")

    def _on_midi_status_changed(self, is_connected: bool, port_name: str):
        if is_connected:
            self.lbl_status.setText(f"● {port_name}")
            self.lbl_status.setStyleSheet("""
                QLabel {
                    background: #103518; color: #39ff14; border: 1px solid #39ff14;
                    border-radius: 12px; padding: 5px 12px; font-weight: bold; font-size: 11px;
                }
            """)
            self.combo_ports.blockSignals(True)
            idx = self.combo_ports.findText(port_name)
            if idx >= 0:
                self.combo_ports.setCurrentIndex(idx)
            else:
                self.combo_ports.addItem(port_name)
                self.combo_ports.setCurrentText(port_name)
            self.combo_ports.blockSignals(False)
        else:
            self.lbl_status.setText(f"● {port_name}")
            self.lbl_status.setStyleSheet("""
                QLabel {
                    background: #33141c; color: #ff007f; border: 1px solid #ff007f;
                    border-radius: 12px; padding: 5px 12px; font-weight: bold; font-size: 11px;
                }
            """)

    def _on_volume_updated(self, track_vol: float, oneshot_vol: float, is_muted: bool):
        t_pct = int(track_vol * 100)
        os_pct = int(oneshot_vol * 100)

        self.slider_track_vol.blockSignals(True)
        self.slider_oneshot_vol.blockSignals(True)

        self.slider_track_vol.setValue(t_pct if not is_muted else 0)
        self.slider_oneshot_vol.setValue(os_pct if not is_muted else 0)

        self.slider_track_vol.blockSignals(False)
        self.slider_oneshot_vol.blockSignals(False)

        if is_muted:
            self.lbl_tvol_val.setText("MUTE")
            self.lbl_tvol_val.setStyleSheet("color: #ff007f; font-weight: bold;")
            self.lbl_osvol_val.setText("MUTE")
            self.lbl_osvol_val.setStyleSheet("color: #ff007f; font-weight: bold;")
            self.btn_mute_toggle.setText("🔊 Unmute")
            self.btn_mute_toggle.setStyleSheet("""
                QPushButton { background: #ff007f; color: #ffffff; border: 1px solid #ffffff; padding: 6px 12px; font-weight: bold; }
            """)
        else:
            self.lbl_tvol_val.setText(f"{t_pct}%")
            self.lbl_tvol_val.setStyleSheet("color: #39ff14; font-weight: bold;")
            self.lbl_osvol_val.setText(f"{os_pct}%")
            self.lbl_osvol_val.setStyleSheet("color: #00ffff; font-weight: bold;")
            self.btn_mute_toggle.setText("🔇 Mute All")
            self.btn_mute_toggle.setStyleSheet("""
                QPushButton { background: #2b121d; color: #ff007f; border: 1px solid #ff007f; border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 11px; }
                QPushButton:hover { background: #ff007f; color: #ffffff; }
            """)

        self.cfg.set_track_volume(track_vol)
        self.cfg.set_oneshot_volume(oneshot_vol)

    def _on_track_state_updated(self, active_slot: int, is_paused: bool):
        for pad in self.track_pads:
            if pad.slot_idx == active_slot:
                pad.set_playing(True, is_paused)
            else:
                pad.set_playing(False, False)

        if active_slot is None:
            self.btn_play_pause_track.setText("▶ Трек")
        elif is_paused:
            self.btn_play_pause_track.setText(f"⏸ P{active_slot+1} (Пауза)")
        else:
            self.btn_play_pause_track.setText(f"▶ P{active_slot+1} (Играет)")

    def _on_track_vol_slider_changed(self, val: int):
        self.audio.set_track_volume(val / 100.0)

    def _on_oneshot_vol_slider_changed(self, val: int):
        self.audio.set_oneshot_volume(val / 100.0)

    def _on_step_changed(self, val: int):
        step = val / 100.0
        self.audio.volume_step = step
        self.cfg.set_volume_step(step)
        if self.btn_track_vol_up:
            self.btn_track_vol_up.set_sub_text(f"+{val}%")
        if self.btn_track_vol_down:
            self.btn_track_vol_down.set_sub_text(f"-{val}%")
        if self.btn_oneshot_vol_up:
            self.btn_oneshot_vol_up.set_sub_text(f"+{val}%")
        if self.btn_oneshot_vol_down:
            self.btn_oneshot_vol_down.set_sub_text(f"-{val}%")

    # ==========================
    # Tray & Window Management
    # ==========================
    def hide_to_tray(self):
        self.hide()
        self.tray.show_message("JAMJUM Pad Launcher", "Приложение свернуто в трей и принимает BLE MIDI.")

    def restore_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        choice = self.tray.confirm_close()
        if choice == 'tray':
            event.ignore()
            self.hide_to_tray()
        elif choice == 'exit':
            self._force_exit()
            event.accept()
        else:
            event.ignore()

    def _force_exit(self):
        self.midi.stop()
        self.audio.stop_all()
        self.tray.tray_icon.hide()
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
