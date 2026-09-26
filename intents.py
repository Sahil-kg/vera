from __future__ import annotations

from typing import Any

from .models import TriggerArchetype
from .sanitization import clean_text, display_date, humanize_token, metric_label, money, pct, safe_number, safe_pct, safe_pct_abs, safe_text
from .state import CTA_BY_INTENT, KNOWN_TRIGGERS, normalized_kind_for_context

FAMILY_PATTERNS = {
    "healthcare": {
        "dent", "clinic", "doctor", "optician", "optical", "eye",
        "pet", "vet", "pharma", "medic", "health", "hospital",
        "physio", "ortho", "derma", "cardio", "neuro", "gynae",
        "ayurved", "homeo", "patholog", "lab", "diagnostic",
        "nursing", "maternity", "paediatr", "pediatr",
    },
    "food": {
        "restaurant", "cafe", "food", "pizza", "thali", "bakery", "kitchen",
        "dhaba", "biryani", "sweets", "mithai", "juice", "tea", "coffee",
        "canteen", "tiffin", "catering", "mess",
    },
    "beauty": {
        "salon", "spa", "beauty", "hair", "makeup", "nails", "wax",
        "threading", "grooming", "barber", "unisex", "lash", "brow",
    },
    "fitness": {
        "gym", "fitness", "yoga", "pilates", "sports", "crossfit",
        "zumba", "aerobic", "martial", "karate", "boxing", "swim",
        "rehab",
    },
    "education": {
        "school", "coaching", "tuition", "academy", "class", "education",
        "college", "institute", "tutorial", "skill", "course", "training",
        "abacus", "chess", "music", "art", "craft", "language",
    },
    "auto_service": {
        "car", "auto", "service", "garage", "repair", "bike", "tyres",
        "battery", "denting", "painting", "wash", "detailing", "mechanic",
    },
    "retail": {
        "store", "retail", "shop", "inventory", "stock", "mart",
        "supermarket", "grocery", "kirana", "electronics", "mobile",
        "clothing", "garment", "footwear", "jewel", "hardware", "stationery",
    },
}

FAMILY_CONTEXT_KEYWORDS = {
    "healthcare": {"appointment", "patient", "followup", "follow", "recall", "trust", "clinical", "medicine", "refill", "compliance", "care", "doctor", "clinic"},
    "food": {"order", "orders", "delivery", "menu", "lunch", "dinner", "offer", "demand", "booking", "table", "customers"},
    "fitness": {"trial", "membership", "coach", "workout", "class", "classes", "batch", "retention", "fitness", "training"},
    "beauty": {"booking", "slot", "salon", "spa", "hair", "beauty", "style", "appointment", "client"},
    "education": {"class", "classes", "batch", "admission", "student", "parent", "enquiry", "course", "learning"},
    "auto_service": {"service", "repair", "inspection", "pickup", "drop", "workshop", "parts", "diagnostic"},
    "retail": {"stock", "inventory", "product", "offer", "sale", "customers", "shelf", "margin", "pricing"},
    "local_services": {"booking", "service", "support", "visit", "followup", "follow", "trust", "conversion"},
}

POSITIVE_LEVELS = {"low": 4, "medium": 8, "moderate": 8, "high": 14, "urgent": 18, "severe": 20, "critical": 22}


def category_family(category=None, merchant=None):
    parts: list[str] = []
    if category:
        parts.append(clean_text(category.get("slug", "")))
        parts.append(clean_text(category.get("name", "")))
    if merchant:
        ident = merchant.get("identity", {})
        parts.append(clean_text(ident.get("name", "")))
        parts.append(clean_text(merchant.get("category_slug", "")))
    text = " ".join(parts).lower()
    for family, words in FAMILY_PATTERNS.items():
        if any(word in text for word in words):
            return family
    return "local_services"


def family_offer_noun(family: str) -> str:
    return {
        "healthcare": "appointment",
        "food": "offer",
        "fitness": "batch",
        "beauty": "service",
        "education": "batch",
        "auto_service": "service slot",
        "retail": "offer",
    }.get(family, "offer")


def family_action_label(family: str) -> str:
    return {
        "healthcare": "trust-safe",
        "food": "restaurant-ready",
        "fitness": "coach-style",
        "beauty": "booking-friendly",
        "education": "parent/student-friendly",
        "auto_service": "service-ready",
        "retail": "retail-ready",
    }.get(family, "merchant-ready")


