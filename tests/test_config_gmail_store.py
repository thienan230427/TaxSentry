from __future__ import annotations

import json
from copy import deepcopy

from taxsentry import config as config_module
from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.gmail import normalize_email, trusted_sender
from taxsentry.reporting import parse_report
from taxsentry.store import JobStore


def test_trust_boundary_normalizes_sender_address():
    assert normalize_email("Kế toán <ACCOUNTING@EXAMPLE.COM>") == "accounting@example.com"
    assert trusted_sender("Kế toán <accounting@example.com>", ["ACCOUNTING@example.com"])
    assert not trusted_sender("attacker@example.com", ["accounting@example.com"])


def test_save_removes_legacy_gmail_oauth_fields(monkeypatch, tmp_path):
    settings = deepcopy(DEFAULT_SETTINGS)
    settings["gmail"].update({"auth_mode": "oauth", "oauth_client_file": "credentials.json"})
    target = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", target)
    monkeypatch.setattr(config_module, "ensure_directories", lambda: None)

    config_module.save_config(settings)

    gmail = json.loads(target.read_text(encoding="utf-8"))["gmail"]
    assert "auth_mode" not in gmail and "oauth_client_file" not in gmail


def test_save_removes_obsolete_web_and_gateway_fields(monkeypatch, tmp_path):
    settings = deepcopy(DEFAULT_SETTINGS)
    settings["ui"]["port"] = 8765
    settings["worker"]["gateway"] = True
    settings["integrations"] = {"telegram": {"enabled": True}}
    target = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", target)
    monkeypatch.setattr(config_module, "ensure_directories", lambda: None)
    config_module.save_config(settings)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert "integrations" not in saved and "port" not in saved["ui"] and "gateway" not in saved["worker"]


def test_store_deduplicates_gmail_messages_and_tracks_state(tmp_path):
    store = JobStore(tmp_path / "state.db")
    job = store.create_job("gmail-1", "accounting@example.com", "Báo cáo tháng")
    assert job and job["state"] == "queued"
    assert store.create_job("gmail-1", "accounting@example.com") is None
    store.transition(job["id"], "fetching")
    store.transition(job["id"], "extracting")
    assert store.get(job["id"])["state"] == "extracting"


def test_report_schema_requires_all_business_sections():
    payload = {
        "executive_summary": "Doanh thu tăng nhưng biên lợi nhuận giảm.",
        "performance": [], "tax_risks": [], "missing_data": [], "recommendations": [], "confidence": 0.82,
    }
    assert parse_report(json.dumps(payload))["confidence"] == 0.82
