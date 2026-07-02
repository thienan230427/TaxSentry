from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.database.session_store import TaxSentrySessionStore


def test_session_store_roundtrip(tmp_path):
    db_path = tmp_path / 'session.sqlite3'
    store = TaxSentrySessionStore(str(db_path))

    session_id = store.start_session(entry_point='automation', mode='run_once', title='Nightly scan')
    event_id = store.log_event(
        session_id=session_id,
        event_type='session_start',
        actor='automation',
        action='start run_once',
        result='started',
        payload={'interval_seconds': 60},
    )
    assert event_id

    event_id_2 = store.log_event(
        session_id=session_id,
        event_type='file_processed',
        actor='automation',
        action='parse xlsx',
        result='ok',
        latency_ms=12.5,
        payload={'file_name': 'report.xlsx'},
    )
    assert event_id_2 != event_id

    assert store.end_session(session_id, summary='Processed one file', outcome='success') is True

    sessions = store.get_recent_sessions(limit=5)
    assert len(sessions) == 1
    assert sessions[0]['session_id'] == session_id
    assert sessions[0]['entry_point'] == 'automation'
    assert sessions[0]['mode'] == 'run_once'
    assert sessions[0]['summary'] == 'Processed one file'
    assert sessions[0]['outcome'] == 'success'
    assert sessions[0]['ended_at'] is not None

    events = store.get_session_events(session_id)
    assert [event['event_type'] for event in events] == ['session_start', 'file_processed']
    assert events[0]['payload']['interval_seconds'] == 60
    assert events[1]['payload']['file_name'] == 'report.xlsx'
    assert events[1]['latency_ms'] == 12.5


def test_session_store_serializes_datetime_payloads(tmp_path):
    db_path = tmp_path / 'session.sqlite3'
    store = TaxSentrySessionStore(str(db_path))

    session_id = store.start_session(entry_point='tui', mode='analysis')
    event_id = store.log_event(
        session_id=session_id,
        event_type='tool_dispatch',
        actor='kernel',
        action='run memory_search',
        result='ok',
        payload={'created_at': datetime(2026, 7, 1, tzinfo=timezone.utc)},
    )

    assert event_id
    events = store.get_session_events(session_id)
    assert events[0]['payload']['created_at'] == '2026-07-01 00:00:00+00:00'