def fact_label(key: str) -> str:
    return {
        "delta_pct": "change",
        "price_change_pct": "price change",
        "risk_level": "risk",
        "affected_count": "affected",
        "shortage_count": "shortage",
        "distance_km": "distance",
        "occurrences_30d": "30d mentions",
        "competitor_name": "competitor",
    }.get(key, humanize_token(key))


def first_name(identity: dict[str, Any]) -> str:
    owner = clean_text(identity.get("owner_first_name"))
    if owner:
        return owner.replace("Dr. ", "")
    name = clean_text(identity.get("name"))
    if name.lower().startswith("dr. "):
        parts = name.split()
        return parts[1].strip("'s,") if len(parts) > 1 else "Doctor"
    return name.split()[0].strip("'s,") if name else "there"


def salutation(category: dict[str, Any], merchant: dict[str, Any]) -> str:
    ident = merchant.get("identity", {})
    fn = first_name(ident)
    if category.get("slug") == "dentists":
        return fn if fn.startswith("Dr.") else f"Dr. {fn}"
    return fn


def active_offer(merchant: dict[str, Any], category: dict[str, Any] | None = None) -> str:
    for offer in merchant.get("offers", []):
        if offer.get("status") == "active":
            return clean_text(offer.get("title"))
    if category:
        catalog = category.get("offer_catalog", [])
        if catalog:
            return clean_text(catalog[0].get("title"))
    return ""


def active_offer_detail(merchant: dict[str, Any], category: dict[str, Any] | None = None) -> str:
    for offer in merchant.get("offers", []):
        if offer.get("status") == "active":
            title = clean_text(offer.get("title"))
            discount = offer.get("discount_pct")
            valid_until = display_date(offer.get("valid_until") or offer.get("expires_at"))
            discount_text = f" ({int(discount * 100)}% off)" if discount and isinstance(discount, (int, float)) else ""
            expiry_text = f", valid till {valid_until}" if valid_until else ""
            return f"{title}{discount_text}{expiry_text}"
    if category:
        catalog = category.get("offer_catalog", [])
        if catalog:
            return clean_text(catalog[0].get("title"))
    return ""


