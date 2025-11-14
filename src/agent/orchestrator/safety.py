from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List


class SafetyDecision(Enum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"


@dataclass
class SafetyResult:
    decision: SafetyDecision
    reason: str | None = None


class SafetySentinel:
    destructive_keywords = (
        "delete",
        "remove",
        "erase",
        "trash",
        "checkout",
        "pay",
        "transfer",
        "purchase",
        "удали",
        "оплати",
        "оформи оплату",
    )

    def __init__(self, custom_keywords: Iterable[str] | None = None) -> None:
        keywords = list(self.destructive_keywords)
        if custom_keywords:
            keywords.extend(custom_keywords)
        self.keywords: List[str] = [kw.lower() for kw in keywords]

    def inspect(self, text: str) -> SafetyResult:
        lower = text.lower()
        for keyword in self.keywords:
            if keyword in lower:
                return SafetyResult(
                    decision=SafetyDecision.REQUIRE_CONFIRMATION,
                    reason=f"Обнаружено потенциально опасное действие (‘{keyword}’)",
                )
        return SafetyResult(decision=SafetyDecision.ALLOW)
