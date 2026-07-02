from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from taxsentry.runtime.policy import PolicyGate, PolicyDecision
from taxsentry.text_normalize import normalize_for_match


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    route: str
    urgency: str
    needs_clarification: bool
    confidence: float
    policy: PolicyDecision
    hints: list[str] = field(default_factory=list)


class InteractionRouter:
    """Classify a request before runtime / capability execution."""

    def __init__(self, policy_gate: PolicyGate | None = None):
        self.policy_gate = policy_gate or PolicyGate()

    def route(self, user_input: str, *, context: dict[str, Any] | None = None) -> RouteDecision:
        text = (user_input or "").strip()
        lowered = text.lower()
        normalized = normalize_for_match(text)
        policy = self.policy_gate.evaluate(text)

        route = "chat"
        intent = "chat"
        urgency = "normal"
        needs_clarification = False
        hints: list[str] = []
        confidence = 0.75

        analysis_keywords = (
            "phân tích",
            "analysis",
            "audit",
            "kiểm tra",
            "review",
            "đối chiếu",
            "phan tich",
            "kiem tra",
            "doi chieu",
            "bao cao thue",
        )
        if any(keyword in lowered or keyword in normalized for keyword in analysis_keywords):
            route = intent = "analysis"
            hints.append("analysis-intent")
            confidence = 0.9
        operation_keywords = (
            "chạy",
            "start",
            "khởi động",
            "bot",
            "up",
            "deploy",
            "service",
            "chay",
            "khoi dong",
        )
        if any(keyword in lowered or keyword in normalized for keyword in operation_keywords):
            route = intent = "operation"
            hints.append("operation-intent")
            confidence = max(confidence, 0.85)
        notification_keywords = ("gửi", "email", "telegram", "notify", "thông báo", "gui", "thong bao")
        if any(keyword in lowered or keyword in normalized for keyword in notification_keywords):
            route = intent = "operation"
            hints.append("notification-intent")
        if "?" in text and route == "chat":
            hints.append("question")

        if len(text) < 12:
            needs_clarification = True
            route = "clarification"
            intent = "clarification"
            hints.append("too-short")
            confidence = 0.35

        urgent_keywords = ("khẩn", "urgent", "ngay", "asap", "khan")
        if any(keyword in lowered or keyword in normalized for keyword in urgent_keywords):
            urgency = "high"
            hints.append("urgent")

        if context and context.get("missing_data"):
            needs_clarification = True
            hints.append("missing-data")
            if route == "chat":
                route = "clarification"
                intent = "clarification"
                confidence = min(confidence, 0.5)

        if policy.risk_level == "high" and route == "chat":
            hints.append("policy-review")
            needs_clarification = True
            route = "clarification"
            intent = "clarification"
            confidence = min(confidence, 0.4)

        return RouteDecision(
            intent=intent,
            route=route,
            urgency=urgency,
            needs_clarification=needs_clarification,
            confidence=confidence,
            policy=policy,
            hints=hints,
        )
