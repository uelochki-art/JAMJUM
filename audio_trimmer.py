"""
Audio Trimmer Dialog for JAMJUM / Gussy Pad Launcher.
Allows visual waveform inspection with interactive mouse dragging,
smooth Start/End mouse sliders, quick-preset slicing buttons,
preview playback of the slice, and saving trimmed WAV to project/preset folder.
"""

import os
import wave
import numpy as np
import pygame

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSlider, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QCursor


class WaveformWidget(QFrame):
    range_changed = pyqtSignal(float, float)  # (start_time, end_time)

    def __init__(self, samples: np.ndarray, sample_rate: int, parent=None):
        super().__init__(parent)
        self.samples = samples
        self.sample_rate = sample_rate
        self.total_duration = max(0.001, len(samples) / float(sample_rate))

        self.start_time = 0.0
        self.end_time = self.total_duration

        self.dragging_marker = None  # 'start' or 'end'
        self.setMouseTracking(True)

        self.setMinimumHeight(130)
        self.setStyleSheet("background-color: #0b0e1b; border: 1px solid rgba(0,255,255,0.3); border-radius: 6px;")

        # Downsample for rendering
        self.peaks = self._compute_peaks(1000)

    def _compute_peaks(self, num_bins: int):
        if len(self.samples) == 0:
            return np.zeros(num_bins)
        # Convert stereo to mono for display
        if len(self.samples.shape) > 1 and self.samples.shape[1] > 1:
            mono = self.samples.mean(axis=1)
        else:
            mono = self.samples
        # Normalize
        max_val = np.max(np.abs(mono))
        if max_val > 0:
            mono = mono / float(max_val)
        bin_size = max(1, len(mono) // num_bins)
        peaks = []
        for i in range(num_bins):
            chunk = mono[i * bin_size : (i + 1) * bin_size]
            peaks.append(np.max(np.abs(chunk)) if len(chunk) > 0 else 0)
        return np.array(peaks)

    def set_range(self, start_t: float, end_t: float):
        self.start_time = max(0.0, min(start_t, self.total_duration))
        self.end_time = max(self.start_time, min(end_t, self.total_duration))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = max(1, self.width())
            x = event.x()
            start_x = int((self.start_time / self.total_duration) * w)
            end_x = int((self.end_time / self.total_duration) * w)

            # Determine whether closer to start or end marker
            dist_start = abs(x - start_x)
            dist_end = abs(x - end_x)

            if dist_start <= 15 and dist_start <= dist_end:
                self.dragging_marker = 'start'
            elif dist_end <= 15:
                self.dragging_marker = 'end'
            else:
                # Clicked elsewhere: move nearest marker
                if dist_start < dist_end:
                    self.dragging_marker = 'start'
                else:
                    self.dragging_marker = 'end'

            self._apply_mouse_pos(x)

    def mouseMoveEvent(self, event):
        w = max(1, self.width())
        x = event.x()
        start_x = int((self.start_time / self.total_duration) * w)
        end_x = int((self.end_time / self.total_duration) * w)

        if event.buttons() & Qt.LeftButton and self.dragging_marker:
            self._apply_mouse_pos(x)
        else:
            # Change cursor if hovering near marker
            if abs(x - start_x) <= 10 or abs(x - end_x) <= 10:
                self.setCursor(QCursor(Qt.SizeHorCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))

    def mouseReleaseEvent(self, event):
        self.dragging_marker = None

    def _apply_mouse_pos(self, x: int):
        w = max(1, self.width())
        ratio = max(0.0, min(1.0, x / float(w)))
        t = ratio * self.total_duration

        if self.dragging_marker == 'start':
            self.start_time = min(t, max(0.0, self.end_time - 0.01))
        elif self.dragging_marker == 'end':
            self.end_time = max(t, min(self.total_duration, self.start_time + 0.01))

        self.update()
        self.range_changed.emit(self.start_time, self.end_time)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        mid_y = h / 2.0

        # Draw selected region background
        start_x = int((self.start_time / self.total_duration) * w)
        end_x = int((self.end_time / self.total_duration) * w)

        painter.fillRect(start_x, 0, max(1, end_x - start_x), h, QColor(0, 255, 255, 30))

        # Draw Waveform
        if len(self.peaks) > 0:
            pen_unsel = QPen(QColor(0, 140, 160, 150))
            pen_sel = QPen(QColor(0, 255, 255, 245))
            pen_sel.setWidth(2)

            for i, p in enumerate(self.peaks):
                x = int((i / float(len(self.peaks))) * w)
                bar_h = p * (mid_y - 8)
                painter.setPen(pen_sel if start_x <= x <= end_x else pen_unsel)
                painter.drawLine(x, int(mid_y - bar_h), x, int(mid_y + bar_h))

        # Draw Start Marker (Green Neon) with top handle
        painter.setPen(QPen(QColor(57, 255, 20), 2))
        painter.drawLine(start_x, 0, start_x, h)
        painter.setBrush(QBrush(QColor(57, 255, 20)))
        painter.drawRect(max(0, start_x - 4), 0, 8, 14)

        # Draw End Marker (Pink Neon) with top handle
        painter.setPen(QPen(QColor(255, 0, 127), 2))
        painter.drawLine(end_x, 0, end_x, h)
        painter.setBrush(QBrush(QColor(255, 0, 127)))
        painter.drawRect(max(0, end_x - 4), 0, 8, 14)


class AudioTrimmerDialog(QDialog):
    def __init__(self, file_path: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.output_dir = output_dir
        self.trimmed_path = None

        self.setWindowTitle("Редактор сэмпла / Подрезка трека (Мышь / Ползунки)")
        self.resize(740, 460)
        self.setStyleSheet("""
            QDialog {
                background-color: #070913;
                color: #f0f4fc;
                font-family: 'Segoe UI', Montserrat, sans-serif;
            }
            QLabel {
                color: #f0f4fc;
                font-size: 12px;
            }
            QDoubleSpinBox {
                background: #141c33;
                color: #00ffff;
                border: 1px solid #00ffff;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton {
                background: #141c33;
                color: #f0f4fc;
                border: 1px solid #7e8fa6;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #1a233a;
                border-color: #00ffff;
                color: #00ffff;
            }
        """)

        # Load audio into memory via pygame
        try:
            self.sound = pygame.mixer.Sound(file_path)
            self.samples = pygame.sndarray.samples(self.sound)
            self.sample_rate = 44100
            self.total_duration = len(self.samples) / float(self.sample_rate)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить аудиофайл:\n{e}")
            self.samples = np.zeros(100)
            self.total_duration = 1.0

        self.preview_channel = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header info
        base_name = os.path.basename(self.file_path)
        lbl_info = QLabel(f"<b>Файл:</b> {base_name} &nbsp;|&nbsp; <b>Полная длительность:</b> {self.total_duration:.2f} сек")
        layout.addWidget(lbl_info)

        lbl_hint = QLabel("💡 <i>Тяните ползунки ниже или прямо по осциллограмме мышкой (зелёный — начало, розовый — конец)</i>")
        lbl_hint.setStyleSheet("color: #7e8fa6; font-size: 11px;")
        layout.addWidget(lbl_hint)

        # 1. Waveform preview with direct mouse interaction
        self.waveform = WaveformWidget(self.samples, self.sample_rate)
        self.waveform.range_changed.connect(self._on_waveform_range_changed)
        layout.addWidget(self.waveform)

        # 2. Smooth Mouse Sliders
        # Start Slider (Green)
        row_start_slider = QHBoxLayout()
        lbl_s_tag = QLabel("🟢 НАЧАЛО:")
        lbl_s_tag.setFixedWidth(80)
        lbl_s_tag.setStyleSheet("color: #39ff14; font-weight: bold; font-size: 11px;")
        row_start_slider.addWidget(lbl_s_tag)

        self.slider_start = QSlider(Qt.Horizontal)
        self.slider_start.setRange(0, 1000)
        self.slider_start.setValue(0)
        self.slider_start.setStyleSheet("""
            QSlider::groove:horizontal { height: 8px; background: #141c33; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: rgba(57, 255, 20, 0.3); border-radius: 4px; }
            QSlider::handle:horizontal {
                background: #39ff14; border: 1px solid #ffffff; width: 18px; margin-top: -5px; margin-bottom: -5px; border-radius: 9px;
            }
            QSlider::handle:horizontal:hover { background: #ffffff; }
        """)
        self.slider_start.valueChanged.connect(self._on_slider_start_changed)
        row_start_slider.addWidget(self.slider_start, 1)

        self.spin_start = QDoubleSpinBox()
        self.spin_start.setRange(0.0, self.total_duration)
        self.spin_start.setSingleStep(0.05)
        self.spin_start.setSuffix(" сек")
        self.spin_start.setValue(0.0)
        self.spin_start.setFixedWidth(90)
        self.spin_start.valueChanged.connect(self._on_spin_start_changed)
        row_start_slider.addWidget(self.spin_start)
        layout.addLayout(row_start_slider)

        # End Slider (Pink)
        row_end_slider = QHBoxLayout()
        lbl_e_tag = QLabel("🔴 КОНЕЦ:")
        lbl_e_tag.setFixedWidth(80)
        lbl_e_tag.setStyleSheet("color: #ff007f; font-weight: bold; font-size: 11px;")
        row_end_slider.addWidget(lbl_e_tag)

        self.slider_end = QSlider(Qt.Horizontal)
        self.slider_end.setRange(0, 1000)
        self.slider_end.setValue(1000)
        self.slider_end.setStyleSheet("""
            QSlider::groove:horizontal { height: 8px; background: #141c33; border-radius: 4px; }
            QSlider::sub-page:horizontal { background: rgba(255, 0, 127, 0.4); border-radius: 4px; }
            QSlider::handle:horizontal {
                background: #ff007f; border: 1px solid #ffffff; width: 18px; margin-top: -5px; margin-bottom: -5px; border-radius: 9px;
            }
            QSlider::handle:horizontal:hover { background: #ffffff; }
        """)
        self.slider_end.valueChanged.connect(self._on_slider_end_changed)
        row_end_slider.addWidget(self.slider_end, 1)

        self.spin_end = QDoubleSpinBox()
        self.spin_end.setRange(0.0, self.total_duration)
        self.spin_end.setSingleStep(0.05)
        self.spin_end.setSuffix(" сек")
        self.spin_end.setValue(self.total_duration)
        self.spin_end.setFixedWidth(90)
        self.spin_end.valueChanged.connect(self._on_spin_end_changed)
        row_end_slider.addWidget(self.spin_end)
        layout.addLayout(row_end_slider)

        # 3. Quick preset slice buttons + duration label
        quick_row = QHBoxLayout()
        lbl_q = QLabel("Быстрый выбор:")
        lbl_q.setStyleSheet("color: #7e8fa6; font-size: 11px;")
        quick_row.addWidget(lbl_q)

        btn_all = QPushButton("Весь файл")
        btn_all.clicked.connect(lambda: self._set_quick_range(0.0, self.total_duration))
        quick_row.addWidget(btn_all)

        btn_05 = QPushButton("Первые 0.5с")
        btn_05.clicked.connect(lambda: self._set_quick_range(0.0, min(0.5, self.total_duration)))
        quick_row.addWidget(btn_05)

        btn_10 = QPushButton("Первые 1.0с")
        btn_10.clicked.connect(lambda: self._set_quick_range(0.0, min(1.0, self.total_duration)))
        quick_row.addWidget(btn_10)

        btn_20 = QPushButton("Первые 2.0с")
        btn_20.clicked.connect(lambda: self._set_quick_range(0.0, min(2.0, self.total_duration)))
        quick_row.addWidget(btn_20)

        quick_row.addStretch()

        self.lbl_selected_dur = QLabel(f"Длина фрагмента: {self.total_duration:.2f} сек")
        self.lbl_selected_dur.setStyleSheet("font-weight: bold; color: #00ffff; font-size: 13px;")
        quick_row.addWidget(self.lbl_selected_dur)
        layout.addLayout(quick_row)

        layout.addSpacing(6)

        # 4. Action Buttons row
        btn_layout = QHBoxLayout()

        self.btn_play = QPushButton("▶ Прослушать фрагмент (Пробел)")
        self.btn_play.setStyleSheet("""
            QPushButton {
                background: #103518; color: #39ff14; border: 1px solid #39ff14;
                padding: 8px 18px; font-size: 12px;
            }
            QPushButton:hover { background: #39ff14; color: #070913; }
        """)
        self.btn_play.clicked.connect(self._toggle_preview)
        btn_layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹ Стоп")
        self.btn_stop.clicked.connect(self._stop_preview)
        btn_layout.addWidget(self.btn_stop)

        btn_layout.addStretch()

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton("💾 Сохранить и применить")
        btn_save.setStyleSheet("""
            QPushButton {
                background: #00ffff; color: #070913; border: 1px solid #00ffff;
                padding: 8px 20px; font-size: 12px; font-weight: 900;
            }
            QPushButton:hover { background: #39ff14; border-color: #39ff14; }
        """)
        btn_save.clicked.connect(self._save_trimmed)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    # ==========================
    # Synchronization Handlers
    # ==========================
    def _on_waveform_range_changed(self, st: float, en: float):
        self._block_signals(True)
        self.spin_start.setValue(st)
        self.spin_end.setValue(en)
        self.slider_start.setValue(int((st / self.total_duration) * 1000))
        self.slider_end.setValue(int((en / self.total_duration) * 1000))
        self._block_signals(False)
        self._update_dur_label()

    def _on_slider_start_changed(self, val: int):
        st = (val / 1000.0) * self.total_duration
        if st >= self.spin_end.value():
            st = max(0.0, self.spin_end.value() - 0.05)
            self.slider_start.setValue(int((st / self.total_duration) * 1000))
        self._block_signals(True)
        self.spin_start.setValue(st)
        self.waveform.set_range(st, self.spin_end.value())
        self._block_signals(False)
        self._update_dur_label()

    def _on_slider_end_changed(self, val: int):
        en = (val / 1000.0) * self.total_duration
        if en <= self.spin_start.value():
            en = min(self.total_duration, self.spin_start.value() + 0.05)
            self.slider_end.setValue(int((en / self.total_duration) * 1000))
        self._block_signals(True)
        self.spin_end.setValue(en)
        self.waveform.set_range(self.spin_start.value(), en)
        self._block_signals(False)
        self._update_dur_label()

    def _on_spin_start_changed(self, val: float):
        if val >= self.spin_end.value():
            val = max(0.0, self.spin_end.value() - 0.05)
            self.spin_start.setValue(val)
        self._block_signals(True)
        self.slider_start.setValue(int((val / self.total_duration) * 1000))
        self.waveform.set_range(val, self.spin_end.value())
        self._block_signals(False)
        self._update_dur_label()

    def _on_spin_end_changed(self, val: float):
        if val <= self.spin_start.value():
            val = min(self.total_duration, self.spin_start.value() + 0.05)
            self.spin_end.setValue(val)
        self._block_signals(True)
        self.slider_end.setValue(int((val / self.total_duration) * 1000))
        self.waveform.set_range(self.spin_start.value(), val)
        self._block_signals(False)
        self._update_dur_label()

    def _set_quick_range(self, st: float, en: float):
        self._block_signals(True)
        self.spin_start.setValue(st)
        self.spin_end.setValue(en)
        self.slider_start.setValue(int((st / self.total_duration) * 1000))
        self.slider_end.setValue(int((en / self.total_duration) * 1000))
        self.waveform.set_range(st, en)
        self._block_signals(False)
        self._update_dur_label()

    def _block_signals(self, block: bool):
        self.slider_start.blockSignals(block)
        self.slider_end.blockSignals(block)
        self.spin_start.blockSignals(block)
        self.spin_end.blockSignals(block)

    def _update_dur_label(self):
        st = self.spin_start.value()
        en = self.spin_end.value()
        dur = max(0.0, en - st)
        self.lbl_selected_dur.setText(f"Длина фрагмента: {dur:.2f} сек")

    # ==========================
    # Preview & Saving
    # ==========================
    def _toggle_preview(self):
        if self.preview_channel and self.preview_channel.get_busy():
            self._stop_preview()
        else:
            self._play_preview()

    def _play_preview(self):
        self._stop_preview()
        st = self.spin_start.value()
        en = self.spin_end.value()
        start_idx = int(st * self.sample_rate)
        end_idx = int(en * self.sample_rate)

        slice_samples = self.samples[start_idx:end_idx]
        if len(slice_samples) == 0:
            return

        try:
            preview_sound = pygame.sndarray.make_sound(slice_samples)
            self.preview_channel = preview_sound.play()
            self.btn_play.setText("⏸ Пауза (Пробел)")
            QTimer.singleShot(int((en - st) * 1000) + 100, self._check_preview_finished)
        except Exception as e:
            print(f"[Trimmer] Preview error: {e}")

    def _check_preview_finished(self):
        if not self.preview_channel or not self.preview_channel.get_busy():
            self.btn_play.setText("▶ Прослушать фрагмент (Пробел)")

    def _stop_preview(self):
        if self.preview_channel and self.preview_channel.get_busy():
            self.preview_channel.stop()
        self.btn_play.setText("▶ Прослушать фрагмент (Пробел)")

    def _save_trimmed(self):
        self._stop_preview()
        st = self.spin_start.value()
        en = self.spin_end.value()
        start_idx = int(st * self.sample_rate)
        end_idx = int(en * self.sample_rate)

        slice_samples = self.samples[start_idx:end_idx]
        if len(slice_samples) == 0:
            QMessageBox.warning(self, "Внимание", "Выбран нулевой фрагмент.")
            return

        os.makedirs(self.output_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(self.file_path))[0]
        out_name = f"{base}_trim_{int(st*1000)}_{int(en*1000)}.wav"
        out_path = os.path.join(self.output_dir, out_name)

        try:
            if len(slice_samples.shape) == 1:
                slice_samples = np.column_stack((slice_samples, slice_samples))
            int_samples = slice_samples.astype(np.int16)

            with wave.open(out_path, 'wb') as wf:
                wf.setnchannels(slice_samples.shape[1])
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(int_samples.tobytes())

            self.trimmed_path = out_path
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить WAV:\n{e}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._toggle_preview()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._stop_preview()
        super().closeEvent(event)
