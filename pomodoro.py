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
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
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

DEFAULT_SETTINGS = {
    "work_min": 25,
    "short_break_min": 5,
    "long_break_min": 15,
    "pomodoros_before_long": 4,
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
            if key in saved and isinstance(saved[key], int) and saved[key] > 0:
                settings[key] = saved[key]
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


class SettingsDialog(QDialog):
    """Lets the user change the timer durations. Values are saved on OK."""

    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Timer settings")
        self.setModal(True)

        form = QFormLayout()
        self.work_spin = self._spin(current["work_min"], 1, 180, " min")
        self.short_spin = self._spin(current["short_break_min"], 1, 60, " min")
        self.long_spin = self._spin(current["long_break_min"], 1, 120, " min")
        self.cycle_spin = self._spin(current["pomodoros_before_long"], 1, 10, " pomodoros")
        form.addRow("Work session:", self.work_spin)
        form.addRow("Short break:", self.short_spin)
        form.addRow("Long break:", self.long_spin)
        form.addRow("Pomodoros before long break:", self.cycle_spin)

        buttons = QHBoxLayout()
        defaults_btn = QPushButton("Defaults (25 / 5 / 15 / 4)")
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
        layout.addLayout(form)
        layout.addLayout(buttons)

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

    def values(self):
        return {
            "work_min": self.work_spin.value(),
            "short_break_min": self.short_spin.value(),
            "long_break_min": self.long_spin.value(),
            "pomodoros_before_long": self.cycle_spin.value(),
        }


class Character(QWidget):
    """Small animated character.

    Typing on a keyboard while focusing, sleeping with ZZZ while resting.
    """

    def __init__(self):
        super().__init__()
        self.setFixedSize(120, 100)
        self.typing = False
        self.frame = 0
        self._anim = QTimer(self)
        self._anim.setInterval(350)
        self._anim.timeout.connect(self._advance)
        self._anim.start()

    def set_typing(self, typing: bool):
        if typing != self.typing:
            self.typing = typing
            self.update()

    def _advance(self):
        self.frame += 1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        # Desk and keyboard
        p.setBrush(QColor("#8B5A2B"))
        p.drawRoundedRect(QRectF(6, 80, 108, 10), 4, 4)
        p.setBrush(QColor("#555555"))
        p.drawRoundedRect(QRectF(34, 72, 52, 8), 2, 2)

        # Body
        p.setBrush(QColor("#4FC3F7"))
        p.drawEllipse(QRectF(40, 44, 40, 32))

        # Head (drops a little when sleeping)
        head_y = 22 if self.typing else 28
        p.setBrush(QColor("#FFE0B2"))
        p.drawEllipse(QRectF(38, head_y, 44, 36))

        # Eyes
        if self.typing:
            p.setBrush(QColor("#333333"))
            p.drawEllipse(QRectF(50, head_y + 14, 5, 5))
            p.drawEllipse(QRectF(65, head_y + 14, 5, 5))
        else:
            eye_pen = QPen(QColor("#333333"), 2)
            eye_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(eye_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(48, head_y + 14, 8, 6), 200 * 16, 140 * 16)
            p.drawArc(QRectF(64, head_y + 14, 8, 6), 200 * 16, 140 * 16)

        # Arms
        arm_pen = QPen(QColor("#FFE0B2"), 7)
        arm_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arm_pen)
        if self.typing:
            # Hands alternate up and down to look like typing
            left_y = 68 if self.frame % 2 == 0 else 72
            right_y = 72 if self.frame % 2 == 0 else 68
            p.drawLine(QPointF(40, 58), QPointF(42, left_y))
            p.drawLine(QPointF(80, 58), QPointF(78, right_y))
        else:
            p.drawLine(QPointF(40, 60), QPointF(30, 74))
            p.drawLine(QPointF(80, 60), QPointF(90, 74))

        # ZZZ rising from the head while sleeping
        if not self.typing:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                t = ((self.frame + i * 4) % 12) / 12.0
                font = QFont()
                font.setBold(True)
                font.setPointSize(8 + i * 2)
                p.setFont(font)
                p.setPen(QColor(179, 229, 252, int(255 * (1 - t))))
                x = 84 + i * 6 + t * 8
                y = 34 - t * 28
                p.drawText(QPointF(x, y), "Z")

        p.end()


