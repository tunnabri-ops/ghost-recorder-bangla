"""Headless tests for Ghost Recorder Bangla v1.1.0 engine features.

Runs with the standard library only — no display, camera, or GUI needed::

    python3 test_v11.py

Covers: screenshot annotation (PIL), GIF export from frames (PIL),
video -> GIF conversion (ffmpeg CLI), the recording scheduler
(pure stdlib), and the webcam overlay compositing (synthetic frames).
MP4 writing is skipped here when imageio is not installed.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image

import recorder
from recorder import (
    RecorderError,
    check_webcam_available,
    draw_annotations,
    export_frames_to_gif,
    export_video_to_gif,
    overlay_webcam_frame,
    save_frame_as_png,
)
from scheduler import (
    RecordingScheduler,
    format_countdown,
    load_schedule,
    next_run_datetime,
    parse_time_of_day,
    save_schedule,
    seconds_until_next,
)

HAS_IMAGEIO = importlib.util.find_spec("imageio") is not None
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _solid_image(w=200, h=120, color=(255, 255, 255)):
    return Image.new("RGB", (w, h), color)


class TestAnnotation(unittest.TestCase):
    def test_pen_changes_pixels(self):
        img = _solid_image()
        out = draw_annotations(img, [
            {"type": "pen", "points": [(10, 10), (100, 10), (100, 60)],
             "color": "#ff0000", "width": 5},
        ])
        self.assertEqual(out.getpixel((50, 10)), (255, 0, 0))
        # Input image is unchanged (function works on a copy).
        self.assertEqual(img.getpixel((50, 10)), (255, 255, 255))

    def test_arrow_draws_line_and_head(self):
        img = _solid_image()
        out = draw_annotations(img, [
            {"type": "arrow", "points": [(10, 60), (150, 60)],
             "color": "#0000ff", "width": 4},
        ])
        self.assertEqual(out.getpixel((80, 60)), (0, 0, 255))

    def test_text_changes_pixels(self):
        img = _solid_image()
        out = draw_annotations(img, [
            {"type": "text", "position": (10, 10), "text": "TEST",
             "color": "#000000", "size": 32},
        ])
        changed = sum(
            1 for x in range(10, 120) for y in range(10, 50)
            if out.getpixel((x, y)) != (255, 255, 255)
        )
        self.assertGreater(changed, 10, "text annotation drew nothing")

    def test_empty_and_unknown_ops_are_noops(self):
        img = _solid_image()
        out = draw_annotations(img, [])
        self.assertEqual(list(img.getdata()), list(out.getdata()))
        out2 = draw_annotations(img, [{"type": "circle", "points": [(5, 5)]}])
        self.assertEqual(list(img.getdata()), list(out2.getdata()))


class TestGifExport(unittest.TestCase):
    def test_frames_to_gif_frame_count(self):
        frames = []
        for i in range(6):
            frame = np.zeros((60, 80, 3), dtype=np.uint8)
            frame[:, :, 0] = (i * 40) % 256
            frame[10:30, 10:30 + i * 5, 1] = 255
            frames.append(frame)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.gif"
            result = export_frames_to_gif(frames, path, fps=10, max_width=80)
            self.assertTrue(Path(result).exists())
            with Image.open(result) as gif:
                self.assertEqual(gif.format, "GIF")
                self.assertEqual(gif.n_frames, 6)
                self.assertEqual(gif.info.get("duration"), 100)

    def test_frames_to_gif_rejects_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RecorderError):
                export_frames_to_gif([], Path(tmp) / "empty.gif")

    def test_frames_to_gif_rejects_bad_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RecorderError):
                export_frames_to_gif([np.zeros((10, 10), dtype=np.uint8)],
                                     Path(tmp) / "bad.gif")

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg not on PATH")
    def test_video_to_gif_via_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mp4 = tmp / "test.mp4"
            proc = os.system(
                f"ffmpeg -y -v error -f lavfi -i testsrc=size=160x120:rate=10:duration=1 "
                f"-pix_fmt yuv420p {mp4} >/dev/null 2>&1"
            )
            self.assertEqual(proc, 0, "ffmpeg could not make a test mp4")
            self.assertTrue(mp4.exists())
            gif_path = export_video_to_gif(mp4, tmp / "test.gif", fps=5, width=160)
            self.assertTrue(Path(gif_path).exists())
            self.assertGreater(Path(gif_path).stat().st_size, 0)
            with Image.open(gif_path) as gif:
                self.assertEqual(gif.format, "GIF")
                self.assertGreaterEqual(gif.n_frames, 2)

    def test_video_to_gif_missing_file(self):
        with self.assertRaises(RecorderError):
            export_video_to_gif("/nonexistent/nope.mp4", "/tmp/nope.gif")


class TestScheduler(unittest.TestCase):
    def test_parse_time_ok(self):
        self.assertEqual(parse_time_of_day("09:30"), (9, 30))
        self.assertEqual(parse_time_of_day("00:00"), (0, 0))
        self.assertEqual(parse_time_of_day("23:59"), (23, 59))

    def test_parse_time_bad(self):
        for bad in ("", "9", "24:00", "12:60", "ab:cd", "9:00:00"):
            with self.assertRaises(ValueError, msg=bad):
                parse_time_of_day(bad)

    def test_seconds_until_next_same_day(self):
        now = datetime(2026, 11, 26, 8, 0, 0)
        delay = seconds_until_next("09:00", now)
        self.assertAlmostEqual(delay, 3600, delta=1)

    def test_seconds_until_next_tomorrow_when_passed(self):
        now = datetime(2026, 11, 26, 10, 0, 0)
        nxt = next_run_datetime("09:00", now)
        self.assertEqual(nxt, datetime(2026, 11, 27, 9, 0, 0))
        self.assertAlmostEqual(seconds_until_next("09:00", now), 23 * 3600, delta=1)

    def test_due_fires_once_per_day(self):
        sched = RecordingScheduler(schedule={
            "time": "09:00", "duration_minutes": 5, "enabled": True,
            "last_fired_date": None,
        })
        t = datetime(2026, 11, 26, 9, 0, 30)
        self.assertTrue(sched.due(t))
        self.assertFalse(sched.due(t))  # same day: already fired
        self.assertFalse(sched.due(datetime(2026, 11, 26, 9, 5, 0)))
        # Next day it fires again.
        self.assertTrue(sched.due(datetime(2026, 11, 27, 9, 0, 10)))

    def test_due_not_before_time_and_not_when_disabled(self):
        sched = RecordingScheduler(schedule={
            "time": "09:00", "duration_minutes": 5, "enabled": True,
            "last_fired_date": None,
        })
        self.assertFalse(sched.due(datetime(2026, 11, 26, 8, 59, 0)))
        # Outside the 90s window: missed, does not fire late.
        self.assertFalse(sched.due(datetime(2026, 11, 26, 9, 5, 0)))
        sched.set_enabled(False)
        self.assertFalse(sched.due(datetime(2026, 11, 26, 9, 0, 5)))

    def test_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schedule.json"
            saved = save_schedule(path, {"time": "07:30", "duration_minutes": 10,
                                         "enabled": True, "last_fired_date": None})
            self.assertEqual(saved["time"], "07:30")
            loaded = load_schedule(path)
            self.assertEqual(loaded, saved)
            sched = RecordingScheduler(path)
            self.assertEqual(sched.time_str, "07:30")
            self.assertEqual(sched.duration_minutes, 10)
            self.assertTrue(sched.enabled)

    def test_load_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_schedule(Path(tmp) / "nope.json")
            self.assertEqual(loaded["time"], "09:00")
            self.assertFalse(loaded["enabled"])

    def test_format_countdown(self):
        self.assertIn("ঘণ্টা", format_countdown(3661))
        self.assertIn("মিনিট", format_countdown(90))
        self.assertIn("সেকেন্ড", format_countdown(45))


class TestWebcamOverlay(unittest.TestCase):
    def test_overlay_bottom_right(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)  # black screen
        cam = np.full((120, 160, 3), 255, dtype=np.uint8)  # white webcam
        out = overlay_webcam_frame(frame, cam, corner="bottom-right")
        self.assertEqual(out.shape, frame.shape)
        # Centre of the webcam patch (bottom-right, 160px wide) is white.
        self.assertTrue(np.all(out[330, 600] == 255))
        # Far top-left corner is untouched black.
        self.assertTrue(np.all(out[5, 5] == 0))

    def test_overlay_top_left(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cam = np.full((120, 160, 3), (10, 200, 30), dtype=np.uint8)
        out = overlay_webcam_frame(frame, cam, corner="top-left")
        self.assertTrue(np.all(out[40, 40] == (10, 200, 30)))
        self.assertTrue(np.all(out[330, 600] == 0))

    def test_overlay_unknown_corner_defaults_bottom_right(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cam = np.full((120, 160, 3), 255, dtype=np.uint8)
        out = overlay_webcam_frame(frame, cam, corner="middle-nowhere")
        self.assertTrue(np.all(out[330, 600] == 255))

    def test_overlay_rejects_bad_shapes(self):
        frame = np.zeros((10, 10), dtype=np.uint8)
        cam = np.zeros((10, 10, 3), dtype=np.uint8)
        with self.assertRaises(RecorderError):
            overlay_webcam_frame(frame, cam)

    def test_check_webcam_returns_honest_pair(self):
        available, reason = check_webcam_available()
        self.assertIsInstance(available, bool)
        self.assertIsInstance(reason, str)
        self.assertTrue(reason.strip())
        if not available:
            # In this sandbox there is no cv2/camera: the reason must say so.
            self.assertIn("OpenCV", reason)


class TestRegression(unittest.TestCase):
    def test_save_frame_as_png_still_works(self):
        frame = np.zeros((40, 60, 3), dtype=np.uint8)
        frame[5:15, 5:15] = (255, 0, 0)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_frame_as_png(frame, Path(tmp) / "frame.png")
            with Image.open(path) as img:
                self.assertEqual(img.size, (60, 40))
                self.assertEqual(img.getpixel((10, 10)), (255, 0, 0))

    @unittest.skipUnless(HAS_IMAGEIO, "imageio not installed")
    def test_write_frames_to_mp4_still_works(self):
        frames = [np.zeros((48, 64, 3), dtype=np.uint8) for _ in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = recorder.write_frames_to_mp4(frames, Path(tmp) / "t.mp4", fps=10)
            self.assertTrue(Path(path).exists())
            self.assertGreater(Path(path).stat().st_size, 0)

    def test_version_bumped(self):
        self.assertEqual(recorder.__version__, "1.1.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
