from pathlib import Path
import asyncio
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_write_env_file_overwrites_previous_content(tmp_path, monkeypatch):
    from taxsentry import config

    env_path = tmp_path / '.env'
    env_path.write_text('DB_PASS=OLD_DB_SECRET\nEMAIL_PASS=OLD_EMAIL_SECRET\nOTHER=keep\n', encoding='utf-8')
    monkeypatch.setitem(config.write_env_file.__globals__, 'ENV_FILE', env_path)

    cfg = config.get_empty_config()
    cfg['extra_env']['OTHER'] = 'value'
    written = config.write_env_file(cfg)
    assert written == env_path

    text = env_path.read_text(encoding='utf-8')
    assert 'DB_PASS=OLD_DB_SECRET' not in text
    assert 'EMAIL_PASS=OLD_EMAIL_SECRET' not in text
    assert 'OTHER="value"' in text
    assert 'TAXSENTRY_PROVIDER_KIND="lmstudio"' in text


def test_python_cli_dispatches_to_tui_and_status(monkeypatch):
    from taxsentry import tui

    calls = {'tui': 0, 'status': 0}

    monkeypatch.setattr(tui, 'run_tui', lambda: calls.__setitem__('tui', calls['tui'] + 1) or 7)
    monkeypatch.setattr(tui, 'run_status', lambda: calls.__setitem__('status', calls['status'] + 1) or 3)

    assert tui.main([]) == 7
    assert tui.main(['status']) == 3
    assert calls['tui'] == 1
    assert calls['status'] == 1


def test_run_status_does_not_bootstrap_memory(monkeypatch):
    from types import SimpleNamespace

    from taxsentry import app

    monkeypatch.setattr(app, 'TaxSentryRuntimeService', lambda: SimpleNamespace(
        settings={},
        status_text=lambda: 'status ok',
    ))
    monkeypatch.setattr(app, 'from_settings', lambda settings: object())
    monkeypatch.setattr(app, 'health_check', lambda provider: (True, 'healthy'))

    assert app.run_status() == 0


def test_memory_commands_bootstrap_memory(monkeypatch):
    from taxsentry import app

    calls = {"list": 0, "add": 0}

    class FakeMemory:
        def recent_facts(self, limit=20):
            calls["list"] += 1
            return [{"kind": "preference", "text": "keep it simple", "source": "cli"}]

        def remember_fact(self, text, source="cli"):
            calls["add"] += 1
            return None

    monkeypatch.setattr(app, "bootstrap_memory", lambda settings: FakeMemory())

    assert app.run_memory_list() == 0
    assert app.run_memory_add("keep it simple") == 0
    assert calls == {"list": 1, "add": 1}


def test_email_poller_marks_specific_email_ids(tmp_path):
    from taxsentry.core.email_poller import TaxSentryEmailPoller

    poller = TaxSentryEmailPoller()
    poller.processed_file = tmp_path / 'processed.json'
    poller.processed_ids = set()
    poller._pending_email_ids = {'email-a': True, 'email-b': True}

    marked = poller.mark_email_ids_as_processed(['email-a', 'missing-email'])

    assert marked == 1
    assert poller.processed_ids == {'email-a'}
    assert 'email-a' not in poller._pending_email_ids
    assert 'email-b' in poller._pending_email_ids
    assert poller.processed_file.exists()


def test_email_poller_builds_nested_or_criteria():
    from taxsentry.core.email_poller import TaxSentryEmailPoller

    poller = TaxSentryEmailPoller()
    criteria = poller._build_sender_search_criteria([
        'b@example.com',
        'a@example.com',
        'c@example.com',
    ])

    assert criteria == (
        'OR',
        'FROM',
        '"a@example.com"',
        'OR',
        'FROM',
        '"b@example.com"',
        'FROM',
        '"c@example.com"',
    )


def test_custom_provider_requires_explicit_base_url():
    from taxsentry.providers import ProviderConfig, ProviderError, build_client

    spec = ProviderConfig(
        kind='custom',
        base_url='',
        model='gpt-4.1-mini',
        api_key='',
        auth_mode='api_key',
    )

    try:
        build_client(spec)
    except ProviderError as exc:
        assert 'base URL' in str(exc)
    else:
        raise AssertionError('Expected ProviderError for blank custom base_url')


