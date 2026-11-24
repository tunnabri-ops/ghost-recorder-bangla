"""
Ghost Recorder Bangla — recording / screenshot engine.

No GUI imports in this file, so it can be imported and tested headless.
Screen capture uses ``mss``; MP4 writing uses ``imageio`` + ``imageio-ffmpeg``.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Union

import numpy as np


class RecorderError(Exception):
    """User-facing error, in Bangla + English."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_output_dir() -> Path:
    """Default save folder: ~/Videos/GhostRecorderBangla (falls back to cwd)."""
    videos = Path.home() / "Videos" / "GhostRecorderBangla"
    try:
        videos.mkdir(parents=True, exist_ok=True)
        return videos
    except OSError:
        fallback = Path.cwd() / "GhostRecorderBangla"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _check_display() -> None:
    """Raise a clear error when there is no display to capture from."""
    # On Linux a screen capture needs an X/Wayland display.
    if os.name == "posix" and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        raise RecorderError(
            "ডিসপ্লে পাওয়া যায়নি — স্ক্রিন ক্যাপচার করতে ডিসপ্লে লাগবে।\n"
            "No display found — screen capture needs a display."
        )


def _open_mss():
    """Open mss, converting any failure into a clear RecorderError."""
    _check_display()
    try:
        import mss
        return mss.mss()
    except Exception as exc:  # noqa: BLE001 - report any mss failure plainly
        raise RecorderError(
            "স্ক্রিন ক্যাপচার শুরু করা যায়নি (mss খুলতে ব্যর্থ)।\n"
            f"Could not open screen capture (mss failed): {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

def save_pil_image(image, path: Union[str, Path]) -> str:
    """Save a Pillow image as PNG. Returns the saved path (as str).

    This is the shared PNG save path used by the screenshot functions,
    and it is testable headless with a synthetic Pillow image.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), format="PNG")
    return str(path)


def save_frame_as_png(frame: np.ndarray, path: Union[str, Path]) -> str:
    """Save a numpy RGB frame (H, W, 3) as PNG. Returns the saved path."""
    from PIL import Image

    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise RecorderError(
            "ছবির ফরম্যাট সঠিক নয়।\n"
            "Invalid frame shape for PNG save: expected (H, W, 3) or (H, W, 4)."
        )
    img = Image.fromarray(frame[:, :, :3].astype(np.uint8), mode="RGB")
    return save_pil_image(img, path)


def take_screenshot(output_dir: Union[str, Path, None] = None,
                    filename: Optional[str] = None) -> str:
    """Capture the full primary screen to PNG. Returns the saved file path."""
    from PIL import Image

    output_dir = Path(output_dir) if output_dir else _default_output_dir()
    filename = filename or f"screenshot-{_timestamp()}.png"
    path = output_dir / filename

    with _open_mss() as sct:
        try:
            shot = sct.grab(sct.monitors[1])  # primary monitor
        except Exception as exc:  # noqa: BLE001
            raise RecorderError(
                "স্ক্রিনশট নেওয়া যায়নি — ডিসপ্লে পাওয়া যায়নি।\n"
                f"Could not take a screenshot: {exc}"
            ) from exc
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return save_pil_image(img, path)


def take_region_screenshot(x: int, y: int, width: int, height: int,
                           output_dir: Union[str, Path, None] = None,
                           filename: Optional[str] = None) -> str:
    """Capture a screen region (x, y, width, height) to PNG.

    Returns the saved file path.
    """
    from PIL import Image

    if width <= 0 or height <= 0:
        raise RecorderError(
            "রিজিয়নের প্রস্থ/উচ্চতা ০-এর বেশি হতে হবে।\n"
            "Region width and height must be greater than 0."
        )
    if x < 0 or y < 0:
        raise RecorderError(
            "রিজিয়নের x/y নেগেটিভ হতে পারবে না।\n"
            "Region x/y must not be negative."
        )

    output_dir = Path(output_dir) if output_dir else _default_output_dir()
    filename = filename or f"screenshot-region-{_timestamp()}.png"
    path = output_dir / filename

    with _open_mss() as sct:
        try:
            shot = sct.grab({"left": int(x), "top": int(y),
                             "width": int(width), "height": int(height)})
        except Exception as exc:  # noqa: BLE001
            raise RecorderError(
                "রিজিয়ন স্ক্রিনশট নেওয়া যায়নি — ডিসপ্লে পাওয়া যায়নি।\n"
                f"Could not take a region screenshot: {exc}"
            ) from exc
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return save_pil_image(img, path)


def get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor."""
    with _open_mss() as sct:
        monitor = sct.monitors[1]
        return int(monitor["width"]), int(monitor["height"])


# ---------------------------------------------------------------------------
# Screen recording
# ---------------------------------------------------------------------------

def write_frames_to_mp4(frames, path: Union[str, Path], fps: int = 15) -> str:
    """Write an iterable of numpy RGB frames to an MP4 file.

    Headless-testable MP4 path (no display needed). Returns the saved path.
    """
    import imageio.v2 as imageio

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        str(path), fps=fps, codec="libx264", quality=8,
        macro_block_size=None,
    )
    try:
        count = 0
        for frame in frames:
            writer.append_data(np.asarray(frame, dtype=np.uint8))
            count += 1
        if count == 0:
            raise RecorderError(
                "কোনো ফ্রেম পাওয়া যায়নি, ভিডিও তৈরি হয়নি।\n"
                "No frames were provided, so no video was written."
            )
    finally:
        writer.close()
    return str(path)


