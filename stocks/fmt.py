"""Number / time formatting helpers."""

import time
from datetime import datetime, timezone

UP_COLOR = (0x2E / 255, 0xC2 / 255, 0x7E / 255)
DOWN_COLOR = (0xE0 / 255, 0x1B / 255, 0x24 / 255)


def color_for(change):
    return DOWN_COLOR if change < 0 else UP_COLOR


def price(value, decimals=2):
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def change(value, decimals=2):
    return f"{value:+,.{decimals}f}"


def percent(value):
    return f"{value:+.2f}%"


def compact(value):
    if not value:
        return "—"
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= div:
            return f"{value / div:.2f}{suffix}"
    return f"{value:,.0f}"


def exchange_time(ts, gmtoffset):
    """A naive datetime in the exchange's local time."""
    return datetime.fromtimestamp(ts + gmtoffset, tz=timezone.utc).replace(tzinfo=None)


def hour_label(dt):
    h = dt.hour % 12 or 12
    return f"{h}" if dt.minute == 0 else f"{h}:{dt.minute:02d}"


def full_time(dt):
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def axis_label(ts, gmtoffset, range_key):
    dt = exchange_time(ts, gmtoffset)
    if range_key == "1D":
        return hour_label(dt)
    if range_key in ("1W", "1M", "3M"):
        return f"{dt:%b} {dt.day}"
    if range_key in ("6M", "YTD", "1Y"):
        return f"{dt:%b}"
    if range_key == "2Y":
        return f"{dt:%b} {dt:%y}"
    return f"{dt:%Y}"


def hover_label(ts, gmtoffset, range_key):
    dt = exchange_time(ts, gmtoffset)
    if range_key == "1D":
        return full_time(dt)
    if range_key in ("1W", "1M"):
        return f"{dt:%b} {dt.day}, {full_time(dt)}"
    return f"{dt:%b} {dt.day}, {dt.year}"


def relative(ts):
    delta = max(0, time.time() - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"