def test_automation_marks_only_successful_email_ids(tmp_path, monkeypatch):
    from taxsentry.core import automation

    class FakePoller:
        def __init__(self):
            self.log_callback = None
            self._contexts = {
                'file-a.xlsx': {'email_id': 'email-a'},
                'file-b.xlsx': {'email_id': 'email-b'},
            }
            self.marked = None

        def connect(self):
            return True

        def check_and_download(self):
            return ['file-a.xlsx', 'file-b.xlsx']

        def disconnect(self):
            return None

        def get_file_context(self, file_path):
            return self._contexts[file_path]

        def mark_email_ids_as_processed(self, email_ids):
            self.marked = list(email_ids)
            return len(email_ids)

    class FakeParser:
        def __init__(self, path):
            self.path = path
        def load(self):
            return None
        def parse_assumptions(self):
            return None
        def parse_income_statement(self):
            return None
        def has_meaningful_data(self):
            return True
        def export_json(self, output_path):
            Path(output_path).write_text('{"ok": true}', encoding='utf-8')
        def log_to_database(self):
            return self.path.endswith('file-a.xlsx')

    class FakeGenerator:
        def generate(self, markdown, output_path):
            Path(output_path).write_text(markdown, encoding='utf-8')
            return True

    monkeypatch.setattr(automation, 'TaxSentryEmailPoller', FakePoller)
    monkeypatch.setattr(automation, 'TaxSentryParser', FakeParser)
    monkeypatch.setattr(automation, 'TaxSentryPDFGenerator', FakeGenerator)
    monkeypatch.setattr(automation, 'TaxSentryPDFParser', lambda path: None)
    monkeypatch.setattr(automation, 'build_evidence_context', lambda parser, file_context: {'image_attachments': []})
    monkeypatch.setattr(automation, 'save_evidence_context', lambda *args, **kwargs: None)

    workflow = automation.TaxSentryAutomationWorkflow()
    workflow.engine.run_audit = lambda: '# report'
    workflow.sender.send_report = lambda *args, **kwargs: True
    workflow.workflow_service.send_telegram_report = lambda **kwargs: True

    result = workflow.run_once()

    assert result == 1
    assert workflow.poller.marked == ['email-a']


def test_email_sender_dry_run_returns_false_when_unconfigured():
    from taxsentry.core.email_sender import TaxSentryEmailSender

    sender = TaxSentryEmailSender()
    sender.user = ''
    sender.password = ''

    assert sender.is_configured() is False
    assert sender.send_report('missing.pdf', 'summary') is False


def test_artifact_store_and_replay_capture_provenance(tmp_path):
    from taxsentry.core.evidence_preview import build_trace_replay_text
    from taxsentry.database import TaxSentryArtifactStore

    db_path = tmp_path / 'artifacts.sqlite3'
    evidence_path = tmp_path / 'evidence_context.json'
    pdf_path = tmp_path / 'report.pdf'
    evidence_path.write_text('{"source_file": "input.xlsx"}', encoding='utf-8')
    pdf_path.write_bytes(b'%PDF-1.4\n%fake\n')

    store = TaxSentryArtifactStore(str(db_path))
    assert store.connect() is True
    store.register_artifact(
        artifact_type='evidence_context',
        artifact_name='evidence_context.json',
        artifact_path=str(evidence_path),
        session_id='sess-1',
        event_id='event-1',
        trace_id='trace-1',
        source_file='input.xlsx',
        source_path='C:/input.xlsx',
        mime_type='application/json',
        metadata={'kind': 'evidence_context'},
    )
    store.register_artifact(
        artifact_type='report_pdf',
        artifact_name='report.pdf',
        artifact_path=str(pdf_path),
        session_id='sess-1',
        event_id='event-1',
        trace_id='trace-1',
        source_file='input.xlsx',
        source_path='C:/input.xlsx',
        mime_type='application/pdf',
        metadata={'kind': 'report_pdf'},
    )

    artifacts = store.get_session_artifacts('sess-1')
    assert len(artifacts) == 2
    assert {artifact['artifact_type'] for artifact in artifacts} == {'evidence_context', 'report_pdf'}
    assert artifacts[0]['metadata']['kind'] in {'evidence_context', 'report_pdf'}

    replay = build_trace_replay_text(
        {'source_file': 'input.xlsx', 'session_id': 'sess-1', 'event_id': 'event-1', 'trace_id': 'trace-1'},
        log_lines=['processed file'],
        session_events=[{'created_at': '2026-06-27T00:00:00+00:00', 'event_type': 'artifact_saved', 'actor': 'automation', 'result': 'success'}],
        artifacts=artifacts,
    )
    assert 'artifact_saved' in replay
    assert 'evidence_context' in replay
    assert 'report_pdf' in replay
    assert 'session=sess-1' in replay


