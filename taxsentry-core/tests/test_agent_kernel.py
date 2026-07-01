from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class FakeSession:
    session_id: str
    entry_point: str
    user_identity: str | None
    mode: str
    started_at: str
    title: str | None = None
    summary: str | None = None
    outcome: str | None = None
    ended_at: str | None = None
    messages: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    final_response: str | None = None


class FakeSessionManager:
    def __init__(self, *args, **kwargs):
        self.events: list[tuple[str, dict]] = []
        self._session: FakeSession | None = None

    def start_session(self, *, entry_point: str, mode: str, user_identity: str | None = None, title: str | None = None):
        self._session = FakeSession(
            session_id="sess-1",
            entry_point=entry_point,
            user_identity=user_identity,
            mode=mode,
            started_at="2026-07-01T00:00:00+00:00",
            title=title,
        )
        return self._session

    def record_event(self, **kwargs):
        self.events.append(("event", kwargs))
        return "event-1"

    def record_message(self, session_id: str, role: str, content: str, *, tool_calls=None):
        self.events.append(("message", {"session_id": session_id, "role": role, "content": content, "tool_calls": tool_calls or []}))

    def record_tool_event(self, session_id: str, *, tool_name: str, action: str, result: str | None = None, payload=None, latency_ms=None, error_message=None, actor: str = "tool_dispatcher"):
        self.events.append(("tool", {"session_id": session_id, "tool_name": tool_name, "action": action, "result": result, "payload": payload or {}, "actor": actor}))
        return "tool-event-1"

    def snapshot(self, session_id: str):
        return self._session


class FakeMemoryManager:
    def __init__(self, *args, **kwargs):
        self.saved: list[str] = []

    def recall_compact(self, query: str, *, scope: str | None = None, limit: int = 5):
        return [{"summary": "memo 1", "text": "memo 1"}]

    def remember(self, **kwargs):
        self.saved.append(kwargs.get("summary", ""))
        return "memory-1"


def _build_kernel(monkeypatch):
    from taxsentry.agent import kernel as kernel_module

    monkeypatch.setattr(kernel_module, "SessionManager", FakeSessionManager)
    monkeypatch.setattr(kernel_module, "MemoryManager", FakeMemoryManager)
    monkeypatch.setattr(kernel_module, "health_check", lambda provider: (True, "ok"))
    monkeypatch.setattr(kernel_module, "generate_chat", lambda provider, messages, temperature=0.3: "stubbed reply")

    class FakeAnalysisEngine:
        def run_audit(self):
            return "# audit ok"

    monkeypatch.setattr(kernel_module, "TaxSentryAnalysisEngine", FakeAnalysisEngine)

    settings = {
        "agent": {
            "name": "TaxSentry",
            "persona": "warm, precise, and practical",
            "language": "vi",
            "memory_enabled": True,
        },
        "provider": {
            "kind": "lmstudio",
            "base_url": "http://localhost:1234/v1",
            "model": "google/gemma-4-e4b",
            "api_key": "",
            "auth_mode": "lmstudio",
        },
        "memory": {
            "max_facts": 50,
            "max_turns": 12,
            "session_title": "TaxSentry session",
        },
    }
    return kernel_module.AgentKernel(settings=settings, session_entry_point="test", session_mode=kernel_module.AgentMode.CHAT)


def test_build_provider_presets_marks_codex_oauth_available(monkeypatch, tmp_path):
    from taxsentry.agent.state import build_provider_presets, Path as StatePath

    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "auth.json").write_text('{"tokens": {"access_token": "token"}}', encoding="utf-8")
    monkeypatch.setattr(StatePath, "home", lambda: tmp_path)

    presets = build_provider_presets({"provider": {"kind": "custom", "base_url": "http://localhost:1234/v1", "model": "gpt-4.1-mini", "api_key": "", "auth_mode": "api_key"}})

    assert [preset.key for preset in presets] == ["lmstudio", "codex_oauth", "custom"]
    assert presets[1].available is True
    assert presets[0].label == "LM Studio"


