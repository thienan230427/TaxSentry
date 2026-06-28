from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.core.automation import TaxSentryAutomationWorkflow
from taxsentry.database.session_store import TaxSentrySessionStore


class _EmptyPoller:
    def __init__(self):
        self.log_callback = None

    def connect(self):
        return False

    def check_and_download(self):
        return []

    def disconnect(self):
        return None


class _NoopEngine:
    def __init__(self):
        self.log_callback = None


class _NoopGenerator:
    def generate(self, *args, **kwargs):
        return True


class _NoopSender:
    def send_report(self, *args, **kwargs):
        return True


def test_automation_run_once_records_session_end_for_empty_run(tmp_path):
    workflow = TaxSentryAutomationWorkflow()
    workflow.poller = _EmptyPoller()
    workflow.engine = _NoopEngine()
    workflow.generator = _NoopGenerator()
    workflow.sender = _NoopSender()
    workflow.session_store = TaxSentrySessionStore(str(tmp_path / 'session.sqlite3'))

    processed = workflow.run_once()

    assert processed == 0
    sessions = workflow.session_store.get_recent_sessions(limit=5)
    assert len(sessions) == 1
    assert sessions[0]['entry_point'] == 'automation'
    assert sessions[0]['mode'] == 'run_once'
    assert sessions[0]['outcome'] == 'success'
    assert sessions[0]['summary'] == 'No new reports found'

    events = workflow.session_store.get_session_events(sessions[0]['session_id'])
    assert [event['event_type'] for event in events] == ['session_start', 'session_end']
    assert events[0]['result'] == 'started'
    assert events[1]['result'] == 'empty'