def test_email_sender_includes_trace_metadata(tmp_path, monkeypatch):
    from taxsentry.core import email_sender as email_sender_module
    from taxsentry.core.email_sender import TaxSentryEmailSender

    class FakeSMTP:
        instances = []

        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.login_args = None
            self.sent = None
            FakeSMTP.instances.append(self)

        def starttls(self):
            return None

        def login(self, user, password):
            self.login_args = (user, password)

        def sendmail(self, user, recipient, message):
            self.sent = (user, recipient, message)

        def quit(self):
            return None

    pdf_path = tmp_path / 'report.pdf'
    pdf_path.write_bytes(b'%PDF-1.4\n%fake\n')
    monkeypatch.setattr(email_sender_module.smtplib, 'SMTP_SSL', FakeSMTP)
    monkeypatch.setattr(email_sender_module.smtplib, 'SMTP', FakeSMTP)

    sender = TaxSentryEmailSender()
    sender.user = 'system@example.com'
    sender.password = 'app-password'
    sender.director_email = 'director@example.com'
    sender.smtp_port = 465

    ok = sender.send_report(
        str(pdf_path),
        'Tóm tắt rủi ro',
        trace_context={'session_id': 'sess-9', 'event_id': 'event-9', 'trace_id': 'trace-9'},
    )
    assert ok is True
    assert FakeSMTP.instances, 'SMTP fake should be used'
    sent_message = FakeSMTP.instances[0].sent[2]
    assert 'X-TaxSentry-Session-ID: sess-9' in sent_message

    from email import message_from_string

    parsed = message_from_string(sent_message)
    body_parts = []
    for part in parsed.walk():
        if part.get_content_type() == 'text/plain':
            body_parts.append(part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace'))
    assert any('Trace: session=sess-9 | event=event-9 | trace=trace-9' in body for body in body_parts)


def test_telegram_active_report_includes_trace_metadata(tmp_path, monkeypatch):
    import types
    from taxsentry.bot import telegram_bot

    class FakeBot:
        instances = []

        def __init__(self, token):
            self.token = token
            self.messages = []
            self.documents = []
            FakeBot.instances.append(self)

        async def send_message(self, chat_id, text):
            self.messages.append((chat_id, text))

        async def send_document(self, chat_id, document, filename, caption):
            self.documents.append((chat_id, filename, caption))

    evidence_path = tmp_path / 'evidence_context.json'
    evidence_path.write_text('{"source_file": "input.xlsx", "attachments": []}', encoding='utf-8')
    pdf_path = tmp_path / 'report.pdf'
    pdf_path.write_bytes(b'%PDF-1.4\n%fake\n')

    telegram_module = types.ModuleType('telegram')
    telegram_module.Bot = FakeBot
    monkeypatch.setitem(sys.modules, 'telegram', telegram_module)
    monkeypatch.setattr(telegram_bot, 'EVIDENCE_CONTEXT_PATH', evidence_path)
    monkeypatch.setattr(telegram_bot, 'load_evidence_context', lambda path=None: {'source_file': 'input.xlsx', 'attachments': []})
    monkeypatch.setattr(telegram_bot.os, 'getenv', lambda key, default=None: {'TELEGRAM_BOT_TOKEN': 'token', 'ADMIN_CHAT_ID': '12345'}.get(key, default))

    ok = asyncio.run(
        telegram_bot.send_active_report_to_director(
            str(pdf_path),
            'Tóm tắt rủi ro',
            evidence_context_path=str(evidence_path),
            trace_context={'session_id': 'sess-7', 'event_id': 'event-7', 'trace_id': 'trace-7'},
        )
    )
    assert ok is True
    assert FakeBot.instances, 'FakeBot should be instantiated'
    bot = FakeBot.instances[0]
    assert bot.messages, 'Message should be sent'
    assert bot.documents, 'Document should be sent'
    assert any('Trace: session=sess-7 | event=event-7 | trace=trace-7' in text for _, text in bot.messages)
    assert any('Trace: session=sess-7 | event=event-7 | trace=trace-7' in caption for _, _, caption in bot.documents)


def test_config_package_reexports_implementation():
    from taxsentry.config import describe_config, get_value, load_config

    config = load_config()
    assert callable(describe_config)
    assert callable(get_value)
    assert isinstance(describe_config(config), str)


def test_config_round_trip_persists_provider_and_memory_settings(tmp_path, monkeypatch):
    import importlib
    import sys

    monkeypatch.setenv("TAXSENTRY_HOME", str(tmp_path / ".taxsentry"))
    monkeypatch.setenv("TAXSENTRY_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("TAXSENTRY_MEMORY_DB", str(tmp_path / "memory.db"))
    for key in [
        "TAXSENTRY_PROVIDER_KIND",
        "TAXSENTRY_PROVIDER_URL",
        "TAXSENTRY_PROVIDER_MODEL",
        "TAXSENTRY_PROVIDER_API_KEY",
        "TAXSENTRY_AI_AUTH_MODE",
        "TAXSENTRY_MEMORY_MAX_FACTS",
        "TAXSENTRY_MEMORY_MAX_TURNS",
        "TAXSENTRY_JOB_TRACKING",
        "TAXSENTRY_JOB_RETRY_LIMIT",
        "TAXSENTRY_JOB_DEFAULT_STATE",
        "TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA",
        "AUTO_SEND_EMAIL",
        "AUTO_SEND_TELEGRAM",
    ]:
        monkeypatch.delenv(key, raising=False)

    sys.modules.pop("taxsentry.config", None)
    sys.modules.pop("taxsentry._config_impl", None)
    config_mod = importlib.import_module("taxsentry.config")

    config = config_mod.load_config()
    config_mod.set_value(config, "provider.kind", "custom")
    config_mod.set_value(config, "provider.base_url", "http://localhost:9999/v1")
    config_mod.set_value(config, "provider.model", "gpt-4.1-mini")
    config_mod.set_value(config, "provider.auth_mode", "api_key")
    config_mod.set_value(config, "provider.api_key", "secret")
    config_mod.set_value(config, "memory.max_facts", 99)
    config_mod.set_value(config, "memory.max_turns", 7)
    config_mod.set_value(config, "jobs.tracking_enabled", True)
    config_mod.set_value(config, "jobs.retry_limit", 3)
    config_mod.set_value(config, "jobs.default_state", "queued")
    config_mod.set_value(config, "jobs.needs_human_review_on_missing_data", False)
    config_mod.set_value(config, "jobs.auto_send_email", False)
    config_mod.set_value(config, "jobs.auto_send_telegram", True)
    config_mod.save_config(config)

    reloaded = config_mod.load_config()
    assert config_mod.get_value(reloaded, "provider.kind") == "custom"
    assert config_mod.get_value(reloaded, "provider.base_url") == "http://localhost:9999/v1"
    assert config_mod.get_value(reloaded, "provider.model") == "gpt-4.1-mini"
    assert config_mod.get_value(reloaded, "provider.auth_mode") == "api_key"
    assert config_mod.get_value(reloaded, "provider.api_key") == ""
    assert config_mod.get_value(reloaded, "memory.max_facts") == 99
    assert config_mod.get_value(reloaded, "memory.max_turns") == 7
    assert config_mod.get_value(reloaded, "jobs.tracking_enabled") is True
    assert config_mod.get_value(reloaded, "jobs.retry_limit") == 3
    assert config_mod.get_value(reloaded, "jobs.default_state") == "queued"
    assert config_mod.get_value(reloaded, "jobs.needs_human_review_on_missing_data") is False
    assert config_mod.get_value(reloaded, "jobs.auto_send_email") is False
    assert config_mod.get_value(reloaded, "jobs.auto_send_telegram") is True


def test_job_manager_persists_state_transitions(tmp_path):
    from taxsentry.database.db_manager import TaxSentryDBManager
    from taxsentry.runtime.session import JobManager

    db_path = tmp_path / "jobs.sqlite3"
    store = TaxSentryDBManager(str(db_path))
    manager = JobManager(store)

    job = manager.start_job(
        job_type="report_processing",
        session_id="sess-1",
        source_file="report.xlsx",
        source_path="C:/reports/report.xlsx",
        email_id="email-1",
        trace_id="trace-1",
        metadata={"source": "test"},
    )
    assert job is not None
    assert job.state == "pending"
    assert job.metadata == {"source": "test"}

    ok = manager.update_job_state(
        job.job_id,
        "completed",
        metadata={"source": "test", "phase": "done"},
    )
    assert ok is True

    reloaded = manager.get_job(job.job_id)
    assert reloaded is not None
    assert reloaded.state == "completed"
    assert reloaded.metadata == {"source": "test", "phase": "done"}
    assert reloaded.source_file == "report.xlsx"

    session_jobs = manager.get_jobs_for_session("sess-1")
    assert len(session_jobs) == 1
    assert session_jobs[0].job_id == job.job_id


def test_runtime_service_replays_sessions_and_jobs(tmp_path):
    from taxsentry.database.db_manager import TaxSentryDBManager
    from taxsentry.database.session_store import TaxSentrySessionStore
    from taxsentry.runtime.service import TaxSentryRuntimeService

    db_path = tmp_path / "service.sqlite3"
    db_manager = TaxSentryDBManager(str(db_path))
    session_store = TaxSentrySessionStore(str(db_path))
    service = TaxSentryRuntimeService(
        settings={
            "agent": {"name": "TaxSentry", "persona": "warm, precise, and practical", "language": "vi", "memory_enabled": True},
            "provider": {"kind": "lmstudio", "base_url": "http://localhost:1234/v1", "model": "google/gemma-4-e4b", "auth_mode": "lmstudio", "api_key": ""},
            "memory": {"max_facts": 50, "max_turns": 12, "session_title": "TaxSentry session"},
            "jobs": {"tracking_enabled": True, "retry_limit": 2, "default_state": "pending", "needs_human_review_on_missing_data": True, "auto_send_email": True, "auto_send_telegram": True},
            "integrations": {"telegram": {"enabled": False, "bot_token": "", "admin_chat_id": ""}},
            "ui": {"theme": "midnight", "show_banner": True},
            "extra_env": {},
        },
        session_store=session_store,
        db_manager=db_manager,
    )

    session = service.session_manager.start_session(entry_point="cli", mode="tui", title="Replay test")
    job = service.job_manager.start_job(
        job_type="report_processing",
        session_id=session.session_id,
        source_file="replay.xlsx",
        source_path="C:/reports/replay.xlsx",
        metadata={"source": "test"},
    )
    assert job is not None
    service.session_manager.record_event(
        session_id=session.session_id,
        event_type="job_update",
        actor="automation",
        action="mark job completed",
        result="completed",
        payload={"job_id": job.job_id},
    )

    replay = service.replay_session(session.session_id)
    assert session.session_id in replay
    assert job.job_id in replay
    assert "Recent jobs" not in replay or "jobs:" in replay


def test_run_replay_prompts_for_recent_session(monkeypatch):
    from taxsentry import app

    calls = {}

    class FakeService:
        def __init__(self):
            pass

        @property
        def settings(self):
            return {}

        def recent_sessions(self, limit=10):
            calls["limit"] = limit
            return [
                {"session_id": "sess-1", "mode": "chat", "outcome": "success", "started_at": "2026-07-01T00:00:00"},
                {"session_id": "sess-2", "mode": "analysis", "outcome": "open", "started_at": "2026-07-01T01:00:00"},
            ]

        def replay_session(self, session_id):
            calls["session_id"] = session_id
            return f"Replay {session_id}"

    monkeypatch.setattr(app, "TaxSentryRuntimeService", FakeService)
    monkeypatch.setattr(app.Prompt, "ask", lambda *args, **kwargs: "2")

    exit_code = app.run_replay()

    assert exit_code == 0
    assert calls["limit"] == 10
    assert calls["session_id"] == "sess-2"


def test_run_dashboard_delegates_to_dashboard_view(monkeypatch):
    from taxsentry import app

    calls = {"run": 0}

    class FakeDashboard:
        def __init__(self, service=None):
            self.service = service

        def run(self):
            calls["run"] += 1
            return 0

    monkeypatch.setattr(app, "TaxSentryDashboard", FakeDashboard)

    assert app.run_dashboard() == 0
    assert calls["run"] == 1
