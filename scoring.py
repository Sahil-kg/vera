from __future__ import annotations

from typing import Any

from .models import TriggerArchetype
from .intents import FAMILY_CONTEXT_KEYWORDS, category_family
from .sanitization import clean_text, display_date, humanize_token, metric_label, safe_pct, safe_pct_abs
from .state import REVENUE_WORDS, RISK_WORDS
from .intents import POSITIVE_LEVELS

ARCHETYPES = {
    "resource_constraint": TriggerArchetype(
        "resource_constraint",
        "capacity risk",
        "prepare a customer-safe reschedule note plus an internal capacity checklist",
        "confirmation",
        95,
    ),
    "inventory_constraint": TriggerArchetype(
        "inventory_constraint",
        "availability risk",
        "prepare a staff checklist and customer-safe alternative message",
        "confirmation",
        98,
    ),
    "customer_communication": TriggerArchetype(
        "customer_communication",
        "customer trust risk",
        "draft a transparent customer update that explains value and next steps",
        "confirmation",
        82,
    ),
    "lead_conversion": TriggerArchetype(
        "lead_conversion",
        "lead conversion leak",
        "draft a recovery post and WhatsApp line around the strongest offer",
        "confirmation",
        78,
    ),
    "trust_repair": TriggerArchetype(
        "trust_repair",
        "trust and review risk",
        "draft a review reply plus fresh proof post",
        "choice",
        76,
    ),
    "campaign_planning": TriggerArchetype(
        "campaign_planning",
        "upcoming demand window",
        "draft a campaign plan before demand bunches up",
        "scheduling",
        62,
    ),
    "learning_question": TriggerArchetype(
        "learning_question",
        "missing merchant input",
        "ask one focused question before drafting",
        "question",
        45,
    ),
    "generic_action": TriggerArchetype(
        "generic_action",
        "new business signal",
        "draft one merchant-ready action note",
        "confirmation",
        50,
    ),
}


def generic_payload_facts(payload: dict[str, Any], limit: int = 3) -> list[str]:
    preferred = [
        "metric",
        "delta_pct",
        "window",
        "risk_level",
        "signal",
        "trend",
        "issue",
        "reason",
        "item",
        "sku",
        "molecule",
        "shortage_count",
        "affected_count",
        "price_change_pct",
        "effective_date",
        "deadline_iso",
        "customer_count",
        "lead_count",
    ]
    facts = []
    seen = set()

    def add_fact(key: str, value: Any) -> None:
        if len(facts) >= limit or key in seen or value in (None, "", [], {}, False):
            return
        seen.add(key)
        label = humanize_token(key)
        if isinstance(value, list):
            vals = [humanize_token(v) for v in value[:3] if humanize_token(v)]
            if vals:
                facts.append(f"{label}: {', '.join(vals)}")
            return
        if isinstance(value, dict):
            vals = [f"{humanize_token(k)} {humanize_token(v)}" for k, v in list(value.items())[:2] if humanize_token(v)]
            if vals:
                facts.append(f"{label}: {', '.join(vals)}")
            return
        if "pct" in key or "rate" in key:
            pct_text = safe_pct(value) if isinstance(value, (int, float)) else humanize_token(value)
            facts.append(f"{label}: {pct_text}")
        elif "date" in key or key.endswith("_at") or "deadline" in key:
            facts.append(f"{label}: {display_date(value)}")
        else:
            facts.append(f"{label}: {humanize_token(value)}")

    for key in preferred:
        add_fact(key, payload.get(key))
    for key, value in payload.items():
        add_fact(str(key), value)
    return facts


def payload_summary(payload: dict[str, Any], fallback: str = "the new signal") -> str:
    facts = generic_payload_facts(payload)
    return "; ".join(facts) if facts else fallback


def _token_set(*values: Any) -> set[str]:
    tokens: set[str] = set()
    import re

    for value in values:
        text = clean_text(value).lower()
        if not text:
            continue
        tokens.update(re.findall(r"[a-z0-9]+", text))
    return tokens


