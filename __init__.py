from __future__ import annotations

import re
from typing import Any

from .compose_customer import action_followup_body, compose_customer, objection_reply_body
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


_SLOT_RE = re.compile(
    r"\b(?:mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)"
    # Accept natural WhatsApp variants such as "Wed, 5th November at 6 pm"
    # as well as the compact "Wed 5 Nov, 6pm" form used in the test harness.
    r"\s*,?\s+\d{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9}\s*,?\s*(?:at\s+)?"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    re.I,
)

OPTION1_PATTERNS = [
    r"\bfirst\s+slot\b",
    r"\boption\s+1\b",
    r"\b1st\s+slot\b",
    r"\bearlier\s+slot\b",
    r"\bearlier\s+one\b",
    r"\bslot\s+1\b",
    r"\bfirst\s+one\b",
    r"\bgo\s+with\s+(the\s+)?first\b",
]
OPTION2_PATTERNS = [
    r"\bsecond\s+slot\b",
    r"\boption\s+2\b",
    r"\b2nd\s+slot\b",
    r"\blater\s+slot\b",
    r"\blater\s+one\b",
    r"\bslot\s+2\b",
    r"\bsecond\s+one\b",
    r"\bgo\s+with\s+(the\s+)?second\b",
]

_XRAY_TERMS = {
    "x-ray", "xray", "x ray",
    "d-speed", "d speed", "e-speed", "e speed",
    "film unit", "film-unit", "film machine",
    "radiograph", "radiography",
    "analogue x", "analog x",
    "dental film", "intraoral film",
    "opg", "cbct", "cone beam", "rvg", "digital sensor",
    "panoramic", "radiology",
    # Equipment / process vocabulary a practice owner actually uses when the
    # imaging setup is the problem, not just the machine name.
    "darkroom", "developer", "fixer", "emulsion", "safelight", "safe light",
    "pacs", "ceph", "phosphor", "imaging plate", "cassette",
    "collimator", "dosimetry", "dosimeter", "tld", "lead apron",
    "bitewing", "periapical", "underexposed", "overexposed", "fogging",
    "cone cut", "light leak", "double exposure", "radiation dose",
    "exposure time", "exposure chart", "grey scale", "gray scale",
    "image quality", "scan quality", "blurry", "low contrast", "retake",
}
_XRAY_SOFT_TERMS = {
    "imaging", "scan result", "image clarity", "old machine", "old unit",
    "old equipment", "poor quality", "unclear image", "unclear scan",
    "blurry", "not working", "malfunctioning", "needs servicing",
}
_CLINIC_CONTEXT_TERMS = {
    "patient", "patients", "clinic", "dental", "dentist",
    "doctor", "dr ", "appointment", "checkup", "diagnosis",
    "teeth", "tooth", "jaw", "oral", "mouth", "opg", "pans", "x-ray",
}
_XRAY_CONTEXT_BOOST = {
    "audit": 1, "setup": 1, "old": 1, "broken": 2, "issue": 1,
    "problem": 1, "help": 1, "check": 1, "upgrade": 2, "replace": 2,
    "not working": 2, "calibrate": 2, "compliance": 2, "safety": 1,
    "exhausted": 2, "faded": 2, "drifting": 2, "quality": 1, "fault": 2,
}

