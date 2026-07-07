from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.runtime import InteractionRouter, PolicyGate, SessionManager, ResponseComposer, normalize_entrypoint
from taxsentry.database.session_store import TaxSentrySessionStore
from taxsentry.database.artifact_store import TaxSentryArtifactStore


def test_interaction_router_routes_analysis_operation_and_clarification():
    router = InteractionRouter()

    analysis = router.route('Hãy phân tích báo cáo Excel này')
    assert analysis.route == 'analysis'
    assert analysis.intent == 'analysis'

    no_accent_analysis = router.route('Hay phan tich bao cao thue va kiem tra provider ngay')
    assert no_accent_analysis.route == 'analysis'
    assert 'analysis-intent' in no_accent_analysis.hints
    assert no_accent_analysis.urgency == 'high'

    operation = router.route('Hãy chạy bot Telegram ngay')
    assert operation.route == 'operation'
    assert operation.intent == 'operation'

    no_accent_operation = router.route('Hay chay bot Telegram va gui thong bao ngay')
    assert no_accent_operation.route == 'operation'
    assert 'notification-intent' in no_accent_operation.hints

    clarification = router.route('ok')
    assert clarification.route == 'clarification'
    assert clarification.needs_clarification is True


def test_policy_gate_and_response_composer_redact_sensitive_values():
    gate = PolicyGate()
    decision = gate.evaluate('API key: sk-test-12345 và password=secret123')
    assert decision.risk_level == 'high'
    assert decision.allowed is False
    assert '[REDACTED]' in decision.redacted_text

    composer = ResponseComposer(policy_gate=gate)
    response = composer.compose('API key: sk-test-12345', route='chat', session_id='sess-1')
    assert '[REDACTED]' in response.text
    assert response.metadata['policy_flags']
    assert response.session_id == 'sess-1'


def test_session_manager_roundtrip_and_entrypoint_normalization(tmp_path):
    store = TaxSentrySessionStore(str(tmp_path / 'runtime.sqlite3'))
    manager = SessionManager(store)

    session = manager.start_session(entry_point='telegram', mode='chat', user_identity='director')
    manager.record_message(session.session_id, 'user', 'Xin chào, kiểm tra báo cáo giúp tôi')
    manager.finish_session(session.session_id, final_response='Đã kiểm tra xong', outcome='success', summary='Completed')

    snapshot = manager.snapshot(session.session_id)
    assert snapshot is not None
    assert snapshot.entry_point == 'telegram'
    assert snapshot.user_identity == 'director'
    assert snapshot.final_response == 'Đã kiểm tra xong'
    assert snapshot.messages[0].role == 'user'

    hydrated = SessionManager(TaxSentrySessionStore(str(tmp_path / 'runtime.sqlite3'))).load_session(session.session_id)
    assert hydrated is not None
    assert hydrated.entry_point == 'telegram'
    assert hydrated.summary == 'Completed'
    assert hydrated.outcome == 'success'
    assert hydrated.messages[0].content == 'Xin chào, kiểm tra báo cáo giúp tôi'

    sessions = store.get_recent_sessions(limit=5)
    assert sessions[0]['session_id'] == session.session_id
    events = store.get_session_events(session.session_id)
    assert [event['event_type'] for event in events][:2] == ['session_start', 'message']

    entrypoint = normalize_entrypoint('bot', ['--dev'])
    assert entrypoint.mode == 'service'
    assert entrypoint.interactive is False


def test_artifact_store_records_evidence_provenance(tmp_path):
    from taxsentry.core.evidence_preview import save_evidence_context

    artifact_db = tmp_path / 'artifacts.sqlite3'
    artifact_path = tmp_path / 'evidence.json'
    store = TaxSentryArtifactStore(str(artifact_db))

    evidence = {
        'session_id': 'sess-123',
        'event_id': 'event-456',
        'trace_id': 'trace-789',
        'source_file': 'report.xlsx',
        'source_path': 'C:/reports/report.xlsx',
        'trace_context': {'session_id': 'sess-123', 'event_id': 'event-456', 'trace_id': 'trace-789'},
    }

    saved = save_evidence_context(evidence, artifact_path, artifact_store=store)
    assert saved == artifact_path

    artifacts = store.get_session_artifacts('sess-123')
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact['artifact_type'] == 'evidence_context'
    assert artifact['artifact_name'] == 'evidence.json'
    assert artifact['session_id'] == 'sess-123'
    assert artifact['trace_id'] == 'trace-789'
    assert artifact['metadata']['kind'] == 'evidence_context'
    assert artifact['metadata']['trace_context']['event_id'] == 'event-456'


def test_session_manager_builds_replay_bundle_from_sqlite(tmp_path, monkeypatch):
    from taxsentry.core import evidence_preview as evidence_preview_module
    from taxsentry.database.db_manager import TaxSentryDBManager

    db_path = tmp_path / 'replay.sqlite3'
    evidence_path = tmp_path / 'evidence_context.json'

    session_store = TaxSentrySessionStore(str(db_path))
    report_db = TaxSentryDBManager()
    report_db.db_path = str(db_path)
    assert report_db.connect() is True

    manager = SessionManager(session_store)
    session = manager.start_session(entry_point='automation', mode='run_once', user_identity='director', title='Nightly scan')
    manager.record_message(session.session_id, 'user', 'Hãy kiểm tra file này')
    manager.record_tool_event(
        session.session_id,
        tool_name='excel_parser',
        action='parse workbook',
        result='ok',
        payload={'file_name': 'report.xlsx'},
    )
    manager.finish_session(session.session_id, final_response='Đã xong', outcome='success', summary='Processed')

    assert report_db.log_report(
        received_at=datetime.now(),
        sender='accountant@example.com',
        file_name='report.xlsx',
        revenue=1000,
        gross_profit=400,
        total_opex=200,
        net_income=200,
        hospitality_no_invoice=50,
        tax_risk_status='low',
        status='Processed',
        session_id=session.session_id,
        event_id='event-123',
        trace_id='trace-abc',
        source_path='C:/reports/report.xlsx',
        source_file='report.xlsx',
        trace_generated_at='2026-06-27T00:00:00+00:00',
    ) is True

    evidence_path.write_text(
        '{"session_id": "%s", "event_id": "event-123", "trace_id": "trace-abc", "source_file": "report.xlsx", "source_path": "C:/reports/report.xlsx", "generated_at": "2026-06-27T00:00:00+00:00", "trace_context": {"session_id": "%s", "event_id": "event-123", "trace_id": "trace-abc"}}'
        % (session.session_id, session.session_id),
        encoding='utf-8',
    )
    monkeypatch.setattr(evidence_preview_module, 'EVIDENCE_CONTEXT_PATH', evidence_path)

    bundle = manager.build_replay_bundle(session.session_id, db_path=str(db_path), evidence_path=evidence_path)
    assert bundle is not None
    assert bundle.session is not None
    assert bundle.session.entry_point == 'automation'
    assert bundle.session.final_response == 'Đã xong'
    assert bundle.events[0]['event_type'] == 'session_start'
    assert bundle.reports[0]['session_id'] == session.session_id
    assert bundle.trace is not None
    assert bundle.trace.session_id == session.session_id
    assert bundle.trace.trace_id == 'trace-abc'
    assert bundle.evidence_context['trace_id'] == 'trace-abc'