def test_agent_planner_builds_route_specific_plans():
    from taxsentry.agent import AgentMode, AgentPlanner, AgentRequest

    planner = AgentPlanner()
    analysis_request = AgentRequest(
        text="Hãy phân tích báo cáo và kiểm tra provider",
        sanitized_text="Hãy phân tích báo cáo và kiểm tra provider",
        route="analysis",
        mode=AgentMode.CHAT,
        session_id="sess-1",
    )
    analysis_plan = planner.build_tool_plan(analysis_request, ["provider_health", "memory_search", "run_audit"])
    assert [step.tool_name for step in analysis_plan] == ["provider_health", "memory_search", "run_audit"]

    operation_request = AgentRequest(
        text="Cho em xem trạng thái hệ thống",
        sanitized_text="Cho em xem trạng thái hệ thống",
        route="operation",
        mode=AgentMode.EXECUTE,
        session_id="sess-1",
    )
    operation_plan = planner.build_tool_plan(operation_request, ["provider_health", "status_summary", "recent_reports", "session_trace"])
    assert [step.tool_name for step in operation_plan] == ["provider_health", "status_summary", "recent_reports", "session_trace"]


def test_agent_planner_includes_document_tools():
    from taxsentry.agent import AgentMode, AgentPlanner, AgentRequest

    planner = AgentPlanner()
    request = AgentRequest(
        text="Hãy parse Excel, tạo PDF rồi gửi email và Telegram",
        sanitized_text="Hãy parse Excel, tạo PDF rồi gửi email và Telegram",
        route="chat",
        mode=AgentMode.CHAT,
        session_id="sess-doc",
    )
    plan = planner.build_tool_plan(
        request,
        ["parse_workbook", "generate_pdf", "send_email", "send_telegram"],
    )
    assert [step.tool_name for step in plan] == ["parse_workbook", "generate_pdf", "send_email", "send_telegram"]


def test_agent_kernel_routes_status_mode_and_provider_switch(monkeypatch):
    from taxsentry.agent import kernel as kernel_module
    from taxsentry.agent.state import AgentMode

    kernel = _build_kernel(monkeypatch)

    status = kernel.handle("/status")
    assert status.route == "operation"
    assert "Provider health: OK" in status.response.text
    assert kernel.state.last_tool_name == "status_summary"

    kernel.handle("/mode analysis")
    assert kernel.state.mode == AgentMode.ANALYZE

    preset = kernel.available_provider_presets()[2]
    updated = kernel.apply_provider_preset(preset, persist=False)
    assert updated.auth_mode == "api_key"
    assert kernel.settings["provider"]["auth_mode"] == "api_key"
    assert kernel.settings["provider"]["api_key"] == ""


def test_agent_kernel_builds_tool_plan_and_timeline(monkeypatch):
    kernel = _build_kernel(monkeypatch)

    result = kernel.handle("Hãy phân tích báo cáo và kiểm tra provider ngay")

    assert result.route == "analysis"
    assert "provider_health" in kernel.state.last_plan
    assert "run_audit" in kernel.state.last_plan
    assert kernel.state.last_progress == "3/3"
    assert result.tool is not None
    assert result.tool.name == "run_audit"
    assert any(event.kind == "plan" for event in kernel.state.recent_events)
    assert any(event.kind == "tool" for event in kernel.state.recent_events)


def test_agent_kernel_emits_progress_callbacks(monkeypatch):
    kernel = _build_kernel(monkeypatch)
    stages: list[tuple[str, dict]] = []

    result = kernel.handle(
        "Hãy phân tích báo cáo và kiểm tra provider ngay",
        progress_callback=lambda stage, payload: stages.append((stage, payload)),
    )

    assert result.route == "analysis"
    assert [stage for stage, _ in stages] == ["plan_start", "plan_step", "plan_step", "plan_step", "plan_complete"]
    assert stages[-1][1]["success"] is True


