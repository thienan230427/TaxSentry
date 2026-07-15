from __future__ import annotations

import json
from copy import deepcopy

from taxsentry import config as config_module
from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.reporting import parse_report
from taxsentry.store import JobStore


def test_save_removes_legacy_gmail_oauth_fields(monkeypatch, tmp_path):
    settings = deepcopy(DEFAULT_SETTINGS)
    settings["gmail"].update({"auth_mode": "oauth", "oauth_client_file": "credentials.json", "trusted_senders": ["old@example.com"]})
    settings["director"]["email"] = "director@example.com"
    target = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", target)
    monkeypatch.setattr(config_module, "ensure_directories", lambda: None)

    config_module.save_config(settings)

    gmail = json.loads(target.read_text(encoding="utf-8"))["gmail"]
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert "auth_mode" not in gmail and "oauth_client_file" not in gmail and "trusted_senders" not in gmail
    assert "email" not in saved["director"]


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


def test_old_config_ui_language_falls_back_to_agent_language(monkeypatch, tmp_path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"agent": {"language": "en"}, "ui": {"theme": "sentinel"}}), encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_FILE", target)
    assert config_module.load_config()["ui"]["language"] == "en"
    target.write_text(json.dumps({"agent": {"language": "fr"}, "ui": {"language": "fr"}}), encoding="utf-8")
    assert config_module.load_config()["ui"]["language"] == "vi"


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
