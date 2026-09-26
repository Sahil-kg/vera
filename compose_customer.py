from __future__ import annotations

from typing import Any

from .intents import active_offer, active_offer_detail, category_customer_due_label, first_name, salutation
from .sanitization import clean_text, display_date, metric_label, safe_text


def _payload_slot_labels(payload: dict[str, Any]) -> list[str]:
    """Return human slot labels without exposing raw slot dictionaries."""
    slots = payload.get("available_slots") or payload.get("next_session_options") or []
    labels: list[str] = []
    for slot in slots:
        label = clean_text(slot.get("label") if isinstance(slot, dict) else slot)
        if label:
            labels.append(label)
    return labels


def compose_customer_context_gap(
    category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any]
) -> str:
    """Create a useful owner-facing action when customer context is unavailable.

    Some integrations intentionally push only merchant and trigger contexts. A
    customer-scoped trigger must still preserve its operational meaning; it
    must not fall through to a generic marketing-post template.
    """
    payload = trigger.get("payload", {}) or {}
    kind = clean_text(trigger.get("kind"))
    owner = salutation(category, merchant)
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)
    slots = _payload_slot_labels(payload)
    slot_text = " or ".join(slots[:2])

    if kind == "recall_due":
        due = category_customer_due_label(merchant.get("category_slug") or category.get("slug", ""), payload.get("service_due"))
        due_date = display_date(payload.get("due_date"))
        timing = f" by {due_date}" if due_date else ""
        slots_clause = f" Available: {slot_text}." if slot_text else ""
        return (
            f"{owner}, a {due} is due{timing}.{slots_clause} "
            f"I can prepare a one-tap confirmation{f' with {offer}' if offer else ''}. "
            "Reply YES and I will make both slot choices approval-ready now."
        )

    if kind == "wedding_package_followup":
        wedding_date = display_date(payload.get("wedding_date") or payload.get("event_date"))
        trial_date = display_date(payload.get("trial_completed") or payload.get("trial_date"))
        days = clean_text(payload.get("days_to_wedding"))
        window = clean_text(payload.get("next_step_window_open")).replace("_", " ")
        window = window.replace("30day", "30-day").replace("60day", "60-day")
        facts = []
        if trial_date:
            facts.append(f"trial completed {trial_date}")
        if wedding_date:
            facts.append(f"wedding {wedding_date}")
        if days:
            facts.append(f"{days} days away")
        detail = "; ".join(facts) or "a bridal follow-up is due"
        return (
            f"{owner}, {detail}. The {window or 'bridal prep'} window is open. "
            f"I can prepare a booking-ready bridal follow-up{f' around {offer}' if offer else ''}. Reply YES to preview it."
        )

    if kind in {"customer_lapsed_hard", "customer_lapsed_soft"}:
        days = clean_text(payload.get("days_since_last_visit"))
        focus = clean_text(payload.get("previous_focus")).replace("_", " ")
        months = clean_text(payload.get("previous_membership_months"))
        detail = f"{days} days since a member's last visit" if days else "for an inactive member"
        history_clause = f"; they completed {months} months in the program" if months else ""
        focus_clause = f" for {focus}" if focus else ""
        return (
            f"{owner}, {detail}{history_clause}{focus_clause}. "
            f"I can prepare a return-to-training WhatsApp{f' using {offer}' if offer else ''}. Reply YES to preview it."
        )

    if kind == "chronic_refill_due":
        medicines = ", ".join(clean_text(item) for item in payload.get("molecule_list", []) if clean_text(item))
        refill_date = display_date(payload.get("stock_runs_out_iso") or payload.get("due_date"))
        medicine_clause = f" for {medicines}" if medicines else ""
        date_clause = f" before {refill_date}" if refill_date else ""
        return (
            f"{owner}, a refill reminder is due{medicine_clause}{date_clause}. "
            "I can prepare a clear confirmation message for the patient. Reply YES to preview it."
        )

    if kind == "trial_followup":
        trial_date = display_date(payload.get("trial_date"))
        trial_clause = f" from {trial_date}" if trial_date else ""
        slot_clause = f" for {slot_text}" if slot_text else ""
        return (
            f"{owner}, the trial follow-up{trial_clause} has a continuation slot{slot_clause}. "
            f"I can prepare the parent-ready continuation WhatsApp{f' with {offer}' if offer else ''}. Reply YES to preview it."
        )

    if kind == "appointment_tomorrow":
        appointment = clean_text(payload.get("appointment_time") or payload.get("slot_label") or payload.get("scheduled_for"))
        time_clause = f" at {appointment}" if appointment else ""
        return (
            f"{owner}, an appointment is due for confirmation tomorrow{time_clause}. "
            "I can prepare the reminder now. Reply YES to preview it."
        )

    if kind in {"followup_due", "customer_lapsed_hard", "customer_lapsed_soft"}:
        return (
            f"{owner}, a customer follow-up is due. I can prepare one concise confirmation message"
            f"{f' with {offer}' if offer else ''}. Reply YES to preview it."
        )

    return (
        f"{owner}, a customer action is ready. I can prepare the exact message from the trigger details "
        "for your approval. Reply YES to preview it."
    )


