from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from taxsentry.advisory import apply_grounding, build_analysis_context, review_reasons

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "advisory_cases.json").read_text(
        encoding="utf-8"
    )
)


def _report(
    *,
    revenue=100,
    confidence=0.9,
    risk="",
    legal_verified=True,
    material_missing=False,
    impact=None,
    priority="medium",
):
    metrics = (
        [
            {
                "id": "revenue",
                "label": "Doanh thu",
                "current": revenue,
                "previous": None,
                "budget": None,
                "benchmark": None,
                "unit": "VND",
                "source_ids": ["input:1"],
                "assessment": "",
            }
        ]
        if revenue is not None
        else []
    )
    sources = [
        {
            "id": "input:1",
            "kind": "file",
            "title": "data.xlsx",
            "locator": "data.xlsx",
            "fetched_at": "",
            "effective_from": "",
            "verified_current": True,
        },
        {
            "id": "knowledge:law",
            "kind": "knowledge",
            "title": "Văn bản",
            "locator": "https://vanban.chinhphu.vn/",
            "fetched_at": "",
            "effective_from": "",
            "verified_current": legal_verified,
        },
    ]
    return {
        "schema_version": 2,
        "profile": "cfo_brief",
        "decision_question": "",
        "period": {"label": "", "start": "", "end": ""},
        "executive_summary": "",
        "metrics": metrics,
        "findings": [],
        "scenario_model": {
            "model_type": "none",
            "drivers": [],
            "primary_output": "",
            "scenarios": [],
        },
        "tax_risks": (
            [
                {
                    "severity": risk,
                    "title": "Rủi ro",
                    "evidence_ids": ["input:1"],
                    "regulation": "Văn bản",
                    "legal_source_ids": ["knowledge:law"],
                    "required_documents": [],
                    "confidence": 0.9,
                }
            ]
            if risk
            else []
        ),
        "recommendations": (
            [
                {
                    "priority": priority,
                    "action": "Hành động",
                    "rationale": "Lý do",
                    "owner": "CFO",
                    "deadline_days": 30,
                    "estimated_impact_vnd": impact,
                    "effort": "low",
                    "evidence_ids": ["input:1"],
                    "confidence": 0.9,
                }
            ]
            if impact is not None or priority == "high"
            else []
        ),
        "sources": sources,
        "missing_data": (
            [
                {
                    "field": "invoice",
                    "impact": "Thiếu chứng từ",
                    "material": material_missing,
                }
            ]
            if material_missing is not None
            else []
        ),
        "assumptions": [],
        "overall_confidence": confidence,
    }


def _context(values: dict) -> dict:
    canonical = {
        key: {"value": value}
        for key, value in values.items()
        if key
        in {"revenue", "cogs", "gross_profit", "total_opex", "ebt", "tax_expense", "net_income"}
    }
    line_items = []
    if "revenue_previous" in values or "revenue_budget" in values:
        periods = {"Kỳ Này": values["revenue"]}
        if "revenue_previous" in values:
            periods["Kỳ Trước"] = values["revenue_previous"]
        if "revenue_budget" in values:
            periods["Kế hoạch"] = values["revenue_budget"]
        line_items.append({"label": "Doanh thu", "values": periods})
    return build_analysis_context(
        [
            {
                "file": "data.xlsx",
                "source": "xlsx",
                "content": {
                    "data": {
                        "canonical_metrics": canonical,
                        "sheets": [{"line_items": line_items}],
                    }
                },
            }
        ]
    )


@pytest.mark.parametrize("case", [item for item in CASES if item["category"] == "cfo"], ids=lambda item: item["id"])
def test_cfo_cases_use_deterministic_calculations(case):
    context = _context(case["metrics"])
    report = apply_grounding(_report(), context)
    if case["expected_metric"] == "scenario_base_net":
        actual = next(
            item["net_income_vnd"]
            for item in report["scenario_model"]["scenarios"]
            if item["name"] == "base"
        )
    else:
        actual = next(
            item["current"]
            for item in report["metrics"]
            if item["id"] == case["expected_metric"]
        )
    assert actual == pytest.approx(case["expected_value"])


@pytest.mark.parametrize("case", [item for item in CASES if item["category"] == "tax"], ids=lambda item: item["id"])
def test_tax_cases_enforce_sources_and_review(case):
    report = _report(
        risk=case["risk"],
        legal_verified=case["legal_verified"],
        material_missing=case.get("material_missing"),
    )
    assert bool(review_reasons(report, {"report": {"minimum_confidence": 0.7}})) is case["expected_review"]


@pytest.mark.parametrize("case", [item for item in CASES if item["category"] == "mixed"], ids=lambda item: item["id"])
def test_mixed_cases_enforce_materiality_and_confidence(case):
    report = _report(
        revenue=case["revenue"],
        confidence=case["confidence"],
        impact=case["impact"],
        priority=case.get("priority", "medium"),
        material_missing=None,
    )
    settings = {
        "report": {"minimum_confidence": 0.7},
        "advisor": {"company": {"materiality_ratio": 0.05}},
    }
    assert bool(review_reasons(report, settings)) is case["expected_review"]


def test_unverified_benchmark_is_removed():
    context = _context({"revenue": 100})
    report = _report()
    report["metrics"][0]["benchmark"] = 90
    grounded = apply_grounding(report, context)
    assert grounded["metrics"][0]["benchmark"] is None
    assert any(item["field"] == "benchmark:revenue" for item in grounded["missing_data"])


@pytest.mark.parametrize(
    ("age_days", "industry", "expected"),
    [(30, "Bán lẻ", 90), (25 * 31, "Bán lẻ", None), (30, "Sản xuất", None)],
)
def test_benchmark_requires_matching_industry_scope_and_fresh_period(
    age_days,
    industry,
    expected,
):
    context = _context({"revenue": 100})
    context["company"] = {"industry": "Bán lẻ"}
    period_end = (datetime.now(timezone.utc) - timedelta(days=age_days)).date()
    benchmark = {
        "id": "benchmark:retail",
        "kind": "benchmark",
        "title": "Retail benchmark",
        "locator": "https://benchmark.example/retail",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "effective_from": period_end.isoformat(),
        "verified_current": True,
        "industry": industry,
        "scope": "Việt Nam",
        "data_period_end": period_end.isoformat(),
    }
    context["sources"].append(benchmark)
    report = _report()
    report["metrics"][0]["benchmark"] = 90
    report["metrics"][0]["source_ids"].append(benchmark["id"])
    report["sources"].append(
        {
            key: benchmark[key]
            for key in (
                "id",
                "kind",
                "title",
                "locator",
                "fetched_at",
                "effective_from",
                "verified_current",
            )
        }
    )

    grounded = apply_grounding(report, context)
    assert grounded["metrics"][0]["benchmark"] == expected
