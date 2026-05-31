from __future__ import annotations

from typing import Any

from .intents import active_offer, category_family, family_offer_noun, metric_line, render_cta, salutation, FAMILY_CONTEXT_KEYWORDS, cta_for
from .models import MessagePlan
from .scoring import generic_payload_facts, rank_trigger, trigger_business_importance, trigger_reason_phrase, _token_set, payload_summary, trigger_archetype
from .sanitization import clean_text
from .state import CONTEXTS, normalized_kind_for_context
from .suppression import standard_suppression_key
from .compose_merchant import sanitize_message


def fusion_signal(trigger: dict[str, Any], merchant: dict[str, Any] | None = None, category: dict[str, Any] | None = None) -> str:
    payload = trigger.get("payload", {})
    kind = clean_text(trigger.get("kind") or "signal")
    facts = generic_payload_facts(payload, 2)
    score = trigger_business_importance(trigger, merchant, category)
    if facts:
        return f"{kind}: {', '.join(facts)} (importance {score})"
    return f"{kind} (importance {score})"


def should_fuse_triggers(triggers, merchant=None, category=None):
    if len(triggers) < 2:
        return False
    scores = sorted((rank_trigger(t, merchant, category) for t in triggers), reverse=True)
    if scores[0] >= 75 and scores[1] >= 60:
        return True
    if sum(scores[:2]) >= 140:
        return True
    return False


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
    primary = sorted(triggers, key=lambda t: rank_trigger(t, merchant, category), reverse=True)[0]
    selected = sorted(triggers, key=lambda t: rank_trigger(t, merchant, category), reverse=True)[:3]
    name = salutation(category, merchant)
    family = category_family(category, merchant)
    offer = active_offer(merchant, category)
    signals = "; ".join(fusion_signal(t, merchant, category) for t in selected)
    snapshot = metric_line(merchant)
    proof = f" Current profile: {snapshot}." if snapshot else ""
    archetypes = [trigger_archetype(t) for t in selected]
    action = archetypes[0].recommended_action
    count_word = "three" if len(selected) >= 3 else "two"
    cta = render_cta(archetypes[0].cta_type, family, offer, None)
    plan = MessagePlan(
        fact=f"{count_word} signals point to one coordinated response: {signals}",
        implication=fusion_rationale(selected, merchant, category) + proof,
        action=f"I can {action} around {offer or f'your {family_offer_noun(family)}'}",
        cta=cta,
        cta_type=archetypes[0].cta_type,
    )
    body = f"{name}, {plan.fact}. {plan.implication}. {plan.action}. {plan.cta}"
    rationale_text = (
        f"Fused {len(selected)} merchant triggers for one action; primary={primary.get('id')}; "
        f"scores={[rank_trigger(t, merchant, category) for t in selected]}; signals={[t.get('kind') for t in selected]}."
    )
    return sanitize_message(
        {
            "body": body,
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
