"""
Pomodoro + Todo desktop app.
Works on Windows and Linux using PySide6 (Qt) and SQLite.

Run:  python pomodoro_todo.py
"""

import json
import math
import sqlite3
import struct
import sys
import wave
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QUrl, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

DB_PATH = Path.home() / ".pomodoro_todo.db"
CHIME_PATH = Path.home() / ".pomodoro_chime.wav"
SETTINGS_PATH = Path.home() / ".pomodoro_settings.json"

# ---------- Pets ----------
# Each pet is described by a few drawing options. Dogs have dog faces, cats have
# pointy ears and whiskers, and the bunny has tall ears.
PETS = {
    "buddy": {
        "name": "Buddy", "species": "dog",
        "fur": "#F6E7CF", "accent": "#8B5A2B", "muzzle": "#FFF6E8",
        "ears": "floppy", "tail": "wag", "collar": "#8B5A2B",
    },
    "coco": {
        "name": "Coco", "species": "dog",
        "fur": "#F3D9A4", "accent": "#E08A3C", "muzzle": "#FFFFFF",
        "ears": "tall", "tail": "curl", "collar": "#C62828",
    },
    "max": {
        "name": "Max", "species": "dog",
        "fur": "#3A6FB0", "accent": "#7FA8D8", "muzzle": "#D9B38C",
        "ears": "floppy", "tail": "wag", "collar": None,
    },
    "luca": {
        "name": "Luca", "species": "dog",
        "fur": "#2E2E33", "accent": "#A0692E", "muzzle": "#A0692E",
        "ears": "pointy", "tail": "stub", "collar": None,
    },
    "milo": {
        "name": "Milo", "species": "cat",
        "fur": "#F5A94B", "accent": "#E08A3C", "muzzle": "#FFF3E0",
        "ears": "pointy", "tail": "curl", "stripes": True, "eye": "#2E7D32",
    },
    "mochi": {
        "name": "Mochi", "species": "cat",
        "fur": "#FFFFFF", "accent": "#F8BBD0", "muzzle": "#FFFFFF",
        "ears": "pointy", "tail": "curl", "eye": "#3B6EA5",
    },
    "whiskers": {
        "name": "Whiskers", "species": "cat",
        "fur": "#C9C2B5", "accent": "#8E857A", "muzzle": "#EDE7DC",
        "ears": "pointy", "tail": "curl", "stripes": True, "eye": "#3B6EA5",
    },
    "sakura": {
        "name": "Sakura", "species": "cat",
        "fur": "#D9C7F2", "accent": "#F48FB1", "muzzle": "#F3EAFD",
        "ears": "pointy", "tail": "curl", "eye": "#3B6EA5",
    },
    "hazel": {
        "name": "Hazel", "species": "bunny",
        "fur": "#FFF4E0", "accent": "#F8BBD0", "muzzle": "#FFFFFF",
        "ears": "tall", "tail": "stub",
    },
}

DEFAULT_SETTINGS = {
    "work_min": 25,
    "short_break_min": 5,
    "long_break_min": 15,
    "pomodoros_before_long": 4,
    "pet": "buddy",
}

PHASE_WORK = "work"
PHASE_SHORT = "short break"
PHASE_LONG = "long break"


