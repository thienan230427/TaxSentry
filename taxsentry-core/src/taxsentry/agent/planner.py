from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from taxsentry.text_normalize import normalize_for_match

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
        normalized_text = normalize_for_match(request.text)
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

        def mentions(*keywords: str) -> bool:
            return any(keyword in text or keyword in normalized_text for keyword in keywords)

        if mentions("memory", "nhớ", "remember", "nho"):
            add("memory_search", "Recall memory", query=request.text, limit=5)
        if mentions("provider", "model", "health", "endpoint"):
            add("provider_health", "Check provider")
        if mentions("report", "báo cáo", "bao cao", "log", "file"):
            add("recent_reports", "Inspect reports", limit=3)
        if mentions("job", "jobs", "state", "trạng thái job", "trang thai job"):
            add("recent_jobs", "Inspect jobs", limit=5)
        if mentions("excel", "sheet", "workbook", "parse"):
            add("parse_workbook", "Parse workbook")
        if mentions("pdf", "export", "generate pdf"):
            add("generate_pdf", "Generate PDF")
        if mentions("email", "send mail", "smtp", "gui mail", "gửi mail"):
            add("send_email", "Send email report")
        if mentions("telegram", "notify", "bot", "thong bao", "thông báo"):
            add("send_telegram", "Push Telegram alert")
        if mentions("trace", "session", "timeline", "replay"):
            add("session_trace", "Inspect trace bundle")
        if mentions("audit", "phân tích", "phan tich", "analysis", "kiểm tra", "kiem tra", "review"):
            add("run_audit", "Run audit")
        if mentions("status", "summary", "trang thai", "trạng thái"):
            add("status_summary", "Summarize runtime status")

        return plan

    @staticmethod
    def summarize_plan(plan: list[ToolPlanStep]) -> str:
        return " -> ".join(step.tool_name for step in plan)
