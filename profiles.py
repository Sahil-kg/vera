from __future__ import annotations

from typing import Any

from .state import MERCHANT_AUTO_REPLY_COUNTS, MERCHANT_PROFILES


def merchant_profile(merchant_id: str | None) -> dict[str, Any]:
    key = merchant_id or "unknown_merchant"
    return MERCHANT_PROFILES.setdefault(
        key,
        {
            "reply_count": 0,
            "confirm_count": 0,
            "question_count": 0,
            "objection_count": 0,
            "offtopic_count": 0,
            "prefers_questions": False,
            "prefers_short": True,
            "last_recommendation": None,
            "open_issues": [],
            "resolved_issues": [],
        },
    )


def remember_open_issue(merchant_id: str | None, issue: str) -> None:
    profile = merchant_profile(merchant_id)
    issues = [item for item in profile.get("open_issues", []) if item != issue]
    issues.append(issue)
    profile["open_issues"] = issues[-5:]


def remember_resolved_issue(merchant_id: str | None, issue: str) -> None:
    profile = merchant_profile(merchant_id)
    resolved = [item for item in profile.get("resolved_issues", []) if item != issue]
    resolved.append(issue)
    profile["resolved_issues"] = resolved[-5:]
    profile["open_issues"] = [item for item in profile.get("open_issues", []) if item != issue][-5:]


def update_merchant_profile(merchant_id: str | None, intent: str, message: str) -> None:
    profile = merchant_profile(merchant_id)
    profile["reply_count"] = int(profile.get("reply_count", 0)) + 1
    if intent == "confirm":
        profile["confirm_count"] = int(profile.get("confirm_count", 0)) + 1
    elif intent == "question":
        profile["question_count"] = int(profile.get("question_count", 0)) + 1
    elif intent == "objection":
        profile["objection_count"] = int(profile.get("objection_count", 0)) + 1
    elif intent == "off_topic":
        profile["offtopic_count"] = int(profile.get("offtopic_count", 0)) + 1
    profile["prefers_questions"] = int(profile.get("question_count", 0)) > int(profile.get("confirm_count", 0))
    profile["prefers_short"] = len(message) < 80


def normalize_auto_reply(message: str) -> str:
    from .state import normalize_auto_reply as _normalize_auto_reply

    return _normalize_auto_reply(message)


def track_merchant_auto_reply(merchant_id: str | None, message: str) -> int:
    key = merchant_id or "unknown_merchant"
    normalized = normalize_auto_reply(message)
    current = MERCHANT_AUTO_REPLY_COUNTS.get(key)
    if current and current.get("message") == normalized:
        current["count"] = int(current.get("count", 0)) + 1
    else:
        current = {"message": normalized, "count": 1}
        MERCHANT_AUTO_REPLY_COUNTS[key] = current
    return int(current["count"])


def reset_merchant_auto_reply(merchant_id: str | None) -> None:
    if merchant_id:
        MERCHANT_AUTO_REPLY_COUNTS.pop(merchant_id, None)
