from __future__ import annotations

from typing import Any

from .state import CONTEXTS, SENT_SUPPRESSIONS, VALID_SCOPES, clean_text, normalized_kind_for_context, slug_part, utc_now


def context_counts() -> dict[str, int]:
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    seen: dict[str, set[int]] = {"category": set(), "merchant": set(), "customer": set(), "trigger": set()}
    for scope, context_id in CONTEXTS:
        entry = CONTEXTS[(scope, context_id)]
        entry_id = id(entry)
        if entry_id not in seen[scope]:
            seen[scope].add(entry_id)
            counts[scope] = counts.get(scope, 0) + 1
    return counts


def _id_aliases(cid: str) -> set[str]:
    aliases: set[str] = set()
    stripped = cid.lstrip("0")
    if stripped and stripped != cid:
        aliases.add(stripped)
    padded = cid.zfill(3)
    if padded != cid:
        aliases.add(padded)
    tail = cid.split("_")[-1]
    if tail and tail != cid:
        aliases.add(tail)
    dashed = cid.replace("-", "_")
    if dashed != cid:
        aliases.add(dashed)
    return aliases


def standard_suppression_key(
    trigger: dict[str, Any],
    category: dict[str, Any] | None = None,
    merchant: dict[str, Any] | None = None,
) -> str:
    audience = trigger.get("customer_id") or "merchant"
    return ":".join(
        [
            slug_part(normalized_kind_for_context(trigger, category, merchant), "generic"),
            slug_part(trigger.get("scope"), "scope"),
            slug_part(trigger.get("merchant_id"), "merchant"),
            slug_part(audience, "audience"),
            slug_part(trigger.get("id") or trigger.get("suppression_key"), "trigger"),
        ]
    )


def clear_suppression_for_trigger(trigger: dict[str, Any]) -> None:
    trigger_id = slug_part(trigger.get("id") or trigger.get("suppression_key"), "trigger")
    raw_key = standard_suppression_key(trigger)
    SENT_SUPPRESSIONS.discard(raw_key)
    for key in list(SENT_SUPPRESSIONS):
        if key.endswith(f":{trigger_id}"):
            SENT_SUPPRESSIONS.discard(key)


def push_context(scope: str, context_id: str, version: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if scope not in VALID_SCOPES:
        return 400, {"accepted": False, "reason": "invalid_scope"}
    key = (scope, context_id)
    current = CONTEXTS.get(key)

    print(f"[push_context] scope={scope} id={context_id} v={version} "
          f"current_v={current['version'] if current else None} "
          f"merchant_id={payload.get('merchant_id')} kind={payload.get('kind')}")

    if current and current["version"] > version:
        print(f"[push_context] REJECTED stale: current={current['version']} > incoming={version}")
        return 409, {"accepted": False, "reason": "stale_version", "current_version": current["version"]}
    if current and current["version"] == version:
        return 409, {"accepted": False, "reason": "stale_version", "current_version": current["version"]}
    entry = {"version": version, "payload": payload, "stored_at": utc_now()}
    CONTEXTS[key] = entry
    for alias in _id_aliases(context_id):
        CONTEXTS[(scope, alias)] = entry
    if scope == "trigger":
        clear_suppression_for_trigger(payload)
    print(f"[push_context] STORED scope={scope} id={context_id}")
    return 200, {"accepted": True, "ack_id": f"ack_{context_id}_v{version}", "stored_at": utc_now()}


def get_payload(scope: str, context_id: str | None) -> dict[str, Any] | None:
    if not context_id:
        return None
    cid = str(context_id).strip()
    entry = CONTEXTS.get((scope, cid))
    return entry["payload"] if entry else None