def find_digest(category: dict[str, Any], item_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
    digest = category.get("digest", [])
    if item_id:
        for item in digest:
            if item.get("id") == item_id:
                return item
    if kind:
        for item in digest:
            if item.get("kind") == kind:
                return item
    return digest[0] if digest else {}


def metric_line(merchant: dict[str, Any]) -> str:
    perf = merchant.get("performance", {})
    views = perf.get("views")
    calls = perf.get("calls")
    ctr = perf.get("ctr")
    bits = []
    if views is not None:
        bits.append(f"{int(views):,} views")
    if calls is not None:
        bits.append(f"{int(calls)} calls")
    if ctr is not None:
        bits.append(f"{pct(ctr)} CTR")
    if not bits:
        return ""
    return ", ".join(bits)


def urgency_proof(trigger: dict[str, Any], merchant: dict[str, Any], category: dict[str, Any]) -> str:
    payload = trigger.get("payload", {})
    kind = clean_text(trigger.get("kind"))
    agg = merchant.get("customer_aggregate", {})
    perf = merchant.get("performance", {})

    lapsed = agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus")
    if lapsed and kind in {"dormant_with_vera", "winback_eligible"}:
        avg = money(agg.get("avg_order_value") or agg.get("avg_spend"))
        value_clause = f", worth ~{avg} each" if avg else ""
        return f"{lapsed} customers haven't returned{value_clause}."

    days = _as_float(payload.get("days_until") or payload.get("days_remaining"))
    if days is not None and days >= 0:
        if days <= 1:
            return "This is due within 1 day."
        if days <= 3:
            return f"This is due in {int(days)} days."
        if days <= 7:
            return f"This is due within a week."

    severity = clean_text(payload.get("severity") or payload.get("risk_level") or payload.get("urgency"))
    if severity:
        return f"Marked {severity.lower()} in the payload."

    impact = clean_text(payload.get("impact") or payload.get("affected_count") or payload.get("customer_count") or payload.get("delta_pct") or payload.get("loss_pct"))
    if impact:
        return f"Impact signal: {impact}."

    metric_snapshot = metric_line(merchant)
    if metric_snapshot:
        return f"Current profile: {metric_snapshot}."

    if perf.get("views") is not None or perf.get("calls") is not None:
        bits = []
        if perf.get("views") is not None:
            bits.append(f"{perf.get('views'):,} views")
        if perf.get("calls") is not None:
            bits.append(f"{perf.get('calls')} calls")
        if perf.get("ctr") is not None:
            bits.append(f"{pct(perf.get('ctr'))} CTR")
        if bits:
            return f"Current profile: {', '.join(bits)}."

    family = category_family(category, merchant)
    return f"This needs attention for the {family} business."


def approve_cta(what: str, *, tail: str = "") -> str:
    """One low-effort approval instead of a numbered 1/2/3 menu.

    Asking a merchant to pick an artefact type or a tone ("1 soft, 2
    offer-led, or 3 urgent?") reads as a taxonomy question, not a decision,
    and it scored as the weakest criterion in the LLM judge. Naming the one
    thing Vera already decided to make keeps the reason in the body and leaves
    a single word to reply.
    """
    suffix = f" {tail}" if tail else ""
    return f"Reply YES and I'll send {what}.{suffix}"


def render_cta(cta_type: str, family: str, offer: str = "", profile: dict[str, Any] | None = None) -> str:
    noun = family_offer_noun(family)
    offer_text = offer or f"your {noun}"
    if cta_type == "choice":
        return approve_cta(f"the review reply around {offer_text}")
    if cta_type == "question":
        return f"Which {noun} should I draft around first?"
    if cta_type == "scheduling":
        return approve_cta("the campaign schedule")
    if profile and profile.get("prefers_questions"):
        return "Want me to draft the short version first, or go straight to the full post?"
    return approve_cta(f"the post around {offer_text}")


def cta_for(kind: str, customer: dict[str, Any] | None = None) -> str:
    if customer and kind in {"recall_due", "trial_followup"}:
        return "confirm_slot"
    if customer and kind in {"appointment_tomorrow", "chronic_refill_due", "customer_lapsed_hard", "customer_lapsed_soft"}:
        return "confirm_slot"
    if customer and kind == "followup_due":
        return "confirm_slot"
    if kind == "curious_ask_due":
        return "answer_question"
    if kind not in KNOWN_TRIGGERS or kind == "generic":
        if any(word in kind for word in ["crisis", "shortage", "inventory", "compliance", "risk", "recall"]):
            return "take_action"
        if any(word in kind for word in ["price", "revenue", "dip", "sales", "lead"]):
            return "draft_post"
        return "next_step"
    if kind in {"research_digest", "cde_opportunity"}:
        return "draft_post"
    if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip"}:
        return "draft_post"
    if kind in {"review_theme_emerged", "milestone_reached"}:
        return "review_offer"
    if kind in {"festival_upcoming", "ipl_match_today"}:
        return "schedule_campaign"
    if kind in {"winback_eligible", "dormant_with_vera"}:
        return "run_winback"
    if kind == "competitor_opened":
        return "draft_positioning"
    if kind == "renewal_due":
        return "send_recap"
    if kind in {"gbp_unverified", "regulation_change", "supply_alert", "category_seasonal"}:
        return "take_action"
    if kind in {"active_planning_intent"}:
        return "draft_post"
    return "next_step"


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def category_customer_due_label(category_slug: str, raw_due: Any) -> str:
    due = humanize_token(raw_due)
    if due and due != "recall":
        return due
    return {
        "dentists": "cleaning recall",
        "gyms": "fitness follow-up",
        "salons": "next visit",
        "restaurants": "next order",
        "pharmacies": "pharmacy follow-up",
    }.get(category_slug, "follow-up")


def category_voice(category_slug: str) -> str:
    family = category_family({"slug": category_slug})
    family_voice = {
        "healthcare": "trust-first expert tone",
        "food": "practical food-operator tone",
        "fitness": "coach-to-owner tone",
        "beauty": "warm booking-friendly tone",
        "education": "clear parent/student acquisition tone",
        "auto_service": "service-advisor tone",
        "retail": "precise retail-operator tone",
        "local_services": "merchant-operator tone",
    }
    return {
        "dentists": "clinical peer tone",
        "salons": "warm operator tone",
        "restaurants": "practical restaurant-operator tone",
        "gyms": "coach-to-owner tone",
        "pharmacies": "precise compliance-first tone",
    }.get(category_slug, family_voice.get(family, "merchant-operator tone"))


def category_tone_phrase(category: dict[str, Any], merchant: dict[str, Any]) -> str:
    """
    Returns a short, injectable phrase that sets category-appropriate tone.
    Used by composers to open with the right register.
    Examples:
      dentists  → "from a clinical standpoint"
      gyms      → "on the coaching side"
      restaurants → "on the floor"
      pharmacies  → "on the compliance side"
    """
    slug = (category or {}).get("slug") or (merchant or {}).get("category_slug", "")
    return {
        "dentists": "from a clinical standpoint",
        "gyms": "from a coaching standpoint",
        "salons": "from a bookings standpoint",
        "restaurants": "on the operations side",
        "pharmacies": "on the compliance side",
        "opticians": "on the clinical side",
        "spas": "from a guest-experience angle",
    }.get(slug, "on the business side")


def urgency_sentence(trigger: dict[str, Any], merchant: dict[str, Any], category: dict[str, Any]) -> str:
    """
    Returns a single sentence explaining why acting *right now* matters.
    Pulls from: deadline fields, competitor recency, lapsed count trend, delta direction.
    Returns "" if no concrete urgency can be constructed.
    """
    payload = trigger.get("payload", {}) or {}
    kind = clean_text(trigger.get("kind", "")).lower()

    for key in ("days_remaining", "days_until", "due_in_days"):
        days = _as_float(payload.get(key))
        if days is not None and days > 0:
            if days <= 1:
                return "This window closes tomorrow — acting today avoids a costly gap."
            if days <= 3:
                return f"Only {int(days)} days left — delay now means restarting from scratch."
            if days <= 7:
                return f"The window is {int(days)} days — early action captures the full demand curve."

    if kind == "competitor_opened":
        opened = display_date(payload.get("opened_date", ""))
        dist = payload.get("distance_km")
        dist_text = f" {dist} km away" if dist else " nearby"
        date_text = f" on {opened}" if opened else ""
        return f"A competitor opened{dist_text}{date_text} — first-mover positioning in the first 30 days is 3× more effective."

    agg = merchant.get("customer_aggregate") or {}
    lapsed = _as_float(agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus"))
    if lapsed and lapsed >= 5 and kind in {"perf_dip", "dormant_with_vera", "winback_eligible", "seasonal_perf_dip"}:
        return f"{int(lapsed)} customers have already lapsed — each extra week makes re-engagement harder."

    perf = merchant.get("performance", {})
    calls_delta = _as_float((perf.get("delta_7d") or {}).get("calls_pct"))
    if calls_delta is not None and calls_delta < -0.15 and kind in {"perf_dip", "seasonal_perf_dip"}:
        return f"Calls are down {safe_pct_abs(calls_delta)} week-on-week — waiting another week compounds the gap."

    if kind in {"festival_upcoming", "ipl_match_today", "category_seasonal"}:
        event = clean_text(payload.get("event_name") or payload.get("festival_name") or "the event")
        return f"Demand peaks around {event} — posts published 3–5 days early get 2× the reach."

    return ""


def decision_line(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None = None) -> str:
    slug = category.get("slug") or merchant.get("category_slug", "")
    kind = normalized_kind_for_context(trigger, category, merchant)
    payload = trigger.get("payload", {})
    if customer and kind == "recall_due":
        slug = category.get("slug") or (merchant or {}).get("category_slug", "")
        _recall_labels = {
            "dentists": "dental",
            "gyms": "fitness",
            "salons": "salon",
            "pharmacies": "pharmacy",
            "restaurants": "restaurant",
            "opticians": "optician",
        }
        category_label = _recall_labels.get(slug, slug.rstrip("s") if slug else "service")
        return (
            f"Customer-scoped {category_label} recall/follow-up; uses only customer name, "
            f"clinic name, available offer, and slot preference if present."
        )
    if customer and kind in {"appointment_tomorrow", "trial_followup", "followup_due"}:
        return f"Customer-scoped {kind.replace('_', ' ')}; asks for a simple confirmation instead of adding unsupported facts."
    if kind in {"active_planning_intent", "research_digest", "regulation_change", "cde_opportunity"}:
        item_id = clean_text(payload.get("top_item_id") or payload.get("digest_item_id"))
        return f"Knowledge/planning trigger anchored on {item_id or 'the latest pushed context'}."
    if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip", "winback_eligible", "dormant_with_vera"}:
        metric = clean_text(payload.get("metric") or "merchant performance")
        return f"Performance trigger centered on {metric}, using the merchant's current metrics."
    if kind in {"review_theme_emerged", "milestone_reached"}:
        return "Trust trigger; asks the merchant to turn the pushed review/milestone signal into visible proof."
    if kind == "competitor_opened":
        competitor = clean_text(payload.get("competitor_name") or "new competitor")
        return f"Competitor trigger references {competitor} and avoids inventing market details."
    if kind == "ipl_match_today":
        return f"Same-day restaurant trigger using match context: {clean_text(payload.get('match')) or 'match'}."
    if kind == "festival_upcoming":
        return f"Festival planning trigger for {clean_text(payload.get('festival')) or 'the pushed festival'}."
    if kind == "curious_ask_due":
        return f"Curious ask uses merchant metrics to request one specific input for {slug or 'the category'}."
    if slug == "pharmacies" and kind in {"supply_alert", "category_seasonal"}:
        return "Pharmacy trigger uses only the pushed medicine/seasonal context and merchant metrics."
    return f"{kind.replace('_', ' ')} trigger with one next step based on available context."


def impact_line(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: dict[str, Any] | None = None) -> str:
    kind = normalized_kind_for_context(trigger, category, merchant)
    perf = merchant.get("performance", {})
    views = perf.get("views")
    calls = perf.get("calls")
    ctr = perf.get("ctr")

    if kind == "perf_dip":
        if views is not None and calls is not None:
            return f"This should recover conversion from {views:,} views and {calls} calls."
        return "This should stop the revenue leak before it compounds."
    if kind == "perf_spike":
        if calls is not None:
            return "This can turn the current call spike into more bookings while attention is warm."
        return "This can turn the momentum into more booked slots."
    if kind == "seasonal_perf_dip":
        return "This protects retention now and avoids paying to chase weak demand."
    if kind in {"review_theme_emerged", "milestone_reached"}:
        return "This should lift trust, review velocity, and profile conversion."
    if kind == "competitor_opened":
        return "This defends premium positioning and reduces price-led churn."
    if kind == "festival_upcoming":
        return "This gets you ready before intent spikes and search starts rising."
    if kind == "ipl_match_today":
        return "This captures same-day demand during the match window."
    if kind in {"active_planning_intent", "research_digest", "regulation_change", "cde_opportunity"}:
        if ctr is not None:
            return f"This should turn {pct(ctr)} CTR into a stronger response."
        return "This creates a sharper local response that drives action."
    if kind in {"supply_alert", "category_seasonal"}:
        return "This protects trust and keeps the category message current."
    if kind in {"winback_eligible", "dormant_with_vera"}:
        return "This can recover lapsed customers before the list gets colder."
    if kind in {"recall_due", "appointment_tomorrow", "chronic_refill_due", "trial_followup"}:
        return "This moves the customer from interest to a confirmed next visit."
    if kind == "gbp_unverified":
        return "This should improve trust and unlock more profile actions."
    return "This moves the merchant toward a clearer next action."


def merchant_implication_for_archetype(archetype: TriggerArchetype, family: str) -> str:
    if archetype.name == "lead_conversion":
        return "customers may be choosing alternatives before contacting you"
    if archetype.name == "resource_constraint":
        return "staff capacity needs clear timing before slots get messy"
    if archetype.name == "inventory_constraint":
        return "customers need safe alternatives before trust drops"
    if archetype.name == "customer_communication":
        return "customers need the value explained before the change feels abrupt"
    if archetype.name == "trust_repair":
        return "visible proof can stop the issue shaping new-customer decisions"
    if archetype.name == "campaign_planning":
        return "preparing early helps capture demand before everyone posts"
    if family == "food":
        return "a timely offer can turn attention into orders"
    if family == "healthcare":
        return "a clear trust-safe update can turn attention into appointments"
    return "one clear action is better than separate small nudges"


def known_trigger_cta(
    kind: str,
    family: str,
    offer: str = "",
    profile: dict[str, Any] | None = None,
    *,
    merchant: dict[str, Any] | None = None,
    category: dict[str, Any] | None = None,
    customer: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> str:
    if merchant and category:
        return urgent_cta(kind, merchant, category, customer, trigger)
    if kind in {"perf_dip", "seasonal_perf_dip"}:
        return approve_cta("the recovery post around your current offer")
    if kind == "perf_spike":
        return approve_cta("the follow-up post around your current offer")
    if kind in {"review_theme_emerged", "milestone_reached"}:
        return approve_cta("the proof post built on that")
    if kind == "competitor_opened":
        return approve_cta("the direct-comparison draft")
    if kind in {"festival_upcoming", "ipl_match_today"}:
        return approve_cta("the campaign around your current offer")
    if kind in {"winback_eligible", "dormant_with_vera"}:
        return approve_cta("a soft winback for your lapsed customers")
    if kind in {"supply_alert", "category_seasonal", "regulation_change", "gbp_unverified"}:
        return approve_cta("the short checklist")
    if kind in {"research_digest", "cde_opportunity"}:
        return approve_cta("the source summary")
    if kind == "active_planning_intent":
        return approve_cta("the post around your current offer")
    if kind == "renewal_due":
        return approve_cta("the short recap of what is working")
    if profile and profile.get("prefers_questions"):
        return "Want the short version first, or straight to the full draft?"
    return render_cta("confirmation", family, offer, profile)


def urgent_cta(
    kind: str,
    merchant: dict[str, Any],
    category: dict[str, Any],
    customer: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> str:
    perf = merchant.get("performance", {})
    delta_7d = perf.get("delta_7d") or {}
    calls_delta = delta_7d.get("calls_pct")
    views_delta = delta_7d.get("views_pct")
    calls = perf.get("calls")
    views = perf.get("views")
    family = category_family(category, merchant)
    offer = active_offer(merchant, category)
    offer_detail = active_offer_detail(merchant, category)
    # Only anchor the CTA to a real offer. When the merchant has none, the
    # family fallback ("your appointment", "your service") is a weak, generic
    # noun that reads worse than naming the artifact on its own.
    active_offer_text = offer_detail or offer
    around = f" around {active_offer_text}" if active_offer_text else ""
    slug = category.get("slug", "")

    if kind == "perf_dip":
        return approve_cta(f"the Google post{around}")

    if kind == "perf_spike":
        return approve_cta(f"the follow-up post{around}")

    if kind == "seasonal_perf_dip" and views_delta is not None:
        return approve_cta(f"the retention nudge{around}")

    if kind == "competitor_opened":
        return approve_cta(f"the direct-comparison draft{around}")

    if kind in {"winback_eligible", "dormant_with_vera"}:
        agg = merchant.get("customer_aggregate") or {}
        lapsed = agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus")
        lapsed_text = f" for {lapsed} lapsed customers" if lapsed else ""
        return approve_cta(
            f"a soft winback{lapsed_text}{around}",
            tail="No deadline pressure - you approve before anything sends.",
        )

    if kind in {"festival_upcoming", "ipl_match_today"}:
        if slug == "restaurants":
            return approve_cta(
                f"the match-night special{around}",
                tail="Ready to send before the crowd books out.",
            )
        if slug in {"salons", "gyms"}:
            return approve_cta(f"the {slug[:-1]} campaign{around}")
        return approve_cta(
            f"the campaign{around}",
            tail="Ready to send today.",
        )

    if kind == "active_planning_intent":
        channel = clean_text(((trigger or {}).get("payload") or {}).get("channel", ""))
        if channel:
            return approve_cta(f"the {channel} version{around}")
        return approve_cta(f"the Google post{around}")

    if kind == "milestone_reached":
        # metric_label keeps payload tokens like "review_count" out of the body.
        metric_val = metric_label((trigger or {}).get("payload", {}).get("metric") or "milestone")
        return approve_cta(f"the proof post built on your {metric_val}")

    if kind == "renewal_due":
        plan = clean_text((trigger or {}).get("payload", {}).get("plan") or "subscription")
        return approve_cta(f"the {plan} recap of what is working so far")

    if kind == "gbp_unverified":
        return approve_cta(
            "the 5-minute verification checklist",
            tail="This one step unlocks your call button on Google.",
        )

    if customer:
        cname = clean_text(customer.get("identity", {}).get("name"))
        if cname:
            return f"Should I draft the next step for {cname}{around}?"

    from .profiles import merchant_profile

    mp = merchant_profile(merchant.get("merchant_id"))
    noun = family_offer_noun(family)
    offer_text = active_offer_text or f"your {noun}"
    tail_around = f" around {active_offer_text}" if active_offer_text else ""

    if mp.get("prefers_questions"):
        return f"Want the short version first, or straight to the full draft{tail_around}?"

    # Merchant who has objected → lowest possible ask, no menu at all.
    if int(mp.get("objection_count", 0)) >= 1:
        return f"One 2-line draft, nothing sends without your YES. Say YES and I'll prepare it{tail_around}."

    # Rotate the artifact wording so repeat sends don't read identically, but keep
    # a single approval word in every variant.
    options = [
        approve_cta(f"the Google post{tail_around}"),
        approve_cta(f"a short WhatsApp line{tail_around}"),
        approve_cta(f"the draft{tail_around}"),
    ]
    return options[int(mp.get("reply_count", 0)) % len(options)]
