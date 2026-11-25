"""
Ghost Recorder Bangla — PySide6 desktop app.

Screen recorder + screenshot tool with a dark Bangla UI.

Run:
    pip install -r requirements.txt
    python app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTime, QTimer, QUrl, Signal, QObject
from PySide6.QtGui import QDesktopServices, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QStatusBar, QTimeEdit, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recorder import (  # noqa: E402
    RecorderError, ScreenRecorder,
    capture_region_image, capture_screenshot_image, check_webcam_available,
    export_video_to_gif, save_pil_image,
)
from scheduler import RecordingScheduler  # noqa: E402

APP_TITLE = "Ghost Recorder Bangla — স্ক্রিন রেকর্ডার"
APP_VERSION = "1.1.0"
DEFAULT_DIR = Path.home() / "Videos" / "GhostRecorderBangla"
WEBCAM_CORNERS = [
    ("bottom-right", "নিচে ডানে"),
    ("bottom-left", "নিচে বামে"),
    ("top-right", "উপরে ডানে"),
    ("top-left", "উপরে বামে"),
]

DARK_STYLE = """
QWidget { background-color: #12141a; color: #e8eaf0; font-size: 14px; }
QPushButton {
    background-color: #2b6cb0; color: white; border: none;
    border-radius: 8px; padding: 10px 14px; font-weight: bold;
}
QPushButton:hover { background-color: #3182ce; }
QPushButton:disabled { background-color: #3a3f4b; color: #9aa0ae; }
QPushButton#danger { background-color: #c53030; }
QPushButton#danger:hover { background-color: #e53e3e; }
QPushButton#secondary { background-color: #2d3748; }
QPushButton#secondary:hover { background-color: #4a5568; }
QSpinBox, QListWidget {
    background-color: #1e222c; border: 1px solid #3a3f4b;
    border-radius: 6px; padding: 6px;
}
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background-color: #2b6cb0; }
QLabel#timer { font-size: 28px; font-weight: bold; color: #63b3ed; }
QLabel#heading { font-size: 18px; font-weight: bold; }
"""


class _ElapsedBridge(QObject):
    """Thread-safe bridge: recorder thread -> GUI thread."""
    elapsed = Signal(int)


# ---------------------------------------------------------------------------
# v1.1.0 — screenshot annotation editor (PySide6 canvas)
# ---------------------------------------------------------------------------

def _pil_to_pixmap(image) -> QPixmap:
    """Convert a Pillow RGB image to a QPixmap."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    qimg = QImage(image.tobytes(), image.width, image.height,
                  image.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _pixmap_to_pil(pixmap: QPixmap):
    """Convert a QPixmap back to a Pillow RGB image."""
    from PIL import Image

    qimg = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
    width, height = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(height * width * 3)
    return Image.frombytes("RGB", (width, height), bytes(ptr))


class _AnnotateCanvas(QWidget):
    """Mouse-driven drawing surface: pen, arrow, or click-to-place text."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setFixedSize(pixmap.width(), pixmap.height())
        self.tool = "pen"
        self.color = "#ff0000"
        self.width = 3
        self._drawing = False
        self._points: list = []
        self._preview: list = []
        self._undo_stack: list[QPixmap] = []

    # -- state -------------------------------------------------------------
    def pixmap(self) -> QPixmap:
        return self._pixmap

    def set_tool(self, tool: str) -> None:
        self.tool = tool

    def set_color(self, color: str) -> None:
        self.color = color

    def set_width(self, width: int) -> None:
        self.width = max(1, int(width))

    def _push_undo(self) -> None:
        self._undo_stack.append(self._pixmap.copy())
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)

    def undo(self) -> None:
        if self._undo_stack:
            self._pixmap = self._undo_stack.pop()
            self.update()

    def clear(self) -> None:
        self._push_undo()
        # Rebuild from the original pixmap is the caller's job; here we
        # simply drop all strokes by restoring the oldest snapshot.
        if self._undo_stack:
            self._pixmap = self._undo_stack[0]
            self._undo_stack = []
        self.update()

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        pts = self._preview or self._points
        if len(pts) >= 2 and self.tool in ("pen", "arrow"):
            from PySide6.QtGui import QColor

            painter.setPen(QPen(QColor(self.color), self.width,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            if self.tool == "pen":
                for a, b in zip(pts, pts[1:]):
                    painter.drawLine(a[0], a[1], b[0], b[1])
            else:
                painter.drawLine(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])

    def _apply_stroke(self) -> None:
        """Commit the current stroke onto the pixmap."""
        if self.tool == "text" or len(self._points) < 1:
            return
        self._push_undo()
        painter = QPainter(self._pixmap)
        from PySide6.QtGui import QColor

        painter.setPen(QPen(QColor(self.color), self.width,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        if self.tool == "pen":
            if len(self._points) >= 2:
                for a, b in zip(self._points, self._points[1:]):
                    painter.drawLine(a[0], a[1], b[0], b[1])
            else:
                x, y = self._points[0]
                painter.drawPoint(x, y)
        elif self.tool == "arrow" and len(self._points) >= 2:
            import math

            (x1, y1), (x2, y2) = self._points[0], self._points[-1]
            painter.drawLine(x1, y1, x2, y2)
            angle = math.atan2(y2 - y1, x2 - x1)
            head = max(10.0, self.width * 4.0)
            for delta in (math.pi - 0.45, math.pi + 0.45):
                a = angle + delta
                painter.drawLine(x2, y2,
                                 int(x2 + head * math.cos(a)),
                                 int(y2 + head * math.sin(a)))
        painter.end()

    # -- mouse -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = (event.position().x(), event.position().y())
        if self.tool == "text":
            text, ok = QInputDialog.getText(
                self, "টেক্সট লিখুন", "ছবিতে বসানোর টেক্সট:")
            if ok and text:
                self._push_undo()
                painter = QPainter(self._pixmap)
                from PySide6.QtGui import QColor, QFont

                font = QFont()
                font.setPointSize(max(12, self.width * 6))
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor(self.color))
                painter.drawText(int(pos[0]), int(pos[1]), text)
                painter.end()
                self.update()
            return
        self._drawing = True
        self._points = [pos]
        self._preview = [pos]

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._drawing:
            return
        self._points.append((event.position().x(), event.position().y()))
        self._preview = list(self._points)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._drawing:
            return
        self._drawing = False
        self._preview = []
        self._apply_stroke()
        self._points = []
        self.update()


class AnnotateDialog(QDialog):
    """Edit a screenshot (pen / arrow / text) before saving it."""

    def __init__(self, pil_image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("স্ক্রিনশট এডিট করুন — আঁকুন, তীর, টেক্সট")
        self.setMinimumSize(700, 560)
        self._original = pil_image
        self.canvas = _AnnotateCanvas(_pil_to_pixmap(pil_image), self)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["কলম (Pen)", "তীর (Arrow)", "টেক্সট (Text)"])
        self.tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        toolbar.addWidget(self.tool_combo)

        self.color_combo = QComboBox()
        for name, code in [("লাল", "#ff0000"), ("সবুজ", "#00c853"),
                           ("নীল", "#2962ff"), ("হলুদ", "#ffd600"),
                           ("সাদা", "#ffffff"), ("কালো", "#000000")]:
            self.color_combo.addItem(name, code)
        self.color_combo.currentIndexChanged.connect(
            lambda i: self.canvas.set_color(self.color_combo.currentData()))
        toolbar.addWidget(self.color_combo)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20)
        self.width_spin.setValue(3)
        self.width_spin.setPrefix("মোটা: ")
        self.width_spin.valueChanged.connect(self.canvas.set_width)
        toolbar.addWidget(self.width_spin)

        undo_btn = QPushButton("↩ Undo")
        undo_btn.clicked.connect(self.canvas.undo)
        toolbar.addWidget(undo_btn)
        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        layout.addWidget(scroll, stretch=1)

        hint = QLabel("কলম/তীর: মাউস টেনে আঁকুন। টেক্সট: ছবিতে ক্লিক করে লিখুন। "
                      "সেভ করলে এডিট করা ছবিটাই PNG হবে।")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_tool_changed(self, index: int) -> None:
        self.canvas.set_tool(["pen", "arrow", "text"][index])

    def annotated_image(self):
        """Return the edited screenshot as a Pillow image."""
        return _pixmap_to_pil(self.canvas.pixmap())



class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(560, 620)

        self.save_dir = DEFAULT_DIR
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.recorder: ScreenRecorder | None = None
        self.recording_path: str = ""
        self.last_recording_path: str = ""
        self._seconds = 0

        # v1.1.0 — scheduled recording (persisted to schedule.json).
        self.scheduler = RecordingScheduler(self.save_dir / "schedule.json")

        # Live timer (driven by the GUI thread, not the capture thread).
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(1000)
        self._ui_timer.timeout.connect(self._tick)

        # Scheduler check: every 5s, is a scheduled recording due?
        self._sched_timer = QTimer(self)
        self._sched_timer.setInterval(5000)
        self._sched_timer.timeout.connect(self._check_schedule)
        self._sched_timer.start()

        self._bridge = _ElapsedBridge()
        self._bridge.elapsed.connect(self._on_recorder_elapsed)

        self._build_ui()
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("প্রস্তুত — Ready")
        self._refresh_buttons()
        self._refresh_schedule_label()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(f"👻 Ghost Recorder Bangla  v{APP_VERSION}")
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("স্ক্রিন রেকর্ড + স্ক্রিনশট — Screen recorder & screenshots")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        # Save location
        save_row = QHBoxLayout()
        self.save_label = QLabel(f"📁 {self.save_dir}")
        self.save_label.setWordWrap(True)
        save_row.addWidget(self.save_label, stretch=1)
        choose_btn = QPushButton("ফোল্ডার বদলান")
        choose_btn.setObjectName("secondary")
        choose_btn.clicked.connect(self._choose_folder)
        save_row.addWidget(choose_btn)
        layout.addLayout(save_row)

        # Timer
        self.timer_label = QLabel("00:00")
        self.timer_label.setObjectName("timer")
        self.timer_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.timer_label)

        # Recording controls
        rec_row = QHBoxLayout()
        self.start_btn = QPushButton("● রেকর্ড শুরু")
        self.start_btn.clicked.connect(self._start_recording)
        rec_row.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.clicked.connect(self._pause_recording)
        rec_row.addWidget(self.pause_btn)

        self.resume_btn = QPushButton("▶ Resume")
        self.resume_btn.clicked.connect(self._resume_recording)
        rec_row.addWidget(self.resume_btn)

        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self._stop_recording)
        rec_row.addWidget(self.stop_btn)
        layout.addLayout(rec_row)

        # v1.1.0 — webcam overlay (honestly disabled when no camera/OpenCV).
        self.webcam_available, webcam_reason = check_webcam_available()
        cam_row = QHBoxLayout()
        self.webcam_chk = QCheckBox("📷 ওয়েবক্যাম ওভারলে (ছোট ছবি কোণায়)")
        self.webcam_chk.setEnabled(self.webcam_available)
        self.webcam_chk.setToolTip(webcam_reason)
        cam_row.addWidget(self.webcam_chk)
        self.cam_corner_combo = QComboBox()
        for value, label in WEBCAM_CORNERS:
            self.cam_corner_combo.addItem(label, value)
        self.cam_corner_combo.setEnabled(self.webcam_available)
        cam_row.addWidget(self.cam_corner_combo)
        layout.addLayout(cam_row)
        self.webcam_status = QLabel(
            "ওয়েবক্যাম প্রস্তুত।" if self.webcam_available else webcam_reason)
        self.webcam_status.setWordWrap(True)
        layout.addWidget(self.webcam_status)

        # v1.1.0 — GIF export of the last recording.
        gif_btn = QPushButton("🎞 শেষ রেকর্ডিং GIF করুন")
        gif_btn.setObjectName("secondary")
        gif_btn.clicked.connect(self._export_gif)
        layout.addWidget(gif_btn)

        # Screenshot: full screen
        shot_btn = QPushButton("📷 স্ক্রিনশট (পুরো স্ক্রিন)")
        shot_btn.clicked.connect(self._screenshot_full)
        layout.addWidget(shot_btn)

        # Screenshot: region
        region_label = QLabel("রিজিয়ন স্ক্রিনশট — Region screenshot (x, y, প্রস্থ, উচ্চতা):")
        layout.addWidget(region_label)
        region_row = QHBoxLayout()
        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 100000)
        self.x_spin.setPrefix("X: ")
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 100000)
        self.y_spin.setPrefix("Y: ")
        self.w_spin = QSpinBox()
        self.w_spin.setRange(1, 100000)
        self.w_spin.setValue(800)
        self.w_spin.setPrefix("W: ")
        self.h_spin = QSpinBox()
        self.h_spin.setRange(1, 100000)
        self.h_spin.setValue(600)
        self.h_spin.setPrefix("H: ")
        for spin in (self.x_spin, self.y_spin, self.w_spin, self.h_spin):
            region_row.addWidget(spin)
        layout.addLayout(region_row)
        region_btn = QPushButton("📷 রিজিয়ন ক্যাপচার করুন")
        region_btn.setObjectName("secondary")
        region_btn.clicked.connect(self._screenshot_region)
        layout.addWidget(region_btn)

        # v1.1.0 — scheduled recording (starts automatically at a set time).
        sched_box = QGroupBox("⏰ নির্ধারিত রেকর্ডিং — Scheduled recording")
        sched_layout = QVBoxLayout(sched_box)
        sched_row = QHBoxLayout()
        sched_row.addWidget(QLabel("সময়:"))
        self.sched_time = QTimeEdit()
        self.sched_time.setDisplayFormat("HH:mm")
        self.sched_time.setTime(QTime(
            int(self.scheduler.time_str.split(":")[0]),
            int(self.scheduler.time_str.split(":")[1])))
        sched_row.addWidget(self.sched_time)
        sched_row.addWidget(QLabel("সময়কাল (মিনিট, ০ = নিজে থামাবেন):"))
        self.sched_duration = QSpinBox()
        self.sched_duration.setRange(0, 480)
        self.sched_duration.setValue(self.scheduler.duration_minutes)
        sched_row.addWidget(self.sched_duration)
        self.sched_enable = QCheckBox("চালু")
        self.sched_enable.setChecked(self.scheduler.enabled)
        self.sched_enable.toggled.connect(self._on_schedule_changed)
        sched_row.addWidget(self.sched_enable)
        save_sched_btn = QPushButton("সংরক্ষণ করুন")
        save_sched_btn.setObjectName("secondary")
        save_sched_btn.clicked.connect(self._on_schedule_changed)
        sched_row.addWidget(save_sched_btn)
        sched_layout.addLayout(sched_row)
        self.sched_status = QLabel("")
        self.sched_status.setWordWrap(True)
        sched_layout.addWidget(self.sched_status)
        layout.addWidget(sched_box)

        # History
        layout.addWidget(QLabel("ইতিহাস — History (খুলতে ডাবল ক্লিক করুন):"))
        self.history = QListWidget()
        self.history.itemDoubleClicked.connect(self._open_history_item)
        layout.addWidget(self.history, stretch=1)

        open_folder_btn = QPushButton("📂 সংরক্ষণের ফোল্ডার খুলুন")
        open_folder_btn.setObjectName("secondary")
        open_folder_btn.clicked.connect(lambda: self._open_path(str(self.save_dir)))
        layout.addWidget(open_folder_btn)

    # -- helpers -----------------------------------------------------------
    def _refresh_buttons(self) -> None:
        recording = self.recorder is not None
        paused = bool(self.recorder and self.recorder.is_paused)
        self.start_btn.setEnabled(not recording)
        self.pause_btn.setEnabled(recording and not paused)
        self.resume_btn.setEnabled(recording and paused)
        self.stop_btn.setEnabled(recording)

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.warning(self, title, str(exc))
        self.statusBar().showMessage(f"ত্রুটি: {exc}")

    def _add_to_history(self, path: str) -> None:
        item = QListWidgetItem(f"{Path(path).name}  —  {path}")
        item.setData(Qt.UserRole, path)
        self.history.insertItem(0, item)

    def _open_path(self, path: str) -> None:
        if not Path(path).exists():
            QMessageBox.warning(self, "পাওয়া যায়নি", f"ফাইল/ফোল্ডার নেই:\n{path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            # Fallback for systems where QDesktopServices fails.
            try:
                if sys.platform.startswith("win"):
                    os.startfile(path)  # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.run(["open", path], check=False)
                else:
                    subprocess.run(["xdg-open", path], check=False)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "খোলা যায়নি", str(exc))

    def _format_time(self, seconds: int) -> str:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    # -- slots -------------------------------------------------------------
    def _tick(self) -> None:
        self._seconds += 1
        self.timer_label.setText(self._format_time(self._seconds))

    def _on_recorder_elapsed(self, seconds: int) -> None:
        # Recorder thread reports elapsed; keep the GUI timer in sync.
        self._seconds = seconds
        self.timer_label.setText(self._format_time(seconds))

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "সংরক্ষণের ফোল্ডার বেছে নিন", str(self.save_dir))
        if folder:
            self.save_dir = Path(folder)
            self.save_dir.mkdir(parents=True, exist_ok=True)
            self.save_label.setText(f"📁 {self.save_dir}")
            self.statusBar().showMessage(f"ফোল্ডার: {self.save_dir}")

    def _start_recording(self) -> None:
        try:
            self.recorder = ScreenRecorder(
                self.save_dir, fps=15,
                on_elapsed=self._bridge.elapsed.emit,
                webcam_enabled=self.webcam_chk.isChecked(),
                webcam_corner=self.cam_corner_combo.currentData(),
            )
            self.recording_path = self.recorder.start()
        except RecorderError as exc:
            self.recorder = None
            self._show_error("রেকর্ডিং শুরু হয়নি", exc)
            return
        self._seconds = 0
        self.timer_label.setText("00:00")
        self._ui_timer.start()
        self.statusBar().showMessage(f"🔴 রেকর্ড হচ্ছে… {self.recording_path}")
        self._refresh_buttons()

    def _pause_recording(self) -> None:
        if not self.recorder:
            return
        try:
            self.recorder.pause()
        except RecorderError as exc:
            self._show_error("Pause হয়নি", exc)
            return
        self._ui_timer.stop()
        self.statusBar().showMessage("⏸ Pause — রেকর্ড বন্ধ আছে")
        self._refresh_buttons()

    def _resume_recording(self) -> None:
        if not self.recorder:
            return
        try:
            self.recorder.resume()
        except RecorderError as exc:
            self._show_error("Resume হয়নি", exc)
            return
        self._ui_timer.start()
        self.statusBar().showMessage("🔴 রেকর্ড হচ্ছে…")
        self._refresh_buttons()

    def _stop_recording(self) -> None:
        if not self.recorder:
            return
        self._ui_timer.stop()
        try:
            path = self.recorder.stop()
        except RecorderError as exc:
            self.recorder = None
            self._show_error("Stop হয়নি", exc)
            self._refresh_buttons()
            return
        self.recorder = None
        self.timer_label.setText("00:00")
        self._seconds = 0
        if path:
            self.last_recording_path = path
            self._add_to_history(path)
            self.statusBar().showMessage(f"✅ সংরক্ষিত: {path}")
        else:
            self.statusBar().showMessage("রেকর্ডিং শেষ হয়েছে")
        self._refresh_buttons()

    def _screenshot_full(self) -> None:
        try:
            image = capture_screenshot_image()
        except RecorderError as exc:
            self._show_error("স্ক্রিনশট হয়নি", exc)
            return
        self._annotate_and_save(image, "screenshot")

    def _screenshot_region(self) -> None:
        try:
            image = capture_region_image(
                self.x_spin.value(), self.y_spin.value(),
                self.w_spin.value(), self.h_spin.value())
        except RecorderError as exc:
            self._show_error("রিজিয়ন স্ক্রিনশট হয়নি", exc)
            return
        self._annotate_and_save(image, "screenshot-region")

    def _annotate_and_save(self, image, prefix: str) -> None:
        """Open the annotation editor; save the (possibly edited) image.

        Cancelling the editor discards the screenshot — nothing is saved.
        """
        from datetime import datetime

        dialog = AnnotateDialog(image, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("স্ক্রিনশট বাতিল করা হয়েছে")
            return
        edited = dialog.annotated_image()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.save_dir / f"{prefix}-{stamp}.png"
        try:
            saved = save_pil_image(edited, path)
        except Exception as exc:  # noqa: BLE001
            self._show_error("স্ক্রিনশট সেভ হয়নি", exc)
            return
        self._add_to_history(saved)
        self.statusBar().showMessage(f"✅ স্ক্রিনশট সংরক্ষিত: {saved}")

    def _export_gif(self) -> None:
        """Export the last recording (or a picked video) as an animated GIF."""
        source = self.last_recording_path
        if not source or not Path(source).exists():
            picked, _ = QFileDialog.getOpenFileName(
                self, "GIF করার ভিডিও বেছে নিন", str(self.save_dir),
                "Videos (*.mp4 *.webm);;All files (*)")
            if not picked:
                return
            source = picked
        gif_path = Path(source).with_suffix(".gif")
        try:
            saved = export_video_to_gif(source, gif_path, fps=10, width=480)
        except RecorderError as exc:
            self._show_error("GIF হয়নি", exc)
            return
        self._add_to_history(saved)
        self.statusBar().showMessage(f"✅ GIF সংরক্ষিত: {saved}")

    # -- scheduled recording (v1.1.0) --------------------------------------
    def _on_schedule_changed(self) -> None:
        time_str = self.sched_time.time().toString("HH:mm")
        try:
            self.scheduler.set(time_str, self.sched_duration.value(),
                               self.sched_enable.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, "সময়সূচি সঠিক নয়", str(exc))
            return
        self._refresh_schedule_label()
        self.statusBar().showMessage("⏰ সময়সূচি সংরক্ষিত হয়েছে")

    def _refresh_schedule_label(self) -> None:
        if not self.scheduler.enabled:
            self.sched_status.setText("নির্ধারিত রেকর্ডিং বন্ধ আছে।")
            return
        self.sched_status.setText(
            f"পরের রেকর্ডিং: {self.scheduler.time_str} — "
            f"আর {self.scheduler.countdown_text()} বাকি"
            + (f" (সময়কাল {self.scheduler.duration_minutes} মিনিট)"
               if self.scheduler.duration_minutes else " (নিজে থামাতে হবে)"))

    def _check_schedule(self) -> None:
        self._refresh_schedule_label()
        if self.recorder is not None:
            return  # already recording — never start a second one
        if not self.scheduler.due():
            return
        self.statusBar().showMessage(
            f"⏰ নির্ধারিত সময় — রেকর্ডিং শুরু হচ্ছে ({self.scheduler.time_str})")
        self._start_recording()
        duration = self.scheduler.duration_minutes
        if duration > 0 and self.recorder is not None:
            QTimer.singleShot(duration * 60 * 1000, self._stop_recording)

    def _open_history_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self._open_path(str(path))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:  # noqa: BLE001 - closing must not fail
                pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