def compose_customer(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None) -> str:
    if not customer:
        if trigger.get("scope") == "customer" or trigger.get("customer_id"):
            return compose_customer_context_gap(category, merchant, trigger)
        from .compose_merchant import compose_merchant

        return compose_merchant(category, merchant, trigger)
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    cname = clean_text(customer.get("identity", {}).get("name", "there"))
    mname = clean_text(merchant.get("identity", {}).get("name", "the clinic"))
    owner = first_name(merchant.get("identity", {}))
    offer = active_offer_detail(merchant, category)
    rel = customer.get("relationship", {})
    prefs = customer.get("preferences", {})
    lang = clean_text(customer.get("identity", {}).get("language_pref", "")).lower()
    hi = "hi" in lang
    category_slug = category.get("slug") or merchant.get("category_slug", "")

    if kind == "recall_due":
        slots = payload.get("available_slots", [])
        slot_labels = [clean_text(s.get("label")) for s in slots[:2] if clean_text(s.get("label"))]
        slot_text = " or ".join(slot_labels)
        if not slot_text:
            slot_text = clean_text(prefs.get("preferred_slots", ""))
        intro = f"Hi {cname}, {mname} here." if not hi else f"Hi {cname}, {mname} se message."
        due = category_customer_due_label(category_slug, payload.get("service_due", "recall"))
        last_visit = display_date(payload.get("last_service_date") or rel.get("last_visit") or "")
        date_text = f" since {last_visit}" if last_visit else ""
        offer_detail = active_offer_detail(merchant, category) or offer or ""
        has_numbered_slots = slot_text and " or " in slot_text
        slot_clause = f"Slots ready: {slot_text}. " if slot_text else "A slot is ready when you are. "
        reply_line = "Reply 1 or 2 to confirm." if has_numbered_slots else "Reply CONFIRM to lock it now."
        offer_clause = f"{offer_detail} included. " if offer_detail else ""
        return f"{intro} Your {due} is due{date_text}. {slot_clause}{offer_clause}{reply_line}"

    if kind == "chronic_refill_due" and category_slug == "dentists":
        slot_text = clean_text(prefs.get("preferred_slots", ""))
        slot_clause = f"hold {slot_text}" if slot_text else "hold the next visit"
        last_visit = display_date(rel.get("last_visit"))
        visits = rel.get("visits_total")
        since = f" since {last_visit}" if last_visit else ""
        history = f" after {visits} visits" if visits else ""
        return f"Hi {cname}, {mname} here. Your follow-up is due{since}{history}. I can {slot_clause}; {offer or 'a consultation'} is available. Reply CONFIRM to lock it now."

    if kind == "wedding_package_followup":
        days_to_wedding = payload.get("days_to_wedding")
        wedding_date = clean_text(payload.get("wedding_date") or payload.get("event_date") or "")
        window = clean_text(payload.get("next_step_window_open", "skin prep")).replace("_", " ")
        slot_text = clean_text(prefs.get("preferred_slots", "")).replace("_", " ")
        if not slot_text:
            slot_text = "the first bridal-prep slot"
        offer_detail = active_offer_detail(merchant, category) or offer

        # Urgency: calculate how tight the window is
        if days_to_wedding is not None:
            try:
                days_int = int(days_to_wedding)
                if days_int <= 30:
                    urgency_note = f" Only {days_int} days to go — this is the last safe window."
                elif days_int <= 60:
                    urgency_note = f" With {days_int} days to go, starting now means full results by the date."
                else:
                    urgency_note = f" {days_int} days out is a good planning window for {window}."
                date_clause = f" on {wedding_date}" if wedding_date else f" in {days_int} days"
            except (TypeError, ValueError):
                urgency_note = ""
                date_clause = f" on {wedding_date}" if wedding_date else " soon"
        else:
            urgency_note = ""
            date_clause = f" on {wedding_date}" if wedding_date else " soon"

        return (
            f"Hi {cname}, {owner} from {mname} here. Your wedding is{date_clause}.{urgency_note} "
            f"Use this window for {window}{f' with {offer_detail}' if offer_detail else ''} "
            f"and hold {slot_text} now. Reply CONFIRM to lock it."
        )

    if kind in {"customer_lapsed_hard", "customer_lapsed_soft"}:
        days = clean_text(payload.get("days_since_last_visit") or "")
        last_visit_known = display_date(rel.get("last_visit"))
        try:
            days_int = int(days)
            days_text = f"{days_int} days"
            # Urgency language scales with recency
            urgency_note = " — your slot is still open." if days_int <= 45 else " — good to reconnect."
        except (TypeError, ValueError):
            days_text = "a while"
            urgency_note = ""
        last_visit_clause = f" (last visit {last_visit_known})" if last_visit_known and not days else ""
        offer_detail = active_offer_detail(merchant, category) or offer or ""
        offer_clause = f" — {offer_detail}" if offer_detail else ""

        if category_slug == "pharmacies":
            return (
                f"Hi {cname}, {mname} here. It has been {days_text} since your last visit{last_visit_clause}{urgency_note} "
                f"{offer_detail or 'Your regular pharmacy offer'} is available. "
                f"Reply CONFIRM to reserve it, or CALL to speak to us."
            )
        if category_slug == "gyms":
            focus = clean_text(payload.get("previous_focus") or prefs.get("training_focus") or "your routine").replace("_", " ")
            return (
                f"Hi {cname}, {owner} from {mname} here. It has been {days_text} — no pressure{urgency_note} "
                f"Restart around {focus}{offer_clause}. Reply CONFIRM and I'll hold one slot this week."
            )
        if category_slug == "restaurants":
            return (
                f"Hi {cname}, {mname} here. It has been {days_text} since your last order{last_visit_clause}{urgency_note} "
                f"{offer_detail or 'Today offer'} is waiting. Reply CONFIRM and we'll keep it ready for you."
            )
        if category_slug in {"dentists", "opticians", "clinics", "doctors", "eye care", "vet", "veterinary"}:
            return (
                f"Hi {cname}, {mname} here. It has been {days_text} since your last visit{last_visit_clause}. "
                f"{offer_detail or 'A consultation'} is available — no pressure, just keeping your care on track. "
                f"Reply CONFIRM to hold a slot, or RESCHEDULE if the timing doesn't work."
            )
        slot_text = clean_text(prefs.get("preferred_slots", "")) or "a convenient slot"
        return (
            f"Hi {cname}, {owner} from {mname} here. It has been {days_text} since your last visit{last_visit_clause}{urgency_note} "
            f"{offer_detail or 'The current offer'} is available; reply CONFIRM to hold {slot_text}."
        )

    if kind == "chronic_refill_due":
        total_offer = active_offer_detail(merchant, category)
        if category_slug == "pharmacies":
            meds = [clean_text(m) for m in payload.get("molecule_list", []) if clean_text(m)]
            meds_text = ", ".join(meds)
            due_iso = display_date(payload.get("stock_runs_out_iso"))
            due_text = f" on {due_iso}" if due_iso else " soon"
            meds_phrase = f" ({meds_text})" if meds_text else ""
            total_offer = active_offer_detail(merchant, category) or active_offer(merchant, category)
            # Add urgency if stock runs out soon
            urgency = ""
            if due_iso:
                urgency = " Stock is running low — don't miss your window."
            return (
                f"Namaste {cname}, {mname} here. Your refill{meds_phrase} is due{due_text}.{urgency} "
                f"{total_offer or 'Pharmacy pickup'} is available. Reply CONFIRM to reserve it, or CALL to check stock."
            )
        if category_slug == "gyms":
            focus = clean_text(prefs.get("training_focus") or "your routine").replace("_", " ")
            return f"Hi {cname}, {owner} from {mname} here. Your plan check-in is due. Restart around {focus} with {total_offer or 'the next session'}. Reply CONFIRM to hold a slot."
        if category_slug == "salons":
            slot_text = clean_text(prefs.get("preferred_slots", "")) or "your preferred slot"
            return f"Hi {cname}, {owner} from {mname} here. Your next visit is due. I can hold {slot_text} with {total_offer or 'the current offer'}. Reply CONFIRM to book."
        if category_slug == "restaurants":
            return f"Hi {cname}, {mname} here. Your next order reminder is due. {total_offer or 'Today offer'} is available. Reply CONFIRM and we will keep it ready."
        return f"Hi {cname}, {mname} here. Your follow-up is due. {total_offer or 'The current offer'} is available. Reply CONFIRM to continue."

    if kind == "trial_followup":
        slots = payload.get("next_session_options", [])
        slot_labels = [clean_text(s.get("label")) for s in slots if clean_text(s.get("label"))]
        slot_text = slot_labels[0] if slot_labels else clean_text(prefs.get("preferred_slots", ""))
        slot_text = slot_text or "the next session"
        trial_date = clean_text(payload.get("trial_date"))
        trial_text = f" on {trial_date}" if trial_date else ""
        focus = clean_text(payload.get("focus") or prefs.get("training_focus") or prefs.get("service_preference") or "").replace("_", " ")
        focus_clause = f" focused on {focus}" if focus else ""
        offer_detail = active_offer_detail(merchant, category) or offer or ""

        # Category-specific trial follow-up
        if category_slug == "gyms":
            return (
                f"Hi {cname}, {owner} from {mname} here. Hope the trial{trial_text}{focus_clause} went well. "
                f"Next slot ready: {slot_text}{f' — includes {offer_detail}' if offer_detail else ''}. "
                f"Reply CONFIRM and I'll hold it, or CHANGE if timing needs adjustment."
            )
        if category_slug in {"salons", "beauty", "spa"}:
            return (
                f"Hi {cname}, {owner} from {mname} here. Hope you enjoyed the trial{trial_text}. "
                f"Your next slot is {slot_text}{f' with {offer_detail}' if offer_detail else ''}. "
                f"Reply CONFIRM to book, or ask for a different day."
            )
        if category_slug in {"dentists", "clinics", "doctors"}:
            return (
                f"Hi {cname}, {mname} here. Following up on your trial visit{trial_text}. "
                f"Your next appointment is ready for {slot_text}. "
                f"Reply CONFIRM to hold it — no paperwork needed."
            )
        return (
            f"Hi {cname}, {owner} from {mname} here. Hope the trial{trial_text} went well. "
            f"Next suitable slot: {slot_text}{f' with {offer_detail}' if offer_detail else ''}. "
            f"Reply CONFIRM to reserve it."
        )

    if kind == "appointment_tomorrow":
        appt_time = clean_text(payload.get("appointment_time") or payload.get("slot_label") or payload.get("scheduled_for"))
        time_text = f" at {appt_time}" if appt_time else ""
        visits = rel.get("visits_total")
        last_visit = display_date(rel.get("last_visit"))
        history = f" Last visit: {last_visit}." if last_visit else (f" You have {visits} visits with us." if visits else "")
        return f"Hi {cname}, reminder from {mname}: your appointment is tomorrow{time_text}.{history} Reply CONFIRM to keep it, or RESCHEDULE if the time no longer works."

    if kind in {"followup_due", "chronic_refill_due"}:
        slot_text = clean_text(prefs.get("preferred_slots", "")) or "a convenient slot"
        last_visit_d = display_date(rel.get("last_visit"))
        since_text = f" since {last_visit_d}" if last_visit_d else ""
        return (
            f"Hi {cname}, {mname} here. Your follow-up is due{since_text}. "
            f"{offer or 'A slot'} is ready — reply CONFIRM to lock {slot_text}."
        )
    last_visit = display_date(rel.get("last_visit")) or "recently"
    offer_text = offer or "a relevant service"
    return f"Hi {cname}, {mname} here. Based on your last visit on {last_visit}, {offer_text} is available. Reply YES to hold a slot."


