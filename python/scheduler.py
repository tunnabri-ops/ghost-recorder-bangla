"""Ghost Recorder Bangla — scheduled recording (v1.1.0).

Pure standard library, no GUI imports, headless-testable.

A schedule is a dict::

    {"time": "09:00", "duration_minutes": 5,
     "enabled": False, "last_fired_date": None}

``time`` is 24-hour "HH:MM". ``duration_minutes`` 0 means "record until
stopped manually". ``last_fired_date`` is an ISO date string ("YYYY-MM-DD")
recording the day the schedule last fired, so it fires at most once a day.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

_BN = ["০", "১", "২", "৩", "৪", "৫", "৬", "৭", "৮", "৯"]


def _bn(n: int) -> str:
    return "".join(_BN[int(d)] for d in str(n))


DEFAULT_SCHEDULE = {
    "time": "09:00",
    "duration_minutes": 5,
    "enabled": False,
    "last_fired_date": None,
}


def parse_time_of_day(value: str) -> tuple[int, int]:
    """Parse "HH:MM" (24h) into (hour, minute).

    Raises ValueError with a Bangla + English message on bad input.
    """
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"সময় সঠিক নয়: '{text}' — HH:MM ফরম্যাটে লিখুন (যেমন 09:00)।\n"
            f"Invalid time: '{text}' — use HH:MM format (e.g. 09:00)."
        )
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(
            f"সময় সঠিক নয়: '{text}' — HH:MM ফরম্যাটে লিখুন (যেমন 09:00)।\n"
            f"Invalid time: '{text}' — use HH:MM format (e.g. 09:00)."
        ) from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(
            f"সময় সঠিক নয়: '{text}' — ঘণ্টা ০–২৩, মিনিট ০–৫৯ হতে হবে।\n"
            f"Invalid time: '{text}' — hour must be 0-23, minute 0-59."
        )
    return hour, minute


def validate_schedule(schedule: dict) -> dict:
    """Validate a schedule dict and return a normalised copy.

    Raises ValueError on a bad time or duration.
    """
    if not isinstance(schedule, dict):
        raise ValueError("সময়সূচি সঠিক নয়।\nInvalid schedule.")
    hour, minute = parse_time_of_day(schedule.get("time", ""))
    duration = schedule.get("duration_minutes", 0)
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        raise ValueError(
            "সময়কাল সঠিক নয় — মিনিটে পূর্ণসংখ্যা লিখুন।\n"
            "Invalid duration — enter whole minutes."
        ) from None
    if duration < 0 or duration > 480:
        raise ValueError(
            "সময়কাল ০–৪৮০ মিনিটের মধ্যে হতে হবে।\n"
            "Duration must be between 0 and 480 minutes."
        )
    last_fired = schedule.get("last_fired_date")
    if last_fired is not None and not isinstance(last_fired, str):
        last_fired = None
    return {
        "time": f"{hour:02d}:{minute:02d}",
        "duration_minutes": duration,
        "enabled": bool(schedule.get("enabled", False)),
        "last_fired_date": last_fired,
    }


def next_run_datetime(time_str: str, now: Optional[datetime] = None) -> datetime:
    """Next datetime the given "HH:MM" time occurs (today if still ahead,
    otherwise tomorrow)."""
    now = now or datetime.now()
    hour, minute = parse_time_of_day(time_str)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def seconds_until_next(time_str: str, now: Optional[datetime] = None) -> float:
    """Seconds until the next occurrence of the given "HH:MM" time."""
    now = now or datetime.now()
    return max(0.0, (next_run_datetime(time_str, now) - now).total_seconds())


def format_countdown(seconds: float) -> str:
    """Bangla countdown string, e.g. '২ ঘণ্টা ১৫ মিনিট' / '৩০ সেকেন্ড'."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{_bn(hours)} ঘণ্টা {_bn(minutes)} মিনিট"
    if minutes:
        return f"{_bn(minutes)} মিনিট {_bn(secs)} সেকেন্ড"
    return f"{_bn(secs)} সেকেন্ড"


def load_schedule(path: Union[str, Path, None]) -> dict:
    """Load a schedule JSON file; missing/corrupt files give defaults."""
    merged = dict(DEFAULT_SCHEDULE)
    if not path:
        return merged
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            merged.update(validate_schedule({**merged, **data}))
    except Exception:  # noqa: BLE001 - any bad file falls back to defaults
        return dict(DEFAULT_SCHEDULE)
    return merged


def save_schedule(path: Union[str, Path], schedule: dict) -> dict:
    """Validate and save a schedule dict as JSON. Returns the saved dict."""
    clean = validate_schedule(schedule)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return clean


class RecordingScheduler:
    """Holds one schedule, persists it to JSON, and answers 'is it due?'.

    ``due(now)`` returns True at most once per day: when the scheduled
    time arrives (within ``window_seconds`` after it) and the schedule
    has not already fired today.
    """

    def __init__(self, path: Union[str, Path, None] = None,
                 schedule: Optional[dict] = None):
        self.path = Path(path) if path else None
        if schedule is not None:
            self.schedule = validate_schedule({**DEFAULT_SCHEDULE, **schedule})
        elif self.path is not None:
            self.schedule = load_schedule(self.path)
        else:
            self.schedule = dict(DEFAULT_SCHEDULE)

    # -- configuration -----------------------------------------------------
    def set(self, time_str: str, duration_minutes: int,
            enabled: bool) -> dict:
        self.schedule = validate_schedule({
            "time": time_str,
            "duration_minutes": duration_minutes,
            "enabled": enabled,
            "last_fired_date": self.schedule.get("last_fired_date"),
        })
        self._persist()
        return dict(self.schedule)

    def set_enabled(self, enabled: bool) -> dict:
        self.schedule["enabled"] = bool(enabled)
        self._persist()
        return dict(self.schedule)

    def _persist(self) -> None:
        if self.path is not None:
            try:
                save_schedule(self.path, self.schedule)
            except Exception:  # noqa: BLE001 - a failed save must not crash the app
                pass

    # -- queries -----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.schedule.get("enabled"))

    @property
    def time_str(self) -> str:
        return str(self.schedule.get("time", "09:00"))

    @property
    def duration_minutes(self) -> int:
        return int(self.schedule.get("duration_minutes") or 0)

    def next_run(self, now: Optional[datetime] = None) -> datetime:
        return next_run_datetime(self.time_str, now)

    def seconds_until_next(self, now: Optional[datetime] = None) -> float:
        return seconds_until_next(self.time_str, now)

    def countdown_text(self, now: Optional[datetime] = None) -> str:
        return format_countdown(self.seconds_until_next(now))

    def due(self, now: Optional[datetime] = None,
            window_seconds: int = 90) -> bool:
        """True once when the scheduled time has arrived.

        Fires only while enabled, only inside ``window_seconds`` after
        the scheduled time, and only once per calendar day.
        """
        if not self.enabled:
            return False
        now = now or datetime.now()
        today = now.date().isoformat()
        if self.schedule.get("last_fired_date") == today:
            return False
        hour, minute = parse_time_of_day(self.time_str)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now < target + timedelta(seconds=window_seconds):
            self.schedule["last_fired_date"] = today
            self._persist()
            return True
        return False


__all__ = [
    "DEFAULT_SCHEDULE",
    "RecordingScheduler",
    "format_countdown",
    "load_schedule",
    "next_run_datetime",
    "parse_time_of_day",
    "save_schedule",
    "seconds_until_next",
    "validate_schedule",
]