def load_settings():
    """Load saved settings, falling back to the defaults for anything missing."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for key in DEFAULT_SETTINGS:
            if key not in saved:
                continue
            value = saved[key]
            if key == "pet":
                if isinstance(value, str) and value in PETS:
                    settings[key] = value
            elif isinstance(value, int) and value > 0:
                settings[key] = value
    except (OSError, ValueError):
        pass  # no file yet or unreadable: use defaults
    return settings


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def make_chime(path: Path):
    """Generate a short two-note chime as a WAV file (no external audio assets needed)."""
    rate = 44100
    notes = [(880, 0.35), (1320, 0.6)]  # (frequency Hz, duration s)
    frames = bytearray()
    for freq, dur in notes:
        n = int(rate * dur)
        for i in range(n):
            t = i / rate
            envelope = max(0.0, 1.0 - i / n)  # fade out each note
            sample = 0.5 * envelope * math.sin(2 * math.pi * freq * t)
            frames += struct.pack("<h", int(sample * 32767))
        frames += b"\x00\x00" * int(rate * 0.1)  # short gap between notes
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))


class Database:
    """Small wrapper around SQLite for storing tasks."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT    NOT NULL,
                done            INTEGER NOT NULL DEFAULT 0,
                est_pomodoros   INTEGER NOT NULL DEFAULT 1,
                done_pomodoros  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def all_tasks(self):
        return self.conn.execute(
            "SELECT * FROM tasks ORDER BY done ASC, id ASC"
        ).fetchall()

    def get_task(self, task_id: int):
        return self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    def add_task(self, title: str, est_pomodoros: int):
        self.conn.execute(
            "INSERT INTO tasks (title, est_pomodoros) VALUES (?, ?)",
            (title, est_pomodoros),
        )
        self.conn.commit()

    def toggle_done(self, task_id: int):
        self.conn.execute(
            "UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,)
        )
        self.conn.commit()

    def delete_task(self, task_id: int):
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    def increment_pomodoro(self, task_id: int):
        self.conn.execute(
            "UPDATE tasks SET done_pomodoros = done_pomodoros + 1 WHERE id = ?",
            (task_id,),
        )
        self.conn.commit()