def objection_reply_body(state: dict[str, Any], low_message: str) -> str:
    from .compose_merchant import metric_line

    structured = state.get("structured_state", {})
    merchant = state.get("merchant", {}) or {}
    category = state.get("category", {}) or {}
    name = salutation(category, merchant) if merchant and category else clean_text(structured.get("owner_first_name") or "Got it")
    offer = clean_text(structured.get("last_offer"))
    if any(word in low_message for word in ["expensive", "cost", "price", "budget"]):
        return f"{name}, fair. I will avoid a discount-heavy pitch and frame value first{f' around {offer}' if offer else ''}. Want a low-cost version or a premium-positioning version?"
    if any(word in low_message for word in ["later", "busy", "not now", "no time"]):
        return f"{name}, understood. I can make this a 2-line draft you approve later. Should I keep it ready for today or park it for tomorrow?"
    if any(word in low_message for word in ["why", "how", "not sure"]):
        metric = metric_line(merchant)
        proof = f" Your current profile shows {metric}." if metric else ""
        return f"{name}, the reason is to turn the current signal into one approved action without extra work from you.{proof} Should I show the short draft first?"
    return f"{name}, understood. I can reduce this to one safe draft and wait for approval. Should I make it softer or more direct?"


def action_followup_body(state: dict[str, Any]) -> str:
    structured = state.get("structured_state", {})
    trigger = state.get("trigger", {})
    merchant = state.get("merchant", {}) or {}
    category = state.get("category", {}) or {}
    name = salutation(category, merchant) if merchant and category else clean_text(structured.get("owner_first_name") or "Great")
    kind = (trigger.get("kind") if trigger else None) or structured.get("last_trigger_kind") or ""
    offer = clean_text(structured.get("last_offer"))
    metrics = structured.get("last_metric_snapshot") or {}
    payload = (trigger.get("payload") if trigger else None) or {}

    # ── Performance triggers ───────────────────────────────────────────────────
    if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip"}:
        metric_bits = []
        if metrics.get("views") is not None:
            metric_bits.append(f"{metrics.get('views'):,} views")
        if metrics.get("calls") is not None:
            metric_bits.append(f"{metrics.get('calls')} calls")
        snapshot = ", ".join(metric_bits) or "your current numbers"
        return f"{name}, done - I will draft one Google post plus one WhatsApp line tied to {snapshot}{f' and {offer}' if offer else ''}. Reply CONFIRM to preview."

    # ── Competitor / market triggers ───────────────────────────────────────────
    if kind == "competitor_opened":
        competitor = clean_text(payload.get("competitor_name") or "the new competitor")
        return f"{name}, understood - I will draft one differentiation post that highlights what makes you stand out from {competitor}. Reply CONFIRM to preview, or tell me which strength to lead with."

    if kind == "review_theme_emerged":
        theme = clean_text(payload.get("theme") or "the recurring theme").replace("_", " ")
        return f"{name}, on it - I will compose a review-response template addressing '{theme}' and a matching Google post. Reply CONFIRM to preview both."

    # ── Festival / event / seasonal triggers ──────────────────────────────────
    if kind in {"festival_upcoming", "ipl_match_today", "category_seasonal"}:
        event = clean_text(payload.get("festival_name") or payload.get("event_name") or payload.get("season") or "the upcoming event")
        return f"{name}, drafting now - one timely offer post for {event}{f' with {offer}' if offer else ''}. Reply CONFIRM to preview, or CHANGE if you want a different angle."

    # ── Subscription / renewal triggers ───────────────────────────────────────
    if kind == "renewal_due":
        plan = clean_text(payload.get("plan") or "your subscription")
        days = payload.get("days_remaining")
        window = f" in {days} days" if days is not None else " soon"
        return f"{name}, noted - {plan} renews{window}. I will prepare a renewal summary and a WhatsApp reminder for you to approve before anything is sent. Reply CONFIRM to proceed."

    # ── Dormancy / re-engagement triggers ─────────────────────────────────────
    if kind == "dormant_with_vera":
        return f"{name}, good to have you back. I will prepare one re-engagement action based on your current profile - a Google post draft and a WhatsApp nudge. Reply CONFIRM and I will show the preview."

    if kind in {"winback_eligible", "customer_lapsed_soft"}:
        customer_name = clean_text(structured.get("customer_name") or "the customer")
        return f"{name}, on it - I will draft a low-pressure winback message for {customer_name} that leads with value, not a discount. Reply CONFIRM to preview."

    # ── Customer care triggers ─────────────────────────────────────────────────
    if kind in {"recall_due", "customer_lapsed_hard", "chronic_refill_due"}:
        customer_name = clean_text(structured.get("customer_name") or "the customer")
        noun = "refill" if category.get("slug") == "pharmacies" and kind == "chronic_refill_due" else "slot"
        return f"Done - I will keep {customer_name}'s {noun} pending approval. Reply CONFIRM to send, or CHANGE with the new timing."

    if kind == "appointment_tomorrow":
        customer_name = clean_text(structured.get("customer_name") or "the customer")
        return f"{name}, done - I will send {customer_name} a confirmation reminder now. Reply CONFIRM to approve it, or RESCHEDULE with the new time."

    if kind in {"followup_due", "trial_followup"}:
        customer_name = clean_text(structured.get("customer_name") or "the customer")
        return f"{name}, on it - I will prepare a follow-up message for {customer_name} with the next slot ready. Reply CONFIRM to send."

    if kind == "wedding_package_followup":
        customer_name = clean_text(structured.get("customer_name") or "the customer")
        return f"{name}, drafting now - one bridal-prep message for {customer_name} with the booking window and offer. Reply CONFIRM to preview it."

    # ── Profile / compliance triggers ──────────────────────────────────────────
    if kind == "gbp_unverified":
        return f"{name}, understood - I will walk you through the Google Business verification steps one at a time. Reply CONFIRM to start with step 1, or tell me where you got stuck."

    if kind == "regulation_change":
        topic = clean_text(payload.get("regulation_topic") or payload.get("topic") or "the regulation update")
        return f"{name}, noted - I will prepare a plain-language summary of the {topic} change and what it means for your practice. Reply CONFIRM to see the brief."

    # ── Knowledge / research triggers ─────────────────────────────────────────
    if kind == "research_digest":
        return f"{name}, done - I am preparing the source summary plus a patient-friendly WhatsApp draft. Reply CONFIRM and I will keep it to one 90-second message with no medical overclaim."

    if kind == "cde_opportunity":
        return f"{name}, on it - I will draft a peer-to-peer summary of the opportunity and one suggested next step. Reply CONFIRM to preview."

    if kind == "curious_ask_due":
        return f"{name}, drafting your question now - one concise message that opens a genuine conversation with your customers. Reply CONFIRM to preview it."

    # ── Planning / milestone triggers ──────────────────────────────────────────
    if kind == "active_planning_intent":
        return f"{name}, drafting now. I will make the package, Google post, and WhatsApp preview in one pass. Reply CONFIRM to use this structure."

    if kind == "milestone_reached":
        milestone = clean_text(payload.get("milestone") or payload.get("metric") or "this milestone")
        return f"{name}, great news worth sharing - I will draft one celebratory post around {milestone} and a customer thank-you message. Reply CONFIRM to preview both."

    # ── Supply / stock triggers ────────────────────────────────────────────────
    if kind == "supply_alert":
        item = clean_text(payload.get("item") or payload.get("product") or "the item")
        return f"{name}, understood - I will draft a brief customer advisory about {item} availability so expectations are managed before they visit. Reply CONFIRM to preview."

    # ── Generic fallback (should rarely fire now) ─────────────────────────────
    return f"{name}, done - I will prepare a focused preview for your approval before anything is sent. Reply CONFIRM to proceed."


