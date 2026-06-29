from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.ui import dashboard_model


class _FakeDB:
    def connect(self):
        return True

    def get_recent_logs(self, limit: int = 5):
        return [
            {
                'received_at': datetime(2026, 6, 27, 9, 15),
                'sender': 'ke-toan-truong@example.com',
                'file_name': 'BaoCao_Q2.xlsx',
                'revenue': 1250000000,
                'net_income': 210000000,
                'tax_risk_status': 'Cần chú ý',
                'status': 'Processed',
            }
        ][:limit]

    def close(self):
        pass


SNAPSHOT_PATH = Path(__file__).resolve().parent / 'snapshots' / 'dashboard_snapshot.json'


def test_dashboard_snapshot_matches_golden(monkeypatch):
    monkeypatch.setenv('DIRECTOR_NAME', 'Giám đốc Minh')
    monkeypatch.setenv('LM_MODEL_NAME', 'google/gemma-4-e4b')
    monkeypatch.setenv('LM_STUDIO_URL', 'http://localhost:1234/v1')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123:token')
    monkeypatch.delenv('TAXSENTRY_AUTOMATION_DISABLED', raising=False)

    monkeypatch.setattr(dashboard_model, 'TaxSentryDBManager', _FakeDB)
    monkeypatch.setattr(
        dashboard_model,
        'load_evidence_context',
        lambda path=None: {
            'source_file': 'BaoCao_Q2.xlsx',
            'email_subject': 'Báo cáo quý 2',
            'attachments': [{'file_name': 'BaoCao_Q2.xlsx', 'kind': 'excel'}],
            'document_types': ['income_statement'],
            'sheet_names': ['IS'],
            'workbook_preview': [{'sheet_name': 'IS', 'sheet_type': 'income_statement', 'preview_lines': ['Doanh thu: 1.25B']}],
            'canonical_metrics_preview': {'revenue': {'value': 1250000000}},
        },
    )

    snapshot = dashboard_model.collect_dashboard_snapshot(limit=3)
    snapshot.last_refresh = '<fixed>'
    data = asdict(snapshot)

    expected = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    assert data == expected