# Each profile answers the merchant's stated setup with the first thing worth
# checking, instead of only promising a preview. `answer` is the substantive
# half; `checklist` names the artefact that a YES delivers.
_XRAY_PROFILES = [
    {
        "issue": "D-speed film X-ray setup",
        "answer": "Contrast falls before detail does, so check developer temperature and fixer exhaustion first - and D-speed needs a longer exposure than E-speed for the same density",
        "checklist": "film speed compliance, exposure settings, processing chemistry, darkroom safety and the digital upgrade path",
        "keywords": {"d-speed", "d speed", "slow film"},
        "weight": 3,
    },
    {
        "issue": "E-speed film X-ray setup",
        "answer": "E-speed tolerates a wider exposure window, so uneven density usually points at the exposure timer or a weak battery rather than the film stock itself",
        "checklist": "film speed settings, exposure consistency, darkroom processing and digital upgrade options",
        "keywords": {"e-speed", "e speed", "ekta", "kodak film"},
        "weight": 3,
    },
    {
        "issue": "film-based X-ray unit",
        "answer": "Three things cause most film faults - exhausted fixer, light leaks at the cassette and a drifting timer - and all three are cheap to rule out before you price up sensors",
        "checklist": "film processing quality, exposure consistency, safety signage and the transition checklist to digital",
        "keywords": {"film unit", "film-unit", "film machine", "dental film", "intraoral film", "darkroom", "film based", "film-based"},
        "weight": 2,
    },
    {
        "issue": "analogue X-ray system",
        "answer": "Analogue setups only fail visibly once tube output drifts, so a baseline exposure chart plus quarterly dosimetry catches it long before patients complain",
        "checklist": "analogue-to-digital readiness, exposure settings, processing unit condition and safety compliance",
        "keywords": {"analogue x", "analog x", "conventional xray", "conventional x-ray", "old xray", "old x-ray"},
        "weight": 2,
    },
    {
        "issue": "digital X-ray setup",
        "answer": "Digital faults are usually calibration or archiving rather than the sensor, so check the calibration plate first and confirm images are saving to the right study",
        "checklist": "sensor calibration, software version, exposure settings and image storage compliance",
        "keywords": {"digital sensor", "ccd sensor", "psp", "rvg", "digital xray", "digital x-ray", "digital imaging", "pacs"},
        "weight": 2,
    },
    {
        "issue": "panoramic X-ray unit",
        "answer": "Panoramic faults are positioning first and rotation second, so check the patient guide and rotation speed before touching the exposure side",
        "checklist": "rotation calibration, patient positioning guides, exposure settings and image quality checks",
        "keywords": {"panoramic", "opg", "orthopantomogram", "pan xray", "full mouth xray"},
        "weight": 2,
    },
    {
        "issue": "CBCT / 3D imaging setup",
        "answer": "CBCT dose is driven by the scan protocol, so trimming the field of view to the actual indication is usually the largest dose reduction still available to you",
        "checklist": "scan protocol review, radiation dose optimisation, software calibration and compliance checks",
        "keywords": {"cbct", "cone beam", "3d xray", "3d imaging", "volumetric", "cone-beam"},
        "weight": 2,
    },
    {
        "issue": "radiography setup",
        "answer": "A baseline exposure chart and a dosimetry badge tell you quickly whether the fault sits in the machine or in the technique",
        "checklist": "exposure consistency, image quality checks, radiation safety compliance and equipment calibration",
        "keywords": {"radiograph", "radiography", "radiology", "x-ray machine", "xray machine", "imaging unit"},
        "weight": 1,
    },
]


def _score_xray_profile(low: str, profile: dict[str, Any]) -> float:
    score = 0.0
    for keyword in profile["keywords"]:
        if keyword in low:
            score += profile["weight"]
            pos = low.find(keyword)
            window = low[max(0, pos - 30): pos + len(keyword) + 30]
            for context_word, boost in _XRAY_CONTEXT_BOOST.items():
                if context_word in window:
                    score += boost * 0.5
    return score


def extract_customer_slot(message: str) -> str:
    match = _SLOT_RE.search(clean_text(message))
    if match:
        # Preserve the customer's spelling: title-casing turns "5th" into "5Th".
        return re.sub(r"\b(am|pm)\b", lambda item: item.group(1).lower(), match.group(0).strip(" .,"), flags=re.I)
    return ""


def resolve_slot_choice(message: str, available_slots: list[Any] | None) -> str:
    """Resolve a bare ordinal answer ("1", "option 2", "the later one").

    Returns a human label for the chosen slot, or "" when the message carries no
    usable choice. Ordinal answers are matched against the slots we actually
    offered so the confirmation quotes a real time rather than "the first slot".
    """
    low = clean_text(message).lower()
    ordinal = slot_ordinal(low)
    if ordinal is None:
        if any(re.search(p, low) for p in OPTION1_PATTERNS):
            ordinal = 1
        elif any(re.search(p, low) for p in OPTION2_PATTERNS):
            ordinal = 2
    if ordinal is None:
        return ""
    labels: list[str] = []
    for slot in available_slots or []:
        label = clean_text(slot.get("label") if isinstance(slot, dict) else slot)
        if label:
            labels.append(label)
    if 1 <= ordinal <= len(labels):
        return labels[ordinal - 1]
    return f"the {'first' if ordinal == 1 else 'second'} slot"


