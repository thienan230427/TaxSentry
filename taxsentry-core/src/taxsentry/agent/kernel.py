from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from taxsentry.config import get_value, load_config, save_config, set_value, write_env_file
from taxsentry.config.paths import DOWNLOAD_DIR, EVIDENCE_CONTEXT_PATH, EXCEL_PATH, JSON_PATH, KNOWLEDGE_PATH
from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
from taxsentry.core.email_sender import TaxSentryEmailSender
from taxsentry.core.evidence_preview import load_evidence_context
from taxsentry.core.excel_parser import TaxSentryParser
from taxsentry.core.pdf_generator import TaxSentryPDFGenerator
from taxsentry.database.db_manager import TaxSentryDBManager
from taxsentry.bot.telegram_bot import send_active_report_to_director
from taxsentry.providers import ProviderConfig, ProviderError, build_client, from_settings, generate_chat, health_check, provider_label
from taxsentry.runtime.copilot_prompt import build_copilot_prompt
from taxsentry.runtime.composer import ResponseComposer
from taxsentry.runtime.policy import PolicyGate
from taxsentry.runtime.router import InteractionRouter
from taxsentry.runtime.service import TaxSentryRuntimeService
from taxsentry.runtime.session import MemoryManager, RuntimeResponse, SessionManager

from .planner import AgentPlanner, ToolPlanStep
from .request import AgentRequest
from .response import AgentTurnResult
from .state import AgentMode, AgentSurfaceState, ProviderPreset, SurfaceEvent, build_provider_presets
from .tool_registry import ToolRegistry, ToolResult


