from __future__ import annotations

from typing import Any

from .compose_customer import action_followup_body, compose_customer, enhance_reply_with_ai, objection_reply_body
from .compose_merchant import compose, compose_merchant, compose_unknown_trigger, deterministic_compose, enrich_body_with_context
from .intents import *
from .models import MessagePlan, TriggerArchetype
from .profiles import merchant_profile, remember_open_issue, remember_resolved_issue, reset_merchant_auto_reply, track_merchant_auto_reply, update_merchant_profile
from .sanitization import *
from .scoring import *
from .state import *
from .suppression import *
from .trigger_fusion import *
from .insights import extract_insights, build_message_plan, clear_insight_cache

def action_from_message(
    *,
    now: str,
    merchant: dict[str, Any],
    category: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None,
    message: dict[str, Any],
    fused_triggers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    conv_id = make_conversation_id(merchant.get("merchant_id", ""), trigger.get("id", ""), trigger.get("customer_id"))
    structured_state = build_structured_state(merchant, category, trigger, customer, message)
    CONVERSATIONS[conv_id] = {
        "merchant_id": merchant.get("merchant_id"),
        "customer_id": trigger.get("customer_id"),
        "trigger_id": trigger.get("id"),
        "fused_trigger_ids": [t.get("id") for t in (fused_triggers or [])],
        "structured_state": structured_state,
        "turns": [{"from": "bot", "body": message["body"], "at": now}],
        "auto_reply_count": 0,
        "topic_drift_count": 0,
        "objection_count": 0,
        "ended": False,
    }
    return {
        "conversation_id": conv_id,
        "merchant_id": merchant.get("merchant_id"),
        "customer_id": trigger.get("customer_id"),
        "send_as": message["send_as"],
        "trigger_id": trigger.get("id"),
        "template_name": template_name(trigger, customer, category, merchant),
        "template_params": [message["body"][:220]],
        **message,
    }


def tick(now: str, available_triggers: list[str]) -> dict[str, Any]:
    actions = []

    candidate_triggers = []
    for trigger_id in available_triggers:
        t = get_payload("trigger", trigger_id)
        if t is None:
            print(f"[tick] MISSING trigger id={trigger_id}", flush=True)
        else:
            candidate_triggers.append(t)

    print(f"[tick] resolved {len(candidate_triggers)}/{len(available_triggers)} triggers", flush=True)

    enriched_triggers = []
    for trigger in candidate_triggers:
        mid = trigger.get("merchant_id")
        merchant = get_payload("merchant", mid)
        if not merchant:
            stored = [cid for (s, cid) in CONTEXTS if s == "merchant"]
            print(f"[tick] MISSING merchant mid={mid}, stored={stored}", flush=True)
            continue
        slug = merchant.get("category_slug")
        category = get_payload("category", slug) or {"slug": slug or "local_services"}
        trigger.setdefault("__summary", payload_summary(trigger.get("payload", {})))
        trigger.setdefault("__tokens", _cached_trigger_tokens(trigger))
        enriched_triggers.append((trigger, merchant, category))

    print(f"[tick] enriched={len(enriched_triggers)}", flush=True)
    enriched_triggers.sort(key=lambda item: rank_trigger(item[0], item[1], item[2]), reverse=True)

    for trigger, merchant, category in enriched_triggers:
        if len(actions) >= 20:
            break
        sup_key = standard_suppression_key(trigger, category, merchant)
        if sup_key in SENT_SUPPRESSIONS:
            print(f"[tick] SUPPRESSED {trigger.get('id')} key={sup_key}", flush=True)
            continue
        customer = get_payload("customer", trigger.get("customer_id")) if trigger.get("customer_id") else None
        if trigger.get("scope") == "customer" and not customer:
            customer = None
            trigger = {**trigger, "scope": "merchant", "customer_id": None}
        try:
            message = compose(category, merchant, trigger, customer)
            SENT_SUPPRESSIONS.add(message["suppression_key"])
            actions.append(action_from_message(
                now=now, merchant=merchant, category=category,
                trigger=trigger, customer=customer, message=message
            ))
            print(f"[tick] ACTION created for trigger={trigger.get('id')} kind={trigger.get('kind')}", flush=True)
        except Exception as e:
            import traceback
            print(f"[tick] ERROR composing trigger={trigger.get('id')}: {e}", flush=True)
            traceback.print_exc()

    print(f"[tick] returning {len(actions)} actions", flush=True)
    if not actions and enriched_triggers:
        print("[tick] WARNING: enriched triggers present but zero actions produced — "
              "check suppression keys or compose errors", flush=True)
    elif not actions and not enriched_triggers and available_triggers:
        print("[tick] WARNING: no merchant context resolved for any trigger — "
              "push merchant contexts before calling tick", flush=True)
    return {"actions": actions}


def reply(conversation_id: str, merchant_id: str | None, customer_id: str | None, message: str, turn_number: int) -> dict[str, Any]:
    state = CONVERSATIONS.setdefault(
        conversation_id,
        {
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "trigger_id": None,
            "structured_state": {**empty_structured_state(), "merchant_id": merchant_id, "customer_id": customer_id},
            "turns": [],
            "auto_reply_count": 0,
            "topic_drift_count": 0,
            "objection_count": 0,
            "ended": False,
        },
    )
    msg = clean_text(message)
    low = msg.lower()
    structured = state.setdefault("structured_state", empty_structured_state())
    intent = classify_intent(msg)
    structured["last_customer_intent"] = intent
    update_merchant_profile(merchant_id or state.get("merchant_id"), intent, msg)
    state["turns"].append({"from": "merchant", "body": msg, "turn": turn_number, "at": utc_now()})

    if any(re.search(p, low) for p in STOP_PATTERNS):
        state["ended"] = True
        structured["opted_out"] = True
        return {"action": "end", "rationale": "Merchant explicitly opted out or reacted negatively; closing without another nudge."}

    if any(re.search(p, low) for p in HOSTILE_PATTERNS):
        response = {
            "action": "send",
            "body": "Understood. I will keep this brief and only stay on the Vera task: I can prepare the draft for your approval, and nothing goes out without your CONFIRM.",
            "cta": "take_action",
            "rationale": "Acknowledged hostile tone without escalating and returned to the active Vera task.",
        }
        structured["last_bot_cta"] = response["cta"]
        structured["last_bot_body"] = response["body"]
        return enhance_reply_with_ai(conversation_id, msg, response)

    if any(re.search(p, low) for p in AUTO_REPLY_PATTERNS):
        state["auto_reply_count"] = state.get("auto_reply_count", 0) + 1
        merchant_auto_count = track_merchant_auto_reply(merchant_id or state.get("merchant_id"), msg)
        effective_count = max(int(state["auto_reply_count"]), merchant_auto_count)
        structured["auto_reply_count"] = effective_count
        if effective_count >= 3:
            state["ended"] = True
            remember_resolved_issue(merchant_id or state.get("merchant_id"), "auto_reply_loop")
            return {"action": "end", "rationale": "Detected repeated WhatsApp Business auto-reply three times; ending the conversation."}
        wait = 86400 if effective_count >= 2 else 14400
        return {"action": "wait", "wait_seconds": wait, "rationale": "Detected canned auto-reply; backing off for the owner/manager."}

    state["auto_reply_count"] = 0
    structured["auto_reply_count"] = 0
    reset_merchant_auto_reply(merchant_id or state.get("merchant_id"))

    if any(re.search(p, low) for p in OFFTOPIC_PATTERNS):
        state["topic_drift_count"] = int(state.get("topic_drift_count", 0)) + 1
        if state["topic_drift_count"] >= 3:
            state["ended"] = True
            return {"action": "end", "rationale": "Merchant repeatedly moved off-topic; ending instead of sending more nudges."}
        response = {
            "action": "send",
            "body": "That part is better handled outside Vera. For this task, I can keep it simple: one draft, no send without your approval. Reply CONFIRM to proceed.",
            "cta": "take_action",
            "rationale": "Politely declined an out-of-scope request and redirected to the active conversation goal.",
        }
        structured["last_bot_cta"] = response["cta"]
        structured["last_bot_body"] = response["body"]
        return enhance_reply_with_ai(conversation_id, msg, response)

    if any(re.search(p, low) for p in OBJECTION_PATTERNS):
        state["objection_count"] = int(state.get("objection_count", 0)) + 1
        body = objection_reply_body(state, low)
        state["turns"].append({"from": "bot", "body": body, "at": utc_now()})
        response = {
            "action": "send",
            "body": body,
            "cta": "next_step",
            "rationale": "Handled merchant objection with a lower-friction option and kept the conversation on the active task.",
        }
        structured["last_bot_cta"] = response["cta"]
        structured["last_bot_body"] = response["body"]
        return enhance_reply_with_ai(conversation_id, msg, response)

    if any(re.search(p, low) for p in YES_PATTERNS):
        structured["action_confirmed"] = True
        body = action_followup_body(state)
        state["turns"].append({"from": "bot", "body": body, "at": utc_now()})
        response = {
            "action": "send",
            "body": body,
            "cta": "take_action",
            "rationale": "Merchant signaled intent; switching from pitching to action mode with a concrete draft/confirmation step.",
        }
        structured["last_bot_cta"] = response["cta"]
        structured["last_bot_body"] = response["body"]
        return enhance_reply_with_ai(conversation_id, msg, response)

    body = "Got it. I will keep it practical: I can draft one version, keep it category-safe, and wait for your approval before sending. Reply YES and I will prepare the preview."
    state["turns"].append({"from": "bot", "body": body, "at": utc_now()})
    response = {"action": "send", "body": body, "cta": "next_step", "rationale": "Acknowledged the reply and offered one low-friction next step."}
    structured["last_bot_cta"] = response["cta"]
    structured["last_bot_body"] = response["body"]
    return enhance_reply_with_ai(conversation_id, msg, response)

def healthz() -> dict[str, Any]:
    from .insights import _INSIGHT_CACHE
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": context_counts(),
        "suppressions_active": len(SENT_SUPPRESSIONS),
        "conversations": len(CONVERSATIONS),
        "auto_reply_counts": len(MERCHANT_AUTO_REPLY_COUNTS),
        "insight_cache_size": len(_INSIGHT_CACHE),   # ← add this line
    }