class Dog(QWidget):
    """Animated pet drawn with Qt. The name stays Dog, but it draws any pet in PETS.

    Awake (work time): sits up, smiling, looking at you, with an occasional blink.
    Asleep (break time): lies down with closed eyes and Z's floating up.
    Click it to make it hop.
    """

    GRID = 120  # all drawing is done on a 120 x 120 grid and scaled to the widget size

    def __init__(self, size: int, pet_key: str = "buddy"):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.pet = PETS[pet_key]
        self.sleeping = False
        self.frame = 0
        self.hop = 0
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_pet(self, pet_key: str):
        self.pet = PETS[pet_key]
        self.update()

    def set_sleeping(self, sleeping: bool):
        if sleeping != self.sleeping:
            self.sleeping = sleeping
            self.update()

    def mousePressEvent(self, event):
        self.hop = 6
        event.ignore()  # let the parent still receive drags and double-clicks

    def _tick(self):
        self.frame += 1
        if self.hop:
            self.hop -= 1
        self.update()

    # ----- drawing helpers -----

    def _draw_tail(self, p, pet, ink, fur):
        kind = pet["tail"]
        if kind == "none":
            return
        start = QPointF(88, 92)
        if self.sleeping:
            end = QPointF(106, 100)
        elif kind == "wag":
            end = QPointF(108, 66 + 5 * math.sin(self.frame * 1.2))
        elif kind == "curl":
            end = QPointF(110, 58)
        else:  # stub
            end = QPointF(96, 86)
        p.setPen(QPen(ink, 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(start, end)
        p.setPen(QPen(fur, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(start, end)

    def _draw_ears(self, p, pet, outline, fur, accent):
        kind = pet["ears"]
        p.setPen(outline)
        p.setBrush(fur)
        if kind == "floppy":
            p.setBrush(accent)
            p.drawEllipse(QRectF(10, 28, 30, 44))
            p.drawEllipse(QRectF(80, 28, 30, 44))
        elif kind == "pointy":
            p.drawPolygon(QPolygonF([QPointF(30, 44), QPointF(36, 6), QPointF(60, 30)]))
            p.drawPolygon(QPolygonF([QPointF(90, 44), QPointF(84, 6), QPointF(60, 30)]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawPolygon(QPolygonF([QPointF(38, 40), QPointF(40, 18), QPointF(54, 30)]))
            p.drawPolygon(QPolygonF([QPointF(82, 40), QPointF(80, 18), QPointF(66, 30)]))
        elif kind == "tall":
            p.drawEllipse(QRectF(32, 0, 18, 44))
            p.drawEllipse(QRectF(70, 0, 18, 44))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawEllipse(QRectF(37, 6, 8, 30))
            p.drawEllipse(QRectF(75, 6, 8, 30))

    def _draw_eyes(self, p, pet, ink):
        arc_pen = QPen(ink, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        if self.sleeping or self.frame % 28 == 0:
            # Closed eyes: sleeping, or a short blink while awake
            p.setPen(arc_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(40, 46, 14, 8), 200 * 16, 140 * 16)
            p.drawArc(QRectF(66, 46, 14, 8), 200 * 16, 140 * 16)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pet.get("eye", "#2B1B10")))
            p.drawEllipse(QRectF(40, 42, 13, 15))
            p.drawEllipse(QRectF(67, 42, 13, 15))
            p.setBrush(QColor("#FFFFFF"))  # shine, makes the eyes look alive
            p.drawEllipse(QRectF(45, 44, 4, 4))
            p.drawEllipse(QRectF(72, 44, 4, 4))

    def _draw_mouth(self, p, pet, ink):
        p.setPen(QPen(ink, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.sleeping:
            p.drawArc(QRectF(56, 66, 8, 5), 200 * 16, 140 * 16)
            return
        p.drawArc(QRectF(50, 64, 20, 12), 200 * 16, 140 * 16)
        if pet["species"] == "dog":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F4A6B8"))  # tongue
            p.drawEllipse(QRectF(56, 70, 8, 8))

    def paintEvent(self, event):
        pet = self.pet
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width(), self.height()) / self.GRID
        p.scale(scale, scale)

        ink = QColor("#222222")
        fur = QColor(pet["fur"])
        accent = QColor(pet["accent"])
        muzzle = QColor(pet["muzzle"])
        outline = QPen(ink, 2.5)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        is_cat = pet["species"] == "cat"
        sleeping = self.sleeping

        # Vertical movement: hop when clicked, lower and breathing when asleep
        bob = 0.0
        if self.hop:
            bob = -8.0 * math.sin(math.pi * self.hop / 6)
        if sleeping:
            bob += 3.0 + 0.6 * math.sin(self.frame * 0.6)

        # Ground shadow (does not move with the pet)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(22, 104, 76, 9))

        p.translate(0, bob)

        self._draw_tail(p, pet, ink, fur)

        # Body and paws
        p.setPen(outline)
        p.setBrush(fur)
        if sleeping:
            p.drawEllipse(QRectF(26, 72, 68, 34))
            p.drawEllipse(QRectF(24, 94, 18, 11))
            p.drawEllipse(QRectF(78, 94, 18, 11))
        else:
            p.drawEllipse(QRectF(32, 58, 56, 48))
            p.drawEllipse(QRectF(34, 92, 20, 14))
            p.drawEllipse(QRectF(66, 92, 20, 14))

        # Ears go behind the head
        self._draw_ears(p, pet, outline, fur, accent)

        # Head
        p.setPen(outline)
        p.setBrush(fur)
        p.drawEllipse(QRectF(26, 20, 68, 56))

        # Tabby stripes on the forehead
        if pet.get("stripes"):
            p.setPen(QPen(ink, 2))
            p.drawLine(QPointF(60, 22), QPointF(60, 30))
            p.drawLine(QPointF(51, 24), QPointF(49, 31))
            p.drawLine(QPointF(69, 24), QPointF(71, 31))

        # Muzzle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(muzzle)
        if is_cat:
            p.drawEllipse(QRectF(44, 56, 32, 20))
        else:
            p.drawEllipse(QRectF(40, 52, 40, 26))

        # Blush for cats and the bunny
        if pet["species"] in ("cat", "bunny"):
            p.setBrush(QColor(255, 138, 160, 140))
            p.drawEllipse(QRectF(28, 62, 10, 6))
            p.drawEllipse(QRectF(82, 62, 10, 6))

        self._draw_eyes(p, pet, ink)

        # Nose
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent if is_cat else ink)
        p.drawEllipse(QRectF(56, 58, 8, 6) if is_cat else QRectF(55, 58, 10, 7))

        self._draw_mouth(p, pet, ink)

        # Collar for dogs while awake
        if pet.get("collar") and not sleeping and not is_cat:
            p.setPen(QPen(QColor(pet["collar"]), 6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(38, 74, 44, 14), 200 * 16, 140 * 16)

        # Whiskers for cats while awake
        if is_cat and not sleeping:
            p.setPen(QPen(ink, 1.5))
            p.drawLine(QPointF(30, 66), QPointF(10, 62))
            p.drawLine(QPointF(30, 70), QPointF(10, 72))
            p.drawLine(QPointF(90, 66), QPointF(110, 62))
            p.drawLine(QPointF(90, 70), QPointF(110, 72))

        # Z's floating up while asleep
        if sleeping:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                t = ((self.frame + i * 4) % 12) / 12.0
                font = QFont()
                font.setBold(True)
                font.setPointSize(7 + i * 2)
                p.setFont(font)
                p.setPen(QColor(90, 140, 200, int(255 * (1 - t))))
                p.drawText(QPointF(92 + i * 8 + t * 6, 34 - t * 26), "Z")

        p.end()


class MiniTimer(QWidget):
    """Small always-on-top, frameless overlay that shows the time and a small pet.

    Drag it anywhere to move it.
    Double-click: toggles play/pause. Pausing opens the task list.
    """

    def __init__(self, on_double_click, pet_key):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.on_double_click = on_double_click
        self._drag_offset = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.label = QLabel("25:00", self)
        self.dog = Dog(56, pet_key)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label)
        layout.addWidget(self.dog, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_time("25:00", running=False)

        self.move(20, 20)  # top-left corner

    def set_time(self, text: str, running: bool, sleeping: bool = False):
        self.label.setText(text)
        self.dog.set_sleeping(sleeping)
        # Green while running, amber while paused
        color = "#7CFC90" if running else "#FFD27F"
        self.label.setStyleSheet(
            "font-size: 22px; font-weight: bold; font-family: monospace;"
            f"color: {color}; background-color: rgba(30, 30, 30, 210);"
            "padding: 4px 10px; border-radius: 6px;"
        )

    def set_pet(self, pet_key):
        self.dog.set_pet(pet_key)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_double_click()


class SettingsDialog(QDialog):
    """Timer durations and pet choice. Values are saved on OK."""

    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        # Pet picker with a live preview at the top
        pet_row = QHBoxLayout()
        self.pet_combo = QComboBox()
        for key, info in PETS.items():
            self.pet_combo.addItem(f"{info['name']} ({info['species']})", key)
        self.pet_combo.setCurrentIndex(self.pet_combo.findData(current["pet"]))
        self.preview = Dog(120, current["pet"])
        self.pet_combo.currentIndexChanged.connect(self._preview_pet)

        form = QFormLayout()
        form.addRow("Pet:", self.pet_combo)
        self.work_spin = self._spin(current["work_min"], 1, 180, " min")
        self.short_spin = self._spin(current["short_break_min"], 1, 60, " min")
        self.long_spin = self._spin(current["long_break_min"], 1, 120, " min")
        self.cycle_spin = self._spin(current["pomodoros_before_long"], 1, 10, " pomodoros")
        form.addRow("Work session:", self.work_spin)
        form.addRow("Short break:", self.short_spin)
        form.addRow("Long break:", self.long_spin)
        form.addRow("Pomodoros before long break:", self.cycle_spin)

        buttons = QHBoxLayout()
        defaults_btn = QPushButton("Defaults")
        defaults_btn.clicked.connect(self.load_defaults)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Save")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(defaults_btn)
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _preview_pet(self, _index):
        self.preview.set_pet(self.pet_combo.currentData())

    @staticmethod
    def _spin(value, low, high, suffix):
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        return spin

    def load_defaults(self):
        self.work_spin.setValue(DEFAULT_SETTINGS["work_min"])
        self.short_spin.setValue(DEFAULT_SETTINGS["short_break_min"])
        self.long_spin.setValue(DEFAULT_SETTINGS["long_break_min"])
        self.cycle_spin.setValue(DEFAULT_SETTINGS["pomodoros_before_long"])
        self.pet_combo.setCurrentIndex(self.pet_combo.findData(DEFAULT_SETTINGS["pet"]))

    def values(self):
        return {
            "work_min": self.work_spin.value(),
            "short_break_min": self.short_spin.value(),
            "long_break_min": self.long_spin.value(),
            "pomodoros_before_long": self.cycle_spin.value(),
            "pet": self.pet_combo.currentData(),
        }


class TaskPanel(QWidget):
    """Small floating task list shown under the mini timer while paused.

    Click a task to tick it off or un-tick it.
    """

    def __init__(self, main):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.main = main
        self.setStyleSheet(
            "TaskPanel { background-color: #2b2b2b; border: 1px solid #555;"
            " border-radius: 6px; }"
            "QLabel { color: #ffffff; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("<b>Tasks</b>  (click to tick off)")
        layout.addWidget(header)

        self.list = QListWidget()
        self.list.setMinimumWidth(320)
        self.list.setMinimumHeight(220)
        self.list.itemClicked.connect(self.toggle_item)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        start_btn = QPushButton("Start timer")
        start_btn.clicked.connect(self.start_timer)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        row.addWidget(start_btn)
        row.addWidget(close_btn)
        layout.addLayout(row)

    def reload(self):
        self.list.clear()
        for row in self.main.db.all_tasks():
            mark = "✔" if row["done"] else "○"
            item = QListWidgetItem(
                f"{mark}  {row['title']}   "
                f"[{row['done_pomodoros']}/{row['est_pomodoros']} 🍅]"
            )
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            if row["done"]:
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
            self.list.addItem(item)

    def toggle_item(self, item):
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.main.db.toggle_done(task_id)
        # Refresh after the click has finished, so the clicked item is not
        # deleted while Qt is still handling it.
        QTimer.singleShot(0, self.main.refresh_tasks)

    def start_timer(self):
        self.hide()
        if not self.main.running:
            self.main.toggle_running()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database(DB_PATH)
        self.settings = load_settings()

        self.setWindowTitle("Pomodoro + Todo")
        self.resize(900, 640)

        # Timer state
        self.phase = PHASE_WORK
        self.remaining = self.phase_seconds(PHASE_WORK)
        self.running = False
        self.pomodoros_in_cycle = 0  # resets after a long break
        self.current_task_id = None

        self.qtimer = QTimer(self)
        self.qtimer.setInterval(1000)
        self.qtimer.timeout.connect(self.tick)

        # System tray for notifications
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.show()

        # Sound played at each phase change
        if not CHIME_PATH.exists():
            make_chime(CHIME_PATH)
        self.sound = QSoundEffect(self)
        self.sound.setSource(QUrl.fromLocalFile(str(CHIME_PATH)))
        self.sound.setVolume(1.0)

        # Floating mini timer and its task panel (both hidden until used)
        self.mini = MiniTimer(on_double_click=self.mini_double_click,
                              pet_key=self.settings["pet"])
        self.task_panel = TaskPanel(self)

        self._build_ui()
        self.refresh_tasks()
        self.update_display()

    # ---------- UI construction ----------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # Left side: tasks
        tasks_layout = QVBoxLayout()
        tasks_layout.addWidget(QLabel("<h3>Tasks</h3>"))

        add_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("New task...")
        self.task_input.returnPressed.connect(self.add_task)
        self.est_spin = QSpinBox()
        self.est_spin.setRange(1, 20)
        self.est_spin.setValue(1)
        self.est_spin.setPrefix("est: ")
        self.est_spin.setSuffix(" 🍅")
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self.add_task)
        add_row.addWidget(self.task_input, 1)
        add_row.addWidget(self.est_spin)
        add_row.addWidget(add_btn)
        tasks_layout.addLayout(add_row)

        self.task_list = QListWidget()
        self.task_list.itemDoubleClicked.connect(self.focus_selected)
        tasks_layout.addWidget(self.task_list, 1)

        action_row = QHBoxLayout()
        focus_btn = QPushButton("Focus selected")
        focus_btn.clicked.connect(self.focus_selected)
        done_btn = QPushButton("Toggle done")
        done_btn.clicked.connect(self.toggle_selected_done)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self.delete_selected)
        action_row.addWidget(focus_btn)
        action_row.addWidget(done_btn)
        action_row.addWidget(del_btn)
        tasks_layout.addLayout(action_row)

        root.addLayout(tasks_layout, 1)

        # Right side: timer
        timer_layout = QVBoxLayout()
        timer_layout.addWidget(QLabel("<h3>Pomodoro</h3>"))

        self.focus_label = QLabel()
        self.focus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_label.setWordWrap(True)
        timer_layout.addWidget(self.focus_label)

        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("font-size: 18px;")
        timer_layout.addWidget(self.phase_label)

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            "font-size: 64px; font-weight: bold; font-family: monospace;"
        )
        timer_layout.addWidget(self.time_label)

        # The pet: looks at you while working, sleeps during breaks
        self.dog = Dog(150, self.settings["pet"])
        timer_layout.addWidget(self.dog, 0, Qt.AlignmentFlag.AlignHCenter)

        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.count_label)

        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.toggle_running)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_phase)
        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(self.finish_phase)
        controls.addWidget(self.start_btn)
        controls.addWidget(reset_btn)
        controls.addWidget(skip_btn)
        timer_layout.addLayout(controls)

        bottom = QHBoxLayout()
        self.mini_btn = QPushButton("Show mini timer")
        self.mini_btn.clicked.connect(self.toggle_mini)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings)
        bottom.addWidget(self.mini_btn)
        bottom.addWidget(settings_btn)
        timer_layout.addLayout(bottom)

        timer_layout.addStretch()
        root.addLayout(timer_layout, 1)

    # ---------- Tasks ----------

    def refresh_tasks(self):
        self.task_list.clear()
        for row in self.db.all_tasks():
            mark = "✔" if row["done"] else "○"
            text = (
                f"{mark}  {row['title']}   "
                f"[{row['done_pomodoros']}/{row['est_pomodoros']} 🍅]"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            if row["done"]:
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
            self.task_list.addItem(item)
        if self.task_panel.isVisible():
            self.task_panel.reload()
        self.update_display()

    def selected_task_id(self):
        item = self.task_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add_task(self):
        title = self.task_input.text().strip()
        if not title:
            return
        self.db.add_task(title, self.est_spin.value())
        self.task_input.clear()
        self.refresh_tasks()

    def focus_selected(self):
        task_id = self.selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "No task", "Select a task first.")
            return
        self.current_task_id = task_id
        self.update_display()

    def toggle_selected_done(self):
        task_id = self.selected_task_id()
        if task_id is None:
            return
        self.db.toggle_done(task_id)
        self.refresh_tasks()

    def delete_selected(self):
        task_id = self.selected_task_id()
        if task_id is None:
            return
        if self.current_task_id == task_id:
            self.current_task_id = None
        self.db.delete_task(task_id)
        self.refresh_tasks()

    # ---------- Timer ----------

    def phase_seconds(self, phase):
        minutes = {
            PHASE_WORK: self.settings["work_min"],
            PHASE_SHORT: self.settings["short_break_min"],
            PHASE_LONG: self.settings["long_break_min"],
        }[phase]
        return minutes * 60

    def toggle_running(self):
        self.running = not self.running
        if self.running:
            self.task_panel.hide()
            self.qtimer.start()
        else:
            self.qtimer.stop()
        self.update_display()

    def tick(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.finish_phase()
        else:
            self.update_display()

    def reset_phase(self):
        self.qtimer.stop()
        self.running = False
        self.remaining = self.phase_seconds(self.phase)
        self.update_display()

    def finish_phase(self):
        """Called when a phase completes (or when the user presses Skip)."""
        self.qtimer.stop()
        self.running = False
        cycle = self.settings["pomodoros_before_long"]

        if self.phase == PHASE_WORK:
            self.pomodoros_in_cycle += 1
            if self.current_task_id is not None:
                self.db.increment_pomodoro(self.current_task_id)
                self.refresh_tasks()

            if self.pomodoros_in_cycle % cycle == 0:
                self.phase = PHASE_LONG
                self.notify("Pomodoro complete!",
                            f"Time for a long break ({self.settings['long_break_min']} min).")
            else:
                self.phase = PHASE_SHORT
                self.notify("Pomodoro complete!",
                            f"Time for a short break ({self.settings['short_break_min']} min).")
        else:
            self.phase = PHASE_WORK
            self.notify("Break over!",
                        f"Back to work ({self.settings['work_min']} min).")

        self.remaining = self.phase_seconds(self.phase)
        self.update_display()

    def notify(self, title, message):
        self.sound.play()
        self.tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 6000
        )

    def update_display(self):
        mins, secs = divmod(self.remaining, 60)
        self.time_label.setText(f"{mins:02d}:{secs:02d}")
        self.phase_label.setText(self.phase.title())
        self.start_btn.setText("Pause" if self.running else "Start")

        # The pet sleeps during breaks and looks at you while working
        sleeping = self.phase != PHASE_WORK
        self.dog.set_sleeping(sleeping)
        self.mini.set_time(self.time_label.text(), self.running, sleeping)

        if self.current_task_id is not None:
            task = self.db.get_task(self.current_task_id)
            if task:
                self.focus_label.setText(f"Focus: {task['title']}")
            else:
                self.current_task_id = None
                self.focus_label.setText("No task focused")
        else:
            self.focus_label.setText("No task focused (select one and click Focus)")

        cycle = self.settings["pomodoros_before_long"]
        in_cycle = self.pomodoros_in_cycle % cycle
        self.count_label.setText(
            f"Pomodoros today: {self.pomodoros_in_cycle}   "
            f"(cycle {in_cycle}/{cycle})"
        )

    # ---------- Settings ----------

    def open_settings(self):
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings = dialog.values()
        save_settings(self.settings)
        # Apply the chosen pet to both the main window and the mini timer
        self.dog.set_pet(self.settings["pet"])
        self.mini.set_pet(self.settings["pet"])
        # If the timer is stopped, show the new length of the current phase right away.
        # If it is running, the new length applies from the next phase.
        if not self.running:
            self.remaining = self.phase_seconds(self.phase)
        self.update_display()

    # ---------- Mini timer and task panel ----------

    def mini_double_click(self):
        """Double-click on the mini timer: play/pause. The task list opens on pause."""
        self.toggle_running()
        if self.running:
            self.task_panel.hide()
        else:
            self.open_task_panel()

    def open_task_panel(self):
        self.task_panel.reload()
        self.task_panel.adjustSize()
        # Place the panel just below the mini timer
        self.task_panel.move(self.mini.x(), self.mini.y() + self.mini.height() + 6)
        self.task_panel.show()
        self.task_panel.raise_()

    def toggle_mini(self):
        if self.mini.isVisible():
            self.mini.hide()
            self.task_panel.hide()
            self.mini_btn.setText("Show mini timer")
        else:
            self.mini.show()
            self.mini_btn.setText("Hide mini timer")

    def closeEvent(self, event):
        self.task_panel.close()
        self.mini.close()
        self.db.conn.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()