def _cached_trigger_tokens(trigger: dict[str, Any]) -> set[str]:
    if "__tokens" not in trigger:
        payload = trigger.get("payload", {})
        trigger["__tokens"] = _token_set(
            trigger.get("kind", ""),
            payload_summary(payload, ""),
            clean_text(payload.get("action", "")),
            clean_text(payload.get("next_step", "")),
            clean_text(payload.get("recommended_action", "")),
        )
    return trigger["__tokens"]


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _deadline_pressure(payload: dict[str, Any]) -> int:
    score = 0
    for key in ("deadline", "deadline_iso", "due_date", "due_in_days", "days_remaining", "expires_at", "expiry", "expires_on"):
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if key in {"due_in_days", "days_remaining"}:
            days = _as_float(value)
            if days is None:
                continue
            if days <= 1:
                score += 18
            elif days <= 3:
                score += 14
            elif days <= 7:
                score += 10
            elif days <= 14:
                score += 6
        elif isinstance(value, (int, float)):
            days = abs(float(value))
            if days <= 1:
                score += 18
            elif days <= 3:
                score += 14
            elif days <= 7:
                score += 10
            elif days <= 14:
                score += 6
        else:
            score += 6
    return min(score, 22)


def _severity_pressure(payload: dict[str, Any]) -> int:
    score = 0
    for key in ("severity", "risk_level", "priority", "importance", "criticality", "urgency"):
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (int, float)):
            score += 4 if value <= 1 else 8 if value <= 3 else 14 if value <= 5 else 18
            continue
        text = clean_text(value).lower()
        score += POSITIVE_LEVELS.get(text, 0)
    return min(score, 24)


def _impact_pressure(payload: dict[str, Any]) -> int:
    score = 0
    impact_keys = (
        "impact",
        "affected_count",
        "customer_count",
        "lead_count",
        "booking_count",
        "order_count",
        "visit_count",
        "view_count",
        "call_count",
        "loss_count",
        "loss_pct",
        "delta_pct",
        "drop_pct",
        "gain_pct",
        "conversion_pct",
        "ctr",
    )
    for key in impact_keys:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        number = _as_float(value)
        if number is None:
            text = clean_text(value).lower()
            score += POSITIVE_LEVELS.get(text, 0)
            continue
        magnitude = abs(number)
        if key.endswith("_pct") or key in {"ctr", "conversion_pct"}:
            if magnitude >= 0.4:
                score += 16
            elif magnitude >= 0.2:
                score += 12
            elif magnitude >= 0.1:
                score += 8
        else:
            if magnitude >= 500:
                score += 16
            elif magnitude >= 100:
                score += 12
            elif magnitude >= 25:
                score += 8
            elif magnitude >= 10:
                score += 4
    return min(score, 20)


def _action_pressure(payload: dict[str, Any]) -> int:
    score = 0
    for key in ("action", "actions", "next_step", "next_steps", "recommended_action", "recommended_actions", "ask", "asks"):
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            score += 4 if value else 0
        elif isinstance(value, dict):
            score += 4 if value else 0
        else:
            score += 6
    return min(score, 10)


def _merchant_pressure(merchant: dict[str, Any] | None) -> int:
    if not merchant:
        return 0
    perf = merchant.get("performance", {})
    score = 0
    views = _as_float(perf.get("views")) or 0.0
    calls = _as_float(perf.get("calls")) or 0.0
    ctr = _as_float(perf.get("ctr"))
    delta_calls = _as_float((perf.get("delta_7d") or {}).get("calls_pct"))
    delta_views = _as_float((perf.get("delta_7d") or {}).get("views_pct"))

    if views >= 1000:
        score += 5
    if calls >= 25:
        score += 5
    if ctr is not None:
        if ctr <= 0.02:
            score += 10
        elif ctr <= 0.04:
            score += 6
        elif ctr >= 0.06:
            score += 3
    if delta_calls is not None and delta_calls < 0:
        score += 6
    if delta_views is not None and delta_views < 0:
        score += 4
    if merchant.get("offers"):
        score += 3
    if merchant.get("customer_aggregate", {}).get("total_unique_ytd"):
        score += 2
    return min(score, 18)


