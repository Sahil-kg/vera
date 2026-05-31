from __future__ import annotations

import re
from typing import Any

_CLEAN_RE = re.compile(r"\s+")
_REPLACEMENTS = [
    ("â‚¹", "Rs."),
    ("₹", "Rs."),
    ("â€", "-"),
    ("–", "-"),
    ("—", "-"),
    ("â†'", "->"),
    ("ðŸ¦·", ""),
    ("ðŸ'‹", ""),
    ("ðŸ'", ""),
    ("ðŸ™", ""),
    ("ðŸ˜Š", ""),
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.isascii() and "  " not in text and "\n" not in text and "\r" not in text:
        return text.strip()
    for src, dst in _REPLACEMENTS:
        if src in text:
            text = text.replace(src, dst)
    return _CLEAN_RE.sub(" ", text).strip()


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(value)


def safe_text(value: Any, default: str = "") -> str:
    text = clean_text(value)
    return text if text else default


def safe_pct(value: Any, default: str = "") -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return default


def safe_pct_abs(value: Any, default: str = "") -> str:
    try:
        return f"{abs(float(value)) * 100:.0f}%"
    except (TypeError, ValueError):
        return default


def safe_number(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    except Exception:
        return default


def money(value: Any) -> str:
    if value is None:
        return ""
    s = clean_text(value)
    if s.startswith("Rs."):
        return s
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return f"Rs.{int(float(s)):,}"
    return s


def display_date(value: Any) -> str:
    from datetime import datetime

    text = clean_text(value)
    if not text:
        return ""
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return text[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text) else text


def humanize_token(value: Any) -> str:
    text = clean_text(value).replace("_", " ").strip()
    return text or ""


def metric_label(value: Any) -> str:
    labels = {
        "review_count": "reviews",
        "calls": "calls",
        "views": "views",
        "ctr": "CTR",
    }
    text = clean_text(value)
    return labels.get(text, humanize_token(text) or "metric")


def driver_label(value: Any) -> str:
    labels = {
        "kids_yoga_post": "kids yoga post",
        "festival_offer": "festival offer",
        "review_reply": "review replies",
    }
    text = clean_text(value)
    return labels.get(text, humanize_token(text) or "recent profile activity")


def trend_label(value: Any) -> str:
    text = humanize_token(value)
    text = re.sub(r"\+(\d+)\b", r"+\1%", text)
    text = re.sub(r"-(\d+)\b", r"-\1%", text)
    return text