def test_agent_kernel_document_tools_are_registered_and_callable(monkeypatch, tmp_path):
    from taxsentry.agent import kernel as kernel_module

    class FakeParser:
        def __init__(self, file_path):
            self.file_path = Path(file_path)

        def load(self):
            return None

        def parse_workbook(self):
            return {"ok": True}

        def export_json(self, output_path=None, trace_context=None, artifact_store=None):
            target = Path(output_path)
            target.write_text("{}", encoding="utf-8")
            return "{}"

        def log_to_database(self, trace_context=None):
            return True

    class FakePDFGenerator:
        def generate(self, markdown_content, output_pdf_path, trace_context=None, artifact_store=None):
            Path(output_pdf_path).write_text("pdf", encoding="utf-8")
            return True

    class FakeEmailSender:
        def __init__(self):
            self.director_email = "director@example.com"

        def send_report(self, pdf_path, summary_text="", trace_context=None):
            return True

    async def fake_send_active_report_to_director(pdf_path, summary_text, evidence_context_path=None, trace_context=None):
        return True

    monkeypatch.setattr(kernel_module, "TaxSentryParser", FakeParser)
    monkeypatch.setattr(kernel_module, "TaxSentryPDFGenerator", FakePDFGenerator)
    monkeypatch.setattr(kernel_module, "TaxSentryEmailSender", FakeEmailSender)
    monkeypatch.setattr(kernel_module, "send_active_report_to_director", fake_send_active_report_to_director)

    kernel = _build_kernel(monkeypatch)
    excel_path = tmp_path / "report.xlsx"
    pdf_path = tmp_path / "report.pdf"
    excel_path.write_text("fake", encoding="utf-8")
    pdf_path.write_text("fake", encoding="utf-8")

    parse_result = kernel.tools.run("parse_workbook", path=str(excel_path))
    assert parse_result.ok is True
    assert "Parsed workbook" in parse_result.output

    pdf_result = kernel.tools.run("generate_pdf", markdown_content="# hi", output_path=str(pdf_path))
    assert pdf_result.ok is True
    assert pdf_path.exists()

    email_result = kernel.tools.run("send_email", pdf_path=str(pdf_path), summary_text="summary")
    assert email_result.ok is True

    telegram_result = kernel.tools.run("send_telegram", pdf_path=str(pdf_path), summary_text="summary")
    assert telegram_result.ok is True


def test_agent_kernel_tools_command_lists_catalog(monkeypatch):
    kernel = _build_kernel(monkeypatch)

    result = kernel.handle("/tools")

    assert result.route == "operation"
    assert "tool_catalog" in result.response.text
    assert "provider_health" in result.response.text


def test_run_tui_uses_hermes_shell(monkeypatch):
    import taxsentry.app as app_module

    calls: list[str] = []

    class FakeShell:
        def __init__(self):
            calls.append("init")

        def run(self):
            calls.append("run")
            return 7

    monkeypatch.setattr(app_module, "HermesShell", FakeShell)

    assert app_module.run_tui() == 7
    assert calls == ["init", "run"]


def test_hermes_shell_smoke_builds_layout(monkeypatch):
    from taxsentry.ui import hermes_shell as hermes_module

    class FakeKernel:
        def __init__(self, settings, session_entry_point="tui", session_mode=None):
            self.settings = settings
            self.state = type(
                "State",
                (),
                {
                    "mode": type("Mode", (), {"value": "chat"})(),
                    "provider_key": "lmstudio",
                    "session_id": "sess-1",
                    "last_route": "analysis",
                    "last_tool_name": "run_audit",
                    "last_tool_status": "ok",
                    "last_user_input": "Hãy phân tích",
                    "last_plan": "provider_health -> run_audit",
                    "last_progress": "2/2",
                    "last_toolchain": ["provider_health", "run_audit"],
                    "recent_events": [],
                },
            )()

        def available_provider_presets(self):
            from taxsentry.agent import ProviderPreset

            return [
                ProviderPreset(
                    key="lmstudio",
                    label="LM Studio",
                    description="Local desktop app",
                    kind="lmstudio",
                    base_url="http://localhost:1234/v1",
                    model="google/gemma-4-e4b",
                    auth_mode="lmstudio",
                )
            ]

        def snapshot(self):
            return {
                "settings": self.settings,
                "provider": type("Provider", (), {"model": "google/gemma-4-e4b"})(),
                "provider_label": "LM Studio",
                "provider_health": (True, "ok"),
                "session": type("Session", (), {"session_id": "sess-1", "mode": "chat", "started_at": "now", "messages": []})(),
                "memory_facts": [{"summary": "memo 1"}],
                "recent_reports": [{"file_name": "report.xlsx", "tax_risk_status": "low"}],
                "evidence_context": {"source_file": "report.xlsx", "session_id": "sess-1", "trace_id": "trace-1"},
                "state": self.state,
                "available_tools": ["provider_health", "run_audit"],
                "recent_events": [],
                "active_plan": self.state.last_plan,
                "toolchain": self.state.last_toolchain,
            }

    monkeypatch.setattr(hermes_module, "AgentKernel", FakeKernel)

    shell = hermes_module.HermesShell(settings={"agent": {"name": "TaxSentry"}})
    frame = shell._build_frame(last_result="Đã phân tích xong", initial=False)

    assert "TaxSentry 1.1.2" in frame.header.renderable.plain
    assert "Progress: 2/2" in frame.center.renderable.plain
    assert "Tool timeline" in frame.right.renderable.plain
    assert frame.center is not None
    assert frame.right is not None