class ScreenRecorder:
    """Screen recorder: mss frames in a background thread -> MP4 via imageio.

    Usage:
        rec = ScreenRecorder(output_dir, fps=15, on_elapsed=callback)
        rec.start()
        rec.pause() / rec.resume()
        path = rec.stop()   # returns the MP4 path

    ``on_elapsed`` is called (from the capture thread) with elapsed seconds.
    ``frame_source`` is an optional callable returning one numpy RGB frame
    (or None to stop); it exists for headless/synthetic testing and is
    only used when supplied — normally frames come from mss.
    """

    def __init__(self, output_dir: Union[str, Path, None] = None,
                 fps: int = 15,
                 on_elapsed: Optional[Callable[[int], None]] = None,
                 frame_source: Optional[Callable[[], Optional[np.ndarray]]] = None):
        self.output_dir = Path(output_dir) if output_dir else _default_output_dir()
        self.fps = int(fps) if fps and int(fps) > 0 else 15
        self.on_elapsed = on_elapsed
        self.frame_source = frame_source

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # set = paused
        self._writer = None
        self._output_path: Optional[Path] = None
        self._start_time: float = 0.0
        self._paused_total: float = 0.0
        self._pause_started: float = 0.0
        self._last_reported_second: int = -1
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------
    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive() \
            and not self._stop_event.is_set()

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def elapsed_seconds(self) -> int:
        if not self._start_time:
            return 0
        paused = self._paused_total
        if self._pause_event.is_set() and self._pause_started:
            paused += time.time() - self._pause_started
        return max(0, int(time.time() - self._start_time - paused))

    # -- control -----------------------------------------------------------
    def start(self, filename: Optional[str] = None) -> str:
        """Start recording. Returns the output MP4 path."""
        if self.is_recording:
            raise RecorderError(
                "রেকর্ডিং ইতিমধ্যে চলছে।\nRecording is already running."
            )
        import imageio.v2 as imageio

        # Fail fast with a clear message if there is no display and no
        # synthetic frame source was supplied (headless test mode).
        if self.frame_source is None:
            _check_display()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = filename or f"recording-{_timestamp()}.mp4"
        self._output_path = self.output_dir / filename
        try:
            self._writer = imageio.get_writer(
                str(self._output_path), fps=self.fps, codec="libx264",
                quality=8, macro_block_size=None,
            )
        except Exception as exc:  # noqa: BLE001
            raise RecorderError(
                "ভিডিও ফাইল খোলা যায়নি (ffmpeg প্রয়োজন)।\n"
                f"Could not open video writer (ffmpeg needed): {exc}"
            ) from exc

        self._stop_event.clear()
        self._pause_event.clear()
        self._start_time = time.time()
        self._paused_total = 0.0
        self._pause_started = 0.0
        self._last_reported_second = -1
        self._thread = threading.Thread(
            target=self._capture_loop, name="ghost-recorder-capture",
            daemon=True,
        )
        self._thread.start()
        return str(self._output_path)

    def pause(self) -> None:
        if not self.is_recording:
            raise RecorderError(
                "রেকর্ডিং চলছে না, Pause করা যাবে না।\n"
                "Nothing is recording, so it cannot be paused."
            )
        if not self._pause_event.is_set():
            self._pause_started = time.time()
            self._pause_event.set()

    def resume(self) -> None:
        if not self.is_recording:
            raise RecorderError(
                "রেকর্ডিং চলছে না, Resume করা যাবে না।\n"
                "Nothing is recording, so it cannot be resumed."
            )
        if self._pause_event.is_set():
            self._paused_total += time.time() - self._pause_started
            self._pause_started = 0.0
            self._pause_event.clear()

    def stop(self) -> str:
        """Stop recording, close the writer, return the MP4 file path."""
        if self._thread is None and self._writer is None:
            raise RecorderError(
                "রেকর্ডিং চলছে না, Stop করা যাবে না।\n"
                "Nothing is recording, so it cannot be stopped."
            )
        self._stop_event.set()
        self._pause_event.clear()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        with self._lock:
            if self._writer is not None:
                try:
                    self._writer.close()
                finally:
                    self._writer = None
        path = str(self._output_path) if self._output_path else ""
        self._output_path = None
        self._start_time = 0.0
        return path

    # -- internals ---------------------------------------------------------
    def write_frame(self, frame: np.ndarray) -> None:
        """Append one RGB frame to the open MP4 writer (testable path)."""
        with self._lock:
            if self._writer is None:
                raise RecorderError(
                    "রেকর্ডার খোলা নেই।\nRecorder writer is not open."
                )
            self._writer.append_data(np.asarray(frame, dtype=np.uint8))

    def _report_elapsed(self) -> None:
        if self.on_elapsed is None:
            return
        seconds = self.elapsed_seconds
        if seconds != self._last_reported_second:
            self._last_reported_second = seconds
            try:
                self.on_elapsed(seconds)
            except Exception:
                pass  # a callback must never kill the recording thread

    def _capture_loop(self) -> None:
        interval = 1.0 / self.fps
        try:
            if self.frame_source is not None:
                self._capture_from_source(interval)
            else:
                self._capture_from_screen(interval)
        except RecorderError:
            # Screen unavailable mid-recording: stop cleanly so stop()
            # still closes the writer and returns a (possibly short) file.
            self._stop_event.set()
        except Exception:  # noqa: BLE001 - never let the thread die silently
            self._stop_event.set()
        finally:
            self._report_elapsed()

    def _capture_from_source(self, interval: float) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(0.05)
                continue
            frame = self.frame_source()
            if frame is None:
                break
            self.write_frame(frame)
            self._report_elapsed()
            time.sleep(interval)

    def _capture_from_screen(self, interval: float) -> None:
        import mss

        with _open_mss() as sct:
            monitor = sct.monitors[1]
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    time.sleep(0.05)
                    continue
                started = time.time()
                try:
                    shot = sct.grab(monitor)
                except Exception as exc:  # noqa: BLE001
                    raise RecorderError(
                        "স্ক্রিন ক্যাপচার বন্ধ হয়ে গেছে।\n"
                        f"Screen capture failed during recording: {exc}"
                    ) from exc
                frame = np.array(shot, dtype=np.uint8)[:, :, :3][:, :, ::-1]
                # mss gives BGRA; drop alpha and reverse to RGB.
                # (np.array(shot) is BGRA; [:, :, :3] is BGR, [::-1] -> RGB)
                self.write_frame(frame)
                self._report_elapsed()
                wait = interval - (time.time() - started)
                if wait > 0:
                    time.sleep(wait)


__all__ = [
    "RecorderError",
    "ScreenRecorder",
    "get_screen_size",
    "save_frame_as_png",
    "save_pil_image",
    "take_region_screenshot",
    "take_screenshot",
    "write_frames_to_mp4",
]
