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
    "fitness": {
        "gym", "fitness", "yoga", "pilates", "sports", "crossfit",
        "zumba", "aerobic", "martial", "karate", "boxing", "swim",
        "dance", "studio", "wellness", "rehab",
    },
    "beauty": {
        "salon", "spa", "beauty", "hair", "makeup", "nails", "wax",
        "threading", "grooming", "barber", "unisex", "lash", "brow",
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
    # Add a brief conversion note when both views and calls are available
    if views is not None and calls is not None and views > 0:
        ratio = calls / views
        if ratio < 0.005:
            bits.append("(low conversion — offer or social proof may help)")
        elif ratio >= 0.03:
            bits.append("(converting well)")
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


def render_cta(cta_type: str, family: str, offer: str = "", profile: dict[str, Any] | None = None) -> str:
    if cta_type == "choice":
        noun = family_offer_noun(family)
        return f"Reply 1 for review reply, 2 for proof post, or 3 for {offer or noun} nudge."
    if cta_type == "question":
        noun = family_offer_noun(family)
        return f"Which {noun} should I draft around first?"
    if cta_type == "scheduling":
        # Fix 5: replace generic YES with a choice
        return f"Reply 1 to schedule the campaign, 2 to preview the draft first, or 3 for both."
    if profile and profile.get("prefers_questions"):
        return "Want me to draft the short version first, or go straight to the full post?"
    # Fix 5: replace bare "Reply YES to preview" with a choice
    noun = family_offer_noun(family)
    offer_text = offer or f"your {noun}"
    return f"Reply 1 for a quick draft, 2 to review the structure first, or 3 to skip and go live."


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
        return f"Knowledge/planning trigger anchored on {item_id or 'the pushed trigger payload'}."
    if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip", "winback_eligible", "dormant_with_vera"}:
        metric = clean_text(payload.get("metric") or "merchant performance")
        return f"Performance trigger centered on {metric}, using the merchant's current metrics."
    if kind in {"review_theme_emerged", "milestone_reached"}:
        return "Trust trigger; asks the merchant to turn the pushed review/milestone signal into visible proof."
    if kind == "competitor_opened":
        competitor = clean_text(payload.get("competitor_name") or "new competitor")
        return f"Competitor trigger references {competitor} and avoids inventing market details."
    if kind == "ipl_match_today":
        return f"Same-day restaurant trigger using match payload: {clean_text(payload.get('match')) or 'match'}."
    if kind == "festival_upcoming":
        return f"Festival planning trigger for {clean_text(payload.get('festival')) or 'the pushed festival'}."
    if kind == "curious_ask_due":
        return f"Curious ask uses merchant metrics to request one specific input for {slug or 'the category'}."
    if slug == "pharmacies" and kind in {"supply_alert", "category_seasonal"}:
        return "Pharmacy trigger uses only the pushed medicine/seasonal payload and merchant metrics."
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
        return "Which should I fix first: 1 calls, 2 reviews, or 3 visibility?"
    if kind == "perf_spike":
        return "Reply 1 for a short follow-up post, 2 for a stronger booking push, or 3 for both."
    if kind in {"review_theme_emerged", "milestone_reached"}:
        return "Reply 1 for review reply, 2 for review ask, or 3 for proof post."
    if kind == "competitor_opened":
        return "Reply 1 for a premium-positioning draft or 2 for a direct comparison draft."
    if kind in {"festival_upcoming", "ipl_match_today"}:
        return "Reply 1 for a post, 2 for WhatsApp, or 3 for both."
    if kind in {"winback_eligible", "dormant_with_vera"}:
        return "Should I make the winback soft, offer-led, or urgent?"
    if kind in {"supply_alert", "category_seasonal", "regulation_change", "gbp_unverified"}:
        return "Reply 1 for the short checklist, 2 for the customer-ready message, or 3 for both."
    if kind in {"research_digest", "cde_opportunity"}:
        return "Reply 1 for the source summary, 2 for the patient-facing draft, or 3 for both."
    if kind == "active_planning_intent":
        return "Want this as 1 Google post, 2 WhatsApp, or 3 both?"
    if kind == "renewal_due":
        return "Reply 1 for a short recap, 2 for a detailed value summary, or 3 to renew now."
    if profile and profile.get("prefers_questions"):
        return "Reply 1 for the short version, 2 for the full draft, or 3 to see both side by side."
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
    active_offer_text = offer_detail or offer or f"your {family_offer_noun(family)}"
    slug = category.get("slug", "")

    if kind == "perf_dip":
        offer_text = offer_detail or offer or f"your {family_offer_noun(family)}"
        # Fix 4: choice-based CTA instead of single YES
        return (
            f"Reply 1 for a Google post, 2 for a WhatsApp nudge, or 3 for both — "
            f"to recover {offer_text}."
        )

    if kind == "perf_spike":
        offer_detail = active_offer_detail(merchant, category)
        return (
            f"Reply 1 for follow-up post, 2 for WhatsApp, or 3 for both around "
            f"{offer_detail or offer or f'your {family_offer_noun(family)}'}."
        )

    if kind == "perf_spike" and calls_delta is not None:
        arrow = "up" if calls_delta > 0 else "down"
        views_text = f"{safe_number(views)} views" if views is not None else "your views"
        return (
            f"Calls are {arrow} {safe_pct(abs(calls_delta))} this week, with {views_text} on the profile. "
            f"Reply 1 for follow-up post, 2 for WhatsApp nudge, or 3 for both around {active_offer_text}."
        )

    if kind == "seasonal_perf_dip" and views_delta is not None:
        arrow = "down" if views_delta < 0 else "up"
        return (
            f"Views are {arrow} {safe_pct(abs(views_delta))} this week while demand is soft. "
            f"Reply 1 for a retention nudge, 2 for an acquisition push, or 3 for both around {active_offer_text}."
        )

    if kind == "competitor_opened":
        return (
            f"Reply 1 for premium-positioning draft or 2 for direct comparison around {active_offer_text}."
        )

    if kind in {"winback_eligible", "dormant_with_vera"}:
        agg = merchant.get("customer_aggregate") or {}
        lapsed = agg.get("lapsed_90d_plus") or agg.get("lapsed_180d_plus")
        lapsed_text = f" for {lapsed} lapsed customers" if lapsed else ""
        # Fix 4: choice-based CTA
        return (
            f"Should I make the winback{lapsed_text} 1 soft, 2 offer-led, or 3 urgent? "
            f"I'll draft around {active_offer_text}."
        )

    if kind in {"festival_upcoming", "ipl_match_today"}:
        if slug == "restaurants":
            return f"Reply 1 for dine-in special, 2 for delivery offer, or 3 for pre-order campaign around {active_offer_text}."
        if slug in {"salons", "gyms"}:
            return f"Reply 1 for post, 2 for WhatsApp, or 3 for both — around {active_offer_text}."
        return f"Reply 1 for a post, 2 for WhatsApp, or 3 to turn {active_offer_text} into a live campaign now."

    if kind == "active_planning_intent":
        channel = clean_text(((trigger or {}).get("payload") or {}).get("channel", ""))
        if channel:
            return f"Reply 1 for the {channel} version now, 2 for a preview first, or 3 for both around {active_offer_text}."
        return f"Reply 1 for Google post, 2 for WhatsApp, or 3 for both around {active_offer_text}."

    if customer:
        cname = clean_text(customer.get("identity", {}).get("name"))
        if cname:
            return f"Should I draft the next step for {cname} around {active_offer_text}?"

    from .profiles import merchant_profile

    mp = merchant_profile(merchant.get("merchant_id"))
    family = category_family(category, merchant)
    noun = family_offer_noun(family)
    offer_text = active_offer_text or f"your {noun}"

    if mp.get("prefers_questions"):
        return f"Reply 1 for a Google post, 2 for a WhatsApp line, or 3 for both around {offer_text}?"

    reply_count = int(mp.get("reply_count", 0))
    confirm_count = int(mp.get("confirm_count", 0))
    objection_count = int(mp.get("objection_count", 0))

    # Merchant who confirms fast → give direct options
    if confirm_count >= 2:
        return f"Reply 1 for Google post, 2 for WhatsApp nudge, or 3 for both around {offer_text}."

    # Merchant who has objected → lower the ask
    if objection_count >= 1:
        return f"One 2-line draft, no send without your approval. Reply 1 to go ahead around {offer_text}."

    # Rotate to avoid repetition
    options = [
        f"Reply 1 for the Google post, 2 for the WhatsApp nudge, or 3 for both around {offer_text}.",
        f"Reply 1 for a quick post, 2 for a WhatsApp line, or 3 for a combined push around {offer_text}.",
        f"Reply 1 to start with the draft, 2 to see the message structure first, around {offer_text}.",
    ]
    return options[reply_count % len(options)]