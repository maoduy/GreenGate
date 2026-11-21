"""
Time windows: "HH:MM-HH:MM [days]; ..." -> is this minute allowed?

Shared by the proxy, the agents and (as a Kotlin port) the Android app, so the format is
defined once, here, with the test vectors in docs/timewindow-vectors.json.

    07:00-21:00
    17:00-20:00 T2-T6; 08:00-22:00 T7,CN
    21:00-06:00            (crosses midnight: 21:00 today .. 06:00 tomorrow)

Days: T2..T7 and CN (Vietnamese), Mon..Sun, 2..7 and 8/CN. Empty text = always allowed.
Malformed text raises ValueError, so a typo in the sheet is reported, not silently "always".
"""
import re

_DAY = {"t2": 0, "t3": 1, "t4": 2, "t5": 3, "t6": 4, "t7": 5, "cn": 6, "t8": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
        "2": 0, "3": 1, "4": 2, "5": 3, "6": 4, "7": 5, "8": 6}
_RANGE = re.compile(r"^\s*(\d{1,2})[:h](\d{2})\s*-\s*(\d{1,2})[:h](\d{2})\s*(.*)$")


def _minutes(h, m):
    h, m = int(h), int(m)
    if h > 24 or m > 59 or (h == 24 and m):
        raise ValueError("giờ không hợp lệ: %02d:%02d" % (h, m))
    return h * 60 + m


def _days(text):
    text = text.strip().lower().replace("thứ", "t").replace("thu ", "t")
    if not text:
        return set(range(7))
    out = set()
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a not in _DAY or b not in _DAY:
                raise ValueError("ngày không hợp lệ: " + part)
            da, db = _DAY[a], _DAY[b]
            i = da
            while True:
                out.add(i)
                if i == db:
                    break
                i = (i + 1) % 7
        else:
            if part not in _DAY:
                raise ValueError("ngày không hợp lệ: " + part)
            out.add(_DAY[part])
    return out


def parse(text):
    """-> list of (start_minute, end_minute, days:set). Empty list = always allowed."""
    windows = []
    for piece in re.split(r"[;\n]+", text or ""):
        piece = piece.strip()
        if not piece or piece.startswith("#"):
            continue
        m = _RANGE.match(piece)
        if not m:
            raise ValueError("khung giờ không hợp lệ: " + piece)
        start, end = _minutes(m.group(1), m.group(2)), _minutes(m.group(3), m.group(4))
        windows.append((start, end, _days(m.group(5))))
    return windows


def allowed(windows, weekday, minute):
    """weekday: 0 = Monday .. 6 = Sunday. minute: minute of day 0..1439."""
    if not windows:
        return True
    for start, end, days in windows:
        if start <= end:
            if weekday in days and start <= minute < end:
                return True
        else:                                   # crosses midnight
            if weekday in days and minute >= start:
                return True
            if (weekday - 1) % 7 in days and minute < end:
                return True
    return False


def allowed_now(text, now=None):
    import time
    t = time.localtime(now) if now is not None else time.localtime()
    return allowed(parse(text), t.tm_wday, t.tm_hour * 60 + t.tm_min)
