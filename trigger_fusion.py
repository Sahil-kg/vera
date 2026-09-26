from __future__ import annotations

from typing import Any

from .intents import active_offer, category_family, family_offer_noun, metric_line, render_cta, salutation, FAMILY_CONTEXT_KEYWORDS, cta_for
from .scoring import generic_payload_facts, rank_trigger, trigger_business_importance, trigger_reason_phrase, _token_set, payload_summary, trigger_archetype
from .sanitization import clean_text, safe_pct, safe_pct_abs
from .state import CONTEXTS, normalized_kind_for_context
from .suppression import standard_suppression_key
from .compose_merchant import sanitize_message


def fusion_signal(trigger: dict[str, Any], merchant: dict[str, Any] | None = None, category: dict[str, Any] | None = None) -> str:
    payload = trigger.get("payload", {})
    kind = clean_text(trigger.get("kind") or "signal").replace("_", " ")
    raw_kind = clean_text(trigger.get("kind") or "")
    if raw_kind in {"perf_dip", "perf_spike", "seasonal_perf_dip"}:
        metric = clean_text(payload.get("metric", "calls")).replace("_", " ")
        delta = payload.get("delta_pct")
        window = clean_text(payload.get("window", "7 days")).replace("7d", "7 days")
        direction = "down" if raw_kind in {"perf_dip", "seasonal_perf_dip"} else "up"
        pct_text = safe_pct_abs(delta) if direction == "down" else safe_pct(delta)
        return f"{metric} {direction} {pct_text or 'this period'} over {window}"
    if raw_kind == "renewal_due":
        days = payload.get("days_remaining")
        plan = clean_text(payload.get("plan", "subscription"))
        return f"{plan} renewal due in {days} days" if days is not None else f"{plan} renewal due soon"
    if raw_kind == "competitor_opened":
        competitor = clean_text(payload.get("competitor_name", "a new competitor"))
        distance = payload.get("distance_km")
        return f"{competitor} opened {distance} km away" if distance else f"{competitor} opened nearby"
    if raw_kind == "review_theme_emerged":
        theme = clean_text(payload.get("theme", "reviews")).replace("_", " ")
        count = payload.get("occurrences_30d")
        return f"{count} reviews mention {theme}" if count else f"reviews mention {theme}"
    facts = generic_payload_facts(payload, 2)
    score = trigger_business_importance(trigger, merchant, category)
    if facts:
        return f"{kind} - {', '.join(facts)} (priority {score})"
    return f"{kind} (priority {score})"


def should_fuse_triggers(triggers, merchant=None, category=None):
    """Fuse only when exactly 2 triggers share the same archetype, business
    problem, and category family.  All three conditions must hold; a single
    mismatch blocks fusion so unrelated signals are never bundled together.
    """
    if len(triggers) < 2:
        return False

    # Work with the top-2 ranked candidates only – fusion is always 2-trigger max.
    top2 = sorted(triggers, key=lambda t: rank_trigger(t, merchant, category), reverse=True)[:2]

    a1 = trigger_archetype(top2[0])
    a2 = trigger_archetype(top2[1])

    # Condition 1 – same archetype name
    if a1.name != a2.name:
        return False

    # Condition 2 – same business problem (derived from the archetype)
    if a1.business_problem != a2.business_problem:
        return False

    # Condition 3 – both triggers must belong to the merchant's category family.
    # category_family() is merchant/category-scoped (not trigger-scoped), so both
    # triggers already share it by definition.  We assert it is not "generic" so
    # we never fuse signals that lack a real vertical context.
    family = category_family(category, merchant)
    if not family or family == "generic":
        return False

    return True


def fusion_rationale(triggers: list[dict[str, Any]], merchant: dict[str, Any] | None = None, category: dict[str, Any] | None = None) -> str:
    if not triggers:
        return ""
    family = category_family(category, merchant)
    selected_scores = [trigger_business_importance(t, merchant, category) for t in triggers]
    total_score = sum(selected_scores)
    peak_score = max(selected_scores)
    peak_trigger = triggers[selected_scores.index(peak_score)]
    reasons = [trigger_reason_phrase(t, merchant, category) for t in triggers[:3]]

    shared_tokens = _token_set(*[payload_summary((t.get("payload") or {}), "") for t in triggers])
    shared_tokens &= FAMILY_CONTEXT_KEYWORDS.get(family, set())
    if shared_tokens:
        shared_theme = sorted(shared_tokens)[0]
    elif category and clean_text(category.get("name")):
        shared_theme = clean_text(category.get("name")).lower()
    else:
        shared_theme = family

    merchant_note = metric_line(merchant or {}) or "current merchant context"
    peak_reason = trigger_reason_phrase(peak_trigger, merchant, category)
    return (
        f"These triggers belong together because they stack pressure on {shared_theme} rather than separate problems. "
        f"The strongest signal is {peak_reason}, and the group totals {total_score} importance points. "
        f"With {merchant_note}, one coordinated response is more efficient than sending separate nudges. "
        f"Signals: {' | '.join(reasons)}."
    )


def compose_fused_merchant_message(category: dict[str, Any], merchant: dict[str, Any], triggers: list[dict[str, Any]]) -> dict[str, Any]:
    # Always fuse exactly 2 – enforced by should_fuse_triggers, but be defensive.
    ranked = sorted(triggers, key=lambda t: rank_trigger(t, merchant, category), reverse=True)
    selected = ranked[:2]
    primary = selected[0]

    name = salutation(category, merchant)
    family = category_family(category, merchant)
    offer = active_offer(merchant, category)
    archetype = trigger_archetype(primary)

    # One tight signal phrase per trigger – avoids blowing the 320-char budget.
    sig1 = fusion_signal(selected[0], merchant, category)
    sig2 = fusion_signal(selected[1], merchant, category)

    cta = render_cta(archetype.cta_type, family, offer, None)

    # Body template: greeting + two signals + single action CTA.
    # Keeps the message concrete and within WhatsApp norms.
    body = f"{name}, two signals need attention: {sig1} & {sig2}. {cta}"

    rationale_text = (
        f"Fused 2 triggers (same archetype={archetype.name}, "
        f"business_problem={archetype.business_problem}); "
        f"primary={primary.get('id')}; "
        f"scores={[rank_trigger(t, merchant, category) for t in selected]}; "
        f"signals={[t.get('kind') for t in selected]}."
    )

    from .sanitization import clamp_body
    return sanitize_message(
        {
            "body": clamp_body(body, 320),
            "cta": cta_for(normalized_kind_for_context(primary, category, merchant), None),
            "send_as": "vera",
            "suppression_key": standard_suppression_key(primary, category, merchant),
            "rationale": rationale_text,
        },
        category,
        merchant,
        primary,
        None,
    )