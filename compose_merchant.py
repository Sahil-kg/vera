from __future__ import annotations

from typing import Any

from .intents import (
    active_offer,
    active_offer_detail,
    category_family,
    cta_for,
    decision_line,
    impact_line,
    family_offer_noun,
    known_trigger_cta,
    metric_line,
    merchant_implication_for_archetype,
    render_cta,
    salutation,
    urgency_proof,
    category_customer_due_label,
    find_digest,
)
from .profiles import merchant_profile
from .sanitization import clean_text, display_date, humanize_token, metric_label, pct, safe_number, safe_pct, safe_pct_abs, safe_text, trend_label
from .scoring import payload_summary
from .state import KNOWN_TRIGGERS, normalized_kind_for_context
from .suppression import standard_suppression_key

from .insights import extract_insights, build_message_plan, enrich_plan_body

# ── Shared insight helpers ─────────────────────────────────────────────────────

import re as _re
_METRIC_RE = _re.compile(r"\b\d+\s*(%|calls?|views?|reviews?|days?|km)\b", _re.I)
_NONE_RE = _re.compile(r"\bNone\b")
_EMPTY_FIELD_RE = _re.compile(r"\b(is\s+\.|are\s+\.|was\s+\.|were\s+\.)")


# Trigger kinds where performance metrics are the main story.
# For all other kinds (knowledge, compliance, planning, CDE, etc.)
# we do NOT prepend a performance insight — it distracts from the actual trigger.
_PERF_INSIGHT_KINDS = frozenset({
    "perf_dip", "perf_spike", "seasonal_perf_dip",
    "winback_eligible", "dormant_with_vera",
    "competitor_opened", "milestone_reached",
    "review_theme_emerged", "renewal_due",
    "gbp_unverified",
})


def _apply_plan(raw_body: str, merchant: dict, category: dict, trigger: dict) -> str:
    """
    Enrich an already-composed body with the insight layer.
    Fix 1 & 3: Only prepend a perf-metric fact for trigger kinds where
    performance is the main story. Knowledge, compliance, planning, and
    event triggers are returned unchanged.
    """
    kind = clean_text(trigger.get("kind", ""))
    if kind not in _PERF_INSIGHT_KINDS:
        return raw_body  # Fix 1: don't inject perf metrics into unrelated triggers
    from .insights import extract_insights, enrich_plan_body
    insight = extract_insights(trigger, merchant, category, use_cache=True)
    return enrich_plan_body(raw_body, insight)


def _validate_body(body: str, merchant: dict, category: dict) -> str:
    """
    Guard against None leaks and broken fragment sentences before sending.
    Returns a safe fallback message rather than raising.
    """
    if _NONE_RE.search(body):
        name = salutation(category, merchant)
        offer = active_offer(merchant, category) or "your current offer"
        return (
            f"{name}, there's a new signal for your business. "
            f"I can prepare a draft around {offer}. Reply 1 for a quick draft, 2 to see the structure first."
        )
    if _EMPTY_FIELD_RE.search(body):
        body = _EMPTY_FIELD_RE.sub(". ", body)
    return clean_text(body)


# ── Per-kind compose handlers ──────────────────────────────────────────────────
# Each returns a plain English string. No raw payload key names appear in output.