# ── Customer-scope reply routing ─────────────────────────────────────────────
# A customer replies to Vera on the merchant's WhatsApp number, so these bodies
# speak to the patient, never to the merchant. Every function returns plain text
# and is hard-capped by enforce_body_limit() in the reply router.


def _slot_labels(state: dict[str, Any]) -> list[str]:
    structured = state.get("structured_state", {}) or {}
    labels: list[str] = []
    for slot in structured.get("available_slots") or []:
        label = clean_text(slot.get("label") if isinstance(slot, dict) else slot)
        if label and label not in labels:
            labels.append(label)
    return labels


def _greeting(state: dict[str, Any]) -> str:
    structured = state.get("structured_state", {}) or {}
    merchant = state.get("merchant", {}) or {}
    name = clean_text(structured.get("customer_name"))
    business = clean_text((merchant.get("identity", {}) or {}).get("name"))
    if name:
        return f"Hi {name}"
    return f"Hi from {business}" if business else "Hi"


def customer_slot_confirm_body(state: dict[str, Any], slot: str) -> str:
    """Confirm the concrete slot a customer just named."""
    greeting = _greeting(state)
    return (
        f"{greeting}, booked for {slot}. Reply CHANGE with another time if that no longer suits, "
        f"or CANCEL to release the slot."
    )


