from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any

START_TIME = time.time()
TEAM_METADATA = {
    "team_name": "Vera Precision Bot",
    "team_members": ["Sahil"],
    "model": "deterministic_rules_engine",
    "approach": "stateful context store, trigger ranking, insight extraction, deterministic message composition, and suppression controls",
    "contact_email": "not-provided@example.com",
    "version": "1.0.0",
    "submitted_at": "2026-05-29T00:00:00Z",
}

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}
CTA_BY_INTENT = {
    "slot_choice": "confirm_slot",
    "confirm": "take_action",
    "yes_no": "next_step",
    "open": "answer_question",
    "none": "none",
}
INTERNAL_BODY_TERMS = {
    "triggercontext",
    "merchantcontext",
    "customercontext",
    "categorycontext",
    "payload",
    "rationale",
    "rubric",
    "judge",
    "suppression",
    "merchant-scoped",
    "customer-scoped",
}
KNOWN_TRIGGERS = {
    "active_planning_intent",
    "appointment_tomorrow",
    "category_seasonal",
    "cde_opportunity",
    "chronic_refill_due",
    "competitor_opened",
    "curious_ask_due",
    "customer_lapsed_hard",
    "customer_lapsed_soft",
    "dormant_with_vera",
    "festival_upcoming",
    "followup_due",
    "gbp_unverified",
    "ipl_match_today",
    "milestone_reached",
    "perf_dip",
    "perf_spike",
    "recall_due",
    "regulation_change",
    "renewal_due",
    "research_digest",
    "review_theme_emerged",
    "seasonal_perf_dip",
    "supply_alert",
    "trial_followup",
    "winback_eligible",
    "wedding_package_followup",
}
RISK_WORDS = {"risk", "urgent", "crisis", "shortage", "compliance", "recall", "stock", "inventory", "staff", "cancel"}
REVENUE_WORDS = {"price", "increase", "revenue", "sales", "booking", "lead", "calls", "conversion", "churn", "competitor"}
AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"thanks for contacting",
    r"our team will respond",
    r"automated assistant",
    r"we will get back",
    r"business hours",
]
STOP_PATTERNS = [r"\bstop\b", r"not interested", r"useless", r"spam", r"do not message", r"don't message"]
HOSTILE_PATTERNS = [r"\bidiot\b", r"\bstupid\b", r"\bshut up\b", r"\bnonsense\b", r"\bwast(?:e|ed|ing)\b", r"\bangry\b", r"\bridiculous\b", r"\bdon'?t (?:bother| bother)\b", r"\bget lost\b"]
YES_PATTERNS = [r"\byes\b", r"\bok\b", r"let'?s do", r"go ahead", r"confirm", r"send", r"proceed", r"what'?s next"]
OFFTOPIC_PATTERNS = [r"\bgst\b", r"\btax\b", r"\bca\b", r"loan", r"file"]
OBJECTION_PATTERNS = [
    r"too expensive",
    r"\bcost\b",
    r"\bprice\b",
    r"\bbudget\b",
    r"\blater\b",
    r"\bbusy\b",
    r"not now",
    r"no time",
    r"already tried",
    r"doesn'?t work",
    r"not sure",
    r"\bwhy\b",
    r"\bhow\b",
]

# ── Sender role resolution ───────────────────────────────────────────────────
# /v1/reply always carries from_role (challenge-testing-brief ReplyBody), so an
# explicit role is authoritative. The fallbacks below only matter when a caller
# omits it, and they keep the customer/merchant split from silently collapsing
# into one voice.
CUSTOMER_ROLE_NAMES = {
    "customer", "client", "patient", "user", "end_user", "enduser", "lead",
    "customer_reply", "patient_reply", "reply_from_customer", "customer_side",
}
MERCHANT_ROLE_NAMES = {
    "merchant", "owner", "business", "shop", "store", "vendor", "admin",
    "manager", "staff", "merchant_reply", "reply_from_merchant", "merchant_side",
}

