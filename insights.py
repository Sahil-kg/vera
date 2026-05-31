"""insights.py – Fact-based insight layer for Vera Precision Bot.

Flow:
    Trigger + Merchant → extract_insights() → MerchantInsight
    MerchantInsight   → build_message_plan()  → MessagePlan
    MessagePlan       → existing composers    → final message body

Nothing here generates non-deterministic content. All facts come directly
from the merchant/trigger/category dicts that are already in scope.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Any

from .models import MessagePlan
from .sanitization import clean_text, pct, safe_number, safe_pct, safe_pct_abs
from .intents import (
    active_offer,
    active_offer_detail,
    category_family,
    family_offer_noun,
    salutation,
    metric_line,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MetricSnapshot:
    """Raw performance numbers extracted from merchant.performance."""
    views: float | None = None
    calls: float | None = None
    ctr: float | None = None
    leads: float | None = None
    directions: float | None = None
    delta_views_pct: float | None = None
    delta_calls_pct: float | None = None
    delta_leads_pct: float | None = None

    def has_data(self) -> bool:
        return any(v is not None for v in (self.views, self.calls, self.ctr, self.leads))


@dataclass
class BusinessTrend:
    """A single detected business trend with a human-readable label."""
    code: str           # machine key, e.g. "calls_down"
    label: str          # e.g. "Calls are down 50% over 7 days"
    severity: str       # "low" | "medium" | "high" | "critical"
    implication: str    # one sentence: what it means for the merchant
    suggested_action: str  # one concrete Vera action


@dataclass
class MerchantInsight:
    """Everything extracted for one trigger + merchant pair."""
    facts: list[str] = field(default_factory=list)
    trends: list[BusinessTrend] = field(default_factory=list)
    metrics: MetricSnapshot = field(default_factory=MetricSnapshot)
    primary_implication: str = ""
    recommended_action: str = ""
    offer_text: str = ""
    family: str = "local_services"
    category_slug: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_label(value: float) -> str:
    """Turn 0.5 → '50%', -0.3 → '30%'."""
    return f"{abs(value) * 100:.0f}%"


def _direction(value: float) -> str:
    return "up" if value >= 0 else "down"


# ---------------------------------------------------------------------------
# Step 1 – Extract measurable facts from trigger payload
# ---------------------------------------------------------------------------

def extract_payload_facts(payload: dict[str, Any]) -> list[str]:
    """
    Pull concrete, numeric facts out of a trigger payload.
    Returns short human-readable strings, e.g. "delta: -50%", "lapsed: 42 customers".
    """
    facts: list[str] = []

    # Percentage deltas
    for key, label in (
        ("delta_pct", "delta"),
        ("price_change_pct", "price change"),
        ("estimated_uplift_pct", "estimated uplift"),
        ("drop_pct", "drop"),
        ("loss_pct", "loss"),
        ("vs_baseline", "vs baseline"),
        ("category_avg_lift", "category avg lift"),
    ):
        v = _as_float(payload.get(key))
        if v is not None:
            facts.append(f"{label}: {_pct_label(v)} {_direction(v)}")

    # Count fields
    for key, label in (
        ("lapsed_count", "lapsed customers"),
        ("affected_count", "affected"),
        ("customer_count", "customers"),
        ("lead_count", "leads"),
        ("shortage_count", "shortage"),
        ("affected_batches", "affected batches"),
    ):
        v = _as_float(payload.get(key))
        if v is not None and v > 0:
            facts.append(f"{label}: {int(v)}")

    # Deadline / window
    for key in ("days_until", "days_remaining", "days_to_wedding"):
        v = _as_float(payload.get(key))
        if v is not None and v >= 0:
            facts.append(f"due in {int(v)} days")
            break

    # Risk / severity
    risk = clean_text(payload.get("risk_level") or payload.get("severity") or payload.get("urgency") or "")
    if risk:
        facts.append(f"risk: {risk.lower()}")

    # Competitor proximity
    comp = clean_text(payload.get("competitor_name") or "")
    dist = clean_text(payload.get("distance_km") or "")
    if comp:
        dist_text = f" ({dist} km away)" if dist else ""
        facts.append(f"competitor: {comp}{dist_text}")

    # Molecule / SKU  (pharmacy / supply)
    meds = payload.get("molecule_list") or []
    if isinstance(meds, list) and meds:
        facts.append(f"molecules: {', '.join(clean_text(m) for m in meds[:3] if clean_text(m))}")
    elif clean_text(payload.get("molecule") or ""):
        facts.append(f"molecule: {clean_text(payload['molecule'])}")

    # Generic metric field
    metric_val = clean_text(payload.get("metric") or "")
    if metric_val:
        facts.append(f"metric: {metric_val}")

    return facts[:8]  # cap to keep messages tight


def extract_metric_snapshot(merchant: dict[str, Any]) -> MetricSnapshot:
    """Pull performance numbers from merchant.performance into a typed snapshot."""
    perf = merchant.get("performance", {})
    delta = perf.get("delta_7d") or {}
    return MetricSnapshot(
        views=_as_float(perf.get("views")),
        calls=_as_float(perf.get("calls")),
        ctr=_as_float(perf.get("ctr")),
        leads=_as_float(perf.get("leads")),
        directions=_as_float(perf.get("directions")),
        delta_views_pct=_as_float(delta.get("views_pct")),
        delta_calls_pct=_as_float(delta.get("calls_pct")),
        delta_leads_pct=_as_float(delta.get("leads_pct")),
    )


# ---------------------------------------------------------------------------
# Step 2 – Detect business trends
# ---------------------------------------------------------------------------

def detect_trends(
    metrics: MetricSnapshot,
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
) -> list[BusinessTrend]:
    """
    Detect business trends from metrics + trigger kind.
    Returns a list of BusinessTrend objects ordered by severity (critical first).
    """
    trends: list[BusinessTrend] = []
    kind = clean_text(trigger.get("kind")).lower()
    payload = trigger.get("payload", {})
    family = category_family(category, merchant)
    slug = (category or {}).get("slug") or merchant.get("category_slug", "")
    agg = merchant.get("customer_aggregate") or {}

    # --- Calls trend ---
    if metrics.delta_calls_pct is not None:
        if metrics.delta_calls_pct <= -0.30:
            calls_text = f"{_pct_label(metrics.delta_calls_pct)} over 7 days"
            calls_abs = f"{int(metrics.calls)} calls" if metrics.calls is not None else "fewer calls"
            trends.append(BusinessTrend(
                code="calls_down",
                label=f"Calls are down {calls_text}",
                severity="high" if metrics.delta_calls_pct <= -0.50 else "medium",
                implication=(
                    f"Potential customers are seeing the profile ({int(metrics.views):,} views) "
                    f"but fewer are converting to enquiries ({calls_abs})."
                    if metrics.views else
                    f"Incoming enquiries have dropped {calls_text}; demand may be shifting to alternatives."
                ),
                suggested_action="draft a recovery post and a WhatsApp nudge to recapture converting intent",
            ))
        elif metrics.delta_calls_pct >= 0.25:
            # Fix 3: category-specific implication instead of generic "Demand is hot"
            family = category_family(category, merchant)
            _family_spike_implication = {
                "healthcare": (
                    "More patients are calling this week — this is the window to convert enquiries "
                    "into confirmed appointments before they book elsewhere."
                ),
                "food": (
                    "Order enquiries are rising — pushing a time-limited offer now can turn "
                    "this call spike into confirmed orders while intent is warm."
                ),
                "fitness": (
                    "More people are enquiring about memberships or classes — "
                    "a fast follow-up can lock in trials before the interest cools."
                ),
                "beauty": (
                    "Booking calls are up — capturing these with a confirmed slot "
                    "now prevents them drifting to a competitor with open availability."
                ),
                "retail": (
                    "Customer enquiries are rising — a visible offer or in-store nudge "
                    "can convert browsers into buyers while footfall intent is high."
                ),
            }
            spike_impl = _family_spike_implication.get(
                family,
                (
                    f"Incoming calls are up {_pct_label(metrics.delta_calls_pct)} — "
                    "this is the right moment to push a booking campaign before the spike flattens."
                ),
            )
            trends.append(BusinessTrend(
                code="calls_up",
                label=f"Calls are up {_pct_label(metrics.delta_calls_pct)} this week",
                severity="low",
                implication=spike_impl,
                suggested_action="draft a follow-up campaign to convert this call spike into confirmed bookings",
            ))

    # --- Views trend ---
    if metrics.delta_views_pct is not None and metrics.delta_views_pct <= -0.20:
        trends.append(BusinessTrend(
            code="views_down",
            label=f"Profile views are down {_pct_label(metrics.delta_views_pct)} this week",
            severity="medium",
            implication="Fewer people are finding the profile; visibility is declining before enquiries follow.",
            suggested_action="refresh the Google Business Profile and post a visibility-boosting update",
        ))

    # --- High views + low CTR = conversion problem ---
    if (
        metrics.views is not None and metrics.views >= 500
        and metrics.ctr is not None and metrics.ctr <= 0.025
    ):
        trends.append(BusinessTrend(
            code="high_views_low_ctr",
            label=f"{int(metrics.views):,} views but only {_pct_label(metrics.ctr)} CTR",
            severity="high",
            implication=(
                "The profile is getting attention but visitors are not clicking through — "
                "offer wording, cover image, or lack of visible social proof may be contributing factors worth reviewing."
            ),
            suggested_action="add a strong offer, improve the profile cover, or add social proof to boost click-through",
        ))

    # --- High views + low calls = conversion problem ---
    if (
        metrics.views is not None and metrics.views >= 500
        and metrics.calls is not None and metrics.calls < 10
    ):
        ratio = metrics.calls / metrics.views
        if ratio < 0.005:
            trends.append(BusinessTrend(
                code="views_calls_gap",
                label=f"{int(metrics.views):,} views but only {int(metrics.calls)} calls",
                severity="high",
                implication=(
                    "A large gap between profile views and calls suggests a conversion barrier — "
                    "trust signals, offer clarity, or call-to-action strength may need work."
                ),
                suggested_action="draft a trust-building post and update the profile offer to close the conversion gap",
            ))

    # --- Lapsed customers ---
    lapsed = _as_float(agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus") or payload.get("lapsed_count"))
    if lapsed and lapsed >= 5 and kind in {"winback_eligible", "dormant_with_vera", "customer_lapsed_hard", "customer_lapsed_soft"}:
        avg = clean_text(agg.get("avg_order_value") or agg.get("avg_spend") or "")
        value_note = f", worth approx. Rs.{avg} each" if avg else ""
        trends.append(BusinessTrend(
            code="lapsed_customers",
            label=f"{int(lapsed)} customers haven't returned in 90+ days",
            severity="high",
            implication=(
                f"{int(lapsed)} customers{value_note} are within reach but cooling down; "
                "waiting longer makes each recovery more expensive."
            ),
            suggested_action="draft a soft-tone winback message with a low-friction return offer",
        ))

    # --- Compound: calls declining AND lapsed customers (compounding problem) ---
    calls_declining = any(t.code == "calls_down" for t in trends)
    has_lapsed = any(t.code == "lapsed_customers" for t in trends)
    if calls_declining and has_lapsed and lapsed:
        for t in list(trends):
            if t.code == "calls_down":
                trends.remove(t)
                lapsed_int = int(lapsed)
                trends.insert(0, BusinessTrend(
                    code="calls_down_with_lapsed",
                    label=t.label,
                    severity="critical",
                    implication=(
                        f"Calls are dropping while {lapsed_int} customers have already lapsed — "
                        "this is a compounding retention problem, not just a visibility dip."
                    ),
                    suggested_action=(
                        "draft a two-step recovery: a visibility post to attract new leads "
                        "and a soft winback for lapsed customers at the same time"
                    ),
                ))
                break

    # --- Silent retention decay (any trigger kind) ---
    silent_lapsed = _as_float(agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus"))
    if (
        silent_lapsed and silent_lapsed >= 10
        and kind not in {"winback_eligible", "dormant_with_vera", "customer_lapsed_hard", "customer_lapsed_soft"}
        and not any(t.code in {"lapsed_customers", "calls_down_with_lapsed"} for t in trends)
    ):
        trends.append(BusinessTrend(
            code="silent_retention_decay",
            label=f"{int(silent_lapsed)} customers drifting - retention risk in the background",
            severity="medium",
            implication=(
                f"{int(silent_lapsed)} customers have not returned in 90+ days; "
                "this compounds silently while other signals get attention."
            ),
            suggested_action="add a soft retention note to the current message or queue a separate winback",
        ))

    # --- Unverified GBP ---
    if kind == "gbp_unverified":
        trends.append(BusinessTrend(
            code="gbp_unverified",
            label="Google Business Profile is not verified",
            severity="critical",
            implication=(
                "An unverified profile blocks key trust features — customers see it as less reliable "
                "and Google may suppress it in local results."
            ),
            suggested_action="complete the GBP verification flow and send the owner a step-by-step checklist",
        ))

    # --- No active offer ---
    offer = active_offer(merchant, category)
    if not offer and kind not in {"gbp_unverified", "regulation_change", "supply_alert"}:
        trends.append(BusinessTrend(
            code="no_active_offer",
            label="No active offer on the profile",
            severity="low",
            implication=(
                "Without a live offer, the profile gives undecided visitors no reason to choose this "
                f"business over nearby {family} alternatives."
            ),
            suggested_action=f"create a simple {family_offer_noun(family)} offer to capture demand from profile visitors",
        ))

    # --- Competitor nearby ---
    comp = clean_text(payload.get("competitor_name") or "")
    if comp or kind == "competitor_opened":
        dist = clean_text(payload.get("distance_km") or "")
        dist_text = f" {dist} km away" if dist else " nearby"
        trends.append(BusinessTrend(
            code="competitor_threat",
            label=f"{comp or 'A new competitor'} has opened{dist_text}",
            severity="medium",
            implication=(
                f"A new competitor{dist_text} can pull undecided customers; "
                "positioning and proof content protect the current base."
            ),
            suggested_action="draft a premium-positioning post that makes the differentiation clear before customers compare",
        ))

    # --- Subscription / renewal risk ---
    if kind == "renewal_due":
        days = _as_float(payload.get("days_until") or payload.get("days_remaining"))
        days_text = f"in {int(days)} days" if days is not None else "soon"
        trends.append(BusinessTrend(
            code="renewal_due",
            label=f"Subscription renews {days_text}",
            severity="medium",
            implication="Losing the subscription would break live features; renewal is the safest default path.",
            suggested_action="send a value recap that makes the renewal decision easy",
        ))

    # Sort: critical → high → medium → low
    _order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    trends.sort(key=lambda t: _order.get(t.severity, 4))
    return trends


# ---------------------------------------------------------------------------
# Step 3 – Convert insights to a structured MessagePlan
# ---------------------------------------------------------------------------

def _primary_fact(
    facts: list[str],
    trends: list[BusinessTrend],
    metrics: MetricSnapshot,
    trigger: dict[str, Any],
    merchant: dict[str, Any],
) -> str:
    """Pick the single most important fact for the opening sentence."""
    # Prefer trend labels (already human-readable and quantified)
    if trends:
        return trends[0].label
    # Fall back to extracted payload facts
    if facts:
        return facts[0]
    # Fall back to metric snapshot
    snapshot = metric_line(merchant)
    if snapshot:
        return snapshot
    # Last resort
    return clean_text(trigger.get("kind") or "new signal").replace("_", " ")


def _primary_implication(
    trends: list[BusinessTrend],
    family: str,
    merchant: dict | None = None,
) -> str:
    if not trends:
        return f"Addressing this now gives the {family} business a clear next-step advantage."
    impl = trends[0].implication
    if merchant:
        locality = clean_text((merchant.get("identity") or {}).get("locality") or "")
        mname = clean_text((merchant.get("identity") or {}).get("name") or "")
        if locality and locality.lower() not in impl.lower():
            impl = impl.rstrip(".") + f" in {locality}."
        elif mname and mname.lower() not in impl.lower() and len(mname) < 30:
            impl = impl.rstrip(".") + f" for {mname}."
    return impl


def _primary_action(trends: list[BusinessTrend], offer: str, family: str) -> str:
    if trends:
        return trends[0].suggested_action
    noun = family_offer_noun(family)
    if offer:
        return f"draft one merchant-ready action note around {offer}"
    return f"draft one {family}-ready action note around the current {noun}"


def build_message_plan(
    insight: MerchantInsight,
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
    customer: dict[str, Any] | None = None,
) -> MessagePlan:
    """
    Convert a MerchantInsight into a MessagePlan ready for the existing composers.

    Structure:  FACT → IMPACT → ACTION → CTA
    """
    from .intents import known_trigger_cta, urgent_cta
    from .scoring import trigger_archetype

    kind = clean_text(trigger.get("kind") or "generic")
    archetype = trigger_archetype(trigger)
    family = insight.family

    fact = _primary_fact(insight.facts, insight.trends, insight.metrics, trigger, merchant)
    implication = _primary_implication(insight.trends, family, merchant)
    action = _primary_action(insight.trends, insight.offer_text, family)

    cta = urgent_cta(kind, merchant, category, customer, trigger) if (merchant and category) else (
        known_trigger_cta(kind, family, insight.offer_text)
    )

    return MessagePlan(
        fact=fact,
        implication=implication,
        action=action,
        cta=cta,
        cta_type=archetype.cta_type,
    )


# ---------------------------------------------------------------------------
# Step 4 – Top-level entry point (cache + assemble)
# ---------------------------------------------------------------------------



def insight_impact_clause(insight: "MerchantInsight") -> str:
    """
    Return a short impact clause (no trailing period) for inserting between
    the FACT and the ACTION in a composed body.
    """
    if not insight.trends:
        return ""
    trend = insight.trends[0]
    impl = trend.implication.strip().rstrip(".")
    if len(impl) > 120:
        first_end = impl.find(".")
        if 0 < first_end < 120:
            impl = impl[:first_end]
        else:
            impl = impl[:117] + "..."
    return impl


def insight_action_verb(insight: "MerchantInsight", offer: str = "", family: str = "") -> str:
    """
    Return a concrete action string for the ACTION slot in a message plan.
    """
    if insight.trends:
        action = insight.trends[0].suggested_action
        if offer and offer not in action:
            return f"{action} around {offer}"
        return action
    noun = family_offer_noun(family) if family else "your offer"
    return f"draft one merchant-ready action note around {offer or noun}"

# Simple per-process cache keyed by (trigger_id, merchant_id, category_slug).
# Avoids re-computing insights for the same input within a tick cycle.
_INSIGHT_CACHE: dict[tuple[str, str, str], MerchantInsight] = {}
_CACHE_MAX = 256


def extract_insights(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
    customer: dict[str, Any] | None = None,
    *,
    use_cache: bool = True,
) -> MerchantInsight:
    """
    Main entry point.  Returns a MerchantInsight for the given trigger/merchant/category.

    Deterministic: same inputs always produce the same output.
    Cached: repeated calls within the same process are free.
    """
    cache_key = (
        clean_text(trigger.get("id") or trigger.get("kind") or ""),
        clean_text(merchant.get("merchant_id") or ""),
        clean_text((category or {}).get("slug") or merchant.get("category_slug") or ""),
    )
    if use_cache and cache_key in _INSIGHT_CACHE:
        return _INSIGHT_CACHE[cache_key]

    payload = trigger.get("payload", {})
    family = category_family(category, merchant)
    slug = (category or {}).get("slug") or merchant.get("category_slug", "")
    metrics = extract_metric_snapshot(merchant)
    facts = extract_payload_facts(payload)
    trends = detect_trends(metrics, trigger, merchant, category)
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)

    primary_implication = _primary_implication(trends, family, merchant)
    recommended_action = _primary_action(trends, offer, family)

    insight = MerchantInsight(
        facts=facts,
        trends=trends,
        metrics=metrics,
        primary_implication=primary_implication,
        recommended_action=recommended_action,
        offer_text=offer,
        family=family,
        category_slug=slug,
    )

    if use_cache:
        if len(_INSIGHT_CACHE) >= _CACHE_MAX:
            # evict oldest quarter
            for old_key in list(_INSIGHT_CACHE.keys())[: _CACHE_MAX // 4]:
                del _INSIGHT_CACHE[old_key]
        _INSIGHT_CACHE[cache_key] = insight

    return insight


def clear_insight_cache() -> None:
    """Call this in /v1/teardown to avoid stale state across test runs."""
    _INSIGHT_CACHE.clear()


# ---------------------------------------------------------------------------
# Convenience: insight-enriched body prefix
# ---------------------------------------------------------------------------

def insight_fact_sentence(insight: MerchantInsight) -> str:
    """
    Return a single, tight opening sentence from the top insight fact.
    Suitable for prepending to existing composer output.
    e.g. "Calls are down 45% over 7 days."
    """
    if insight.trends:
        return f"{insight.trends[0].label}."
    if insight.facts:
        return f"{insight.facts[0].capitalize()}."
    if insight.metrics.has_data():
        m = insight.metrics
        # Fix 5: interpret metrics rather than listing raw numbers
        if m.views is not None and m.calls is not None:
            ratio = m.calls / m.views if m.views > 0 else 0
            if ratio < 0.005:
                return (
                    f"{int(m.views):,} views but only {int(m.calls)} calls — "
                    f"strong visibility but weak conversion on the profile."
                )
            elif ratio >= 0.02:
                return (
                    f"{int(m.views):,} views and {int(m.calls)} calls — "
                    f"profile is converting well; this is a good window to push further."
                )
            else:
                return (
                    f"{int(m.views):,} views converting to {int(m.calls)} calls — "
                    f"moderate conversion rate; there may be room to improve uptake with a clearer offer or call-to-action."
                )
        if m.views is not None:
            return f"{int(m.views):,} views on the profile this period."
        if m.calls is not None:
            return f"{int(m.calls)} calls recorded on the profile."
        if m.ctr is not None:
            ctr_pct = abs(m.ctr) * 100
            if ctr_pct < 1.5:
                return f"{ctr_pct:.1f}% CTR — visitors are seeing the profile but not clicking through."
            return f"{ctr_pct:.1f}% CTR on the profile."
    return ""


def insight_implication_sentence(insight: MerchantInsight) -> str:
    """Return the primary implication as a clean sentence."""
    impl = insight.primary_implication.strip().rstrip(".")
    return f"{impl}." if impl else ""


_METRIC_RE = re.compile(r"\d+\s*(%|calls?|views?|reviews?|days?|km)", re.I)


def enrich_plan_body(
    body: str,
    insight: MerchantInsight,
    *,
    max_prepend_chars: int = 120,
) -> str:
    """
    Optionally prepend a fact sentence to an existing message body IF the body
    doesn't already contain a specific metric phrase (to avoid double-quoting metrics).

    Fix 1 (duplicate injection): also skip when the opening fact sentence is
    substantially already present in the body (case-insensitive token overlap ≥ 60%).
    """
    if _METRIC_RE.search(body):
        return body
    fact = insight_fact_sentence(insight)
    if not fact or len(fact) > max_prepend_chars:
        return body

    # Fix 1: check token-level overlap to catch paraphrase duplicates
    fact_tokens = set(re.sub(r"[^a-z0-9]", " ", fact.lower()).split())
    body_tokens = set(re.sub(r"[^a-z0-9]", " ", body[:200].lower()).split())
    meaningful = fact_tokens - {"the", "a", "an", "is", "are", "was", "were", "and", "but", "or", "in", "on", "at", "of", "to", "for"}
    if meaningful and len(meaningful & body_tokens) / len(meaningful) >= 0.60:
        return body  # fact already expressed in the body — skip prepend

    return f"{fact} {body}"