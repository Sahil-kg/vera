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
    "model": "openai_via_langchain_optional_with_rules_fallback",
    "approach": "stateful context store, trigger ranking, LangChain summary-buffer memory AI generator, and deterministic safety fallback",
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
HOSTILE_PATTERNS = [r"\bidiot\b", r"\bstupid\b", r"\bshut up\b", r"\bnonsense\b", r"\bwaste\b", r"\bangry\b"]
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
