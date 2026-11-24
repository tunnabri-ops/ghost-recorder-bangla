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

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QObject
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QStatusBar, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recorder import (  # noqa: E402
    RecorderError, ScreenRecorder, take_region_screenshot, take_screenshot,
)

APP_TITLE = "Ghost Recorder Bangla — স্ক্রিন রেকর্ডার"
DEFAULT_DIR = Path.home() / "Videos" / "GhostRecorderBangla"

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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(560, 620)

        self.save_dir = DEFAULT_DIR
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.recorder: ScreenRecorder | None = None
        self.recording_path: str = ""
        self._seconds = 0

        # Live timer (driven by the GUI thread, not the capture thread).
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(1000)
        self._ui_timer.timeout.connect(self._tick)

        self._bridge = _ElapsedBridge()
        self._bridge.elapsed.connect(self._on_recorder_elapsed)

        self._build_ui()
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("প্রস্তুত — Ready")
        self._refresh_buttons()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("👻 Ghost Recorder Bangla")
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
            self._add_to_history(path)
            self.statusBar().showMessage(f"✅ সংরক্ষিত: {path}")
        else:
            self.statusBar().showMessage("রেকর্ডিং শেষ হয়েছে")
        self._refresh_buttons()

    def _screenshot_full(self) -> None:
        try:
            path = take_screenshot(self.save_dir)
        except RecorderError as exc:
            self._show_error("স্ক্রিনশট হয়নি", exc)
            return
        self._add_to_history(path)
        self.statusBar().showMessage(f"✅ স্ক্রিনশট সংরক্ষিত: {path}")

    def _screenshot_region(self) -> None:
        try:
            path = take_region_screenshot(
                self.x_spin.value(), self.y_spin.value(),
                self.w_spin.value(), self.h_spin.value(),
                self.save_dir,
            )
        except RecorderError as exc:
            self._show_error("রিজিয়ন স্ক্রিনশট হয়নি", exc)
            return
        self._add_to_history(path)
        self.statusBar().showMessage(f"✅ রিজিয়ন স্ক্রিনশট সংরক্ষিত: {path}")

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
