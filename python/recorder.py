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
                 frame_source: Optional[Callable[[], Optional[np.ndarray]]] = None,
                 webcam_enabled: bool = False,
                 webcam_corner: str = "bottom-right"):
        self.output_dir = Path(output_dir) if output_dir else _default_output_dir()
        self.fps = int(fps) if fps and int(fps) > 0 else 15
        self.on_elapsed = on_elapsed
        self.frame_source = frame_source
        # v1.1.0 — webcam overlay (OpenCV). Off unless requested; start()
        # fails fast with a clear message when no camera is available,
        # instead of silently recording without the overlay.
        self.webcam_enabled = bool(webcam_enabled)
        self.webcam_corner = webcam_corner or "bottom-right"
        self.webcam_lost = False  # set if the camera drops mid-recording

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

        # Webcam overlay requested: refuse clearly when no camera exists
        # rather than recording without the overlay and pretending.
        if self.webcam_enabled:
            available, reason = check_webcam_available()
            if not available:
                raise RecorderError(
                    "ওয়েবক্যাম ওভারলে চালু করা যায়নি।\n"
                    f"{reason}"
                )

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

        cam = None
        if self.webcam_enabled:
            try:
                import cv2

                cam = cv2.VideoCapture(0)
                if not cam.isOpened():
                    cam = None
                    self.webcam_lost = True
            except Exception:  # noqa: BLE001 - camera loss must not kill recording
                cam = None
                self.webcam_lost = True
        try:
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
                    if cam is not None:
                        ok, cframe = cam.read()
                        if ok and cframe is not None:
                            try:
                                # OpenCV gives BGR; overlay helper takes RGB.
                                frame = overlay_webcam_frame(
                                    frame, cframe[:, :, ::-1],
                                    corner=self.webcam_corner)
                            except Exception:  # noqa: BLE001 - keep recording
                                pass
                        else:
                            self.webcam_lost = True
                    self.write_frame(frame)
                    self._report_elapsed()
                    wait = interval - (time.time() - started)
                    if wait > 0:
                        time.sleep(wait)
        finally:
            if cam is not None:
                try:
                    cam.release()
                except Exception:  # noqa: BLE001
                    pass


__version__ = "1.1.0"


def capture_screenshot_image():
    """Capture the full primary screen and return it as a Pillow Image.

    Unlike :func:`take_screenshot` this does not save anything, so the
    caller can annotate the image first and then save it.
    """
    from PIL import Image

    with _open_mss() as sct:
        try:
            shot = sct.grab(sct.monitors[1])  # primary monitor
        except Exception as exc:  # noqa: BLE001
            raise RecorderError(
                "স্ক্রিনশট নেওয়া যায়নি — ডিসপ্লে পাওয়া যায়নি।\n"
                f"Could not take a screenshot: {exc}"
            ) from exc
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_region_image(x: int, y: int, width: int, height: int):
    """Capture a screen region and return it as a Pillow Image (not saved)."""
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
    with _open_mss() as sct:
        try:
            shot = sct.grab({"left": int(x), "top": int(y),
                             "width": int(width), "height": int(height)})
        except Exception as exc:  # noqa: BLE001
            raise RecorderError(
                "রিজিয়ন স্ক্রিনশট নেওয়া যায়নি — ডিসপ্লে পাওয়া যায়নি।\n"
                f"Could not take a region screenshot: {exc}"
            ) from exc
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# ---------------------------------------------------------------------------
# v1.1.0 — screenshot annotation, GIF export, webcam overlay
# ---------------------------------------------------------------------------

def draw_annotations(image, annotations):
    """Draw annotation ops onto a copy of a Pillow image; return the copy.

    ``annotations`` is a list of dicts, one per stroke::

        {"type": "pen",   "points": [(x, y), ...], "color": "#ff0000", "width": 3}
        {"type": "arrow", "points": [(x1, y1), (x2, y2)], "color": "#ff0000", "width": 3}
        {"type": "text",  "position": (x, y), "text": "hello", "color": "#ff0000", "size": 20}

    Unknown op types are ignored. The input image is never modified.
    """
    import math

    from PIL import ImageDraw, ImageFont

    img = image.copy()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    draw = ImageDraw.Draw(img)
    for ann in annotations or []:
        if not isinstance(ann, dict):
            continue
        kind = ann.get("type")
        color = ann.get("color") or "#ff0000"
        width = max(1, int(ann.get("width") or 3))
        if kind == "pen":
            pts = [(float(x), float(y)) for x, y in (ann.get("points") or [])]
            if len(pts) >= 2:
                draw.line(pts, fill=color, width=width, joint="curve")
            elif len(pts) == 1:
                r = width / 2.0
                x, y = pts[0]
                draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        elif kind == "arrow":
            pts = [(float(x), float(y)) for x, y in (ann.get("points") or [])]
            if len(pts) >= 2:
                (x1, y1), (x2, y2) = pts[0], pts[-1]
                draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
                angle = math.atan2(y2 - y1, x2 - x1)
                head = max(10.0, width * 4.0)
                for delta in (math.pi - 0.45, math.pi + 0.45):
                    a = angle + delta
                    draw.line([(x2, y2), (x2 + head * math.cos(a),
                                           y2 + head * math.sin(a))],
                              fill=color, width=width)
        elif kind == "text":
            text = str(ann.get("text") or "")
            if not text:
                continue
            size = max(10, int(ann.get("size") or 20))
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", size)
            except Exception:  # noqa: BLE001 - fall back to any usable font
                try:
                    font = ImageFont.truetype("arial.ttf", size)
                except Exception:  # noqa: BLE001
                    font = ImageFont.load_default()
            x, y = ann.get("position") or (10, 10)
            draw.text((float(x), float(y)), text, fill=color, font=font)
    return img


