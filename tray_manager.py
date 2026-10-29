"""
Tray Manager for Gussy Pad Launcher.
Handles system tray icon, notifications, context menu, and window close dialog.
"""

import os
import sys
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QMessageBox, QApplication
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt5.QtCore import Qt, QObject, pyqtSignal


def create_default_icon() -> QIcon:
    """Returns the neon pad QIcon from app_icon.ico or generates it."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    ico_path = os.path.join(base, "app_icon.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Background rounded rect
    painter.setBrush(QColor(15, 20, 36))
    painter.setPen(QColor(0, 255, 255))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)

    # 4 small squares representing pads
    colors = [QColor(0, 255, 255), QColor(255, 0, 127), QColor(255, 215, 0), QColor(57, 255, 20)]
    coords = [(14, 14), (34, 14), (14, 34), (34, 34)]
    for (x, y), c in zip(coords, colors):
        painter.setBrush(c)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(x, y, 16, 16, 4, 4)

    painter.end()
    return QIcon(pixmap)


class TrayManager(QObject):
    restore_requested = pyqtSignal()
    panic_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.icon = create_default_icon()

        self.tray_icon = QSystemTrayIcon(self.icon, main_window)
        self.tray_icon.setToolTip("Gussy Pad Launcher — Bluetooth MIDI Player")

        self._create_menu()
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _create_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #0f1424;
                color: #f0f4fc;
                border: 1px solid #00ffff;
                padding: 5px;
                font-family: 'Segoe UI', sans-serif;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1a233a;
                color: #00ffff;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(0, 255, 255, 0.3);
                margin: 4px 8px;
            }
        """)

        action_show = QAction("Показать окно", self.main_window)
        action_show.triggered.connect(self.restore_requested.emit)
        menu.addAction(action_show)

        action_panic = QAction("⏹ Остановить всё (Panic)", self.main_window)
        action_panic.triggered.connect(self.panic_requested.emit)
        menu.addAction(action_panic)

        menu.addSeparator()

        action_exit = QAction("Выход из программы", self.main_window)
        action_exit.triggered.connect(self.exit_requested.emit)
        menu.addAction(action_exit)

        self.tray_icon.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.restore_requested.emit()

    def show_message(self, title: str, text: str, msec: int = 2500):
        if self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, text, self.icon, msec)

    def confirm_close(self) -> str:
        """
        Prompts user when pressing 'X':
        Returns 'tray', 'exit', or 'cancel'.
        """
        msg_box = QMessageBox(self.main_window)
        msg_box.setWindowTitle("Gussy Pad Launcher")
        msg_box.setText("<h3>Что вы хотите сделать?</h3>")
        msg_box.setInformativeText("Свернуть приложение в системный трей для фоновой работы с пэдами или полностью закрыть?")
        msg_box.setIconPixmap(self.icon.pixmap(48, 48))
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #0f1424;
                color: #f0f4fc;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #f0f4fc;
            }
            QPushButton {
                background-color: #141c33;
                color: #00ffff;
                border: 1px solid #00ffff;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00ffff;
                color: #070913;
            }
        """)

        btn_tray = msg_box.addButton("Свернуть в трей", QMessageBox.AcceptRole)
        btn_exit = msg_box.addButton("Закрыть", QMessageBox.DestructiveRole)
        btn_cancel = msg_box.addButton("Отмена", QMessageBox.RejectRole)
        msg_box.setDefaultButton(btn_tray)

        msg_box.exec_()
        clicked = msg_box.clickedButton()

        if clicked == btn_tray:
            return 'tray'
        elif clicked == btn_exit:
            return 'exit'
        return 'cancel'