# ── Customer-scope reply intents ─────────────────────────────────────────────
# Ordered by routing precedence in reply(): the first group that matches wins.
CUSTOMER_RESCHEDULE_PATTERNS = [
    r"\breschedul", r"\bchange (?:my |the |it |to )?(?:time|slot|day|date|appointment)",
    r"\bany other (?:day|slot|time)", r"\bnext (?:day|week|slot|available)",
    r"\bdifferent (?:day|slot|time)", r"\bmove (?:it|my|the)",
    r"\bsome other time\b", r"\banother time\b", r"\blater (?:slot|time|day)\b",
    r"\bafter \d", r"\bnext month\b", r"\bnot (?:this|that) (?:day|time|slot)\b",
]
CUSTOMER_CANCEL_PATTERNS = [
    r"\bcancel\b", r"\bcall off\b", r"\bnot coming\b", r"\bwon'?t (?:make|come|attend)\b",
    r"\bskip (?:it|this|my)\b", r"\bdrop (?:it|my)\b", r"\bstop the reminder\b",
]
CUSTOMER_CALL_PATTERNS = [
    r"\bcall me\b", r"\bcall (?:me )?back\b", r"\bphone me\b", r"\bring up\b",
    r"\bcall (?:my|us)\b", r"\bspeak to (?:me|someone|the doctor)\b",
    r"\btalk to (?:me|someone|doctor)\b", r"\bconnect me\b", r"\bhuman\b",
]
CUSTOMER_QUESTION_PATTERNS = [
    r"\bhow much\b", r"\bprice\b", r"\bcost\b", r"\bcharges?\b", r"\brate\b",
    r"\bfee\b", r"\bwhat(?:'s| is| does| do| are| will| can) (?:the |it |this )?\b",
    r"\bwhich (?:one|slot|package|service|product)\b", r"\bdo you (?:do|offer|take|have|accept)\b",
    r"\bis (?:it|this|that) (?:included|available|possible|covered)\b",
    r"\bavailable\b", r"\bincluded\b", r"\boptions?\b", r"\bdifference between\b",
]
CUSTOMER_THANKS_PATTERNS = [
    r"^\s*(thanks|thank you|thx|ok|okay|cool|great|perfect|awesome|noted|got it|done|bye|good night)\b",
    r"\bthanks a lot\b", r"\bthank you so much\b", r"\bthat works\b", r"\bsounds good\b",
    r"\bwill do\b", r"\bno problem\b", r"\bfine\b",
]
CUSTOMER_OBJECTION_PATTERNS = [
    r"too expensive", r"\btoo costly\b", r"\bafford\b", r"\bdiscount\b",
    r"\brunning late\b", r"\bwill be late\b", r"\bstuck in (?:traffic|a )\b",
    r"\bneed (?:more )?time\b", r"\bnot sure\b", r"\bthink about it\b",
    r"\bsome other time\b", r"\bcan'?t make it\b",
]
# Bare ordinal / keyword answers to a "Reply 1 or 2" customer prompt.
CUSTOMER_ORDINAL_PATTERNS = [r"^\s*(?:option\s*|slot\s*|#)?([1-9])\s*(?:st|nd|rd|th)?\b\.?\s*$"]

