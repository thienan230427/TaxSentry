from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.bot import telegram_bot


def test_free_chat_prompt_injects_recalled_memory(monkeypatch):
    class _FakeMemoryStore:
        def __init__(self):
            self.connected = True

        def recall(self, query: str, scope: str | None = None, limit: int = 5):
            assert query == 'Có quy tắc release nào?'
            return [
                {
                    'memory_id': 'mem_001',
                    'memory_type': 'decision',
                    'subject': 'release-gate',
                    'summary': 'Use fresh Node + Python verification before marking release ready.',
                    'payload': {'source': 'roadmap'},
                    'tags': ['release', 'verification'],
                    'confidence': 0.98,
                    'importance': 0.95,
                    'source_ref': 'D:/Obsidian Vault/10_Projects/Taxsentry 0.2.1/05_Checklists/Taxsentry 0.2.1 - Master Checklists.md',
                    'created_at': '2026-06-27T09:15:00+00:00',
                    'updated_at': '2026-06-27T09:15:00+00:00',
                }
            ]

    monkeypatch.setattr(telegram_bot, 'TaxSentryMemoryStore', _FakeMemoryStore)

    prompt = telegram_bot._build_free_chat_prompt(
        user_query='Có quy tắc release nào?',
        director_name='Sếp Minh',
        financial_context={'latest': 'report'},
        tax_rules_snippet='Luật thuế mẫu',
        evidence_context={'source_file': 'BaoCao_Q2.xlsx'},
    )

    assert '## Memory / state liên quan' in prompt
    assert 'release-gate' in prompt
    assert 'Use fresh Node + Python verification before marking release ready.' in prompt
    assert 'BaoCao_Q2.xlsx' in prompt