def export_frames_to_gif(frames, path: Union[str, Path], fps: int = 10,
                         max_width: int = 480) -> str:
    """Write an iterable of numpy RGB frames (or Pillow images) to an
    animated GIF. Returns the saved path. Headless-testable (PIL only)."""
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fps = max(1, min(30, int(fps or 10)))
    pil_frames = []
    for frame in frames:
        if isinstance(frame, np.ndarray):
            if frame.ndim != 3 or frame.shape[2] not in (3, 4):
                raise RecorderError(
                    "ছবির ফরম্যাট সঠিক নয়।\n"
                    "Invalid frame shape for GIF export: expected (H, W, 3) or (H, W, 4)."
                )
            img = Image.fromarray(frame[:, :, :3].astype(np.uint8), mode="RGB")
        else:  # assume a Pillow image
            img = frame.convert("RGB")
        if max_width and img.width > max_width:
            new_h = max(1, round(img.height * max_width / img.width))
            img = img.resize((max_width, new_h), Image.LANCZOS)
        pil_frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=256))
    if not pil_frames:
        raise RecorderError(
            "কোনো ফ্রেম পাওয়া যায়নি, GIF তৈরি হয়নি।\n"
            "No frames were provided, so no GIF was written."
        )
    pil_frames[0].save(
        str(path), format="GIF", save_all=True,
        append_images=pil_frames[1:], duration=int(1000 / fps), loop=0,
    )
    return str(path)


def _find_ffmpeg_exe():
    """Return an ffmpeg binary path: system ffmpeg first, then the
    imageio-ffmpeg bundled binary. Returns None when neither exists."""
    import shutil

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def export_video_to_gif(video_path: Union[str, Path],
                        gif_path: Union[str, Path, None] = None,
                        fps: int = 10, width: int = 480) -> str:
    """Convert a recorded video file (MP4/WebM) to an animated GIF.

    Tries an imageio reader first; falls back to the ffmpeg CLI
    (two-pass palettegen/paletteuse) when imageio is unavailable or
    cannot read the file. Raises RecorderError with a clear message
    when neither route is available. Returns the GIF path.
    """
    import subprocess
    import tempfile

    video_path = Path(video_path)
    if not video_path.exists():
        raise RecorderError(
            f"ভিডিও ফাইল পাওয়া যায়নি: {video_path}\n"
            f"Video file not found: {video_path}"
        )
    gif_path = Path(gif_path) if gif_path else video_path.with_suffix(".gif")
    gif_path.parent.mkdir(parents=True, exist_ok=True)
    fps = max(1, min(30, int(fps or 10)))
    width = max(64, int(width or 480))

    # Route 1: imageio reader (no shell needed).
    try:
        import imageio.v2 as imageio

        reader = imageio.get_reader(str(video_path))
        try:
            try:
                src_fps = float(reader.get_meta_data().get("fps") or 15) or 15
            except Exception:  # noqa: BLE001
                src_fps = 15
            step = max(1, int(round(src_fps / fps)))
            frames = []
            for i, frame in enumerate(reader):
                if i % step == 0:
                    frames.append(frame)
                if len(frames) >= 300:
                    break
        finally:
            reader.close()
        if frames:
            return export_frames_to_gif(frames, gif_path, fps=fps,
                                        max_width=width)
    except ImportError:
        pass  # no imageio: fall through to ffmpeg
    except RecorderError:
        raise
    except Exception:  # noqa: BLE001 - unreadable file: try ffmpeg instead
        pass

    # Route 2: ffmpeg CLI, two-pass palette for decent colours.
    ffmpeg = _find_ffmpeg_exe()
    if not ffmpeg:
        raise RecorderError(
            "GIF বানাতে ffmpeg বা imageio লাগবে — কোনোটাই পাওয়া যায়নি।\n"
            "GIF export needs ffmpeg or imageio, neither was found."
        )
    palette = Path(tempfile.gettempdir()) / f"ghost-recorder-palette-{os.getpid()}.png"
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    commands = [
        [ffmpeg, "-y", "-i", str(video_path), "-vf", f"{vf},palettegen",
         str(palette)],
        [ffmpeg, "-y", "-i", str(video_path), "-i", str(palette), "-lavfi",
         f"{vf}[x];[x][1:v]paletteuse", str(gif_path)],
    ]
    try:
        for cmd in commands:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=300)
            if proc.returncode != 0:
                raise RecorderError(
                    "ffmpeg দিয়ে GIF বানানো যায়নি।\n"
                    f"ffmpeg failed while exporting GIF: {(proc.stderr or '')[-300:]}"
                )
    finally:
        try:
            palette.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    if not gif_path.exists() or gif_path.stat().st_size == 0:
        raise RecorderError(
            "GIF ফাইল তৈরি হয়নি।\nGIF file was not created."
        )
    return str(gif_path)