def _technical_profile_for(message: str) -> tuple[dict[str, Any], float, float] | None:
    """Pick the imaging/equipment profile that best matches what the merchant said."""
    low = clean_text(message).lower()
    hard_match = any(term in low for term in _XRAY_TERMS)
    soft_match = any(term in low for term in _XRAY_SOFT_TERMS) and any(ctx in low for ctx in _CLINIC_CONTEXT_TERMS)
    if not hard_match and not soft_match:
        return None
    scores = sorted(((_score_xray_profile(low, profile), profile) for profile in _XRAY_PROFILES), key=lambda item: item[0], reverse=True)
    best_score, best_profile = scores[0]
    gap = best_score - scores[1][0] if len(scores) > 1 else best_score
    return best_profile, best_score, gap


_CTA_CHOICE_RE = re.compile(
    r"(?:^|[\s:;,(\[])1(?=[\s:,;]|\s*$)\s*(?:for|to|means|=|:)?\s*(?P<one>[^,;]+?)"
    r"\s*[,;]\s*(?:or\s+)?2(?=[\s:,;]|\s*$)\s*(?:for|to|means|=|:)?\s*(?P<two>[^,;]+?)"
    r"\s*[,;]\s*(?:or\s+)?3(?=[\s:,;]|\s*$)\s*(?:for|to|means|=|:)?\s*(?P<three>[^,;?.]+)",
    re.I,
)


def _merchant_choice_label(last_bot_body: str, ordinal: int) -> str:
    """Recover the label a merchant picked from the 'Reply 1 for X, 2 for Y' CTA.

    Lets a bare "2" commit to the deliverable we actually offered instead of
    falling through to a generic acknowledgement. Returns "" when the previous
    message was not a numbered choice.
    """
    match = _CTA_CHOICE_RE.search(clean_text(last_bot_body))
    if not match:
        return ""
    label = clean_text(match.group({1: "one", 2: "two", 3: "three"}.get(ordinal, "")) or "")
    label = re.split(r"\s+[-\u2013\u2014]\s+", label)[0]
    label = re.sub(r"^(?:the|a|an)\s+", "", label, flags=re.I).strip(" .")
    if not label or len(label) > 90:
        return ""
    if label.lower() in {"both", "all", "both options", "both in one pass"}:
        other = {1: "two", 2: "one"}.get(ordinal)
        partner = clean_text(match.group(other) or "").strip(" .") if other else ""
        return f"both - {partner} and the other in one pass" if partner else "both options in one pass"
    return label


def _slot_prompt_active(state: dict[str, Any]) -> bool:
    """True only when the last bot turn actually offered bookable slots.

    Without this, a merchant replying "1" to 'Reply 1 for the source summary,
    2 for a WhatsApp draft' would be read as picking a slot.
    """
    structured = state.get("structured_state", {}) or {}
    if not structured.get("available_slots"):
        return False
    last = clean_text(structured.get("last_bot_body") or "").lower()
    return bool(re.search(r"\bslots?\b|\bbook|\bavailable\b|reply\s*1\s*or\s*2|\bconfirm\b|\bhold\b", last))


def _owner_salutation(state: dict[str, Any]) -> str:
    structured = state.get("structured_state", {}) or {}
    merchant = state.get("merchant", {}) or {}
    category = state.get("category", {}) or {}
    if merchant and category:
        return salutation(category, merchant)
    return clean_text(structured.get("owner_first_name") or "Doc")


