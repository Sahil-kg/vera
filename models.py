from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MessagePlan:
    fact: str
    implication: str
    action: str
    cta: str
    cta_type: str = "confirmation"


@dataclass(frozen=True)
class TriggerArchetype:
    name: str
    business_problem: str
    recommended_action: str
    cta_type: str
    base_priority: int