def check_webcam_available():
    """Probe for a usable webcam.

    Returns ``(available, reason)`` where reason is a Bangla + English
    message. No camera is faked: when OpenCV is missing or no camera
    opens, available is False and the reason says so plainly.
    """
    try:
        import cv2
    except ImportError:
        return False, (
            "OpenCV (cv2) ইনস্টল নেই — ওয়েবক্যাম ওভারলে বন্ধ আছে। "
            "চালু করতে: pip install opencv-python\n"
            "OpenCV (cv2) is not installed, so the webcam overlay is off. "
            "Enable it with: pip install opencv-python"
        )
    try:
        cap = cv2.VideoCapture(0)
        try:
            if not cap.isOpened():
                return False, (
                    "ক্যামেরা খোলা যায়নি — কোনো ওয়েবক্যাম পাওয়া যায়নি বা "
                    "অন্য অ্যাপ সেটা ব্যবহার করছে।\n"
                    "Could not open a camera — no webcam found or it is busy."
                )
            ok, _frame = cap.read()
            if not ok:
                return False, (
                    "ক্যামেরা খুলেছে কিন্তু ছবি আসছে না।\n"
                    "Camera opened but returned no frame."
                )
            return True, "ওয়েবক্যাম প্রস্তুত।\nWebcam ready."
        finally:
            cap.release()
    except Exception as exc:  # noqa: BLE001
        return False, (
            f"ক্যামেরা দেখা যায়নি: {exc}\nCould not access a camera: {exc}"
        )


def overlay_webcam_frame(frame: np.ndarray, webcam_frame: np.ndarray,
                         corner: str = "bottom-right",
                         size_frac: float = 0.25,
                         margin: int = 12, border: int = 3) -> np.ndarray:
    """Composite a webcam frame onto a screen frame (both numpy RGB).

    The webcam picture is scaled to ``size_frac`` of the screen width and
    pasted in the requested corner with a thin white border. Returns a
    new array; inputs are unchanged. Headless-testable with synthetic
    frames (no camera needed).
    """
    from PIL import Image, ImageDraw

    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise RecorderError(
            "ছবির ফরম্যাট সঠিক নয়।\n"
            "Invalid frame shape for webcam overlay: expected (H, W, 3) or (H, W, 4)."
        )
    if webcam_frame.ndim != 3 or webcam_frame.shape[2] not in (3, 4):
        raise RecorderError(
            "ওয়েবক্যাম ছবির ফরম্যাট সঠিক নয়।\n"
            "Invalid webcam frame shape for overlay."
        )
    h, w = int(frame.shape[0]), int(frame.shape[1])
    cam = Image.fromarray(webcam_frame[:, :, :3].astype(np.uint8), mode="RGB")
    target_w = max(32, int(w * float(size_frac)))
    target_h = max(32, int(target_w * cam.height / cam.width)) if cam.width else target_w
    if target_h > int(h * 0.5):
        target_h = int(h * 0.5)
        target_w = max(32, int(target_h * cam.width / cam.height))
    cam = cam.resize((target_w, target_h), Image.LANCZOS)
    positions = {
        "top-left": (margin, margin),
        "top-right": (w - target_w - margin, margin),
        "bottom-left": (margin, h - target_h - margin),
        "bottom-right": (w - target_w - margin, h - target_h - margin),
    }
    x, y = positions.get(corner, positions["bottom-right"])
    base = Image.fromarray(frame[:, :, :3].astype(np.uint8), mode="RGB")
    base.paste(cam, (x, y))
    draw = ImageDraw.Draw(base)
    draw.rectangle([x - border, y - border,
                    x + target_w + border - 1, y + target_h + border - 1],
                   outline="white", width=border)
    return np.array(base)


__all__ = [
    "RecorderError",
    "ScreenRecorder",
    "__version__",
    "capture_region_image",
    "capture_screenshot_image",
    "check_webcam_available",
    "draw_annotations",
    "export_frames_to_gif",
    "export_video_to_gif",
    "get_screen_size",
    "overlay_webcam_frame",
    "save_frame_as_png",
    "save_pil_image",
    "take_region_screenshot",
    "take_screenshot",
    "write_frames_to_mp4",
]