def merchant_issue_followup_body(state: dict[str, Any], message: str) -> str:
    """Answer a merchant's stated imaging/equipment problem in their own terms.

    Returns "" when the message is not about imaging or equipment. The first
    sentence is a real answer drawn from the matched profile; the CTA offers
    the written audit checklist. Never a generic approval prompt.
    """
    matched = _technical_profile_for(message)
    if not matched:
        return ""
    best_profile, best_score, gap = matched
    name = _owner_salutation(state)
    issue = best_profile["issue"]
    article = "an" if issue[0].lower() in "aeiou" else "a"
    answer = clean_text(best_profile["answer"])

    if best_score >= 4 and gap >= 1.5:
        return enforce_body_limit(
            f"Got it {name} - on {article} {issue}: {answer}. "
            f"Reply YES and I will send the full audit checklist."
        )
    if best_score >= 2:
        return enforce_body_limit(
            f"Got it {name} - on {article} {issue}: {answer}. "
            f"Reply YES for the audit checklist, or tell me if I have the setup wrong."
        )
    return enforce_body_limit(
        f"Got it {name} - before I write the audit checklist, is this film-based (D/E-speed) "
        f"or digital (RVG/CBCT)? Reply FILM or DIGITAL and I will answer it directly."
    )


def technical_preview_body(state: dict[str, Any]) -> str:
    """Deliver the audit checklist a merchant asked for with their first YES."""
    last_bot_body = clean_text((state.get("structured_state", {}) or {}).get("last_bot_body") or "")
    for profile in _XRAY_PROFILES:
        if any(kw in last_bot_body.lower() for kw in profile["keywords"]):
            return enforce_body_limit(
                f"Here is the {profile['issue']} audit checklist: {profile['checklist']}. "
                f"Reply CONFIRM to send it to the team, or CHANGE with what to adjust."
            )
    return enforce_body_limit(
        f"Here is the audit checklist: {clean_text(last_bot_body) or 'film speed, exposure settings, processing unit and upgrade path'}. "
        f"Reply CONFIRM to send it, or CHANGE with what to adjust."
    )


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
    # Compose paths normally sanitize their own output, but this is the public
    # action boundary. Keep the contract true even when a new composer is added.
    message = {**message, "body": enforce_body_limit(message.get("body", ""))}
    conv_id = make_conversation_id(merchant.get("merchant_id", ""), trigger.get("id", ""), trigger.get("customer_id"))
    structured_state = build_structured_state(merchant, category, trigger, customer, message)
    # Link prior conversations for this merchant so reply() has cross-trigger context.
    prior_conv_ids = [
        cid for cid, c in CONVERSATIONS.items()
        if c.get("merchant_id") == merchant.get("merchant_id")
        and c.get("trigger_id") != trigger.get("id")
    ]
    CONVERSATIONS[conv_id] = {
        "merchant_id": merchant.get("merchant_id"),
        "customer_id": trigger.get("customer_id"),
        "trigger_id": trigger.get("id"),
        "merchant": merchant,
        "category": category,
        "trigger": trigger,
        "customer": customer,
        "fused_trigger_ids": [t.get("id") for t in (fused_triggers or [])],
        "structured_state": structured_state,
        "turns": [{"from": "bot", "body": message["body"], "at": now}],
        "history": prior_conv_ids[-3:],  # last 3 prior conv IDs for this merchant
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

    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {}
    for item in enriched_triggers:
        trigger, merchant, _category = item
        grouped.setdefault(clean_text(merchant.get("merchant_id")), []).append(item)

    merchant_batches = []
    for merchant_id, items in grouped.items():
        items.sort(key=lambda item: rank_trigger(item[0], item[1], item[2]), reverse=True)
        merchant_batches.append((rank_trigger(items[0][0], items[0][1], items[0][2]), merchant_id, items))
    merchant_batches.sort(reverse=True, key=lambda item: item[0])

    for _score, _merchant_id, items in merchant_batches:
        if len(actions) >= 20:
            break
        trigger, merchant, category = items[0]
        sup_key = standard_suppression_key(trigger, category, merchant)
        if sup_key in SENT_SUPPRESSIONS:
            print(f"[tick] SUPPRESSED {trigger.get('id')} key={sup_key}", flush=True)
            continue
        customer = get_payload("customer", trigger.get("customer_id")) if trigger.get("customer_id") else None
        if trigger.get("scope") == "customer" and not customer:
            # Customer profiles are optional in the context protocol. Preserve
            # the trigger scope so compose_customer_context_gap() can produce
            # an owner-facing booking/refill action rather than a generic post.
            customer = None
        try:
            fusion_kinds = {
                "perf_dip", "perf_spike", "seasonal_perf_dip", "renewal_due",
                "competitor_opened", "review_theme_emerged", "milestone_reached",
                "winback_eligible", "dormant_with_vera", "gbp_unverified",
                "festival_upcoming", "ipl_match_today", "category_seasonal",
            }
            merchant_only = [
                item[0] for item in items
                if not item[0].get("customer_id")
                and item[0].get("scope") != "customer"
                and normalized_kind_for_context(item[0], category, merchant) in fusion_kinds
            ]
            if customer is None and should_fuse_triggers(merchant_only, merchant, category):
                selected = sorted(merchant_only, key=lambda t: rank_trigger(t, merchant, category), reverse=True)[:3]
                message = compose_fused_merchant_message(category, merchant, selected)
                for selected_trigger in selected:
                    SENT_SUPPRESSIONS.add(standard_suppression_key(selected_trigger, category, merchant))
            else:
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


def _send(
    state: dict[str, Any],
    structured: dict[str, Any],
    body: str,
    cta: str,
    rationale: str,
) -> dict[str, Any]:
    """Single exit for every outbound body: hard 320-char cap + bookkeeping."""
    capped = enforce_body_limit(body)
    state["turns"].append({"from": "bot", "body": capped, "at": utc_now()})
    structured["last_bot_cta"] = cta
    structured["last_bot_body"] = capped
    return {"action": "send", "body": capped, "cta": cta, "rationale": rationale}


def _reply_merchant(state: dict[str, Any], structured: dict[str, Any], msg: str, low: str) -> dict[str, Any]:
    """Merchant/owner turns: answer the stated problem, then move to one next step."""
    # 1. A specific imaging or equipment problem gets a specific answer, never a
    #    generic approval prompt.
    issue_body = merchant_issue_followup_body(state, msg)
    if issue_body:
        return _send(
            state, structured, issue_body, "take_action",
            "Merchant named a specific imaging/equipment setup; answered that setup directly "
            "and offered the matching audit checklist.",
        )

    # 2. A merchant can also book on a customer's behalf, so a named slot stays
    #    valid here. A bare "1"/"2" only counts as a slot when the last turn
    #    actually offered slots — otherwise it is a choice of deliverable.
    picked_slot = extract_customer_slot(msg)
    if not picked_slot and _slot_prompt_active(state):
        picked_slot = resolve_slot_choice(low, structured.get("available_slots"))
    if picked_slot:
        customer_name = clean_text(structured.get("customer_name") or "")
        subject = f" for {customer_name}" if customer_name else ""
        structured["selected_slot"] = picked_slot
        structured["action_confirmed"] = True
        return _send(
            state, structured,
            f"Slot held{subject} for {picked_slot}. Reply CONFIRM and the clinic sees it as booked, "
            f"or CHANGE with a different time.",
            "confirm_slot",
            "Merchant picked a concrete slot; confirmed that time instead of re-pitching the draft.",
        )

    # 3. A bare "1"/"2"/"3" answers the numbered CTA we sent last turn.
    ordinal = slot_ordinal(low)
    if ordinal:
        label = _merchant_choice_label(clean_text(structured.get("last_bot_body") or ""), ordinal)
        if label:
            structured["action_confirmed"] = True
            return _send(
                state, structured,
                f"Got it {_owner_salutation(state)} - I will prepare the {label} now, category-safe, "
                f"and nothing is sent until you approve it. Reply CHANGE with anything to adjust.",
                "take_action",
                f"Merchant picked option {ordinal} of the offered CTA; committed to that specific deliverable.",
            )

    # 3. Out-of-scope business question: decline once, redirect, and stop after
    #    three attempts instead of piling on.
    if any(re.search(p, low) for p in OFFTOPIC_PATTERNS):
        state["topic_drift_count"] = int(state.get("topic_drift_count", 0)) + 1
        if state["topic_drift_count"] >= 3:
            state["ended"] = True
            return {"action": "end", "rationale": "Merchant repeatedly moved off-topic; ending instead of sending more nudges."}
        return _send(
            state, structured,
            "That is better handled outside Vera. On the task we are on, I can keep it to one draft "
            "and nothing goes out without your approval. Reply CONFIRM to proceed.",
            "take_action",
            "Declined an out-of-scope request and redirected to the active Vera task.",
        )

    # 4. Objection: lower the friction rather than repeating the pitch.
    if any(re.search(p, low) for p in OBJECTION_PATTERNS):
        state["objection_count"] = int(state.get("objection_count", 0)) + 1
        return _send(
            state, structured, objection_reply_body(state, low), "next_step",
            "Handled a merchant objection with a lower-friction option and kept the active task on track.",
        )

    # 5. Affirmative. If the previous turn promised an audit checklist, deliver it.
    if any(re.search(p, low) for p in YES_PATTERNS):
        structured["action_confirmed"] = True
        last_bot_body = clean_text(structured.get("last_bot_body") or "").lower()
        if "checklist" in last_bot_body:
            return _send(
                state, structured, technical_preview_body(state), "take_action",
                "Merchant confirmed the imaging follow-up; delivered the promised audit checklist "
                "instead of a generic confirmation prompt.",
            )
        return _send(
            state, structured, action_followup_body(state), "take_action",
            "Merchant signalled intent; switched from pitching to one concrete draft awaiting approval.",
        )

    # 6. Open question from the owner: answer from pushed context only.
    if "?" in msg:
        return _send(
            state, structured, objection_reply_body(state, low), "answer_question",
            "Merchant asked a question; answered from pushed profile context and offered the short draft.",
        )

    # 7. Anything else: one acknowledgement, one low-friction next step.
    return _send(
        state, structured,
        f"Got it { _owner_salutation(state) }. I will keep it practical: one draft, category-safe, "
        f"and nothing sent without your approval. Reply YES and I will prepare the preview.",
        "next_step",
        "Acknowledged the reply and offered one low-friction next step.",
    )


def _reply_customer(state: dict[str, Any], structured: dict[str, Any], msg: str, low: str) -> dict[str, Any]:
    """Customer turns: stay in the patient voice and resolve the booking ask."""
    intent = classify_customer_intent(msg)

    # 1. A named day/time is a slot pick, whatever else the message contains.
    named_slot = extract_customer_slot(msg)
    if named_slot:
        structured["selected_slot"] = named_slot
        structured["action_confirmed"] = True
        return _send(
            state, structured, customer_slot_confirm_body(state, named_slot), "confirm_slot",
            "Customer named a specific day and time; confirmed that exact slot.",
        )

    # 2. A bare "1"/"2" resolves against the slots we actually offered.
    if intent == "slot_ordinal":
        ordinal = slot_ordinal(low) or 1
        return _send(
            state, structured, customer_slot_choice_body(state, ordinal), "confirm_slot",
            "Customer picked a numbered option; resolved it to the slot label we offered.",
        )

    # 3. Move the appointment rather than lose it.
    if intent == "reschedule":
        return _send(
            state, structured, customer_reschedule_body(state), "confirm_slot",
            "Customer asked to move the appointment; offered the open slots or asked for a time.",
        )

    # 4. Release the slot and stop the reminders.
    if intent == "cancel":
        structured["action_confirmed"] = False
        return _send(
            state, structured, customer_cancel_body(state), "confirm_slot",
            "Customer cancelled; released the slot and offered an easy rebook path.",
        )

    # 5. Asked for a person.
    if intent == "call_me":
        return _send(
            state, structured, customer_call_body(state), "next_step",
            "Customer asked to be called; confirmed the callback route instead of sending another nudge.",
        )

    # 6. Price/what-included question: answer from the pushed offer, no invention.
    if intent == "question":
        return _send(
            state, structured, customer_question_body(state, low), "answer_question",
            "Customer asked a question; answered the specific question type from pushed context only.",
        )

    # 7. Price or timing pushback: acknowledge without a discount reflex.
    if intent == "objection":
        state["objection_count"] = int(state.get("objection_count", 0)) + 1
        return _send(
            state, structured, customer_objection_body(state), "next_step",
            "Customer raised cost or timing; acknowledged it and kept reschedule/cancel open.",
        )

    # 8. Bare yes/CONFIRM: hold what is on offer rather than re-pitching a draft.
    if intent in {"confirm", "thanks"}:
        structured["action_confirmed"] = True
        body = customer_thanks_body(state) if intent == "thanks" else customer_confirm_body(state)
        return _send(
            state, structured, body, "confirm_slot",
            "Customer confirmed the pending slot; confirmed the concrete time we offered.",
        )

    # 9. Anything else: ask for the one detail needed to book.
    return _send(
        state, structured, customer_fallback_body(state), "confirm_slot",
        "Customer reply was not actionable; asked for the day and time needed to hold a slot.",
    )


def reply(
    conversation_id: str,
    merchant_id: str | None,
    customer_id: str | None,
    message: str,
    turn_number: int,
    from_role: str | None = None,
) -> dict[str, Any]:
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

    # Route on from_role first, then fall back to the customer ids the request and
    # the stored conversation carry. A customer never gets merchant copy.
    sender = resolve_sender_role(
        from_role,
        customer_id=customer_id,
        state_customer_id=state.get("customer_id"),
        state_customer_name=structured.get("customer_name"),
    )
    structured["last_inbound_role"] = sender
    if sender == "merchant":
        structured["last_customer_intent"] = classify_intent(msg)
        update_merchant_profile(merchant_id or state.get("merchant_id"), structured["last_customer_intent"], msg)
    else:
        structured["last_customer_intent"] = classify_customer_intent(msg)
    state["turns"].append({"from": sender, "body": msg, "turn": turn_number, "at": utc_now()})

    # ── Shared guards: opt-out, hostility, auto-reply. Both roles hit these first.
    if any(re.search(p, low) for p in STOP_PATTERNS):
        state["ended"] = True
        structured["opted_out"] = True
        return {
            "action": "end",
            "rationale": f"{sender.capitalize()} explicitly opted out or reacted negatively; closing without another nudge.",
        }

    if any(re.search(p, low) for p in HOSTILE_PATTERNS):
        if sender == "customer":
            # The body promises reminders stop, so the state has to agree with it.
            state["ended"] = True
            structured["opted_out"] = True
            return _send(
                state, structured,
                "Sorry about that. I will stop the reminders now, and nothing further is scheduled. "
                "Reply START any time to switch them back on.",
                "next_step",
                "Customer was hostile; stopped the reminders without escalating or arguing.",
            )
        return _send(
            state, structured,
            "Understood. I will keep this brief and stay only on the Vera task: one draft for your "
            "approval, and nothing is sent without your CONFIRM.",
            "take_action",
            "Merchant was hostile; did not escalate and returned to the active Vera task.",
        )

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

    if sender == "customer":
        return _reply_customer(state, structured, msg, low)
    return _reply_merchant(state, structured, msg, low)


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
    classify_customer_intent,
    classify_intent,
    empty_structured_state,
    normalized_kind_for_context,
    resolve_sender_role,
    slot_ordinal,
    utc_now,
)
from .intents import *
from .compose_customer import (
    action_followup_body,
    compose_customer,
    customer_call_body,
    customer_cancel_body,
    customer_confirm_body,
    customer_fallback_body,
    customer_objection_body,
    customer_question_body,
    customer_reschedule_body,
    customer_slot_choice_body,
    customer_slot_confirm_body,
    customer_thanks_body,
    objection_reply_body,
)
from .compose_merchant import compose as compose, compose_merchant, compose_unknown_trigger, deterministic_compose, enrich_body_with_context
from .trigger_fusion import *