def customer_slot_choice_body(state: dict[str, Any], ordinal: int) -> str:
    """Resolve a bare '1' / '2' answer against the slots we actually offered."""
    greeting = _greeting(state)
    labels = _slot_labels(state)
    if 1 <= ordinal <= len(labels):
        return (
            f"{greeting}, booked for {labels[ordinal - 1]}. "
            f"Reply CHANGE with another time if that no longer suits, or CANCEL to release the slot."
        )
    if labels:
        options = " or ".join(labels[:2])
        return (
            f"{greeting}, I have {options} open. Reply 1 or 2 and I will hold that slot for you."
        )
    return f"{greeting}, I am checking the next open slot now. I will confirm the exact time here shortly."


def customer_reschedule_body(state: dict[str, Any]) -> str:
    greeting = _greeting(state)
    labels = _slot_labels(state)
    if labels:
        options = " or ".join(labels[:2])
        return f"{greeting}, no problem. I can move you to {options}. Reply 1 or 2 and I will hold that slot."
    return (
        f"{greeting}, no problem. Send me a day and time that works for you "
        f"(for example Sat 7 Nov, 11am) and I will hold it."
    )


def customer_cancel_body(state: dict[str, Any]) -> str:
    greeting = _greeting(state)
    labels = _slot_labels(state)
    tail = (
        f" I can rebook you for {labels[0]} instead, just reply RESCHEDULE."
        if labels else " Reply RESCHEDULE any time and I will find you a new slot."
    )
    return f"{greeting}, your slot is cancelled and you will not get further reminders for it.{tail}"


