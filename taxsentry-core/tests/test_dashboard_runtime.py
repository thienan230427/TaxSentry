from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.runtime.copilot_prompt import build_copilot_prompt
from taxsentry.ui import dashboard_model, startup_context, tui


class _FakeProcess:
    def __init__(self, alive: bool = True):
        self.alive = alive
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        self.alive = False

    def wait(self, timeout: int = 2):
        self.waited = True

    def kill(self):
        self.killed = True
        self.alive = False


class _FakeDB:
    def __init__(self):
        self.closed = False

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
        self.closed = True


def test_build_copilot_prompt_uses_shared_voice_and_context():
    prompt = build_copilot_prompt(
        user_query='Tình hình quý này thế nào?',
        director_name='An',
        financial_context={'latest': 'report'},
        tax_rules_snippet='Luật thuế mẫu',
        evidence_context={'source_file': 'BaoCao_Q2.xlsx'},
        financial_json={'revenue': 1250000000},
    )

    assert 'Sếp An' in prompt
    assert "Xưng 'em', gọi người dùng là 'Sếp'." in prompt
    assert 'Tình hình quý này thế nào?' in prompt
    assert 'Luật thuế mẫu' in prompt
    assert 'BaoCao_Q2.xlsx' in prompt
    assert '1250000000' in prompt


def test_collect_dashboard_snapshot_builds_friendly_cards(monkeypatch):
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
    layout = dashboard_model.build_dashboard_layout(snapshot)
    console = Console(record=True, width=120)
    console.print(layout)
    rendered = console.export_text()
    summary_console = Console(record=True, width=180)
    summary_console.print(dashboard_model._build_summary_panel(snapshot))
    summary_rendered = summary_console.export_text()

    assert 'Bảng Điều Khiển Nhanh' in rendered
    assert 'Telegram' in summary_rendered
    assert 'Tự động hoá' in summary_rendered
    assert [card.label for card in snapshot.status_cards] == [
        'Giám đốc',
        'AI server',
        'Model',
        'Telegram',
        'Tự động hoá',
        'Bản ghi',
    ]
    assert snapshot.status_cards[0].value == 'Giám đốc Minh'
    assert snapshot.status_cards[1].value == 'http://localhost:1234/v1'
    assert snapshot.status_cards[5].value == '1 báo cáo gần nhất'
    assert snapshot.recent_reports[0].file_name == 'BaoCao_Q2.xlsx'
    assert snapshot.recent_reports[0].received_at == '27/06 09:15'
    assert snapshot.recent_reports[0].status == 'Đã xử lý'
    assert 'Doanh thu' in snapshot.evidence_preview
    assert 'Nhấn [c] để mở chế độ chat trực tiếp với Copilot.' in snapshot.action_hints[0]
    assert any('thoát dashboard nhanh' in hint for hint in snapshot.action_hints)


def test_sync_telegram_gateway_status_updates_runtime_state(monkeypatch):
    monkeypatch.setattr(tui, 'TELEGRAM_PROCESS', _FakeProcess(alive=True))

    tui._sync_telegram_gateway_status()
    assert tui.SYSTEM_STATUS['Telegram Bot'] == '[green]Online (Listening...)[/green]'

    tui.TELEGRAM_PROCESS.alive = False
    tui._sync_telegram_gateway_status()
    assert tui.SYSTEM_STATUS['Telegram Bot'] == '[red]Offline (Stopped)[/red]'

    monkeypatch.setattr(tui, 'TELEGRAM_PROCESS', None)
    tui._sync_telegram_gateway_status()
    assert tui.SYSTEM_STATUS['Telegram Bot'] == '[yellow]Offline (Not Started)[/yellow]'


def test_dashboard_hotkeys_open_chat_and_exit(monkeypatch):
    class _FakeLive:
        def __init__(self):
            self.stopped = False
            self.started = False

        def stop(self):
            self.stopped = True

        def start(self):
            self.started = True

    class _FakeMsvcrt:
        def __init__(self, key: bytes):
            self._key = key

        def kbhit(self):
            return True

        def getch(self):
            return self._key

    fake_live = _FakeLive()
    monkeypatch.setattr(tui, '_MSVCRT', _FakeMsvcrt(b'c'))
    monkeypatch.setattr(tui, 'run_chat_mode', lambda: None)

    should_exit = tui._handle_dashboard_hotkeys(fake_live)
    assert should_exit is False
    assert fake_live.stopped is True
    assert fake_live.started is True

    monkeypatch.setattr(tui, '_MSVCRT', _FakeMsvcrt(b'q'))
    should_exit = tui._handle_dashboard_hotkeys(fake_live)
    assert should_exit is True

    monkeypatch.setattr(tui, '_MSVCRT', _FakeMsvcrt(b'\x1b'))
    should_exit = tui._handle_dashboard_hotkeys(fake_live)
    assert should_exit is True


def test_startup_context_builds_status_from_environment(monkeypatch):
    monkeypatch.setenv('DIRECTOR_NAME', 'Sếp Minh')
    monkeypatch.setenv('DIRECTOR_EMAIL', 'director@example.com')
    monkeypatch.setenv('ACCOUNTANT_EMAIL', 'accountant@example.com')
    monkeypatch.setenv('EMAIL_USER', 'director-login@example.com')
    monkeypatch.setenv('LM_MODEL_NAME', 'google/gemma-4-e4b')
    monkeypatch.setenv('LM_STUDIO_URL', 'http://localhost:1234/v1')

    class _FakeEngine:
        def connect(self):
            return True

    monkeypatch.setattr(startup_context, 'TaxSentryAnalysisEngine', _FakeEngine)

    logs: list[str] = []
    status = {'LM Studio': '[yellow]Checking...[/yellow]'}
    ctx = startup_context.build_startup_context(logs, status)

    assert ctx.director_name == 'Sếp Minh'
    assert ctx.director_email == 'director@example.com'
    assert ctx.accountant_email == 'accountant@example.com'
    assert ctx.email_user == 'director-login@example.com'
    assert ctx.model_name == 'google/gemma-4-e4b'
    assert ctx.llm_url == 'http://localhost:1234/v1'
    assert status['LM Studio'] == '[green]Connected (gemma-4-e4b)[/green]'
    assert any('Kính chào Giám đốc Sếp Minh' in line for line in logs)
    assert any('Kết nối AI Server thành công' in line for line in logs)


def test_startup_context_records_engine_failure(monkeypatch):
    monkeypatch.delenv('DIRECTOR_NAME', raising=False)
    monkeypatch.setenv('LM_STUDIO_URL', 'http://localhost:1234/v1')

    class _FakeEngine:
        def connect(self):
            return False

    monkeypatch.setattr(startup_context, 'TaxSentryAnalysisEngine', _FakeEngine)

    logs: list[str] = []
    status = {'LM Studio': '[yellow]Checking...[/yellow]'}
    ctx = startup_context.build_startup_context(logs, status)

    assert ctx.director_name == ''
    assert status['LM Studio'] == '[red]Disconnected[/red]'
    assert any('Kính chào Sếp' in line for line in logs)
    assert any('Không thể kết nối AI Server' in line for line in logs)


