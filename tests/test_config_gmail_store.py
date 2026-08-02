from __future__ import annotations

import json
from copy import deepcopy

import pytest

from taxsentry import config as config_module
from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.reporting import REPORT_SCHEMA, normalize_report, normalize_report_v3, parse_report
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


def test_job_and_report_queries_are_company_scoped(tmp_path):
    store = JobStore(tmp_path / "companies.db")
    alpha = store.create_job(
        "gmail-shared",
        "alpha@example.test",
        company_id="alpha",
    )
    beta = store.create_job(
        "gmail-shared",
        "beta@example.test",
        company_id="beta",
    )
    assert alpha and beta
    store.report(alpha["id"], {"company": "alpha"}, 1.0)
    store.report(beta["id"], {"company": "beta"}, 1.0)

    assert store.by_message("gmail-shared", company_id="alpha")["id"] == alpha["id"]
    assert store.by_message("gmail-shared", company_id="beta")["id"] == beta["id"]
    assert store.resolve(company_id="alpha")["id"] == alpha["id"]
    assert [job["id"] for job in store.recent_jobs(company_id="beta")] == [
        beta["id"]
    ]
    assert store.latest_report(company_id="alpha")["payload"]["company"] == "alpha"
    assert store.state_counts(company_id="alpha")["queued"] == 1


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


def test_report_v3_adapter_preserves_currency_and_evidence():
    legacy = normalize_report({
        "executive_summary": "USD report",
        "performance": [],
        "tax_risks": [],
        "missing_data": [],
        "recommendations": [],
        "confidence": 0.9,
    })
    legacy["metrics"] = [{"id": "revenue", "label": "Revenue", "current": 43.5, "previous": None, "budget": None, "benchmark": None, "unit": "USD", "source_ids": ["s"], "assessment": ""}]
    legacy["sources"] = [{"id": "s", "kind": "file", "title": "statement", "locator": "sheet=PL;cell=C5", "fetched_at": "", "effective_from": "", "verified_current": True}]
    v3 = normalize_report_v3(legacy)
    parsed = parse_report(json.dumps(v3))
    assert parsed["schema_version"] == 3
    assert parsed["metrics"][0]["current"]["currency"] == "USD"
    assert parsed["metrics"][0]["current"]["evidence_ids"] == ["s"]


def test_report_v3_adapter_converts_legacy_vnd_scenarios_and_impacts():
    legacy = normalize_report({
        "executive_summary": "Legacy report",
        "performance": [],
        "tax_risks": [],
        "missing_data": [],
        "recommendations": [],
        "confidence": 0.9,
    })
    legacy["sources"] = [{"id": "s", "kind": "file", "title": "statement", "locator": "sheet=PL;cell=C5", "fetched_at": "", "effective_from": "", "verified_current": True}]
    legacy["scenario_model"] = {
        "model_type": "pnl_driver",
        "drivers": [{"key": "growth", "label": "Growth", "base": 0.1, "downside": 0.0, "upside": 0.2, "unit": "%", "source_ids": []}],
        "primary_output": "revenue",
        "scenarios": [{"name": "base", "assumptions": "Driver is illustrative.", "revenue_vnd": 100, "net_income_vnd": 10, "cash_effect_vnd": 5}],
    }
    legacy["findings"] = [{"id": "f1", "category": "cash", "severity": "high", "statement": "Cash mismatch", "root_cause": "Source disagreement", "estimated_impact_vnd": 20, "assumptions": ["Legacy range"], "evidence_ids": [], "confidence": 0.8}]
    v3 = normalize_report_v3(legacy)
    parsed = parse_report(json.dumps(v3))
    scenario = parsed["scenario_model"]["scenarios"][0]
    assert scenario["revenue"]["currency"] == "VND"
    assert scenario["revenue"]["normalized_value"] == "100"
    assert scenario["revenue"]["scenario"] == "base"
    impact = parsed["findings"][0]["impact_estimate"]
    assert impact["label"] == "EXPERT_ESTIMATE"
    assert impact["base"]["currency"] == "VND"
    assert impact["base"]["confidence"] <= 0.60

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not any(str(key).endswith("_vnd") for key in keys(parsed))


def test_report_v3_rejects_unknown_money_currency():
    legacy = normalize_report({
        "executive_summary": "Legacy report",
        "performance": [],
        "tax_risks": [],
        "missing_data": [],
        "recommendations": [],
        "confidence": 0.9,
    })
    legacy["metrics"] = [{"id": "revenue", "label": "Revenue", "current": 10, "previous": None, "budget": None, "benchmark": None, "unit": "USD", "source_ids": ["s"], "assessment": ""}]
    legacy["sources"] = [{"id": "s", "kind": "file", "title": "statement", "locator": "sheet=PL;cell=C5", "fetched_at": "", "effective_from": "", "verified_current": True}]
    report = normalize_report_v3(legacy)
    report["metrics"][0]["current"]["currency"] = "ZZZ"
    with pytest.raises(ValueError, match="unknown ISO currency"):
        parse_report(json.dumps(report))


def test_legacy_scenario_uses_metric_currency_in_v3():
    legacy = normalize_report({
        "executive_summary": "Legacy report",
        "performance": [],
        "tax_risks": [],
        "missing_data": [],
        "recommendations": [],
        "confidence": 0.9,
    })
    legacy["metrics"] = [{"id": "revenue", "label": "Revenue", "current": 43_500_000_000, "previous": None, "budget": None, "benchmark": None, "unit": "USD", "source_ids": ["s"], "assessment": ""}]
    legacy["sources"] = [{"id": "s", "kind": "file", "title": "statement", "locator": "sheet=PL;cell=C5", "fetched_at": "", "effective_from": "", "verified_current": True}]
    legacy["scenario_model"] = {"model_type": "percentage_change", "drivers": [], "primary_output": "revenue", "scenarios": [{"name": "base", "assumptions": "", "revenue_vnd": 43_500_000_000, "net_income_vnd": None, "cash_effect_vnd": None}]}
    report = normalize_report_v3(legacy)
    assert report["scenario_model"]["scenarios"][0]["revenue"]["currency"] == "USD"


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