def business_impact_score(trigger: dict[str, Any]) -> int:
    payload = trigger.get("payload", {})
    kind = clean_text(trigger.get("kind")).lower()
    text = f"{kind} {trigger.get('__summary', payload_summary(payload, ''))}".lower()
    score = 0
    if any(w in text for w in ["crisis", "recall", "compliance", "inventory", "stock", "shortage", "staff"]):
        score += 30
    if any(w in text for w in ["competitor", "churn", "lapsed", "renewal", "price"]):
        score += 20
    if any(w in text for w in ["calls", "leads", "sales", "booking", "conversion", "revenue"]):
        score += 15
    numeric_fields = [
        "affected_count",
        "customer_count",
        "shortage_count",
        "lead_count",
        "lapsed_count",
        "value_now",
        "occurrences_30d",
    ]
    for field in numeric_fields:
        try:
            value = float(payload.get(field, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value >= 100:
            score += 15
        elif value >= 10:
            score += 8
    for field in ("delta_pct", "price_change_pct", "estimated_loss_pct"):
        try:
            value = abs(float(payload.get(field, 0) or 0))
        except (TypeError, ValueError):
            value = 0
        if value >= 0.4:
            score += 18
        elif value >= 0.15:
            score += 10
    risk_level = clean_text(payload.get("risk_level")).lower()
    if risk_level in {"critical", "high", "severe"}:
        score += 20
    elif risk_level in {"medium", "moderate"}:
        score += 10
    return min(score, 45)


def trigger_archetype(trigger: dict[str, Any]) -> TriggerArchetype:
    kind = clean_text(trigger.get("kind")).lower()
    text = f"{kind} {trigger.get('__summary', payload_summary(trigger.get('payload', {}), ''))}".lower()
    if any(w in text for w in ["staff", "capacity", "unavailable", "short staffed"]):
        return ARCHETYPES["resource_constraint"]
    if any(w in text for w in ["inventory", "stock", "shortage", "out of stock", "supply", "recall"]):
        return ARCHETYPES["inventory_constraint"]
    if any(w in text for w in ["price", "increase", "hike", "fee", "cost"]):
        return ARCHETYPES["customer_communication"]
    if any(w in text for w in ["calls", "lead", "booking", "conversion", "sales", "revenue", "dip", "drop", "competitor"]):
        return ARCHETYPES["lead_conversion"]
    if any(w in text for w in ["review", "rating", "complaint", "trust", "late", "slow"]):
        return ARCHETYPES["trust_repair"]
    if any(w in text for w in ["festival", "match", "season", "campaign", "event"]):
        return ARCHETYPES["campaign_planning"]
    if any(w in text for w in ["ask", "question", "curious"]):
        return ARCHETYPES["learning_question"]
    return ARCHETYPES["generic_action"]


def category_fit_score(trigger: dict[str, Any], category: dict[str, Any] | None = None, merchant: dict[str, Any] | None = None) -> int:
    family = category_family(category, merchant)
    payload = trigger.get("payload", {})
    tokens = trigger.get("__tokens") or _cached_trigger_tokens(trigger)
    keyword_hits = tokens & FAMILY_CONTEXT_KEYWORDS.get(family, set())
    score = min(len(keyword_hits) * 4, 16)

    merchant_text = " ".join(
        [
            clean_text((merchant or {}).get("identity", {}).get("name")),
            clean_text((merchant or {}).get("identity", {}).get("locality")),
            clean_text((category or {}).get("name")),
            clean_text((__import__("bot.intents", fromlist=["active_offer"]).active_offer(merchant or {}, category or {}))),
            family,
        ]
    ).lower()
    merchant_tokens = _token_set(merchant_text)
    overlap = tokens & merchant_tokens
    score += min(len(overlap) * 2, 8)

    if overlap and payload.get("action"):
        score += 2
    if family == "healthcare" and any(word in tokens for word in {"patient", "appointment", "followup", "recall", "refill"}):
        score += 4
    if family == "food" and any(word in tokens for word in {"order", "delivery", "menu", "demand"}):
        score += 4
    if family == "fitness" and any(word in tokens for word in {"trial", "membership", "class", "retention"}):
        score += 4
    if family == "beauty" and any(word in tokens for word in {"booking", "slot", "hair", "salon"}):
        score += 4
    if family == "retail" and any(word in tokens for word in {"stock", "inventory", "offer", "sale"}):
        score += 4
    return min(score, 20)


 
def trigger_business_importance(trigger, merchant=None, category=None):
    payload = trigger.get("payload", {})
    score = 0
    urgency = trigger.get("urgency", payload.get("urgency"))
    urgency_value = _as_float(urgency)
    if urgency_value is not None:
        score += min(int(round(max(urgency_value, 0.0) * 9)), 27)
    else:
        urgency_text = clean_text(urgency).lower()
        score += POSITIVE_LEVELS.get(urgency_text, 0)
 
    score += _severity_pressure(payload)
    score += _deadline_pressure(payload)
    score += _impact_pressure(payload)
    score += _action_pressure(payload)
    score += _merchant_pressure(merchant)
    score += category_fit_score(trigger, category, merchant)
 
    # ── NEW: lapsed-customer aggregate pressure ───────────────────────
    if merchant:
        agg = merchant.get("customer_aggregate") or {}
        lapsed = _as_float(agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus") or 0)
        if lapsed and lapsed >= 100:
            score += 12
        elif lapsed and lapsed >= 20:
            score += 7
        elif lapsed and lapsed >= 5:
            score += 3
    # ─────────────────────────────────────────────────────────────────
 
    source = clean_text(trigger.get("source")).lower()
    if source == "external":
        score += 3
    if trigger.get("scope") == "customer" or trigger.get("customer_id"):
        score += 4
    if trigger.get("merchant_id"):
        score += 2
    return min(score, 150)

def trigger_reason_phrase(trigger: dict[str, Any], merchant: dict[str, Any] | None = None, category: dict[str, Any] | None = None) -> str:
    payload = trigger.get("payload", {})
    parts: list[str] = []
    urgency = clean_text(trigger.get("urgency") or payload.get("urgency"))
    severity = clean_text(payload.get("severity") or payload.get("risk_level"))
    deadline = clean_text(payload.get("deadline") or payload.get("deadline_iso") or payload.get("due_date") or payload.get("days_remaining"))
    impact = clean_text(payload.get("impact") or payload.get("affected_count") or payload.get("customer_count") or payload.get("delta_pct") or payload.get("loss_pct"))
    action = clean_text(payload.get("action") or payload.get("next_step") or payload.get("recommended_action"))
    if urgency:
        parts.append(f"urgency={urgency}")
    if severity:
        parts.append(f"severity={severity}")
    if deadline:
        parts.append(f"deadline={deadline}")
    if impact:
        parts.append(f"impact={impact}")
    if action:
        parts.append(f"action={humanize_token(action)}")
    if not parts:
        parts.append(payload_summary(payload, humanize_token(trigger.get("kind") or "signal")))

    fit = category_fit_score(trigger, category, merchant)
    if fit:
        parts.append(f"fit={fit}")
    merchant_pressure = _merchant_pressure(merchant)
    if merchant_pressure:
        parts.append(f"merchant_pressure={merchant_pressure}")
    return "; ".join(parts)

def rank_trigger(trigger, merchant=None, category=None):
    from .insights import extract_insights    # lazy import — avoids circular deps
 
    payload = trigger.get("payload", {})
    kind = clean_text(trigger.get("kind"))
    text = f"{kind} {trigger.get('__summary', payload_summary(payload, ''))}".lower()
    archetype = trigger_archetype(trigger)
    urgency = _as_float(trigger.get("urgency", payload.get("urgency")))
    urgency_score = int(round(max(urgency or 0.0, 0.0) * 10)) if urgency is not None else 0
    risk_score    = 20 if any(word in text for word in RISK_WORDS) else 0
    revenue_score = 15 if any(word in text for word in REVENUE_WORDS) else 0
    trust_score   = 12 if archetype.name == "trust_repair" else 0
    source_score  = 5  if clean_text(trigger.get("source")).lower() == "external" else 0
    customer_score = 14 if trigger.get("scope") == "customer" or trigger.get("customer_id") else 0
 
    importance_score = trigger_business_importance(trigger, merchant, category)
    blended_score    = int(round(importance_score * 0.55 + business_impact_score(trigger) * 0.75))
 
    # ── NEW: insight-driven severity boost ────────────────────────────
    # Avoids double-fetching: insights are cached after first call in tick().
    insight_boost = 0
    try:
        if merchant and category:
            insight = extract_insights(trigger, merchant, category, use_cache=True)
            _sev_score = {"critical": 18, "high": 12, "medium": 6, "low": 2}
            for trend in insight.trends[:3]:
                insight_boost += _sev_score.get(trend.severity, 0)
            insight_boost = min(insight_boost, 24)  # cap contribution
    except Exception:
        pass  # insight layer is additive; never block a rank
    # ──────────────────────────────────────────────────────────────────
 
    return min(
        100,
        blended_score
        + urgency_score // 10
        + risk_score // 4
        + revenue_score // 5
        + trust_score // 4
        + source_score
        + customer_score
        + insight_boost,
    )