def metadata() -> dict[str, Any]:
    return TEAM_METADATA


import re
import time

from .scoring import _cached_trigger_tokens, payload_summary, rank_trigger
from .suppression import context_counts, get_payload, push_context, standard_suppression_key, _id_aliases
from .profiles import update_merchant_profile, track_merchant_auto_reply, reset_merchant_auto_reply, remember_resolved_issue
from .sanitization import clean_text
from .state import (
    AUTO_REPLY_PATTERNS,
    CONVERSATIONS,
    CONTEXTS,
    HOSTILE_PATTERNS,
    INTERNAL_BODY_TERMS,
    KNOWN_TRIGGERS,
    MERCHANT_AUTO_REPLY_COUNTS,
    OFFTOPIC_PATTERNS,
    OBJECTION_PATTERNS,
    SENT_SUPPRESSIONS,
    STOP_PATTERNS,
    TEAM_METADATA,
    VALID_SCOPES,
    YES_PATTERNS,
    build_structured_state,
    classify_intent,
    empty_structured_state,
    normalized_kind_for_context,
    utc_now,
)
from .intents import *
from .compose_customer import compose_customer, objection_reply_body, action_followup_body
from .compose_merchant import compose as compose, compose_merchant, compose_unknown_trigger, deterministic_compose, enrich_body_with_context
from .trigger_fusion import *
