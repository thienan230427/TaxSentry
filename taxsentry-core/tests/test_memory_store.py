from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taxsentry.database.memory_store import TaxSentryMemoryStore


def test_memory_store_remember_recall_and_forget_roundtrip(tmp_path):
    db_path = tmp_path / 'memory.sqlite3'
    store = TaxSentryMemoryStore(str(db_path))

    memory_id = store.remember(
        memory_type='decision',
        subject='release-gate',
        summary='Use fresh Node + Python verification before marking release ready.',
        payload={'source': 'roadmap', 'importance': 0.9},
        tags=['release', 'verification'],
        confidence=0.98,
        importance=0.95,
        source_ref='D:/Obsidian Vault/10_Projects/Taxsentry 0.2.1/05_Checklists/Taxsentry 0.2.1 - Master Checklists.md',
    )

    results = store.recall('release verification', limit=5)
    assert len(results) == 1
    assert results[0]['memory_id'] == memory_id
    assert results[0]['memory_type'] == 'decision'
    assert results[0]['subject'] == 'release-gate'
    assert 'fresh Node + Python verification' in results[0]['summary']
    assert results[0]['tags'] == ['release', 'verification']
    assert results[0]['payload']['source'] == 'roadmap'

    removed = store.forget(memory_id)
    assert removed is True
    assert store.recall('release verification', limit=5) == []


def test_memory_store_recalls_vietnamese_without_accents(tmp_path):
    db_path = tmp_path / 'memory.sqlite3'
    store = TaxSentryMemoryStore(str(db_path))

    memory_id = store.remember(
        memory_type='preference',
        subject='khách hàng ACME',
        summary='Khách hàng ACME cần kiểm tra hóa đơn đầu vào tháng 7.',
        tags=['thuế', 'hóa đơn'],
        confidence=0.9,
        importance=0.8,
    )

    results = store.recall('khach hang acme hoa don dau vao', limit=5)
    assert results
    assert results[0]['memory_id'] == memory_id


def test_memory_store_semantic_lite_recall_handles_partial_query(tmp_path):
    db_path = tmp_path / 'memory.sqlite3'
    store = TaxSentryMemoryStore(str(db_path))

    memory_id = store.remember(
        memory_type='decision',
        subject='audit workflow',
        summary='Always verify provider health before running tax audit.',
        tags=['workflow', 'audit'],
        confidence=0.9,
        importance=0.8,
    )

    results = store.recall('provider readiness before audit run', limit=5)
    assert results
    assert results[0]['memory_id'] == memory_id