class AgentKernel:
    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        session_entry_point: str = "tui",
        session_mode: AgentMode = AgentMode.CHAT,
    ) -> None:
        self.settings = settings or load_config()
        self.policy_gate = PolicyGate()
        self.router = InteractionRouter(self.policy_gate)
        self.composer = ResponseComposer(self.policy_gate)
        self.session_manager = SessionManager()
        self.memory = MemoryManager()
        self.planner = AgentPlanner()
        self.provider = from_settings(self.settings)
        self.runtime_service = TaxSentryRuntimeService(self.settings)
        self.state = AgentSurfaceState(
            mode=session_mode,
            provider_key=self.provider.kind or "lmstudio",
        )
        self.session = self.session_manager.start_session(
            entry_point=session_entry_point,
            mode=session_mode.value,
            title=str(get_value(self.settings, "memory.session_title", "TaxSentry session")),
        )
        self.state.session_id = self.session.session_id
        self.tools = ToolRegistry()
        self._register_tools()

    def _register_tools(self) -> None:
        self.tools.register("provider_health", self._tool_provider_health)
        self.tools.register("memory_search", self._tool_memory_search)
        self.tools.register("remember_fact", self._tool_remember_fact)
        self.tools.register("run_audit", self._tool_run_audit)
        self.tools.register("status_summary", self._tool_status_summary)
        self.tools.register("recent_jobs", self._tool_recent_jobs)
        self.tools.register("recent_reports", self._tool_recent_reports)
        self.tools.register("session_trace", self._tool_session_trace)
        self.tools.register("tool_catalog", self._tool_tool_catalog)
        self.tools.register("parse_workbook", self._tool_parse_workbook)
        self.tools.register("generate_pdf", self._tool_generate_pdf)
        self.tools.register("send_email", self._tool_send_email)
        self.tools.register("send_telegram", self._tool_send_telegram)

    def available_provider_presets(self) -> list[ProviderPreset]:
        return build_provider_presets(self.settings)

    def set_mode(self, mode: AgentMode) -> None:
        if self.state.mode == mode:
            return
        self.state.mode = mode
        self.session_manager.record_event(
            session_id=self.state.session_id,
            event_type="mode_change",
            actor="surface",
            action=f"switch to {mode.value}",
            result="changed",
            payload={"mode": mode.value},
        )
        self.state.push_event(SurfaceEvent(kind="mode", title=f"Mode changed to {mode.value}", status="info"))

    def apply_provider_preset(self, preset: ProviderPreset, *, persist: bool = True) -> ProviderConfig:
        set_value(self.settings, "provider.kind", preset.kind)
        set_value(self.settings, "provider.base_url", preset.base_url)
        set_value(self.settings, "provider.model", preset.model)
        set_value(self.settings, "provider.auth_mode", preset.auth_mode)
        set_value(self.settings, "provider.api_key", preset.api_key)
        if persist:
            save_config(self.settings)
            write_env_file(self.settings)
        self.provider = from_settings(self.settings)
        self.state.provider_key = preset.key
        self.session_manager.record_event(
            session_id=self.state.session_id,
            event_type="provider_change",
            actor="surface",
            action=f"select provider {preset.key}",
            result="changed",
            payload={"provider": preset.key, "model": preset.model},
        )
        self.state.push_event(
            SurfaceEvent(
                kind="provider",
                title=f"Provider set to {preset.label}",
                detail=f"{preset.base_url} · {preset.model}",
                status="success",
            )
        )
        return self.provider

    def snapshot(self) -> dict[str, Any]:
        session_snapshot = self.session_manager.snapshot(self.state.session_id)
        memory_facts = self.memory.recall_compact("", limit=5) if self._memory_enabled() else []
        recent_reports = self._recent_reports(limit=5)
        evidence_context = load_evidence_context(EVIDENCE_CONTEXT_PATH)
        return {
            "settings": self.settings,
            "provider": self.provider,
            "provider_label": provider_label(self.provider),
            "provider_health": self._provider_health(),
            "session": session_snapshot,
            "memory_facts": memory_facts,
            "recent_reports": recent_reports,
            "recent_jobs": self._recent_jobs(limit=5),
            "recent_sessions": self._recent_sessions(limit=5),
            "evidence_context": evidence_context,
            "state": self.state,
            "available_tools": self.tools.available(),
            "recent_events": list(self.state.recent_events),
            "active_plan": self.state.last_plan,
            "toolchain": list(self.state.last_toolchain),
        }

    def _config_bool(self, path: str, default: bool) -> bool:
        value = get_value(self.settings, path, default)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _memory_enabled(self) -> bool:
        return self._config_bool("agent.memory_enabled", True)

    def _llm_planner_enabled(self) -> bool:
        return self._config_bool("agent.llm_planner_enabled", False)

    def handle(
        self,
        user_text: str,
        *,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> AgentTurnResult:
        text = (user_text or "").strip()
        sanitized = self.policy_gate.redact(text)
        context = {
            "missing_data": not bool(text),
            "mode": self.state.mode.value,
        }
        decision = self.router.route(sanitized, context=context)
        self.state.last_user_input = text
        self.session_manager.record_message(self.state.session_id, "user", sanitized)

        if not decision.policy.allowed:
            response = self.composer.compose(
                "Em đã che thông tin nhạy cảm trong câu hỏi của Sếp rồi. Nếu cần, hãy gửi lại phần không chứa token/password nhé.",
                route="clarification",
                confidence=0.5,
                session_id=self.state.session_id,
                metadata={"mode": self.state.mode.value, "policy_flags": decision.policy.flags},
            )
            self._finish_turn(response, route="clarification")
            return AgentTurnResult(response=response, route="clarification", mode=self.state.mode, hints=decision.hints)

        if text.startswith("/"):
            response = self._handle_slash_command(text)
            self._finish_turn(response, route=response.route)
            return AgentTurnResult(response=response, route=response.route, mode=self.state.mode)

        if decision.route == "clarification":
            response = self.composer.compose(
                "Sếp cho em thêm chút ngữ cảnh nhé. Em chưa đủ dữ liệu để đi tiếp một cách chắc chắn.",
                route="clarification",
                confidence=0.55,
                session_id=self.state.session_id,
                metadata={"mode": self.state.mode.value, "hints": decision.hints},
            )
            self._finish_turn(response, route="clarification")
            return AgentTurnResult(response=response, route="clarification", mode=self.state.mode, hints=decision.hints)

        request = AgentRequest(
            text=text,
            sanitized_text=sanitized,
            route=decision.route,
            mode=self.state.mode,
            session_id=self.state.session_id,
            context=context,
            hints=list(decision.hints),
        )
        planned_steps = self._build_tool_plan(request, decision.route)
        if not planned_steps:
            self.state.last_plan = ""
            self.state.last_toolchain = []
            self.state.last_progress = ""
        tool_results = self._execute_tool_plan(
            planned_steps,
            source_text=text,
            progress_callback=progress_callback,
        ) if planned_steps else []

        if decision.route == "analysis" or self.state.mode == AgentMode.ANALYZE:
            response_text = self._compose_analysis_reply(text, tool_results)
            response = self.composer.compose(
                response_text,
                route="analysis",
                confidence=0.88 if any(result.ok for result in tool_results) else 0.45,
                session_id=self.state.session_id,
                metadata={
                    "mode": self.state.mode.value,
                    "tool_names": [result.name for result in tool_results],
                    "tool_results": [result.metadata for result in tool_results],
                },
            )
            primary_tool = tool_results[-1] if tool_results else None
            self._finish_turn(response, route="analysis", tool=primary_tool)
            return AgentTurnResult(response=response, route="analysis", mode=self.state.mode, tool=primary_tool, hints=decision.hints)

        if decision.route == "operation" or self.state.mode in {AgentMode.EXECUTE, AgentMode.REVIEW, AgentMode.SETUP}:
            response_text = self._compose_operation_reply(text, tool_results)
            response = self.composer.compose(
                response_text,
                route="operation",
                confidence=0.82 if any(result.ok for result in tool_results) else 0.6,
                session_id=self.state.session_id,
                metadata={
                    "mode": self.state.mode.value,
                    "tool_names": [result.name for result in tool_results],
                },
            )
            primary_tool = tool_results[-1] if tool_results else None
            self._finish_turn(response, route="operation", tool=primary_tool)
            return AgentTurnResult(response=response, route="operation", mode=self.state.mode, tool=primary_tool, hints=decision.hints)

        response_text = self._chat_reply(text, tool_results=tool_results)
        response = self.composer.compose(
            response_text,
            route="chat",
            confidence=decision.confidence,
            session_id=self.state.session_id,
            metadata={"mode": self.state.mode.value, "hints": decision.hints, "tool_names": [result.name for result in tool_results]},
        )
        primary_tool = tool_results[-1] if tool_results else None
        self._finish_turn(response, route="chat", tool=primary_tool)
        return AgentTurnResult(response=response, route="chat", mode=self.state.mode, tool=primary_tool, hints=decision.hints)

    def _build_tool_plan(self, request: AgentRequest, route: str) -> list[ToolPlanStep]:
        effective_request = request
        if request.route != route:
            effective_request = AgentRequest(
                text=request.text,
                sanitized_text=request.sanitized_text,
                route=route,
                mode=request.mode,
                session_id=request.session_id,
                context=request.context,
                hints=request.hints,
            )
        rule_plan = self.planner.build_tool_plan(effective_request, self.tools.available())
        if not self._llm_planner_enabled():
            return rule_plan
        return self._merge_llm_plan(effective_request, rule_plan)

    def _merge_llm_plan(self, request: AgentRequest, rule_plan: list[ToolPlanStep]) -> list[ToolPlanStep]:
        available_tools = self.tools.available()
        allowed_tools = set(available_tools)
        if not allowed_tools:
            return rule_plan

        prompt = (
            "You are a tool planner for TaxSentry. Return only JSON in this shape: "
            '{"tools":["tool_name"]}. '
            "Choose zero to four tools from the allowlist. Do not invent tool names.\n"
            f"Allowlist: {', '.join(available_tools)}\n"
            f"Route: {request.route}\n"
            f"Mode: {request.mode.value}\n"
            f"User request: {request.sanitized_text[:1000]}"
        )
        try:
            raw = generate_chat(
                self.provider,
                [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            suggested = self._parse_llm_tool_suggestions(raw, allowed_tools)
        except Exception as exc:
            self.state.push_event(
                SurfaceEvent(kind="planner", title="LLM planner fallback", detail=str(exc)[:160], status="warning")
            )
            return rule_plan

        plan = list(rule_plan)
        existing = {step.tool_name for step in plan}
        for tool_name in suggested:
            if tool_name in existing:
                continue
            plan.append(ToolPlanStep(tool_name=tool_name, title=f"LLM suggested {tool_name}"))
            existing.add(tool_name)
        return plan

    @staticmethod
    def _parse_llm_tool_suggestions(raw: str, allowed_tools: set[str]) -> list[str]:
        payload = (raw or "").strip()
        if not payload:
            return []
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            parsed = json.loads(payload[start : end + 1])
        except json.JSONDecodeError:
            return []
        tools = parsed.get("tools", [])
        if not isinstance(tools, list):
            return []
        suggestions: list[str] = []
        for tool_name in tools:
            if not isinstance(tool_name, str):
                continue
            value = tool_name.strip()
            if value in allowed_tools and value not in suggestions:
                suggestions.append(value)
            if len(suggestions) >= 4:
                break
        return suggestions

    def _execute_tool_plan(
        self,
        plan: list[ToolPlanStep],
        *,
        source_text: str,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> list[ToolResult]:
        if not plan:
            return []

        plan_label = " -> ".join(step.tool_name for step in plan)
        self.state.last_plan = plan_label
        self.state.last_toolchain = [step.tool_name for step in plan]
        self.state.last_progress = f"0/{len(plan)}"
        self.state.push_event(
            SurfaceEvent(
                kind="plan",
                title=f"Plan: {plan_label}",
                detail=source_text[:160],
                status="info",
            )
        )
        self.session_manager.record_event(
            session_id=self.state.session_id,
            event_type="plan_start",
            actor="kernel",
            action="start tool plan",
            result="running",
            payload={"plan": plan_label, "steps": [step.title for step in plan], "source_text": source_text},
        )
        if progress_callback is not None:
            progress_callback(
                "plan_start",
                {
                    "plan": plan_label,
                    "steps": [step.title for step in plan],
                    "progress": self.state.last_progress,
                },
            )

        results: list[ToolResult] = []
        for index, step in enumerate(plan, start=1):
            self.session_manager.record_event(
                session_id=self.state.session_id,
                event_type="plan_step",
                actor="kernel",
                action=f"{index}. {step.tool_name}",
                result="running",
                payload={"step": step.title, "kwargs": step.kwargs, "plan": plan_label},
            )
            result = self.tools.run(step.tool_name, **step.kwargs)
            self._record_tool(step.tool_name, result, payload={"step": step.title, "step_index": index, "plan": plan_label})
            results.append(result)
            self.state.last_progress = f"{index}/{len(plan)}"
            if progress_callback is not None:
                progress_callback(
                    "plan_step",
                    {
                        "step_index": index,
                        "step_title": step.title,
                        "tool_name": step.tool_name,
                        "progress": self.state.last_progress,
                        "tool_ok": result.ok,
                    },
                )

        self.session_manager.record_event(
            session_id=self.state.session_id,
            event_type="plan_complete",
            actor="kernel",
            action="complete tool plan",
            result="ok" if any(result.ok for result in results) else "fail",
            payload={
                "plan": plan_label,
                "success": any(result.ok for result in results),
                "tool_names": [result.name for result in results],
            },
        )
        self.state.push_event(
            SurfaceEvent(
                kind="plan",
                title=f"Plan completed: {plan_label}",
                detail=", ".join(result.name for result in results),
                status="success" if any(result.ok for result in results) else "error",
            )
        )
        self.state.last_progress = f"{len(plan)}/{len(plan)}"
        if progress_callback is not None:
            progress_callback(
                "plan_complete",
                {
                    "plan": plan_label,
                    "progress": self.state.last_progress,
                    "success": any(result.ok for result in results),
                },
            )
        return results

    def _compose_analysis_reply(self, user_text: str, tool_results: list[ToolResult]) -> str:
        lines = [
            "Em đã chạy một chuỗi phân tích cho Sếp.",
            f"- Câu hỏi: {user_text}",
        ]
        if self.state.last_plan:
            lines.append(f"- Plan: {self.state.last_plan}")
        for result in tool_results:
            status = "OK" if result.ok else "FAIL"
            lines.append(f"- Tool {result.name}: {status}")
            if result.output:
                lines.append(f"  {result.output}")
        lines.append("Nếu Sếp muốn, em có thể chuyển sang /mode execute để đi tiếp theo luồng thao tác.")
        return "\n".join(lines)

    def _handle_slash_command(self, text: str) -> RuntimeResponse:
        command = text.lstrip("/").strip()
        if command in {"help", "?"}:
            return self.composer.compose(
                "Commands: /help, /status, /memory, /remember <text>, /mode <chat|analysis|execute|review|setup>, /provider, /audit, /dashboard, /tools, /trace, /jobs, /replay [session_id], /exit",
                route="chat",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "help"},
            )
        if command == "status":
            tool_result = self.tools.run("status_summary")
            self._record_tool("status_summary", tool_result)
            return self.composer.compose(
                tool_result.output,
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "status", "tool_ok": tool_result.ok},
            )
        if command == "memory":
            if not self._memory_enabled():
                return self.composer.compose(
                    "Memory đang tắt trong cấu hình hiện tại.",
                    route="chat",
                    confidence=1.0,
                    session_id=self.state.session_id,
                    metadata={"command": "memory", "facts": [], "memory_enabled": False},
                )
            facts = self.memory.recall_compact(self.state.last_user_input or "", limit=8)
            text_out = self._format_memory_facts(facts)
            return self.composer.compose(
                text_out,
                route="chat",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "memory", "facts": facts},
            )
        if command.startswith("remember "):
            fact = command[len("remember "):].strip()
            tool_result = self.tools.run("remember_fact", text=fact)
            self._record_tool("remember_fact", tool_result, payload={"fact": fact})
            return self.composer.compose(
                tool_result.output,
                route="chat",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "remember", "tool_ok": tool_result.ok},
            )
        if command.startswith("mode "):
            mode_name = command[len("mode "):].strip().lower()
            mode = self._parse_mode(mode_name)
            self.set_mode(mode)
            return self.composer.compose(
                f"Mode switched to {mode.value}.",
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "mode", "mode": mode.value},
            )
        if command == "provider":
            presets = self.available_provider_presets()
            lines = ["Provider presets:"]
            for index, preset in enumerate(presets, start=1):
                status = "active" if preset.key == self.state.provider_key else ("available" if preset.available else "unavailable")
                lines.append(f"{index}. {preset.label} [{status}] - {preset.description}")
            return self.composer.compose(
                "\n".join(lines),
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "provider"},
            )
        if command == "audit":
            results = self._execute_tool_plan([ToolPlanStep(tool_name="provider_health", title="Preflight provider health"), ToolPlanStep(tool_name="run_audit", title="Run audit")], source_text=text)
            tool_result = results[-1] if results else self.tools.run("run_audit")
            return self.composer.compose(
                tool_result.output,
                route="analysis",
                confidence=0.9 if tool_result.ok else 0.4,
                session_id=self.state.session_id,
                metadata={"command": "audit", "tool_ok": tool_result.ok},
            )
        if command == "tools":
            tool_result = self.tools.run("tool_catalog")
            self._record_tool("tool_catalog", tool_result)
            return self.composer.compose(
                tool_result.output,
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "tools", "tool_ok": tool_result.ok},
            )
        if command == "jobs":
            tool_result = self.tools.run("recent_jobs")
            self._record_tool("recent_jobs", tool_result)
            return self.composer.compose(
                tool_result.output,
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "jobs", "tool_ok": tool_result.ok},
            )
        if command == "trace":
            tool_result = self.tools.run("session_trace")
            self._record_tool("session_trace", tool_result)
            return self.composer.compose(
                tool_result.output,
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "trace", "tool_ok": tool_result.ok},
            )
        if command.startswith("replay"):
            parts = command.split(" ", 1)
            target_session = parts[1].strip() if len(parts) > 1 and parts[1].strip() else self.state.session_id
            replay_text = self.runtime_service.replay_session(target_session)
            if not replay_text:
                replay_text = "No session trace available."
            return self.composer.compose(
                replay_text,
                route="operation",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "replay", "target_session": target_session},
            )
        if command == "exit":
            return self.composer.compose(
                "Goodbye ✨",
                route="chat",
                confidence=1.0,
                session_id=self.state.session_id,
                metadata={"command": "exit"},
            )
        return self.composer.compose(
            f"Unknown command: /{command}. Type /help for the available shortcuts.",
            route="clarification",
            confidence=0.75,
            session_id=self.state.session_id,
            metadata={"command": command},
        )

    def _chat_reply(self, user_text: str, *, tool_results: list[ToolResult] | None = None) -> str:
        memory_context = self.memory.recall_compact(user_text, limit=5) if self._memory_enabled() else []
        evidence_context = load_evidence_context(EVIDENCE_CONTEXT_PATH)
        financial_context = self._recent_reports(limit=3)
        tool_context = [
            {
                "name": result.name,
                "ok": result.ok,
                "output": result.output,
                "metadata": result.metadata,
            }
            for result in (tool_results or [])
        ]
        tax_rules_snippet = ""
        if KNOWLEDGE_PATH.exists():
            try:
                tax_rules_snippet = KNOWLEDGE_PATH.read_text(encoding="utf-8")[:3000]
            except Exception:
                tax_rules_snippet = ""

        financial_json = {}
        if JSON_PATH.exists():
            try:
                financial_json = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            except Exception:
                financial_json = {}

        prompt = build_copilot_prompt(
            user_query=user_text,
            director_name=str(get_value(self.settings, "agent.name", "TaxSentry")),
            financial_context=financial_context,
            tax_rules_snippet=tax_rules_snippet,
            evidence_context=evidence_context,
            financial_json=financial_json,
            memory_context=memory_context,
            tool_context=tool_context,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are {get_value(self.settings, 'agent.name', 'TaxSentry')}, a local-first AI agent.\n"
                    f"Persona: {get_value(self.settings, 'agent.persona', 'warm, precise, and practical')}.\n"
                    f"Respond in {get_value(self.settings, 'agent.language', 'vi')}."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        try:
            return generate_chat(self.provider, messages, temperature=0.3)
        except ProviderError as exc:
            return f"Provider error: {exc}"
        except Exception as exc:
            return f"Agent error: {exc}"

    def _compose_operation_reply(self, user_text: str, tool_results: list[ToolResult]) -> str:
        lines = [
            "Em đang ở chế độ hành động cho Sếp.",
            f"- Câu hỏi: {user_text}",
        ]
        if self.state.last_plan:
            lines.append(f"- Plan: {self.state.last_plan}")
        if not tool_results:
            lines.append("- Chưa có tool nào được kích hoạt.")
        for result in tool_results:
            lines.append(f"- Tool: {result.name} ({'OK' if result.ok else 'FAIL'})")
            if result.output:
                lines.append(f"  {result.output}")
        lines.append("Nếu Sếp muốn, em có thể chuyển sang /mode analysis hoặc /mode chat ngay.")
        return "\n".join(lines)

    def _recent_reports(self, limit: int = 5) -> list[dict[str, Any]]:
        try:
            db = TaxSentryDBManager()
            if db.connect():
                try:
                    return db.get_recent_logs(limit=limit)
                finally:
                    db.close()
        except Exception:
            return []
        return []

    def _recent_jobs(self, limit: int = 5) -> list[dict[str, Any]]:
        try:
            return [
                {
                    "job_id": job.job_id,
                    "session_id": job.session_id,
                    "job_type": job.job_type,
                    "state": job.state,
                    "source_file": job.source_file,
                    "source_path": job.source_path,
                    "retry_count": job.retry_count,
                    "error_message": job.error_message,
                    "metadata": job.metadata,
                }
                for job in self.runtime_service.recent_jobs(limit=limit)
            ]
        except Exception:
            return []

    def _recent_sessions(self, limit: int = 5) -> list[dict[str, Any]]:
        try:
            return self.runtime_service.recent_sessions(limit=limit)
        except Exception:
            return []

    def _provider_health(self) -> tuple[bool, str]:
        return health_check(self.provider)

    def _tool_provider_health(self) -> ToolResult:
        ok, message = self._provider_health()
        return ToolResult(
            name="provider_health",
            ok=ok,
            output=f"Provider check: {'OK' if ok else 'FAIL'} — {message}",
            metadata={"provider": provider_label(self.provider)},
        )

    def _tool_memory_search(self, query: str = "", limit: int = 5) -> ToolResult:
        if not self._memory_enabled():
            return ToolResult(
                name="memory_search",
                ok=True,
                output="Memory is disabled.",
                metadata={"items": [], "memory_enabled": False},
            )
        items = self.memory.recall_compact(query, limit=limit)
        return ToolResult(
            name="memory_search",
            ok=True,
            output=self._format_memory_facts(items),
            metadata={"items": items},
        )

    def _tool_remember_fact(self, text: str = "") -> ToolResult:
        if not self._memory_enabled():
            return ToolResult(
                name="remember_fact",
                ok=False,
                output="Memory is disabled.",
                metadata={"memory_enabled": False},
            )
        fact = text.strip()
        if not fact:
            return ToolResult(name="remember_fact", ok=False, output="No fact provided.")
        memory_id = self.memory.remember(
            memory_type="preference",
            subject="user",
            summary=fact,
            payload={"source": "tui"},
            tags=["tui", "preference"],
            confidence=0.85,
            importance=0.75,
            source_ref="tui",
        )
        return ToolResult(name="remember_fact", ok=True, output=f"Saved memory: {fact}", metadata={"memory_id": memory_id})

    def _tool_run_audit(self) -> ToolResult:
        try:
            engine = TaxSentryAnalysisEngine()
            report = engine.run_audit()
        except Exception as exc:
            return ToolResult(name="run_audit", ok=False, output=str(exc))
        ok = bool(report and not report.startswith("❌"))
        return ToolResult(name="run_audit", ok=ok, output=report)

    def _tool_status_summary(self) -> ToolResult:
        ok, message = self._provider_health()
        summary = [
            f"Agent: {get_value(self.settings, 'agent.name', 'TaxSentry')}",
            f"Provider: {provider_label(self.provider)}",
            f"Model: {self.provider.model}",
            f"Endpoint: {self.provider.base_url}",
            f"Memory: {'on' if get_value(self.settings, 'agent.memory_enabled', True) else 'off'}",
            f"Session: {self.state.session_id}",
            f"Jobs: {len(self._recent_jobs(limit=3))}",
            f"Provider health: {'OK' if ok else 'FAIL'} — {message}",
        ]
        return ToolResult(name="status_summary", ok=ok, output="\n".join(summary), metadata={"provider_health": message})

    def _tool_recent_jobs(self, limit: int = 5) -> ToolResult:
        jobs = self._recent_jobs(limit=limit)
        if not jobs:
            return ToolResult(name="recent_jobs", ok=True, output="No recent jobs yet.", metadata={"jobs": []})

        lines = ["Recent jobs:"]
        for job in jobs:
            lines.append(
                f"- {job.get('job_id', 'n/a')} | {job.get('job_type', 'n/a')} | {job.get('state', 'n/a')} | "
                f"{job.get('source_file', 'n/a')} | retry={job.get('retry_count', 0)}"
            )
        return ToolResult(name="recent_jobs", ok=True, output="\n".join(lines), metadata={"jobs": jobs})

    def _tool_recent_reports(self, limit: int = 5) -> ToolResult:
        reports = self._recent_reports(limit=limit)
        if not reports:
            return ToolResult(name="recent_reports", ok=True, output="No recent reports yet.", metadata={"reports": []})

        lines = ["Recent reports:"]
        for report in reports:
            lines.append(
                f"- {report.get('file_name', 'n/a')} | {report.get('tax_risk_status', 'n/a')} | {report.get('sender', 'n/a')}"
            )
        return ToolResult(name="recent_reports", ok=True, output="\n".join(lines), metadata={"reports": reports})

    def _tool_session_trace(self) -> ToolResult:
        bundle = self.session_manager.build_replay_bundle(
            self.state.session_id,
            db_path=str(get_value(self.settings, "paths.memory_db", "")) or None,
            evidence_path=EVIDENCE_CONTEXT_PATH,
        )
        if bundle is None:
            return ToolResult(name="session_trace", ok=False, output="No session trace available.", metadata={})

        trace = bundle.trace
        lines = [
            f"Session: {bundle.session.session_id if bundle.session else self.state.session_id}",
            f"Entry point: {bundle.session.entry_point if bundle.session else 'unknown'}",
            f"Mode: {bundle.session.mode if bundle.session else 'unknown'}",
            f"Events: {len(bundle.events)}",
            f"Reports: {len(bundle.reports)}",
        ]
        if trace is not None:
            lines.extend(
                [
                    f"Trace ID: {trace.trace_id or 'n/a'}",
                    f"Event ID: {trace.event_id or 'n/a'}",
                    f"Source: {trace.source_file or 'n/a'}",
                ]
            )
        return ToolResult(name="session_trace", ok=True, output="\n".join(lines), metadata={"trace": trace, "events": bundle.events, "reports": bundle.reports})

    def _tool_tool_catalog(self) -> ToolResult:
        tools = self.tools.available()
        lines = ["Available tools:"]
        for name in tools:
            lines.append(f"- {name}")
        return ToolResult(name="tool_catalog", ok=True, output="\n".join(lines), metadata={"tools": tools})

    def _tool_parse_workbook(self, path: str = "") -> ToolResult:
        workbook_path = Path(path or EXCEL_PATH)
        if not workbook_path.exists():
            return ToolResult(name="parse_workbook", ok=False, output=f"Workbook not found: {workbook_path}")

        try:
            parser = TaxSentryParser(str(workbook_path))
            parser.load()
            analysis = parser.parse_workbook()
            json_path = Path(JSON_PATH)
            parser.export_json(str(json_path))
            logged = parser.log_to_database(trace_context={"session_id": self.state.session_id})
            summary = f"Parsed workbook: {workbook_path.name}\nJSON: {json_path}\nDatabase: {'OK' if logged else 'FAIL'}"
            return ToolResult(
                name="parse_workbook",
                ok=True,
                output=summary,
                metadata={"analysis": analysis, "json_path": str(json_path), "workbook_path": str(workbook_path)},
            )
        except Exception as exc:
            return ToolResult(name="parse_workbook", ok=False, output=str(exc), metadata={"workbook_path": str(workbook_path)})

    def _tool_generate_pdf(self, markdown_content: str = "", output_path: str = "", trace_context: dict[str, Any] | None = None) -> ToolResult:
        try:
            generator = TaxSentryPDFGenerator()
            pdf_path = Path(output_path or (DOWNLOAD_DIR / "taxsentry_report.pdf"))
            markdown = markdown_content or self.state.last_response or "# TaxSentry Report\n\nNo markdown content provided."
            ok = generator.generate(markdown, str(pdf_path), trace_context=trace_context)
            return ToolResult(
                name="generate_pdf",
                ok=ok,
                output=f"PDF {'generated' if ok else 'failed'}: {pdf_path}",
                metadata={"pdf_path": str(pdf_path), "trace_context": trace_context or {}},
            )
        except Exception as exc:
            return ToolResult(name="generate_pdf", ok=False, output=str(exc))

    def _tool_send_email(self, pdf_path: str = "", summary_text: str = "", trace_context: dict[str, Any] | None = None) -> ToolResult:
        try:
            sender = TaxSentryEmailSender()
            target_pdf = Path(pdf_path or (DOWNLOAD_DIR / "taxsentry_report.pdf"))
            if not target_pdf.exists():
                return ToolResult(name="send_email", ok=False, output=f"PDF not found: {target_pdf}")
            ok = sender.send_report(str(target_pdf), summary_text or self.state.last_response, trace_context=trace_context)
            return ToolResult(
                name="send_email",
                ok=ok,
                output=f"Email {'sent' if ok else 'failed'}: {sender.director_email}",
                metadata={"pdf_path": str(target_pdf), "trace_context": trace_context or {}},
            )
        except Exception as exc:
            return ToolResult(name="send_email", ok=False, output=str(exc))

    def _tool_send_telegram(self, pdf_path: str = "", summary_text: str = "", trace_context: dict[str, Any] | None = None) -> ToolResult:
        try:
            target_pdf = Path(pdf_path or (DOWNLOAD_DIR / "taxsentry_report.pdf"))
            if not target_pdf.exists():
                return ToolResult(name="send_telegram", ok=False, output=f"PDF not found: {target_pdf}")
            import asyncio

            ok = asyncio.run(
                send_active_report_to_director(
                    str(target_pdf),
                    summary_text or self.state.last_response,
                    trace_context=trace_context,
                )
            )
            return ToolResult(
                name="send_telegram",
                ok=ok,
                output=f"Telegram {'sent' if ok else 'failed'}",
                metadata={"pdf_path": str(target_pdf), "trace_context": trace_context or {}},
            )
        except Exception as exc:
            return ToolResult(name="send_telegram", ok=False, output=str(exc))

    def _record_tool(self, tool_name: str, result: ToolResult, *, payload: dict[str, Any] | None = None) -> None:
        self.session_manager.record_tool_event(
            self.state.session_id,
            tool_name=tool_name,
            action=f"run {tool_name}",
            result="ok" if result.ok else "fail",
            payload={**(payload or {}), "output": result.output, "metadata": result.metadata},
            actor="kernel",
        )
        self.state.last_tool_name = tool_name
        self.state.last_tool_status = "ok" if result.ok else "fail"
        self.state.last_error = "" if result.ok else result.output
        self.state.push_event(
            SurfaceEvent(
                kind="tool",
                title=f"Tool {tool_name}",
                detail=result.output[:120],
                status="success" if result.ok else "error",
            )
        )

    def _finish_turn(self, response: RuntimeResponse, *, route: str, tool: ToolResult | None = None) -> None:
        self.session_manager.record_message(self.state.session_id, "assistant", response.text)
        self.state.last_route = route
        self.state.last_response = response.text
        if tool is not None:
            self.state.last_tool_name = tool.name
            self.state.last_tool_status = "ok" if tool.ok else "fail"
            self.state.last_error = "" if tool.ok else tool.output
        self.state.push_event(
            SurfaceEvent(
                kind="response",
                title=f"{route} response",
                detail=response.text[:120],
                status="success",
            )
        )

    @staticmethod
    def _format_memory_facts(facts: list[dict[str, Any]]) -> str:
        if not facts:
            return "No memory facts yet."
        lines = ["Recent memory facts:"]
        for item in facts:
            lines.append(f"- {item.get('summary') or item.get('text') or ''}")
        return "\n".join(lines)

    @staticmethod
    def _parse_mode(value: str) -> AgentMode:
        normalized = (value or "").strip().lower()
        for mode in AgentMode:
            if mode.value == normalized:
                return mode
        return AgentMode.CHAT