def customer_call_body(state: dict[str, Any]) -> str:
    merchant = state.get("merchant", {}) or {}
    category = state.get("category", {}) or {}
    business = clean_text((merchant.get("identity", {}) or {}).get("name")) or "the clinic"
    greeting = _greeting(state)
    return (
        f"{greeting}, noted. The team at {business} will call you back on the number you "
        f"messaged from, usually within one working day."
    )


def customer_question_body(state: dict[str, Any], low_message: str = "") -> str:
    """Answer the question that was actually asked, using pushed context only.

    The sub-type matters: a price question gets the offer, a clinical concern gets
    routed to the clinic, and a capability question gets an honest "let me check"
    rather than a recited offer that does not answer anything.
    """
    from .state import classify_customer_question

    kind = classify_customer_question(low_message or "")
    greeting = _greeting(state)
    structured = state.get("structured_state", {}) or {}
    offer = clean_text(structured.get("last_offer"))
    labels = _slot_labels(state)
    clinic = clean_text((state.get("merchant", {}) or {}).get("identity", {}).get("name")) or "the clinic"

    if kind == "concern":
        return (
            f"{greeting}, sorry about that. I am flagging it to {clinic} now so the team can look at "
            f"your record and sort it out. Is now a good time for them to call you?"
        )
    if kind == "price":
        if offer:
            return f"{greeting}, {offer} is the current price. Want me to hold that for you while you decide?"
        return (
            f"{greeting}, let me get the exact price from {clinic} rather than guess. "
            f"Is there a day and time that suits you if it works for you?"
        )
    if kind == "inclusion":
        if offer:
            return f"{greeting}, {offer} is what we currently have running, and I can send the full list of what it covers. Want me to?"
        return f"{greeting}, I will get the exact inclusions from {clinic} and send them here. Anything specific you want covered?"
    if kind == "availability":
        if labels:
            options = " or ".join(labels[:2])
            return f"{greeting}, I have {options} open. Reply 1 or 2 and I will hold that slot for you."
        return (
            f"{greeting}, let me confirm the open times for you. Send me a day and time that suits "
            f"(for example Sat 7 Nov, 11am) and I will hold it."
        )
    if kind == "capability":
        return (
            f"{greeting}, let me check that with {clinic} and come back to you here rather than "
            f"guess. Is there anything else you need sorted in the same message?"
        )
    if offer:
        return f"{greeting}, {offer} is what we currently have running. Anything else you want me to check with the team?"
    if labels:
        return f"{greeting}, I have {labels[0]} open. Want me to hold it while you decide?"
    return (
        f"{greeting}, let me check that with {clinic} and come back to you here. "
        f"Is there a day and time that suits you best?"
    )


