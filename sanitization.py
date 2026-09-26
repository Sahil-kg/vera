from __future__ import annotations

import re
from typing import Any

MAX_BODY_CHARS = 320
BODY_SOFT_LIMIT = 300

_CLEAN_RE = re.compile(r"\s+")
_TRAILING_JUNK_RE = re.compile(r"[\s,;:.!?()\[\]-]+$")
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


def _word_safe_cut(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` chars, preferring a word boundary.

    Last-resort guard for bodies whose first sentence is already longer than
    the budget, where sentence-level truncation cannot help. Cuts back to the
    nearest space so a WhatsApp message never ends mid-word.
    """
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(" "), window.rfind(", "), window.rfind("; "), window.rfind(". "))
    if cut >= limit // 2:
        window = window[:cut]
    return _TRAILING_JUNK_RE.sub("", window)


def clamp_body(value: Any, limit: int = MAX_BODY_CHARS) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text


    protected = text.replace("Dr. ", "Dr__DOT__ ").replace("Mr. ", "Mr__DOT__ ").replace("Mrs. ", "Mrs__DOT__ ").replace("Ms. ", "Ms__DOT__ ")
    sentences = [s.replace("__DOT__", ".") for s in re.split(r"(?<=[.!?])\s+", protected)]
    cta = ""
    for sentence in reversed(sentences):
        if re.search(r"\b(reply|which|should|want)\b", sentence, re.I):
            cta = sentence
            break

    if cta and len(cta) < limit - 20:
        prefix_limit = limit - len(cta) - 1
        prefix_parts: list[str] = []
        for sentence in sentences:
            if sentence == cta:
                break
            candidate = clean_text(" ".join(prefix_parts + [sentence]))
            if len(candidate) <= prefix_limit:
                prefix_parts.append(sentence)
            else:
                break
        prefix = clean_text(" ".join(prefix_parts))
        if not prefix:
            prefix = _word_safe_cut(text, prefix_limit)
            prefix = re.sub(r"\s*\(e\.g\.?.*$", "", prefix, flags=re.I).rstrip(" ,.;:-")
            prefix = re.sub(r"\s*\([^)]*$", "", prefix).rstrip(" ,.;:-")
        return _word_safe_cut(clean_text(f"{prefix} {cta}"), limit)

    kept: list[str] = []
    for sentence in sentences:
        candidate = clean_text(" ".join(kept + [sentence]))
        if len(candidate) <= limit:
            kept.append(sentence)
        elif kept:
            break
        else:
            break

    shortened = clean_text(" ".join(kept))
    if shortened:
        return _word_safe_cut(shortened, limit)
    return _word_safe_cut(text, limit)


def enforce_body_limit(value: Any, limit: int = MAX_BODY_CHARS) -> str:
    """Single hard gate for every outbound WhatsApp body.

    Every response path (proactive tick, fused trigger, reply routing) funnels
    through this so the official 320-character limit can never be exceeded,
    regardless of how long a merchant name, offer, or checklist template is.
    `limit` may be lowered to tighten composition, never raised above
    MAX_BODY_CHARS.
    """
    capped = min(int(limit), MAX_BODY_CHARS)
    text = clamp_body(value, limit=capped)
    if len(text) > capped:
        text = _word_safe_cut(text, capped)
    return text



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