# Sub-types of customer question, so the answer matches what was actually asked
# instead of reciting the current offer at every "?"-shaped message.
CUSTOMER_PRICE_PATTERNS = [
    r"\bhow much\b", r"\bprice\b", r"\bcost\b", r"\bcharges?\b", r"\brate\b",
    r"\bfee\b", r"\bdiscount\b", r"\bafford\b", r"\bexpensive\b", r"\bbudget\b",
    r"\bpackage price\b", r"\bcharges?\b",
]
CUSTOMER_INCLUSION_PATTERNS = [
    r"\bwhat(?:'s| is| does| do| are| will) (?:the |it |this )?\w*\s*(include|cover|comprise)",
    r"\bis (?:it|this|that) (?:included|covered|part of)\b",
    r"\bwhat (?:does|do) .*\binclude\b", r"\bwhat is covered\b", r"\bwhat all\b",
    r"\bwhat comes with\b", r"\bwhat do i get\b", r"\bwhat will i get\b",
]
CUSTOMER_CAPABILITY_PATTERNS = [
    r"\bdo you (?:do|offer|take|have|accept|provide|carry|handle)\b",
    r"\bcan you (?:do|offer|take|handle|help)\b", r"\bare you (?:open|available)\b",
    r"\bdo (?:you|we) (?:walk|accept)\b", r"\bis .*\bavailable\b",
    r"\bwhat are your (?:hours|timings)\b", r"\bwhere are you\b",
]
# A patient reporting a clinical problem, not asking about the offer.
CUSTOMER_CONCERN_PATTERNS = [
    r"\bblurr?y\b", r"\bunclear\b", r"\bpoor quality\b", r"\bnot right\b",
    r"\bhurt(?:ing)?\b", r"\bpain\b", r"\bpainful\b", r"\bswelling\b",
    r"\bbleeding\b", r"\binfection\b", r"\bbroken\b", r"\bfell off\b",
    r"\bnot happy\b", r"\bcomplain(?:t|ed|ing)?\b", r"\bwrong\b", r"\breshoot\b",
    r"\bmistake\b", r"\bproblem\b", r"\bissue\b", r"\bstuck\b", r"\bwaited\b",
    r"\bno one (?:came|answered)\b", r"\bwaiting\b",
]
CUSTOMER_AVAILABILITY_PATTERNS = [
    r"\bwhen (?:can|is|are)\b", r"\bwhat (?:slot|slots|time|times)\b",
    r"\bnext (?:slot|available|opening)\b", r"\bopen (?:slot|slots)\b",
    r"\bany (?:slot|slots|availability)\b", r"\bfree (?:slot|slots)\b",
    r"\bavailable (?:slot|slots|times)\b",
    r"\bpossible\b", r"\bdo you have\b", r"\bany (?:day|slot|time|date)\b",
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", r"\bwork for you\b",
]


