from __future__ import annotations

import json
from copy import deepcopy

import pytest

from taxsentry import config as config_module
from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.reporting import REPORT_SCHEMA, normalize_report, parse_report
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
    assert normalize_report(payload)["schema_version"] == 2


def test_report_schema_is_strict_at_every_object_level():
    assert REPORT_SCHEMA["additionalProperties"] is False
    for name in ("metrics", "findings", "tax_risks", "recommendations", "sources"):
        assert REPORT_SCHEMA["properties"][name]["items"]["additionalProperties"] is False


def test_report_parser_rejects_formatted_financial_strings_and_unknown_fields():
    report = normalize_report(
        {
            "executive_summary": "Test",
            "performance": [],
            "tax_risks": [],
            "missing_data": [],
            "recommendations": [],
            "confidence": 0.9,
        }
    )
    report.pop("confidence")
    report["metrics"] = [
        {
            "id": "revenue",
            "label": "Doanh thu",
            "current": "120.000.000 VND",
            "previous": None,
            "budget": None,
            "benchmark": None,
            "unit": "VND",
            "source_ids": ["input:1"],
            "assessment": "",
        }
    ]
    report["sources"] = [
        {
            "id": "input:1",
            "kind": "file",
            "title": "data.xlsx",
            "locator": "data.xlsx",
            "fetched_at": "",
            "effective_from": "",
            "verified_current": True,
        }
    ]
    with pytest.raises(ValueError, match="must be number or null"):
        parse_report(json.dumps(report))
    report["metrics"][0]["current"] = 120_000_000
    report["unexpected"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        parse_report(json.dumps(report))


def test_automatic_retry_keeps_its_budget(tmp_path):
    store = JobStore(tmp_path / "retry.db")
    job = store.create_job("gmail-1:sha", "accounting@example.com")
    for attempt in range(1, 4):
        store.transition(job["id"], "fetching")
        assert store.increment_retry(job["id"], "provider error") == attempt
        store.requeue(job["id"], reset_retries=False)
    assert store.get(job["id"])["retries"] == 3
