from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .request import AgentRequest
from .state import AgentMode


@dataclass(frozen=True)
class ToolPlanStep:
    tool_name: str
    title: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class AgentPlanner:
    def build_tool_plan(self, request: AgentRequest, available_tools: Sequence[str] | None = None) -> list[ToolPlanStep]:
        text = (request.text or "").lower()
        route = request.route
        plan: list[ToolPlanStep] = []
        toolset = set(available_tools or [])

        def add(tool_name: str, title: str, **kwargs: Any) -> None:
            if toolset and tool_name not in toolset:
                return
            if any(step.tool_name == tool_name for step in plan):
                return
            plan.append(ToolPlanStep(tool_name=tool_name, title=title, kwargs=kwargs))

        if route == "analysis" or request.mode == AgentMode.ANALYZE:
            add("provider_health", "Preflight provider health")
            add("memory_search", "Pull relevant memory", query=request.text, limit=5)
            add("run_audit", "Run tax audit")
            return plan

        if route == "operation" or request.mode in {AgentMode.EXECUTE, AgentMode.REVIEW, AgentMode.SETUP}:
            add("provider_health", "Check provider readiness")
            add("status_summary", "Summarize runtime status")
            add("recent_reports", "Inspect recent reports", limit=3)
            add("session_trace", "Inspect current trace bundle")
            return plan

        if any(keyword in text for keyword in ("memory", "nhớ", "remember")):
            add("memory_search", "Recall memory", query=request.text, limit=5)
        if any(keyword in text for keyword in ("provider", "model", "health", "endpoint")):
            add("provider_health", "Check provider")
        if any(keyword in text for keyword in ("report", "báo cáo", "log", "file")):
            add("recent_reports", "Inspect reports", limit=3)
        if any(keyword in text for keyword in ("job", "jobs", "state", "trạng thái job")):
            add("recent_jobs", "Inspect jobs", limit=5)
        if any(keyword in text for keyword in ("excel", "sheet", "workbook", "parse")):
            add("parse_workbook", "Parse workbook")
        if any(keyword in text for keyword in ("pdf", "export", "generate pdf")):
            add("generate_pdf", "Generate PDF")
        if any(keyword in text for keyword in ("email", "send mail", "smtp")):
            add("send_email", "Send email report")
        if any(keyword in text for keyword in ("telegram", "notify", "bot")):
            add("send_telegram", "Push Telegram alert")
        if any(keyword in text for keyword in ("trace", "session", "timeline", "replay")):
            add("session_trace", "Inspect trace bundle")
        if any(keyword in text for keyword in ("audit", "phân tích", "analysis", "kiểm tra", "review")):
            add("run_audit", "Run audit")
        if any(keyword in text for keyword in ("status", "summary")):
            add("status_summary", "Summarize runtime status")

        return plan

    @staticmethod
    def summarize_plan(plan: list[ToolPlanStep]) -> str:
        return " -> ".join(step.tool_name for step in plan)