class Pet(QWidget):
    """Small 2D dog next to the mini timer.

    Running: trots and wags its tail. Paused: lies down asleep with Z's.
    Click it to make it jump.
    """

    def __init__(self):
        super().__init__()
        self.setFixedSize(60, 46)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.running = False
        self.frame = 0
        self.jump_frames = 0
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_running(self, running: bool):
        if running != self.running:
            self.running = running
            self.update()

    def jump(self):
        self.jump_frames = 6

    def mousePressEvent(self, event):
        self.jump()
        event.ignore()  # let the mini timer still receive drags and double-clicks

    def _tick(self):
        self.frame += 1
        if self.jump_frames:
            self.jump_frames -= 1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        fur = QColor("#D7A86E")
        dark = QColor("#4A3520")

        # Vertical position: bob while running, lower while lying down, hop when jumping
        if self.running:
            base = 1.5 * math.sin(self.frame * 0.9)
        else:
            base = 4.0
        if self.jump_frames:
            base -= 8.0 * math.sin(math.pi * self.jump_frames / 6)

        # Ground shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QRectF(10, 40, 40, 5))

        # Tail
        wag = 5 * math.sin(self.frame * 1.2) if self.running else 1.0
        tail_pen = QPen(fur, 4)
        tail_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(tail_pen)
        p.drawLine(QPointF(12, 24 + base), QPointF(6, 16 + base + wag))

        # Legs (alternate while running)
        swing = 3 * math.sin(self.frame * 1.1) if self.running else 0.0
        leg_pen = QPen(fur, 3)
        leg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(leg_pen)
        p.drawLine(QPointF(16, 30 + base), QPointF(16 + swing, 40))
        p.drawLine(QPointF(22, 30 + base), QPointF(22 - swing, 40))
        p.drawLine(QPointF(34, 30 + base), QPointF(34 - swing, 40))
        p.drawLine(QPointF(38, 30 + base), QPointF(38 + swing, 40))

        # Body
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fur)
        p.drawEllipse(QRectF(10, 20 + base, 32, 14))

        # Head and ear
        p.drawEllipse(QRectF(34, 10 + base, 16, 14))
        p.setBrush(dark)
        p.drawEllipse(QRectF(40, 9 + base, 6, 8))

        # Snout and nose
        p.setBrush(QColor("#E8C48F"))
        p.drawEllipse(QRectF(46, 17 + base, 7, 5))
        p.setBrush(dark)
        p.drawEllipse(QRectF(50, 17 + base, 3, 3))

        # Eye: open dot while running, closed arc while sleeping
        if self.running:
            p.drawEllipse(QRectF(41, 14 + base, 3, 3))
        else:
            eye_pen = QPen(dark, 1.5)
            eye_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(eye_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(40, 15 + base, 5, 3), 200 * 16, 140 * 16)

        # Z's rising while asleep
        if not self.running:
            p.setPen(Qt.PenStyle.NoPen)
            font = QFont()
            font.setBold(True)
            font.setPointSize(7)
            p.setFont(font)
            for i in range(2):
                t = ((self.frame + i * 5) % 10) / 10.0
                p.setPen(QColor(150, 210, 255, int(255 * (1 - t))))
                p.drawText(QPointF(44 + i * 4 + t * 4, 8 - t * 8), "Z")

        p.end()


class MiniTimer(QWidget):
    """Small always-on-top, frameless overlay that shows the time and a small dog.

    Drag it anywhere to move it.
    Double-click: toggles play/pause. Pausing opens the task list.
    """

    def __init__(self, on_double_click):
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
        self.pet = Pet()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label)
        layout.addWidget(self.pet, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_time("25:00", running=False)

        self.move(20, 20)  # top-left corner

    def set_time(self, text: str, running: bool):
        self.label.setText(text)
        self.pet.set_running(running)
        # Green while running, amber while paused
        color = "#7CFC90" if running else "#FFD27F"
        self.label.setStyleSheet(
            "font-size: 22px; font-weight: bold; font-family: monospace;"
            f"color: {color}; background-color: rgba(30, 30, 30, 210);"
            "padding: 4px 10px; border-radius: 6px;"
        )

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
        self.resize(900, 560)

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
        self.mini = MiniTimer(on_double_click=self.mini_double_click)
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

        # Animated character: types while focusing, sleeps while resting
        self.character = Character()
        timer_layout.addWidget(self.character, 0, Qt.AlignmentFlag.AlignHCenter)

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
        self.mini.set_time(self.time_label.text(), self.running)
        # Typing only during a running work session; sleeping otherwise
        self.character.set_typing(self.running and self.phase == PHASE_WORK)

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