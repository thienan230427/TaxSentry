from pathlib import Path
import asyncio
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_write_env_file_overwrites_blank_values(tmp_path, monkeypatch):
    from taxsentry.ui import tui

    env_path = tmp_path / '.env'
    env_path.write_text('DB_PASS=OLD_DB_SECRET\nEMAIL_PASS=OLD_EMAIL_SECRET\nOTHER=keep\n', encoding='utf-8')
    monkeypatch.setattr(tui, 'ENV_PATH', env_path)

    ok = tui.write_env_file({'DB_PASS': '', 'EMAIL_PASS': '', 'OTHER': 'value'})
    assert ok is True

    text = env_path.read_text(encoding='utf-8')
    assert 'DB_PASS=OLD_DB_SECRET' not in text
    assert 'EMAIL_PASS=OLD_EMAIL_SECRET' not in text
    assert 'DB_PASS=' in text
    assert 'EMAIL_PASS=' in text
    assert 'OTHER=value' in text


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

    def fake_run(coro):
        coro.close()
        return True

    monkeypatch.setattr(automation.asyncio, 'run', fake_run)

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