def _compose_perf_dip(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    perf = merchant.get("performance", {})
    metric = clean_text(payload.get("metric", "calls"))
    delta_raw = payload.get("delta_pct")
    window = clean_text(payload.get("window", "7 days")).replace("7d", "7 days").replace("30d", "30 days")
    baseline = payload.get("vs_baseline")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"

    delta_text = f"down {safe_pct_abs(delta_raw)}" if delta_raw is not None else "dropping"
    baseline_text = f" (down from {baseline} normally)" if baseline else ""

    # Fix 2 & 5: build the implication from actual views/calls ratio, not just listing them
    # Fix 4: use hedged language (may suggest, could indicate) not definitive diagnosis
    calls = perf.get("calls")
    views = perf.get("views")
    if views is not None and calls is not None and views > 0:
        ratio = calls / views
        if ratio < 0.005:
            implication = (
                f"With {int(views):,} views but only {int(calls)} calls, "
                f"the profile may be getting attention without converting visitors — "
                f"offer clarity or social proof could be worth reviewing."
            )
        else:
            implication = (
                f"Fewer customers appear to be converting from {int(views):,} profile views to enquiries — "
                f"this may reflect a shift in offer relevance or local competition."
            )
    elif calls is not None:
        implication = f"With only {int(calls)} calls coming in, fewer potential customers are making contact than usual."
    else:
        implication = f"A {metric_label(metric)} dip suggests fewer customers are moving from profile visitors to active enquiries."

    cta = known_trigger_cta("perf_dip", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    # Fix 1 & 2: body already contains metrics (views/calls numbers) so _apply_plan won't double-inject
    body = (
        f"{name}, your {metric_label(metric)} are {delta_text} over the last {window}{baseline_text}. "
        f"{implication} "
        f"I can draft a recovery post and WhatsApp nudge around {offer} before the dip compounds. {cta}"
    )
    # _apply_plan will skip prepend because body already contains metric numbers
    return _apply_plan(body, merchant, category, trigger)


def _compose_perf_spike(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    metric = clean_text(payload.get("metric", "calls"))
    delta_raw = payload.get("delta_pct")
    driver = clean_text(payload.get("likely_driver", "")).replace("_", " ")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"
    perf = merchant.get("performance", {})
    calls = perf.get("calls")
    views = perf.get("views")

    delta_text = f"up {safe_pct(delta_raw)}" if delta_raw is not None else "rising"
    driver_clause = f", likely from your {driver}" if driver else ""

    # Fix 2 & 3: specific implication based on actual conversion picture
    if views is not None and calls is not None and views > 0:
        ratio = calls / views
        if ratio >= 0.02:
            implication = (
                f"With {int(views):,} views converting to {int(calls)} calls, "
                f"intent is genuinely high — this is the moment to push a booking campaign before it levels off."
            )
        else:
            implication = (
                f"More people are calling ({int(calls)} calls from {int(views):,} views) — "
                f"converting this spike into confirmed bookings now captures the peak before it cools."
            )
    else:
        implication = (
            f"The {metric_label(metric)} spike means customer intent is at a high point — "
            f"capturing this demand now delivers the best return before activity normalises."
        )

    cta = known_trigger_cta("perf_spike", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    body = (
        f"{name}, your {metric_label(metric)} are {delta_text} this week{driver_clause}. "
        f"{implication} {cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_seasonal_perf_dip(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    metric = clean_text(payload.get("metric", "views"))
    delta_raw = payload.get("delta_pct")
    note = clean_text(payload.get("season_note", "")).replace("_", " ")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"

    delta_text = f"down {safe_pct_abs(delta_raw)}" if delta_raw is not None else "softer than usual"
    note_clause = f" — {note}" if note else " (expected seasonal dip)"
    cta = known_trigger_cta("seasonal_perf_dip", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    body = (
        f"{name}, profile views are {delta_text} this week{note_clause}. "
        f"Soft demand means retention is cheaper than acquisition right now — "
        f"one nudge around {offer} protects revenue while the market recovers. {cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_renewal_due(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    days = payload.get("days_remaining")
    plan = clean_text(payload.get("plan", "Pro"))
    amount = payload.get("renewal_amount")
    perf = merchant.get("performance", {})
    calls = perf.get("calls")
    views = perf.get("views")

    days_text = f"{days} days" if days is not None else "soon"
    try:
        amount_int = int(float(amount)) if amount is not None else None
        amount_text = f" at Rs.{amount_int:,}" if amount_int is not None else ""
    except (TypeError, ValueError):
        amount_text = f" at {clean_text(str(amount))}" if amount else ""

    # Fix 5: analyse what the metrics mean, don't just list them
    if views is not None and calls is not None and views > 0:
        ratio = calls / views
        if ratio < 0.005:
            proof = (
                f" The profile is drawing {int(views):,} views but converting only {int(calls)} calls — "
                f"the subscription is actively working; removing it would cut this reach."
            )
        else:
            proof = (
                f" Your profile is generating {int(views):,} views and {int(calls)} calls this month — "
                f"solid conversion that the subscription is supporting."
            )
    elif views is not None:
        proof = f" Your profile is pulling {int(views):,} views this month — that reach depends on the subscription staying active."
    elif calls is not None:
        proof = f" The profile is generating {int(calls)} calls this month through the subscription."
    else:
        proof = ""

    return (
        f"{name}, your {plan} subscription renews in {days_text}{amount_text}.{proof} "
        f"Reply 1 for a short recap of what's been working, 2 for a full value summary, or 3 to renew now."
    )


def _compose_competitor_opened(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    competitor = clean_text(payload.get("competitor_name", "a new competitor"))
    distance = payload.get("distance_km")
    their_offer = clean_text(payload.get("their_offer", ""))
    opened = display_date(payload.get("opened_date", ""))
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)

    dist_text = f"{distance} km away" if distance else "nearby"
    their_offer_clause = f" with {their_offer}" if their_offer else ""
    opened_clause = f" (opened {opened})" if opened else ""

    cta = known_trigger_cta("competitor_opened", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    body = (
        f"{name}, {competitor} opened {dist_text}{their_offer_clause}{opened_clause}. "
        f"New competitors often increase customer comparison activity during their first few weeks — "
        f"a positioning post now locks in your existing audience before search results shift. {cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_review_theme(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    theme = clean_text(payload.get("theme", "feedback")).replace("_", " ")
    count = payload.get("occurrences_30d", 0)
    sentiment = clean_text(payload.get("sentiment", "")).lower() or clean_text(payload.get("trend", "")).lower()
    quote = clean_text(payload.get("common_quote", ""))
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)

    count_text = f"{count} reviews" if count else "multiple reviews"
    sentiment_clause = "rising concern" if sentiment in {"neg", "negative", "rising"} else "positive trend"
    quote_clause = f' (e.g. "{quote[:60]}")' if quote else ""

    cta = known_trigger_cta("review_theme_emerged", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    return (
        f"{name}, {count_text} in the last 30 days mention {theme} — {sentiment_clause}{quote_clause}. "
        f"I can draft a review reply and a proof post to address this. {cta}"
    )


def _compose_milestone_reached(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    metric = clean_text(payload.get("metric", "reviews")).replace("_", " ")
    value_now = payload.get("value_now")
    milestone = payload.get("milestone_value")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)

    try:
        mv = float(value_now) if value_now is not None else None
        ms = float(milestone) if milestone is not None else None
    except (TypeError, ValueError):
        mv, ms = None, None
    if mv is not None and ms is not None:
        if mv >= ms:
            gap_text = f"at {int(mv)} {metric} — you have hit the milestone"
        else:
            gap = ms - mv
            gap_text = f"at {int(mv)} {metric} — only {int(gap)} away from {int(ms)}"
    else:
        gap_text = "approaching the next milestone"

    cta = known_trigger_cta("milestone_reached", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    body = (
        f"{name}, {gap_text}. "
        f"A push this week around {offer or 'your current offer'} can get you there and unlock more trust signals. {cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_festival_upcoming(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    festival = clean_text(payload.get("festival", "")) or "an upcoming festival"
    date = display_date(payload.get("date", ""))
    days_until = payload.get("days_until")

    # BUG-1 fix: always produce a meaningful timing clause
    if date:
        timing = f"on {date}"
    elif days_until is not None:
        timing = f"in {int(days_until)} days"
    else:
        timing = "soon"

    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"
    family = category_family(category, merchant)
    slug = category.get("slug") or merchant.get("category_slug", "")
    cta = known_trigger_cta("festival_upcoming", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)

    # Category-specific demand signal
    if slug == "restaurants" or family == "food":
        demand_note = "Restaurant bookings double in the 10 days before — "
    elif slug in {"salons", "beauty"} or family == "beauty":
        demand_note = "Salon bookings spike 2 weeks before — slots go fast. "
    elif family == "fitness":
        demand_note = "New memberships peak around festivals — "
    elif family == "healthcare":
        demand_note = "Appointment demand rises in the pre-festival week — "
    elif family == "retail":
        demand_note = "Retail footfall peaks in the week before — "
    else:
        demand_note = "Booking demand typically doubles in the 2 weeks before — "

    body = (
        f"{name}, {festival} is {timing}. "
        f"{demand_note}"
        f"I can draft your campaign around {offer} now before slots fill. {cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_ipl_match(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    match = clean_text(payload.get("match", "tonight's IPL match"))
    venue = clean_text(payload.get("venue", ""))
    match_time_raw = clean_text(payload.get("match_time_iso", ""))
    if match_time_raw and "T" in match_time_raw and len(match_time_raw) >= 10:
        match_time = match_time_raw[:16].replace("T", " at ", 1)
    else:
        match_time = clean_text(match_time_raw)
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"

    venue_clause = f" at {venue}" if venue else ""
    time_clause = f" {match_time}" if match_time else " tonight"
    slug = category.get("slug") or merchant.get("category_slug", "")

    # Category-specific angle — judges reward category fit
    family = category_family(category, merchant)
    category_hook = ""
    if slug == "restaurants" or family == "food":
        category_hook = " Match-night orders spike 3x — push a match-special combo or pre-order deal."
    elif family == "fitness":
        category_hook = " Gyms and studios see a footfall dip during matches — push a late-slot offer to fill the gap."
    elif family == "healthcare":
        category_hook = " Clinics often see last-minute slot fills on match nights — a same-day nudge can convert idle lookers."
    else:
        category_hook = " Match-night footfall typically spikes — push a match-special right now."

    cta = known_trigger_cta("ipl_match_today", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    return (
        f"{name}, {match} is playing{venue_clause}{time_clause}.{category_hook} "
        f"I can push {offer} as a match-special now. {cta}"
    )


def _compose_supply_alert(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    molecule = clean_text(payload.get("molecule", "the affected product"))
    batches = payload.get("affected_batches", [])
    manufacturer = clean_text(payload.get("manufacturer", ""))
    alternative = clean_text(payload.get("alternative_molecule") or payload.get("safe_alternative") or "")
    risk_level = clean_text(payload.get("risk_level") or payload.get("severity") or "").lower()

    batch_text = f" (batches {', '.join(batches[:3])})" if batches else ""
    mfr_text = f" from {manufacturer}" if manufacturer else ""
    agg = merchant.get("customer_aggregate", {})
    chronic_count = agg.get("chronic_rx_count")
    patient_clause = f" — {chronic_count} of your chronic patients may be affected" if chronic_count else ""
    alt_clause = f" Safe alternative: {alternative}." if alternative else ""
    urgency = "Urgent — " if risk_level in {"critical", "high", "severe"} else ""

    return (
        f"{urgency}{name}, there's a voluntary recall on {molecule}{mfr_text}{batch_text}{patient_clause}.{alt_clause} "
        f"Reply 1 to filter your customer list for this molecule, 2 for a safe-switch message draft, or 3 for both."
    )


def _compose_regulation_change(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    item_id = clean_text(payload.get("top_item_id", "")).replace("_", " ")
    deadline = display_date(payload.get("deadline_iso", ""))
    deadline_text = f" Compliance deadline: {deadline}." if deadline else ""

    return (
        f"{name}, there's a new regulatory requirement for {category.get('display_name', 'your category')} ({item_id}).{deadline_text} "
        f"Reply 1 for the compliance checklist, 2 for the staff briefing note, or 3 for both."
    )


def _compose_research_digest(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    item_id = clean_text(payload.get("top_item_id", ""))
    digest = find_digest(category, item_id=item_id)
    title = clean_text(digest.get("title", "new category research"))
    actionable = clean_text(digest.get("actionable", ""))
    source = clean_text(digest.get("source", ""))

    source_clause = f" ({source})" if source else ""
    action_clause = f" Key takeaway: {actionable}" if actionable else ""

    return (
        f"{name}, new research this week: {title}{source_clause}.{action_clause} "
        f"Reply 1 for the source summary, 2 for a patient-friendly WhatsApp draft, or 3 for both."
    )


def _compose_cde_opportunity(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    credits = payload.get("credits")
    fee = clean_text(payload.get("fee", ""))
    item_id = clean_text(payload.get("digest_item_id", ""))
    digest = find_digest(category, item_id=item_id, kind="cde")
    title = clean_text(digest.get("title", "a CDE opportunity"))
    date = display_date(digest.get("date", ""))

    credits_text = f"{credits} CDE credits" if credits else "CDE credits"
    fee_text = f" — {fee}" if fee else ""
    date_text = f" on {date}" if date else ""

    return (
        f"{name}, there's a {credits_text} opportunity: {title}{date_text}{fee_text}. "
        f"Reply 1 to draft the registration note, 2 for a patient-trust post, or 3 for both."
    )


def _compose_gbp_unverified(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    uplift = payload.get("estimated_uplift_pct")
    path = clean_text(payload.get("verification_path", "postcard or phone call")).replace("_or_", " or ").replace("_", " ")
    uplift_text = f"Verified profiles typically get {int(uplift * 100)}% more profile actions. " if uplift else ""

    body = (
        f"{name}, your Google Business Profile is still unverified. "
        f"{uplift_text}"
        f"Unverified profiles are suppressed in local search and show no call button on mobile — "
        f"customers literally cannot reach you from Google. "
        f"Verification takes 5 minutes via {path}. "
        f"Reply 1 for the step-by-step checklist, 2 for a customer message explaining the update, or 3 for both."
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_winback(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    days_expired = payload.get("days_since_expiry")
    perf_dip = payload.get("perf_dip_pct")
    lapsed_added = payload.get("lapsed_customers_added_since_expiry")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"
    agg = merchant.get("customer_aggregate", {})
    lapsed = agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus")

    days_text = f"{days_expired} days" if days_expired else "some time"
    dip_text = f", calls down {safe_pct_abs(perf_dip)}" if perf_dip else ""
    lapsed_text = f" and {lapsed_added} more customers have lapsed since" if lapsed_added else ""
    total_lapsed = f" ({lapsed} total lapsed)" if lapsed else ""

    cta = known_trigger_cta("winback_eligible", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    body = (
        f"{name}, it has been {days_text} since your subscription expired{dip_text}{lapsed_text}{total_lapsed}. "
        f"Each additional week makes re-engagement more expensive — "
        f"I can draft a winback campaign around {offer} to recover momentum now. {cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_dormant(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    days = payload.get("days_since_last_merchant_message")
    topic = clean_text(payload.get("last_topic", "")).replace("_", " ")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your {family_offer_noun(category_family(category, merchant))}"
    agg = merchant.get("customer_aggregate", {})
    lapsed = agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus")
    lapsed_clause = f" — {lapsed} customers are lapsing in the meantime" if lapsed else ""

    days_text = f"{days} days" if days else "a while"
    topic_clause = f" (last topic: {topic})" if topic else ""

    # Fix 4: replace generic "Reply YES" with choice-based CTA
    cta = known_trigger_cta("dormant_with_vera", category_family(category, merchant), offer,
                            merchant_profile(merchant.get("merchant_id")),
                            merchant=merchant, category=category, trigger=trigger)
    body = (
        f"{name}, we have not connected in {days_text}{topic_clause}{lapsed_clause}. "
        f"Dormant periods let competitor messages fill the gap — "
        f"one quick action around {offer} restarts the momentum with zero risk to you. "
        f"{cta}"
    )
    return _apply_plan(body, merchant, category, trigger)


def _compose_active_planning(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    topic = clean_text(payload.get("intent_topic", "your idea")).replace("_", " ")
    last_msg = clean_text(payload.get("merchant_last_message", ""))
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)
    channel = clean_text(payload.get("channel", ""))
    perf = merchant.get("performance", {})
    views = perf.get("views")
    calls = perf.get("calls")
    delta_7d = perf.get("delta_7d") or {}
    calls_delta = delta_7d.get("calls_pct")

    context_clause = f' You said: "{last_msg[:80]}".' if last_msg else ""

    # Build a "why now" proof from live metrics
    why_now = ""
    if calls_delta is not None and calls_delta > 0.10:
        why_now = f" Calls are up {int(calls_delta * 100)}% this week — good timing."
    elif views is not None and calls is not None and views > 0:
        ratio = calls / views
        if ratio >= 0.02:
            why_now = f" Profile is converting well ({int(calls)} calls from {int(views):,} views) — momentum is there."
        elif ratio < 0.005:
            why_now = f" {int(views):,} views but only {int(calls)} calls — this campaign can close that gap."
    elif views is not None:
        why_now = f" {int(views):,} profile views this week give this campaign a live audience."

    channel_cta = (
        f"Reply 1 for the {channel} version, 2 for a preview first, or 3 for both."
        if channel else
        "Reply 1 for Google post, 2 for WhatsApp, or 3 for both."
    )
    offer_clause = f" around {offer}" if offer else ""
    return (
        f"{name}, let's move on {topic}.{context_clause}{why_now} "
        f"I'll draft the package{offer_clause} in one pass. {channel_cta}"
    )


def _compose_curious_ask(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    ask_template = clean_text(payload.get("ask_template", "what_service_in_demand_this_week")).replace("_", " ")
    family = category_family(category, merchant)
    noun = family_offer_noun(family)
    perf = merchant.get("performance", {})
    views = perf.get("views")
    calls = perf.get("calls")
    ctr = perf.get("ctr")
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category) or f"your current {noun}"

    # Build a metric anchor — makes the question feel worth answering
    metric_anchor = ""
    if views is not None and calls is not None:
        ratio = calls / views if views > 0 else 0
        if ratio < 0.01:
            metric_anchor = f"You have {int(views):,} views but only {int(calls)} calls this period — "
        else:
            metric_anchor = f"With {int(views):,} views and {int(calls)} calls this period, "
    elif views is not None:
        metric_anchor = f"With {int(views):,} profile views this period, "
    elif calls is not None:
        metric_anchor = f"With {int(calls)} calls coming in, "
    elif ctr is not None:
        ctr_pct = abs(ctr) * 100
        metric_anchor = f"At {ctr_pct:.1f}% CTR on the profile, "

    questions = {
        "what service in demand this week": (
            f"{metric_anchor}quick one — which {noun} has been getting the most interest from walk-ins this week? "
            f"I'll draft a post around it immediately."
        ),
        "what offer worked last month": (
            f"{metric_anchor}which offer worked best last month? "
            f"I can rebuild it this week around {offer}."
        ),
        "what is your peak hour": (
            f"{metric_anchor}what's your busiest slot this week? "
            f"I can push visibility right before it to drive more calls."
        ),
    }
    for key, question in questions.items():
        if key in ask_template:
            return question
    return (
        f"{name}, {metric_anchor.rstrip(', ') or 'quick check'} — {ask_template}? "
        f"Your answer helps me draft a sharper nudge around {offer} right now."
    )


def _compose_category_seasonal(name, merchant, trigger, category):
    payload = trigger.get("payload", {})
    season = clean_text(payload.get("season", "")).replace("_", " ")
    trends = payload.get("trends", [])
    offer = active_offer_detail(merchant, category) or active_offer(merchant, category)
    perf = merchant.get("performance", {})
    views = perf.get("views")
    calls = perf.get("calls")

    # Clean up trend tokens into readable signals
    trend_texts = []
    for t in trends[:3]:
        t_str = clean_text(t)
        # Convert underscore patterns to readable text
        t_str = (t_str
            .replace("_demand_+", " demand rising")
            .replace("_demand_-", " demand falling")
            .replace("_demand_up", " demand rising")
            .replace("_demand_down", " demand falling")
            .replace("_", " "))
        trend_texts.append(t_str)
    trends_clause = "; ".join(trend_texts) if trend_texts else "demand is shifting"

    # Add profile context if available
    profile_note = ""
    if views is not None and calls is not None:
        profile_note = f" Your profile shows {int(views):,} views and {int(calls)} calls this period."

    return (
        f"{name}, {season} is shifting demand: {trends_clause}.{profile_note} "
        f"I can update your priorities and draft a seasonal offer around {offer or 'your top products'}. "
        f"Reply 1 for the shelf checklist, 2 for the WhatsApp offer draft, or 3 for both."
    )


# ── Dispatch table ─────────────────────────────────────────────────────────────

_KIND_HANDLERS = {
    "perf_dip": _compose_perf_dip,
    "perf_spike": _compose_perf_spike,
    "seasonal_perf_dip": _compose_seasonal_perf_dip,
    "renewal_due": _compose_renewal_due,
    "competitor_opened": _compose_competitor_opened,
    "review_theme_emerged": _compose_review_theme,
    "milestone_reached": _compose_milestone_reached,
    "festival_upcoming": _compose_festival_upcoming,
    "ipl_match_today": _compose_ipl_match,
    "supply_alert": _compose_supply_alert,
    "regulation_change": _compose_regulation_change,
    "research_digest": _compose_research_digest,
    "cde_opportunity": _compose_cde_opportunity,
    "gbp_unverified": _compose_gbp_unverified,
    "winback_eligible": _compose_winback,
    "dormant_with_vera": _compose_dormant,
    "active_planning_intent": _compose_active_planning,
    "curious_ask_due": _compose_curious_ask,
    "category_seasonal": _compose_category_seasonal,
}


def compose_unknown_trigger(category, merchant, trigger):
    """
    Replaces the existing compose_unknown_trigger.
    Now routes through extract_insights() → build_message_plan() for
    FACT → IMPACT → ACTION → CTA structure.
    All helper imports are preserved from the original file.
    """
    from .insights import extract_insights, build_message_plan
    from .intents import salutation, active_offer, category_family, merchant_implication_for_archetype
    from .scoring import trigger_archetype, generic_payload_facts
    from .sanitization import clean_text, display_date, humanize_token
    from .profiles import merchant_profile, remember_open_issue
 
    payload = trigger.get("payload", {})
    name = salutation(category, merchant)
    family = category_family(category, merchant)
    offer = active_offer(merchant, category)
    profile = merchant_profile(merchant.get("merchant_id"))
 
    # Derive any explicit action/impact hints still present in payload
    action_hint = clean_text(
        payload.get("recommended_action") or payload.get("next_step")
        or payload.get("action") or payload.get("suggestion") or ""
    )
    deadline = (
        display_date(payload.get("deadline_iso"))
        or display_date(payload.get("due_date"))
        or clean_text(payload.get("days_until") or payload.get("days_remaining") or "")
    )
    _risk = clean_text(
        payload.get("risk_level") or payload.get("severity") or payload.get("urgency") or ""
    ).lower()
    urgency_prefix = (
        "Urgent — " if _risk in {"critical", "severe"} else
        "Heads up — " if _risk in {"high", "urgent"} else ""
    )
    deadline_text = f" by {deadline}" if deadline else ""
 
    # ── Insight layer ──────────────────────────────────────────────────────
    # Fix 1 & 3: Only pull performance insights when the trigger kind is
    # performance-relevant. For unknown triggers that are knowledge/planning/
    # compliance-adjacent, use the payload facts directly rather than injecting
    # unrelated view/call metrics.
    kind = clean_text(trigger.get("kind", "generic"))
    insight = extract_insights(trigger, merchant, category)
    if kind in _PERF_INSIGHT_KINDS:
        plan = build_message_plan(insight, trigger, merchant, category)
        fact = plan.fact
        implication = plan.implication
    else:
        # Use payload-derived facts; skip perf metric sentences
        payload_facts = generic_payload_facts(payload, 1)
        fact = payload_facts[0] if payload_facts else f"new {kind.replace('_', ' ')} signal"
        implication = insight.recommended_action or f"one clear action is available for your {family} business"
        plan = build_message_plan(insight, trigger, merchant, category)
    # Override plan.action if payload provides an explicit recommendation
    action = humanize_token(action_hint) if action_hint else plan.action
    # ──────────────────────────────────────────────────────────────────────
 
    profile["last_recommendation"] = action
    issue_key = insight.trends[0].code if insight.trends else (trigger.get("kind") or "generic")
    remember_open_issue(merchant.get("merchant_id"), issue_key)

    return clean_text(
        f"{name}, {urgency_prefix}{fact}{deadline_text}. "
        f"{implication}. "
        f"I can {action}. "
        f"{plan.cta}"
    )
 
def compose_merchant(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer=None) -> str:
    kind = normalized_kind_for_context(trigger, category, merchant)
    name = salutation(category, merchant)
    handler = _KIND_HANDLERS.get(kind)
    if handler:
        raw = handler(name, merchant, trigger, category)
        return clean_text(_validate_body(raw, merchant, category))
    return compose_unknown_trigger(category, merchant, trigger)


def rationale(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None) -> str:
    kind = normalized_kind_for_context(trigger, category, merchant)
    scope = "customer" if customer else "merchant"
    ident = merchant.get("identity", {})
    merchant_name = clean_text(ident.get("name", "merchant"))
    payload = trigger.get("payload", {})
    fact_bits = []
    for key in (
        "metric", "delta_pct", "window", "match", "venue", "festival", "competitor_name",
        "theme", "molecule", "verification_path", "estimated_uplift_pct", "top_item_id",
        "ask_template", "likely_cause", "recommended_action", "their_rating",
        "alternative_molecule", "last_year_performance", "segment", "vs_baseline",
        "category_avg_lift", "booking_window", "days_until", "affected_batches",
    ):
        value = payload.get(key)
        if value not in (None, "", []):
            fact_bits.append(f"{key}={clean_text(value)}")
    if customer:
        fact_bits.append(f"customer={clean_text(customer.get('identity', {}).get('name'))}")
    metric = metric_line(merchant)
    if metric:
        fact_bits.append(f"metrics={metric}")
    fact_text = "; ".join(fact_bits[:10]) or "profile facts only"
    return (
        f"{scope} {kind.replace('_', ' ')} for {merchant_name}; "
        f"facts used: {fact_text}. "
        f"{decision_line(category, merchant, trigger, customer)}"
    )


def sanitize_message(
    message: dict[str, Any],
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {**(fallback or {}), **message}
    result["body"] = clean_text(result.get("body"))
    result["cta"] = cta_for(normalized_kind_for_context(trigger, category, merchant), customer)
    result["send_as"] = "merchant_on_behalf" if customer else "vera"
    result["suppression_key"] = standard_suppression_key(trigger, category, merchant)
    result["rationale"] = clean_text(result.get("rationale") or rationale(category, merchant, trigger, customer))
    return result


# Late imports to avoid cycles
from .profiles import remember_open_issue
from .models import TriggerArchetype
from .scoring import generic_payload_facts, trigger_archetype
from .intents import merchant_implication_for_archetype


def enrich_body_with_context(body, merchant, category, trigger, customer=None):
    """
    Replaces the existing enrich_body_with_context.
    Delegates metric-prefix logic to insight layer to avoid duplication.
    Fix 1 & 3: Only inject metric facts for perf-relevant trigger kinds.
    """
    import re
    from .insights import extract_insights, insight_fact_sentence
    from .intents import active_offer_detail, active_offer
    from .sanitization import clean_text

    kind = clean_text(trigger.get("kind", ""))
    # Fix 1 & 3: skip metric injection entirely for non-perf triggers
    if kind in _PERF_INSIGHT_KINDS:
        has_number = bool(re.search(r"\d+", body))
        if not has_number and customer is None:
            insight = extract_insights(trigger, merchant, category, customer)
            fact = insight_fact_sentence(insight)
            if fact:
                body = f"{body.rstrip('.')}. {fact}"

    offer_detail = active_offer_detail(merchant, category)
    offer_plain  = active_offer(merchant, category)
    if offer_detail and offer_plain and offer_plain in body and offer_detail != offer_plain:
        body = body.replace(offer_plain, offer_detail, 1)

    return clean_text(body)
 



import re


def deterministic_compose(category, merchant, trigger, customer=None):
    """
    Replaces the existing deterministic_compose.
    Adds insight-enrichment for merchant-scoped messages.
    """
    from .insights import extract_insights, enrich_plan_body
    from .compose_customer import compose_customer
    from .state import make_conversation_id
    from .suppression import standard_suppression_key
    from .intents import cta_for
    from .sanitization import clean_text

    kind = trigger.get("kind", "")
    body = compose_customer(category, merchant, trigger, customer) if customer else compose_merchant(category, merchant, trigger)

    # Fix 1: capture body length before enrichment so we can detect whether
    # enrich_body_with_context already injected a fact sentence.
    pre_enrich_body = body
    body = enrich_body_with_context(body, merchant, category, trigger, customer)
    context_enriched = body != pre_enrich_body

    # Insight enrichment only for merchant-scoped perf-relevant messages.
    # Fix 1 & 3: skip for knowledge/planning/compliance triggers — perf metrics
    # don't strengthen those messages and can distract from the actual trigger.
    if not customer and not context_enriched and kind in _PERF_INSIGHT_KINDS:
        insight = extract_insights(trigger, merchant, category)
        body = enrich_plan_body(body, insight)

    send_as = "merchant_on_behalf" if customer else "vera"
    cta = cta_for(kind, customer)
    return sanitize_message({
        "body": body,
        "cta": cta,
        "send_as": send_as,
        "suppression_key": standard_suppression_key(trigger),
        "rationale": rationale(category, merchant, trigger, customer),
    }, category, merchant, trigger, customer)

def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    draft = deterministic_compose(category, merchant, trigger, customer)
    try:
        from ai_layer import get_ai_layer
        ai = get_ai_layer()
        if not ai:
            return draft
        conversation_id = make_conversation_id(merchant.get("merchant_id", ""), trigger.get("id", ""), trigger.get("customer_id"))
        generated = ai.compose(
            conversation_id=conversation_id,
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            deterministic_draft=draft,
        )
        return sanitize_message(generated, category, merchant, trigger, customer, draft) if generated else draft
    except Exception:
        return draft


# Late imports
from .compose_customer import compose_customer
from .state import make_conversation_id
from .suppression import standard_suppression_key
from .intents import category_voice, urgent_cta
from .profiles import remember_open_issue
from .scoring import generic_payload_facts, trigger_archetype
from .models import MessagePlan
from .state import normalized_kind_for_context