CONTEXTS: dict[tuple[str, str], dict[str, Any]] = {}
SENT_SUPPRESSIONS: set[str] = set()
CONVERSATIONS: dict[str, dict[str, Any]] = {}
MERCHANT_AUTO_REPLY_COUNTS: dict[str, dict[str, Any]] = {}
MERCHANT_PROFILES: dict[str, dict[str, Any]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_structured_state() -> dict[str, Any]:
    return {
        "merchant_id": None,
        "merchant_name": None,
        "owner_first_name": None,
        "category_slug": None,
        "customer_id": None,
        "customer_name": None,
        "customer_state": None,
        "language_pref": None,
        "last_trigger_id": None,
        "last_trigger_kind": None,
        "available_slots": [],
        "selected_slot": None,
        "last_slot_question": None,
        "last_inbound_role": None,
        "last_offer": None,
        "last_metric_snapshot": {},
        "last_customer_intent": None,
        "last_bot_cta": None,
        "last_bot_body": None,
        "auto_reply_count": 0,
        "opted_out": False,
        "action_confirmed": False,
        "coupon_sent": False,
    }


def build_structured_state(
    merchant: dict[str, Any],
    category: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None,
    message: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ident = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    payload = trigger.get("payload", {}) or {}
    customer_identity = (customer or {}).get("identity", {})
    from .intents import active_offer, first_name

    return {
        **empty_structured_state(),
        "merchant_id": merchant.get("merchant_id"),
        "merchant_name": ident.get("name"),
        "owner_first_name": ident.get("owner_first_name") or first_name(ident),
        "category_slug": category.get("slug") or merchant.get("category_slug"),
        "customer_id": trigger.get("customer_id"),
        "customer_name": customer_identity.get("name"),
        "customer_state": (customer or {}).get("state"),
        "language_pref": customer_identity.get("language_pref") or ",".join(ident.get("languages", [])),
        "last_trigger_id": trigger.get("id"),
        "last_trigger_kind": trigger.get("kind"),
        "available_slots": payload.get("available_slots") or payload.get("next_session_options") or [],
        "last_offer": active_offer(merchant, category),
        "last_metric_snapshot": {
            "views": perf.get("views"),
            "calls": perf.get("calls"),
            "directions": perf.get("directions"),
            "ctr": perf.get("ctr"),
            "leads": perf.get("leads"),
            "delta_7d": perf.get("delta_7d", {}),
        },
        "last_bot_cta": (message or {}).get("cta"),
        "last_bot_body": (message or {}).get("body"),
    }


def classify_intent(message: str) -> str:
    low = message.lower()
    import re

    stop_patterns = [r"\bstop\b", r"not interested", r"useless", r"spam", r"do not message", r"don't message"]
    auto_reply_patterns = [
        r"thank you for contacting",
        r"thanks for contacting",
        r"our team will respond",
        r"automated assistant",
        r"we will get back",
        r"business hours",
    ]
    offtopic_patterns = [r"\bgst\b", r"\btax\b", r"\bca\b", r"loan", r"file"]
    objection_patterns = [
        r"too expensive",
        r"\bcost\b",
        r"\bprice\b",
        r"\bbudget\b",
        r"\blater\b",
        r"\bbusy\b",
        r"not now",
        r"no time",
        r"already tried",
        r"doesn'?t work",
        r"not sure",
        r"\bwhy\b",
        r"\bhow\b",
    ]
    yes_patterns = [r"\byes\b", r"\bok\b", r"let'?s do", r"go ahead", r"confirm", r"send", r"proceed", r"what'?s next"]

    if any(re.search(p, low) for p in stop_patterns):
        return "opt_out"
    if any(re.search(p, low) for p in auto_reply_patterns):
        return "auto_reply"
    if any(re.search(p, low) for p in HOSTILE_PATTERNS):
        return "hostile"
    if any(re.search(p, low) for p in offtopic_patterns):
        return "off_topic"
    if any(re.search(p, low) for p in objection_patterns):
        return "objection"
    if any(re.search(p, low) for p in yes_patterns):
        return "confirm"
    if "?" in message:
        return "question"
    return "neutral"


def normalize_auto_reply(message: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", message.lower()).strip()[:160]


def resolve_sender_role(
    from_role: Any,
    *,
    customer_id: Any = None,
    state_customer_id: Any = None,
    state_customer_name: Any = None,
) -> str:
    """Decide whether an inbound /v1/reply turn came from a customer or a merchant.

    Precedence:
      1. An explicit from_role always wins — the judge contract requires it.
      2. A populated customer_id (request or stored conversation) means customer.
      3. A conversation already scoped to a named customer means customer.
      4. Otherwise the turn is treated as the merchant/owner talking.
    """
    role = clean_text(from_role).lower().replace("-", "_").replace(" ", "_")
    if role in CUSTOMER_ROLE_NAMES:
        return "customer"
    if role in MERCHANT_ROLE_NAMES:
        return "merchant"
    if role:
        # Unknown but non-empty role: fall through to the id-based signals below
        # rather than guessing from the free-text message.
        pass
    if clean_text(customer_id) or clean_text(state_customer_id):
        return "customer"
    if clean_text(state_customer_name):
        return "customer"
    return "merchant"


def classify_customer_intent(message: str) -> str:
    """Bucket a customer-scope reply so the router can pick a concrete answer.

    Returns one of: opt_out, auto_reply, hostile, slot_pick, slot_ordinal,
    reschedule, cancel, call_me, question, thanks, objection, confirm, neutral.
    """
    text = clean_text(message)
    low = text.lower()
    if any(re.search(p, low) for p in STOP_PATTERNS):
        return "opt_out"
    if any(re.search(p, low) for p in AUTO_REPLY_PATTERNS):
        return "auto_reply"
    if any(re.search(p, low) for p in HOSTILE_PATTERNS):
        return "hostile"
    for pattern in CUSTOMER_ORDINAL_PATTERNS:
        if re.search(pattern, low):
            return "slot_ordinal"
    for pattern in CUSTOMER_CANCEL_PATTERNS:
        if re.search(pattern, low):
            return "cancel"
    for pattern in CUSTOMER_RESCHEDULE_PATTERNS:
        if re.search(pattern, low):
            return "reschedule"
    for pattern in CUSTOMER_CALL_PATTERNS:
        if re.search(pattern, low):
            return "call_me"
    for pattern in CUSTOMER_THANKS_PATTERNS:
        if re.search(pattern, low):
            return "thanks"
    for pattern in CUSTOMER_QUESTION_PATTERNS:
        if re.search(pattern, low):
            return "question"
    for pattern in CUSTOMER_OBJECTION_PATTERNS:
        if re.search(pattern, low):
            return "objection"
    if any(re.search(p, low) for p in YES_PATTERNS):
        return "confirm"
    if "?" in text:
        return "question"
    return "neutral"


def slot_ordinal(message: str) -> int | None:
    """Return the 1-based slot number a bare '2' / 'option 2' reply selects."""
    for pattern in CUSTOMER_ORDINAL_PATTERNS:
        match = re.search(pattern, clean_text(message).lower())
        if match:
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                return None
            return value if 1 <= value <= 9 else None
    return None


_QUESTION_GROUPS = (
    ("concern", CUSTOMER_CONCERN_PATTERNS),
    ("price", CUSTOMER_PRICE_PATTERNS),
    ("inclusion", CUSTOMER_INCLUSION_PATTERNS),
    ("availability", CUSTOMER_AVAILABILITY_PATTERNS),
    ("capability", CUSTOMER_CAPABILITY_PATTERNS),
)


def classify_customer_question(message: str) -> str:
    """Sub-type a customer question so the answer matches what was asked.

    Returns one of: concern, price, inclusion, availability, capability, generic.
    """
    low = clean_text(message).lower()
    for label, group in _QUESTION_GROUPS:
        if any(re.search(p, low) for p in group):
            return label
    return "generic"



def slug_part(value: Any, default: str = "na") -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or default


def normalized_kind_for_context(
    trigger: dict[str, Any],
    category: dict[str, Any] | None = None,
    merchant: dict[str, Any] | None = None,
) -> str:
    kind = clean_text(trigger.get("kind"))
    slug = (category or {}).get("slug") or (merchant or {}).get("category_slug") or ""
    if kind == "chronic_refill_due" and slug and slug != "pharmacies":
        if slug == "dentists":
            return "recall_due"
        return "followup_due"
    if not kind:
        return "generic"
    return kind or "generic"


def make_conversation_id(merchant_id: str, trigger_id: str, customer_id: str | None = None) -> str:
    raw = f"{merchant_id}:{trigger_id}:{customer_id or ''}"
    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    short_mid = merchant_id.split("_")[1] if "_" in merchant_id else merchant_id[:8]
    return f"conv_{short_mid}_{trigger_id[:18]}_{suffix}"


def template_name(trigger: dict[str, Any], customer: dict[str, Any] | None, category: dict[str, Any] | None = None, merchant: dict[str, Any] | None = None) -> str:
    kind = normalized_kind_for_context(trigger, category, merchant)
    if customer:
        return f"merchant_{kind}_v1"
    if kind in {"research_digest", "regulation_change", "cde_opportunity"}:
        return "vera_knowledge_nudge_v1"
    if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip"}:
        return "vera_performance_nudge_v1"
    return f"vera_{kind}_v1"


from .sanitization import clean_text
