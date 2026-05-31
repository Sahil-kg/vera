from __future__ import annotations

from typing import Any

from .intents import active_offer, active_offer_detail, category_customer_due_label, first_name, salutation
from .sanitization import clean_text, display_date, metric_label, safe_text


def compose_customer(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None) -> str:
    if not customer:
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
        slot_text = clean_text(prefs.get("preferred_slots", "")) or "the first session"
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
                    urgency_note = f" {days_int} days out is the ideal time to start {window}."
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
    if kind == "research_digest":
        return f"{name}, done - I am preparing the source summary plus a patient-friendly WhatsApp draft. Reply CONFIRM and I will keep it to one 90-second message with no medical overclaim."
    if kind == "active_planning_intent":
        return f"{name}, drafting now. I will make the package, Google post, and WhatsApp preview in one pass. Reply CONFIRM to use this structure."
    if kind in {"recall_due", "customer_lapsed_hard", "chronic_refill_due"}:
        customer_name = clean_text(structured.get("customer_name") or "the customer")
        noun = "refill" if category.get("slug") == "pharmacies" and kind == "chronic_refill_due" else "slot"
        return f"Done - I will keep {customer_name}'s {noun} pending approval. Reply CONFIRM to send, or CHANGE with the new timing."
    if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip"}:
        metric_bits = []
        if metrics.get("views") is not None:
            metric_bits.append(f"{metrics.get('views'):,} views")
        if metrics.get("calls") is not None:
            metric_bits.append(f"{metrics.get('calls')} calls")
        snapshot = ", ".join(metric_bits) or "your current numbers"
        return f"{name}, done - I will draft one Google post plus one WhatsApp line tied to {snapshot}{f' and {offer}' if offer else ''}. Reply CONFIRM to preview."
    return f"{name}, done - I am moving to action mode now. Reply CONFIRM and I will prepare the final preview before anything is sent."