def customer_objection_body(state: dict[str, Any]) -> str:
    greeting = _greeting(state)
    structured = state.get("structured_state", {}) or {}
    offer = clean_text(structured.get("last_offer"))
    low_offer = f" We do have {offer} if the cost is the concern." if offer else ""
    return (
        f"{greeting}, understood, no pressure at all.{low_offer} "
        f"Reply RESCHEDULE with a better time or CANCEL, and we will leave it there."
    )


def customer_thanks_body(state: dict[str, Any]) -> str:
    greeting = _greeting(state)
    return f"{greeting}, perfect. See you then, and reply CHANGE here any time if your plans move."


def customer_confirm_body(state: dict[str, Any]) -> str:
    """A bare yes/CONFIRM from a customer: hold what is on offer, don't re-pitch."""
    greeting = _greeting(state)
    labels = _slot_labels(state)
    if labels:
        return (
            f"{greeting}, confirmed for {labels[0]}. "
            f"Reply CHANGE with another time if that no longer suits, or CANCEL to release the slot."
        )
    return (
        f"{greeting}, noted. Send me a day and time that works (for example Sat 7 Nov, 11am) "
        f"and I will hold it for you."
    )


def customer_fallback_body(state: dict[str, Any]) -> str:
    greeting = _greeting(state)
    labels = _slot_labels(state)
    if labels:
        options = " or ".join(labels[:2])
        return (
            f"{greeting}, I want to get this right. Reply 1 or 2 to hold {options}, "
            f"or send me a day and time you prefer."
        )
    return (
        f"{greeting}, happy to help. Send me a day and time that suits you "
        f"(for example Sat 7 Nov, 11am) and I will hold the slot."
    )
