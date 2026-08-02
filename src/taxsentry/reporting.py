from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .measurements import ISO4217_CODES

NUMBER = {"type": ["number", "null"]}
STRING_LIST = {"type": "array", "items": {"type": "string"}}
PROFILES = (
    "cfo_brief",
    "tax_risk_memo",
    "cashflow_advisory",
    "performance_review",
    "scenario_plan",
)


def _strict(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SOURCE_SCHEMA = _strict(
    {
        "id": {"type": "string"},
        "kind": {
            "type": "string",
            "enum": ["file", "email", "history", "knowledge", "benchmark"],
        },
        "title": {"type": "string"},
        "locator": {"type": "string"},
        "fetched_at": {"type": "string"},
        "effective_from": {"type": "string"},
        "verified_current": {"type": "boolean"},
    }
)
METRIC_SCHEMA = _strict(
    {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "current": NUMBER,
        "previous": NUMBER,
        "budget": NUMBER,
        "benchmark": NUMBER,
        "unit": {"type": "string", "pattern": "^(?:[A-Z]{3}|%|days|count|ratio)$"},
        "source_ids": STRING_LIST,
        "assessment": {"type": "string"},
    }
)
FINDING_SCHEMA = _strict(
    {
        "id": {"type": "string"},
        "category": {"type": "string"},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
        "statement": {"type": "string"},
        "root_cause": {"type": "string"},
        "estimated_impact_vnd": NUMBER,
        "assumptions": STRING_LIST,
        "evidence_ids": STRING_LIST,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
)
DRIVER_SCHEMA = _strict(
    {
        "key": {"type": "string"},
        "label": {"type": "string"},
        "base": {"type": "number"},
        "downside": {"type": "number"},
        "upside": {"type": "number"},
        "unit": {"type": "string", "pattern": "^(?:[A-Z]{3}|%|days|count|ratio)$"},
        "source_ids": STRING_LIST,
    }
)
SCENARIO_SCHEMA = _strict(
    {
        "name": {"type": "string", "enum": ["downside", "base", "upside"]},
        "assumptions": {"type": "string"},
        "revenue_vnd": NUMBER,
        "net_income_vnd": NUMBER,
        "cash_effect_vnd": NUMBER,
    }
)
RISK_SCHEMA = _strict(
    {
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
        "title": {"type": "string"},
        "evidence_ids": STRING_LIST,
        "regulation": {"type": "string"},
        "legal_source_ids": STRING_LIST,
        "required_documents": STRING_LIST,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
)
RECOMMENDATION_SCHEMA = _strict(
    {
        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        "action": {"type": "string"},
        "rationale": {"type": "string"},
        "owner": {"type": "string"},
        "deadline_days": {"type": ["integer", "null"], "minimum": 0},
        "estimated_impact_vnd": NUMBER,
        "effort": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence_ids": STRING_LIST,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
)
MISSING_SCHEMA = _strict(
    {
        "field": {"type": "string"},
        "impact": {"type": "string"},
        "material": {"type": "boolean"},
    }
)

REPORT_SCHEMA: dict[str, Any] = _strict(
    {
        "schema_version": {"type": "integer", "enum": [2]},
        "profile": {"type": "string", "enum": list(PROFILES)},
        "decision_question": {"type": "string"},
        "period": _strict(
            {
                "label": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
            }
        ),
        "executive_summary": {"type": "string"},
        "metrics": {"type": "array", "items": METRIC_SCHEMA},
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "scenario_model": _strict(
            {
                "model_type": {
                    "type": "string",
                    "enum": ["none", "pnl_driver", "percentage_change"],
                },
                "drivers": {"type": "array", "items": DRIVER_SCHEMA},
                "primary_output": {"type": "string"},
                "scenarios": {"type": "array", "items": SCENARIO_SCHEMA},
            }
        ),
        "tax_risks": {"type": "array", "items": RISK_SCHEMA},
        "recommendations": {"type": "array", "items": RECOMMENDATION_SCHEMA},
        "sources": {"type": "array", "items": SOURCE_SCHEMA},
        "missing_data": {"type": "array", "items": MISSING_SCHEMA},
        "assumptions": STRING_LIST,
        "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
)

OBSERVATION_SCHEMA = _strict(
    {
        "raw_value": {"type": "string"},
        "normalized_value": {"type": ["string", "null"]},
        "measure": {"type": "string", "enum": ["money", "percentage", "ratio", "days", "count"]},
        "currency": {"type": ["string", "null"], "pattern": "^[A-Z]{3}$"},
        "scale_multiplier": {"type": "string"},
        "display_unit": {"type": "string"},
        "period": _strict(
            {
                "label": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "basis": {"type": "string", "enum": ["actual", "forecast", "estimate", "budget", "benchmark"]},
            }
        ),
        "scenario": {"type": "string", "enum": ["none", "base", "bull", "bear"]},
        "status": {"type": "string", "enum": ["reported", "calculated", "assumption", "expert_estimate", "missing", "conflict"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_ids": STRING_LIST,
    }
)
OBSERVATION_OR_NULL = {"type": ["object", "null"], "properties": OBSERVATION_SCHEMA["properties"], "required": OBSERVATION_SCHEMA["required"], "additionalProperties": False}
EVIDENCE_REF_SCHEMA = _strict(
    {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": ["file", "email", "history", "knowledge", "benchmark"]},
        "document_id": {"type": "string"},
        "file_hash": {"type": "string"},
        "title": {"type": "string"},
        "locator": {"type": "string"},
        "sheet": {"type": "string"},
        "cell": {"type": "string"},
        "page": {"type": ["integer", "null"]},
        "table": {"type": "string"},
        "row_label": {"type": "string"},
        "formula": {"type": "string"},
        "number_format": {"type": "string"},
        "effective_at": {"type": "string"},
        "effective_to": {"type": "string"},
        "retrieved_at": {"type": "string"},
        "verified_at": {"type": "string"},
        "authority": {"type": "string"},
        "jurisdiction": {"type": "string"},
        "topic": {"type": "string"},
        "industry": {"type": "string"},
        "scope": {"type": "string"},
        "url": {"type": "string"},
        "checksum": {"type": "string"},
        "status": {"type": "string"},
        "verified_current": {"type": "boolean"},
    }
)
METRIC_V3_SCHEMA = _strict(
    {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "current": OBSERVATION_OR_NULL,
        "previous": OBSERVATION_OR_NULL,
        "budget": OBSERVATION_OR_NULL,
        "benchmark": OBSERVATION_OR_NULL,
        "assessment": {"type": "string"},
    }
)
IMPACT_ESTIMATE_SCHEMA = _strict(
    {
        "low": OBSERVATION_OR_NULL,
        "base": OBSERVATION_OR_NULL,
        "high": OBSERVATION_OR_NULL,
        "method": {"type": "string"},
        "drivers": STRING_LIST,
        "assumption_ids": STRING_LIST,
        "evidence_ids": STRING_LIST,
        "label": {"type": "string", "enum": ["EXPERT_ESTIMATE", "REPORTED", "CALCULATED"]},
    }
)
IMPACT_ESTIMATE_OR_NULL = {
    "type": ["object", "null"],
    "properties": IMPACT_ESTIMATE_SCHEMA["properties"],
    "required": IMPACT_ESTIMATE_SCHEMA["required"],
    "additionalProperties": False,
}
ASSUMPTION_SCHEMA = _strict(
    {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "owner": {"type": "string"},
        "as_of": {"type": "string"},
        "impact": {"type": "string"},
    }
)
CHECK_SCHEMA_V3 = _strict(
    {
        "id": {"type": "string"},
        "status": {"type": "string", "enum": ["PASS", "WARN", "FAIL"]},
        "actual": {"type": ["string", "null"]},
        "expected": {"type": ["string", "null"]},
        "delta": {"type": ["string", "null"]},
        "tolerance": {"type": "string"},
        "evidence_ids": STRING_LIST,
        "where_to_fix": {"type": "string"},
    }
)
REPORT_SCHEMA_V3: dict[str, Any] = _strict(
    {
        "schema_version": {"type": "integer", "enum": [3]},
        "profile": {"type": "string", "enum": list(PROFILES)},
        "decision_question": {"type": "string"},
        "report_context": _strict(
            {
                "company_id": {"type": "string"},
                "jurisdiction": {"type": "string"},
                "primary_period": {"type": "string"},
                "basis": {"type": "string", "enum": ["actual", "forecast", "estimate", "budget", "benchmark"]},
                "scenario": {"type": "string", "enum": ["none", "base", "bull", "bear"]},
                "source_hashes": STRING_LIST,
                "generated_at": {"type": "string"},
            }
        ),
        "executive_summary": {"type": "string"},
        "metrics": {"type": "array", "items": METRIC_V3_SCHEMA},
        "findings": {"type": "array", "items": _strict({
            "id": {"type": "string"}, "category": {"type": "string"}, "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            "statement": {"type": "string"}, "root_cause": {"type": "string"}, "impact_estimate": IMPACT_ESTIMATE_OR_NULL, "evidence_ids": STRING_LIST,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        })},
        "scenario_model": _strict({
            "model_type": {"type": "string", "enum": ["none", "pnl_driver", "percentage_change"]},
            "drivers": {"type": "array", "items": _strict({"key": {"type": "string"}, "label": {"type": "string"}, "base": OBSERVATION_OR_NULL, "downside": OBSERVATION_OR_NULL, "upside": OBSERVATION_OR_NULL, "source_ids": STRING_LIST})},
            "primary_output": {"type": "string"},
            "scenarios": {"type": "array", "items": _strict({"name": {"type": "string", "enum": ["downside", "base", "upside"]}, "assumptions": {"type": "string"}, "revenue": OBSERVATION_OR_NULL, "net_income": OBSERVATION_OR_NULL, "cash_effect": OBSERVATION_OR_NULL})},
        }),
        "tax_risks": {"type": "array", "items": RISK_SCHEMA},
        "recommendations": {"type": "array", "items": _strict({
            "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "action": {"type": "string"}, "rationale": {"type": "string"}, "owner": {"type": "string"}, "deadline_days": {"type": ["integer", "null"], "minimum": 0}, "impact_estimate": IMPACT_ESTIMATE_OR_NULL, "effort": {"type": "string", "enum": ["low", "medium", "high"]}, "evidence_ids": STRING_LIST, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        })},
        "sources": {"type": "array", "items": EVIDENCE_REF_SCHEMA},
        "missing_data": {"type": "array", "items": MISSING_SCHEMA},
        "assumptions": {"type": "array", "items": ASSUMPTION_SCHEMA},
        "reconciliation_checks": {"type": "array", "items": CHECK_SCHEMA_V3},
        "data_quality": _strict({"coverage": {"type": "number", "minimum": 0, "maximum": 1}, "conflict_count": {"type": "integer", "minimum": 0}, "missing_material_fields": STRING_LIST, "confidence_caps": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}}, "review_reasons": STRING_LIST}),
        "approval": _strict({"status": {"type": "string", "enum": ["draft", "needs_review", "approved"]}, "reasons": STRING_LIST}),
        "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
)


def parse_report(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Provider did not return a JSON report")
    report = json.loads(text[start : end + 1])
    if not isinstance(report, dict):
        raise ValueError("Provider report must be an object")
    if report.get("schema_version") == 3:
        _validate_schema(report, REPORT_SCHEMA_V3, "report")
        _validate_evidence_v3(report)
        report["overall_confidence"] = max(0.0, min(1.0, float(report["overall_confidence"])))
        return report
    legacy = report.get("schema_version") != 2
    report = normalize_report(report)
    schema_value = (
        {key: value for key, value in report.items() if key != "confidence"}
        if legacy
        else report
    )
    _validate_schema(schema_value, REPORT_SCHEMA, "report")
    _validate_evidence(report)
    report["overall_confidence"] = max(
        0.0, min(1.0, float(report["overall_confidence"]))
    )
    return report


def normalize_report_v3(report: dict[str, Any]) -> dict[str, Any]:
    """Adapt v2 data to v3 while retaining facts and legacy ``*_vnd`` values."""
    if report.get("schema_version") == 3:
        return report
    legacy = normalize_report(report)
    period = dict(legacy.get("period", {}))
    context = report.get("report_context") if isinstance(report.get("report_context"), dict) else {}
    context = context or (report.get("_v3_report_context") if isinstance(report.get("_v3_report_context"), dict) else {})
    try:
        overall_confidence = max(0.0, min(1.0, float(legacy.get("overall_confidence", 0))))
    except (TypeError, ValueError):
        overall_confidence = 0.0
    allowed_basis = {"actual", "forecast", "estimate", "budget", "benchmark"}
    allowed_scenarios = {"none", "base", "bull", "bear"}
    assumptions_by_id: dict[str, dict[str, str]] = {}

    def add_assumption(identifier: str, text: Any, *, owner: Any = "", as_of: Any = "", impact: Any = "") -> str:
        key = str(identifier or f"legacy_assumption_{len(assumptions_by_id) + 1}")
        assumptions_by_id.setdefault(key, {"id": key, "text": str(text or ""), "owner": str(owner or ""), "as_of": str(as_of or ""), "impact": str(impact or "")})
        return key

    for item in report.get("_v3_assumptions", []) if isinstance(report.get("_v3_assumptions"), list) else []:
        if isinstance(item, dict):
            add_assumption(item.get("id"), item.get("text"), owner=item.get("owner"), as_of=item.get("as_of"), impact=item.get("impact"))
    for index, value in enumerate(legacy.get("assumptions", []), 1):
        if isinstance(value, dict):
            add_assumption(value.get("id") or f"assumption_{index}", value.get("text"), owner=value.get("owner"), as_of=value.get("as_of"), impact=value.get("impact"))
        else:
            add_assumption(f"assumption_{index}", value)

    def legacy_assumption_ids(item: dict[str, Any], prefix: str) -> list[str]:
        ids = [str(value) for value in item.get("assumption_ids", []) if str(value)]
        raw_assumptions = item.get("assumptions", [])
        if isinstance(raw_assumptions, str):
            raw_assumptions = [raw_assumptions] if raw_assumptions else []
        for index, value in enumerate(raw_assumptions, 1):
            if isinstance(value, dict):
                identifier = add_assumption(value.get("id") or f"{prefix}_{index}", value.get("text"), owner=value.get("owner"), as_of=value.get("as_of"), impact=value.get("impact"))
            else:
                identifier = add_assumption(f"{prefix}_{index}", value)
            ids.append(identifier)
        for identifier in ids:
            if identifier not in assumptions_by_id:
                add_assumption(identifier, "Legacy v2 assumption; source detail was not available.")
        return list(dict.fromkeys(ids))

    def observation(
        value: Any,
        unit: str = "",
        *,
        status: str = "reported",
        evidence_ids: list[str] | None = None,
        scenario: str = "none",
        basis: str | None = None,
        source_measurement: dict[str, Any] | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any] | None:
        source = dict(source_measurement or {})
        if isinstance(value, dict) and "normalized_value" in value:
            source = {**source, **value}
            value = source.get("normalized_value")
        if value is None and source.get("normalized_value") is None:
            return None
        measure = str(source.get("measure") or ("percentage" if unit == "%" else "days" if unit == "days" else "count" if unit == "count" else "money"))
        if measure not in {"money", "percentage", "ratio", "days", "count"}:
            measure = "money"
        currency = str(source.get("currency") or "") or None
        if measure == "money" and not currency and re.fullmatch(r"[A-Z]{3}", str(unit or "")):
            currency = str(unit).upper()
        if measure != "money":
            currency = None
        period_source = source.get("period") if isinstance(source.get("period"), dict) else {}
        resolved_basis = str(period_source.get("basis") or basis or context.get("basis") or "actual")
        if resolved_basis not in allowed_basis:
            resolved_basis = "actual"
        resolved_scenario = str(source.get("scenario") or scenario or "none")
        if resolved_scenario not in allowed_scenarios:
            resolved_scenario = "none"
        ids = list(dict.fromkeys([*(source.get("evidence_ids", []) if isinstance(source.get("evidence_ids"), list) else []), *(evidence_ids or [])]))
        normalized = source.get("normalized_value")
        if normalized is None:
            normalized = str(value)
        final_status = str(source.get("status") or status)
        if final_status not in {"reported", "calculated", "assumption", "expert_estimate", "missing", "conflict"}:
            final_status = status
        if measure == "money" and not currency and normalized is not None:
            final_status, normalized = "conflict", None
        try:
            resolved_confidence = float(source.get("confidence", confidence if confidence is not None else overall_confidence))
        except (TypeError, ValueError):
            resolved_confidence = overall_confidence
        if final_status == "expert_estimate":
            resolved_confidence = min(resolved_confidence, 0.60)
        elif final_status == "assumption":
            resolved_confidence = min(resolved_confidence, 0.70)
        return {
            "raw_value": str(source.get("raw_value", value if value is not None else "")),
            "normalized_value": str(normalized) if normalized is not None else None,
            "measure": measure,
            "currency": currency,
            "scale_multiplier": str(source.get("scale_multiplier") or "1"),
            "display_unit": str(source.get("display_unit") or unit or measure),
            "period": {
                "label": str(period_source.get("label") or period.get("label", context.get("primary_period", ""))),
                "start": str(period_source.get("start") or period.get("start", "")),
                "end": str(period_source.get("end") or period.get("end", "")),
                "basis": resolved_basis,
            },
            "scenario": resolved_scenario,
            "status": final_status,
            "confidence": max(0.0, min(1.0, resolved_confidence)),
            "evidence_ids": ids,
        }

    def clean_impact(value: Any, *, item: dict[str, Any], prefix: str, index: int) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            legacy_value = item.get("estimated_impact_vnd")
            if legacy_value is None:
                return None
            evidence_ids = [str(value) for value in item.get("evidence_ids", []) if str(value)]
            assumption_ids = legacy_assumption_ids(item, f"{prefix}_{index}_assumption")
            if not evidence_ids and not assumption_ids:
                assumption_ids = [add_assumption(f"{prefix}_{index}_assumption", "Legacy v2 estimated impact; source range was not available.")]
            return {
                "low": None,
                "base": observation(legacy_value, "VND", status="expert_estimate", evidence_ids=evidence_ids, basis="estimate", confidence=0.60),
                "high": None,
                "method": "Legacy v2 estimated_impact_vnd; source range unavailable.",
                "drivers": [],
                "assumption_ids": assumption_ids,
                "evidence_ids": evidence_ids,
                "label": "EXPERT_ESTIMATE",
            }
        evidence_ids = [str(value) for value in value.get("evidence_ids", []) if str(value)]
        assumption_ids = [str(value) for value in value.get("assumption_ids", []) if str(value)]
        for identifier in assumption_ids:
            if identifier not in assumptions_by_id:
                add_assumption(identifier, "Estimate assumption retained from the source report.")
        if not evidence_ids and not assumption_ids:
            assumption_ids = [add_assumption(f"{prefix}_{index}_assumption", "Estimate retained from a report without explicit source lineage.")]
        observations = {
            role: observation(value.get(role), "", status=str(value.get(role, {}).get("status", "expert_estimate")) if isinstance(value.get(role), dict) else "expert_estimate", evidence_ids=evidence_ids, basis="estimate", source_measurement=value.get(role) if isinstance(value.get(role), dict) else None, confidence=0.60)
            for role in ("low", "base", "high")
        }
        label = str(value.get("label") or "EXPERT_ESTIMATE")
        if label not in {"EXPERT_ESTIMATE", "REPORTED", "CALCULATED"}:
            label = "EXPERT_ESTIMATE"
        return {
            **observations,
            "method": str(value.get("method") or "Report-supplied estimate."),
            "drivers": [str(item) for item in value.get("drivers", [])],
            "assumption_ids": assumption_ids,
            "evidence_ids": evidence_ids,
            "label": label,
        }

    source_records: dict[str, dict[str, Any]] = {}
    for source in [
        *(report.get("_v3_sources", []) if isinstance(report.get("_v3_sources"), list) else []),
        *legacy.get("sources", []),
    ]:
        if not isinstance(source, dict) or not source.get("id"):
            continue
        identifier = str(source["id"])
        page = source.get("page")
        if not isinstance(page, int) or isinstance(page, bool):
            page = int(page) if str(page or "").isdigit() else None
        kind = str(source.get("kind", "file"))
        if kind not in {"file", "email", "history", "knowledge", "benchmark"}:
            kind = "file"
        previous = source_records.get(identifier, {})
        source_records[identifier] = {
            **previous,
            "id": identifier,
            "kind": kind,
            "document_id": str(source.get("document_id", "")),
            "file_hash": str(source.get("file_hash", "")),
            "title": str(source.get("title", "")),
            "locator": str(source.get("locator", "")),
            "sheet": str(source.get("sheet", "")),
            "cell": str(source.get("cell", "")),
            "page": page,
            "table": str(source.get("table", "")),
            "row_label": str(source.get("row_label", "")),
            "formula": str(source.get("formula", "")),
            "number_format": str(source.get("number_format", "")),
            "effective_at": str(source.get("effective_at", source.get("effective_from", ""))),
            "effective_to": str(source.get("effective_to", "")),
            "retrieved_at": str(source.get("retrieved_at", source.get("fetched_at", ""))),
            "verified_at": str(source.get("verified_at", "")),
            "authority": str(source.get("authority", "")),
            "jurisdiction": str(source.get("jurisdiction", "")),
            "topic": str(source.get("topic", "")),
            "industry": str(source.get("industry", "")),
            "scope": str(source.get("scope", "")),
            "url": str(source.get("url", "")),
            "checksum": str(source.get("checksum", "")),
            "status": str(source.get("status", "")),
            "verified_current": bool(source.get("verified_current", False)),
        }
        for field in ("document_id", "file_hash", "title", "locator", "sheet", "cell", "table", "row_label", "formula", "number_format", "effective_at", "effective_to", "retrieved_at", "verified_at", "authority", "jurisdiction", "topic", "industry", "scope", "url", "checksum", "status"):
            if not source.get(field) and previous.get(field):
                source_records[identifier][field] = previous[field]
        if source.get("page") is None and previous.get("page") is not None:
            source_records[identifier]["page"] = previous["page"]
        if not source.get("verified_current") and previous.get("verified_current"):
            source_records[identifier]["verified_current"] = previous["verified_current"]

    metrics = []
    for item in legacy.get("metrics", []):
        evidence_ids = [str(value) for value in item.get("source_ids", []) if str(value)]
        unit = str(item.get("currency") or item.get("unit") or "")
        measurement = item.get("measurement") if isinstance(item.get("measurement"), dict) else None
        metrics.append({
            "id": str(item.get("id", "")),
            "label": str(item.get("label", "")),
            "current": observation(item.get("current"), unit, evidence_ids=evidence_ids, source_measurement=measurement),
            "previous": observation(item.get("previous"), unit, evidence_ids=evidence_ids),
            "budget": observation(item.get("budget"), unit, evidence_ids=evidence_ids),
            "benchmark": observation(item.get("benchmark"), unit, status="reported", evidence_ids=evidence_ids),
            "assessment": str(item.get("assessment", "")),
        })

    findings_input = report.get("_v3_findings") if isinstance(report.get("_v3_findings"), list) else legacy.get("findings", [])
    findings = []
    for index, item in enumerate(findings_input, 1):
        item = item if isinstance(item, dict) else {}
        findings.append({
            "id": str(item.get("id", "")),
            "category": str(item.get("category", "")),
            "severity": item.get("severity", "medium") if item.get("severity") in {"low", "medium", "high"} else "medium",
            "statement": str(item.get("statement", "")),
            "root_cause": str(item.get("root_cause", "")),
            "impact_estimate": clean_impact(item.get("impact_estimate"), item=item, prefix="finding", index=index),
            "evidence_ids": [str(value) for value in item.get("evidence_ids", []) if str(value)],
            "confidence": max(0.0, min(1.0, float(item.get("confidence", overall_confidence)))),
        })

    scenario_input = report.get("_v3_scenario_model") if isinstance(report.get("_v3_scenario_model"), dict) else None
    if scenario_input is not None and not any(
        isinstance(item, dict)
        and any(key in item for key in ("revenue", "net_income", "cash_effect"))
        for item in scenario_input.get("scenarios", [])
    ):
        scenario_input = None
    if scenario_input is not None and scenario_input.get("schema_version") is None:
        scenario_model = {
            "model_type": scenario_input.get("model_type", "none") if scenario_input.get("model_type") in {"none", "pnl_driver", "percentage_change"} else "none",
            "drivers": [dict(item) for item in scenario_input.get("drivers", []) if isinstance(item, dict)],
            "primary_output": str(scenario_input.get("primary_output", "")),
            "scenarios": [dict(item) for item in scenario_input.get("scenarios", []) if isinstance(item, dict)],
        }
    else:
        scenario_legacy = legacy.get("scenario_model", {}) if isinstance(legacy.get("scenario_model"), dict) else {}
        drivers = []
        for index, item in enumerate(scenario_legacy.get("drivers", []), 1):
            item = item if isinstance(item, dict) else {}
            unit = str(item.get("unit", ""))
            evidence_ids = [str(value) for value in item.get("source_ids", []) if str(value)]
            assumption_ids = [] if evidence_ids else [add_assumption(f"scenario_driver_{index}", "Legacy scenario driver without explicit source lineage.")]
            drivers.append({
                "key": str(item.get("key", "")), "label": str(item.get("label", "")),
                "base": observation(item.get("base"), unit, status="reported" if evidence_ids else "assumption", evidence_ids=evidence_ids, basis="estimate", scenario="base"),
                "downside": observation(item.get("downside"), unit, status="reported" if evidence_ids else "assumption", evidence_ids=evidence_ids, basis="estimate", scenario="bear"),
                "upside": observation(item.get("upside"), unit, status="reported" if evidence_ids else "assumption", evidence_ids=evidence_ids, basis="estimate", scenario="bull"),
                "source_ids": evidence_ids,
            })
        scenario_currency = next(
            (
                str(role.get("currency"))
                for metric in metrics
                for role in (metric.get("current"),)
                if isinstance(role, dict)
                and role.get("measure") == "money"
                and role.get("currency")
            ),
            "VND",
        )
        scenarios = []
        for index, item in enumerate(scenario_legacy.get("scenarios", []), 1):
            item = item if isinstance(item, dict) else {}
            name = str(item.get("name", "base"))
            scenario_name = {"downside": "bear", "upside": "bull", "base": "base"}.get(name, "base")
            assumption_ids = legacy_assumption_ids(item, f"scenario_{index}_assumption")
            evidence_ids = [str(value) for value in item.get("evidence_ids", []) if str(value)]
            if not evidence_ids and not assumption_ids:
                assumption_ids = [add_assumption(f"scenario_{index}_assumption", "Legacy scenario output without explicit source lineage.")]
            status = "reported" if evidence_ids else "assumption"
            scenarios.append({
                "name": name if name in {"downside", "base", "upside"} else "base",
                "assumptions": str(item.get("assumptions", "")),
                "revenue": observation(item.get("revenue_vnd"), scenario_currency, status=status, evidence_ids=evidence_ids, basis="estimate", scenario=scenario_name),
                "net_income": observation(item.get("net_income_vnd"), scenario_currency, status=status, evidence_ids=evidence_ids, basis="estimate", scenario=scenario_name),
                "cash_effect": observation(item.get("cash_effect_vnd"), scenario_currency, status=status, evidence_ids=evidence_ids, basis="estimate", scenario=scenario_name),
            })
        scenario_model = {"model_type": scenario_legacy.get("model_type", "none") if scenario_legacy.get("model_type") in {"none", "pnl_driver", "percentage_change"} else "none", "drivers": drivers, "primary_output": str(scenario_legacy.get("primary_output", "")), "scenarios": scenarios}

    recommendations_input = report.get("_v3_recommendations") if isinstance(report.get("_v3_recommendations"), list) else legacy.get("recommendations", [])
    recommendations = []
    for index, item in enumerate(recommendations_input, 1):
        item = item if isinstance(item, dict) else {}
        recommendations.append({
            "priority": item.get("priority", "medium") if item.get("priority") in {"low", "medium", "high"} else "medium",
            "action": str(item.get("action", "")), "rationale": str(item.get("rationale", "")), "owner": str(item.get("owner", "")),
            "deadline_days": item.get("deadline_days") if isinstance(item.get("deadline_days"), int) or item.get("deadline_days") is None else None,
            "impact_estimate": clean_impact(item.get("impact_estimate"), item=item, prefix="recommendation", index=index),
            "effort": item.get("effort", "medium") if item.get("effort") in {"low", "medium", "high"} else "medium",
            "evidence_ids": [str(value) for value in item.get("evidence_ids", []) if str(value)],
            "confidence": max(0.0, min(1.0, float(item.get("confidence", overall_confidence)))),
        })

    raw_context = {
        "company_id": str(context.get("company_id") or legacy.get("company_id", "")),
        "jurisdiction": str(context.get("jurisdiction") or legacy.get("jurisdiction", "")),
        "primary_period": str(context.get("primary_period") or period.get("label", "")),
        "basis": str(context.get("basis") or "actual"),
        "scenario": str(context.get("scenario") or "none"),
        "source_hashes": [str(value) for value in context.get("source_hashes", []) if str(value)],
        "generated_at": str(context.get("generated_at", "")),
    }
    if raw_context["basis"] not in allowed_basis:
        raw_context["basis"] = "actual"
    if raw_context["scenario"] not in allowed_scenarios:
        raw_context["scenario"] = "none"
    quality = report.get("data_quality") if isinstance(report.get("data_quality"), dict) else report.get("_v3_data_quality") if isinstance(report.get("_v3_data_quality"), dict) else {}
    missing_data = [dict(item) for item in legacy.get("missing_data", []) if isinstance(item, dict)]
    data_quality = {
        "coverage": max(0.0, min(1.0, float(quality.get("coverage", 1.0) if not isinstance(quality.get("coverage"), dict) else quality.get("coverage", {}).get("ratio", 1.0)))),
        "conflict_count": max(0, int(quality.get("conflict_count", 0))),
        "missing_material_fields": [str(value) for value in quality.get("missing_material_fields", [])] or [str(item.get("field")) for item in missing_data if item.get("material")],
        "confidence_caps": [float(value) for value in quality.get("confidence_caps", [])],
        "review_reasons": [str(value) for value in quality.get("review_reasons", [])],
    }
    approval = report.get("approval") if isinstance(report.get("approval"), dict) else {}
    approval_status = approval.get("status") if approval.get("status") in {"draft", "needs_review", "approved"} else "draft"
    return {
        "schema_version": 3,
        "profile": legacy.get("profile", "cfo_brief"),
        "decision_question": str(legacy.get("decision_question", "")),
        "report_context": raw_context,
        "executive_summary": str(legacy.get("executive_summary", "")),
        "metrics": metrics,
        "findings": findings,
        "scenario_model": scenario_model,
        "tax_risks": [
            {"severity": item.get("severity", "medium"), "title": str(item.get("title", "")), "evidence_ids": [str(value) for value in item.get("evidence_ids", []) if str(value)], "regulation": str(item.get("regulation", "")), "legal_source_ids": [str(value) for value in item.get("legal_source_ids", []) if str(value)], "required_documents": [str(value) for value in item.get("required_documents", [])], "confidence": max(0.0, min(1.0, float(item.get("confidence", overall_confidence))))}
            for item in legacy.get("tax_risks", []) if isinstance(item, dict)
        ],
        "recommendations": recommendations,
        "sources": list(source_records.values()),
        "missing_data": missing_data,
        "assumptions": list(assumptions_by_id.values()),
        "reconciliation_checks": [
            {"id": str(item.get("id", "")), "status": item.get("status", "WARN") if item.get("status") in {"PASS", "WARN", "FAIL"} else "WARN", "actual": item.get("actual"), "expected": item.get("expected"), "delta": item.get("delta"), "tolerance": str(item.get("tolerance", "0")), "evidence_ids": [str(value) for value in item.get("evidence_ids", []) if str(value)], "where_to_fix": str(item.get("where_to_fix", ""))}
            for item in legacy.get("reconciliation_checks", []) if isinstance(item, dict)
        ],
        "data_quality": data_quality,
        "approval": {"status": approval_status, "reasons": [str(value) for value in approval.get("reasons", [])]},
        "overall_confidence": overall_confidence,
    }


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    allowed_types = schema.get("type")
    if allowed_types:
        choices = allowed_types if isinstance(allowed_types, list) else [allowed_types]
        if not any(_matches_type(value, choice) for choice in choices):
            raise ValueError(f"{path} must be {' or '.join(choices)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
    if (
        isinstance(value, str)
        and "pattern" in schema
        and not re.fullmatch(str(schema["pattern"]), value)
    ):
        raise ValueError(f"{path} does not match the required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} exceeds the maximum")
    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"{path} is missing: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(schema.get("properties", {}))
            if unknown:
                raise ValueError(f"{path} has unknown fields: {', '.join(sorted(unknown))}")
        for key, child in schema.get("properties", {}).items():
            if key in value:
                _validate_schema(value[key], child, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(expected, False)


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") == 3:
        return v3_to_v2(report)
    if report.get("schema_version") == 2:
        return report
    performance = report.get("performance", [])
    normalized = {
        "schema_version": 2,
        "profile": "cfo_brief",
        "decision_question": "Doanh nghiệp cần ưu tiên hành động nào?",
        "period": {"label": "", "start": "", "end": ""},
        "executive_summary": str(report.get("executive_summary", "")),
        "metrics": [
            {
                "id": f"legacy_metric_{index}",
                "label": str(item.get("metric", "Chỉ số")),
                "current": None,
                "previous": None,
                "budget": None,
                "benchmark": None,
                "unit": "VND",
                "source_ids": [],
                "assessment": f"{item.get('value', '')} — {item.get('assessment', '')}".strip(
                    " —"
                ),
            }
            for index, item in enumerate(performance, 1)
        ],
        "findings": [],
        "scenario_model": {
            "model_type": "none",
            "drivers": [],
            "primary_output": "",
            "scenarios": [],
        },
        "tax_risks": [
            {
                "severity": _severity(item.get("severity")),
                "title": str(item.get("title", "Rủi ro")),
                "evidence_ids": [],
                "regulation": str(item.get("regulation", "")),
                "legal_source_ids": [],
                "required_documents": [],
                "confidence": float(item.get("confidence", 0)),
            }
            for item in report.get("tax_risks", [])
        ],
        "recommendations": [
            {
                "priority": _severity(item.get("priority")),
                "action": str(item.get("action", "")),
                "rationale": "",
                "owner": "Giám đốc",
                "deadline_days": None,
                "estimated_impact_vnd": None,
                "effort": "medium",
                "evidence_ids": [],
                "confidence": float(report.get("confidence", 0)),
            }
            for item in report.get("recommendations", [])
        ],
        "sources": [],
        "missing_data": [
            {"field": str(item), "impact": str(item), "material": False}
            for item in report.get("missing_data", [])
        ],
        "assumptions": [],
        "overall_confidence": float(report.get("confidence", 0)),
    }
    normalized["confidence"] = normalized["overall_confidence"]
    return normalized


def _severity(value: Any) -> str:
    return str(value).casefold() if str(value).casefold() in {"low", "medium", "high"} else "medium"


def _observation_value(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("normalized_value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def v3_to_v2(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != 3:
        return report
    metrics = []
    for item in report.get("metrics", []):
        current = item.get("current")
        unit = str((current or {}).get("currency") or (current or {}).get("display_unit") or "") if isinstance(current, dict) else ""
        metrics.append({
            "id": str(item.get("id", "")), "label": str(item.get("label", "")),
            "current": _observation_value(item.get("current")), "previous": _observation_value(item.get("previous")), "budget": _observation_value(item.get("budget")), "benchmark": _observation_value(item.get("benchmark")),
            "unit": unit, "source_ids": list((current or {}).get("evidence_ids", [])) if isinstance(current, dict) else [], "assessment": str(item.get("assessment", "")),
        })
    scenarios = []
    for item in report.get("scenario_model", {}).get("scenarios", []):
        scenarios.append({
            "name": "upside" if item.get("name") == "upside" else item.get("name", "base"), "assumptions": str(item.get("assumptions", "")),
            "revenue_vnd": _observation_value(item.get("revenue")), "net_income_vnd": _observation_value(item.get("net_income")), "cash_effect_vnd": _observation_value(item.get("cash_effect")),
        })
    recommendations = []
    for item in report.get("recommendations", []):
        impact = item.get("impact_estimate") or {}
        recommendations.append({
            "priority": item.get("priority", "medium"), "action": str(item.get("action", "")), "rationale": str(item.get("rationale", "")), "owner": str(item.get("owner", "")), "deadline_days": item.get("deadline_days"), "estimated_impact_vnd": _observation_value(impact.get("base")) if isinstance(impact, dict) else None, "effort": item.get("effort", "medium"), "evidence_ids": list(item.get("evidence_ids", [])), "confidence": float(item.get("confidence", 0)),
        })
    findings = []
    for item in report.get("findings", []):
        impact = item.get("impact_estimate") or {}
        findings.append({
            "id": str(item.get("id", "")), "category": str(item.get("category", "")), "severity": item.get("severity", "medium"), "statement": str(item.get("statement", "")), "root_cause": str(item.get("root_cause", "")), "estimated_impact_vnd": _observation_value(impact.get("base")) if isinstance(impact, dict) else None, "assumptions": list(impact.get("assumption_ids", [])) if isinstance(impact, dict) and isinstance(impact.get("assumption_ids"), list) else [], "evidence_ids": list(item.get("evidence_ids", [])), "confidence": float(item.get("confidence", 0)),
        })
    context = report.get("report_context", {})
    sources = [
        {
            "id": str(source.get("id", "")), "kind": str(source.get("kind", "file")), "title": str(source.get("title", "")), "locator": str(source.get("locator", "")), "fetched_at": str(source.get("fetched_at", "")), "effective_from": str(source.get("effective_at", source.get("effective_from", ""))), "verified_current": bool(source.get("verified_current", False)),
        }
        for source in report.get("sources", [])
    ]
    return {
        "schema_version": 2, "profile": report.get("profile", "cfo_brief"), "decision_question": str(report.get("decision_question", "")), "period": {"label": str(context.get("primary_period", "")), "start": "", "end": ""}, "executive_summary": str(report.get("executive_summary", "")), "metrics": metrics, "findings": findings, "scenario_model": {"model_type": report.get("scenario_model", {}).get("model_type", "none"), "drivers": [], "primary_output": str(report.get("scenario_model", {}).get("primary_output", "")), "scenarios": scenarios}, "tax_risks": list(report.get("tax_risks", [])), "recommendations": recommendations, "sources": sources, "missing_data": list(report.get("missing_data", [])), "assumptions": [str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in report.get("assumptions", [])], "overall_confidence": float(report.get("overall_confidence", 0)), "_v3_metrics": list(report.get("metrics", [])), "_v3_sources": list(report.get("sources", [])), "_v3_findings": list(report.get("findings", [])), "_v3_recommendations": list(report.get("recommendations", [])), "_v3_scenario_model": dict(report.get("scenario_model", {})), "_v3_assumptions": list(report.get("assumptions", [])), "_v3_report_context": dict(report.get("report_context", {})), "_v3_reconciliation_checks": list(report.get("reconciliation_checks", [])), "_v3_data_quality": dict(report.get("data_quality", {})),
    }


def _validate_evidence(report: dict[str, Any]) -> None:
    source_ids = {str(item.get("id")) for item in report["sources"]}
    for index, item in enumerate(report["metrics"]):
        if any(item.get(key) is not None for key in ("current", "previous", "budget", "benchmark")):
            if not item.get("source_ids"):
                raise ValueError(f"Metric {index} has numbers without evidence")
            unknown = set(item["source_ids"]) - source_ids
            if unknown:
                raise ValueError(f"Metric {index} references unknown sources: {', '.join(unknown)}")
    for group in ("findings", "recommendations"):
        for index, item in enumerate(report[group]):
            if item.get("estimated_impact_vnd") is not None and not (
                item.get("evidence_ids") or item.get("assumptions")
            ):
                raise ValueError(f"{group} item {index} has impact without evidence or assumptions")


def _validate_evidence_v3(report: dict[str, Any]) -> None:
    source_ids = {str(item.get("id")) for item in report.get("sources", [])}
    sources = {str(item.get("id")): item for item in report.get("sources", [])}

    def validate_observation(observation: Any, path: str) -> None:
        if not observation:
            return
        value_present = observation.get("normalized_value") is not None
        if value_present and observation.get("status") not in {"assumption", "expert_estimate", "missing"} and not observation.get("evidence_ids"):
            raise ValueError(f"{path} has numbers without evidence")
        if value_present and observation.get("measure") == "money" and not observation.get("currency"):
            raise ValueError(f"{path} has money without ISO currency")
        if value_present and observation.get("measure") == "money" and observation.get("currency") not in ISO4217_CODES:
            raise ValueError(f"{path} has an unknown ISO currency")
        if observation.get("measure") != "money" and observation.get("currency") is not None:
            raise ValueError(f"{path} has currency on a non-money measure")

    for metric_index, metric in enumerate(report.get("metrics", [])):
        for role in ("current", "previous", "budget", "benchmark"):
            observation = metric.get(role)
            if not observation:
                continue
            validate_observation(observation, f"Metric {metric_index}.{role}")
            evidence_ids = set(observation.get("evidence_ids", []))
            unknown = evidence_ids - source_ids
            if unknown:
                raise ValueError(f"Metric {metric_index}.{role} references unknown sources: {', '.join(sorted(unknown))}")
    for driver_index, driver in enumerate(report.get("scenario_model", {}).get("drivers", [])):
        for role in ("base", "downside", "upside"):
            validate_observation(driver.get(role), f"Scenario driver {driver_index}.{role}")
            unknown = set((driver.get(role) or {}).get("evidence_ids", [])) - source_ids
            if unknown:
                raise ValueError(f"Scenario driver {driver_index}.{role} references unknown sources: {', '.join(sorted(unknown))}")
    for scenario_index, scenario in enumerate(report.get("scenario_model", {}).get("scenarios", [])):
        for role in ("revenue", "net_income", "cash_effect"):
            validate_observation(scenario.get(role), f"Scenario {scenario_index}.{role}")
            unknown = set((scenario.get(role) or {}).get("evidence_ids", [])) - source_ids
            if unknown:
                raise ValueError(f"Scenario {scenario_index}.{role} references unknown sources: {', '.join(sorted(unknown))}")
    for index, check in enumerate(report.get("reconciliation_checks", [])):
        if check.get("status") == "FAIL" and not check.get("evidence_ids"):
            raise ValueError(f"Reconciliation check {index} has no evidence")
    for index, risk in enumerate(report.get("tax_risks", [])):
        if not risk.get("regulation"):
            continue
        for source_id in risk.get("legal_source_ids", []):
            source = sources.get(str(source_id))
            if (
                not source
                or source.get("kind") != "knowledge"
                or not source.get("authority")
                or not source.get("effective_at")
                or not source.get("url")
                or not source.get("checksum")
                or not source.get("retrieved_at")
                or not source.get("verified_at")
                or not source.get("verified_current")
            ):
                raise ValueError(f"Tax risk {index} lacks a verified official legal source")
    for group in ("findings", "recommendations"):
        for index, item in enumerate(report.get(group, [])):
            estimate = item.get("impact_estimate")
            if not estimate:
                continue
            if not estimate.get("method") or estimate.get("label") != "EXPERT_ESTIMATE":
                raise ValueError(f"{group} item {index} expert estimate needs method and label")
            observations = [estimate.get(key) for key in ("low", "base", "high")]
            for role, observation in zip(("low", "base", "high"), observations, strict=True):
                validate_observation(observation, f"{group} item {index} estimate.{role}")
            if any(observation and observation.get("status") != "expert_estimate" for observation in observations):
                raise ValueError(f"{group} item {index} estimate observations must be expert_estimate")
            if any(observation and float(observation.get("confidence", 1)) > 0.60 for observation in observations):
                raise ValueError(f"{group} item {index} expert estimate confidence exceeds 0.60")
            if not (estimate.get("evidence_ids") or estimate.get("assumption_ids")):
                raise ValueError(f"{group} item {index} expert estimate needs evidence or assumptions")


def report_confidence(report: dict[str, Any]) -> float:
    normalized = normalize_report(report)
    return float(normalized.get("overall_confidence", 0))


def markdown(report: dict[str, Any], warning: str = "") -> str:
    report = normalize_report(report)
    lines = ["# TaxSentry — Báo cáo tư vấn tài chính & thuế"]
    if warning:
        lines.extend(["", f"> CẢNH BÁO: {warning}"])
    lines.extend(
        [
            "",
            "## Tóm tắt cho Chủ doanh nghiệp",
            str(report["executive_summary"]),
            "",
            f"**Câu hỏi quyết định:** {report['decision_question'] or 'Chưa xác định.'}",
            "",
            "## Chỉ số điều hành",
        ]
    )
    if report["metrics"]:
        lines.extend(
            [
                "| Chỉ số | Hiện tại | Kỳ trước | Kế hoạch | Đánh giá |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for item in report["metrics"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item["label"]),
                        _format(item.get("current"), item.get("unit")),
                        _format(item.get("previous"), item.get("unit")),
                        _format(item.get("budget"), item.get("unit")),
                        str(item.get("assessment", "")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- Chưa có chỉ số định lượng đủ tin cậy.")
    lines.extend(["", "## Phát hiện chính"])
    for item in report["findings"]:
        impact = _format(item.get("estimated_impact_vnd"), "VND")
        lines.append(
            f"- **[{item['severity'].upper()}] {item['statement']}** — Nguyên nhân: "
            f"{item['root_cause'] or 'chưa đủ dữ liệu'} · Tác động: {impact} · "
            f"Tin cậy: {float(item['confidence']):.0%}"
        )
    if report["scenario_model"]["scenarios"]:
        lines.extend(
            [
                "",
                "## Kịch bản kinh tế",
                "| Kịch bản | Doanh thu | Lợi nhuận ròng | Tác động dòng tiền |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for item in report["scenario_model"]["scenarios"]:
            lines.append(
                f"| {item['name']} | {_format(item['revenue_vnd'], 'VND')} | "
                f"{_format(item['net_income_vnd'], 'VND')} | "
                f"{_format(item['cash_effect_vnd'], 'VND')} |"
            )
    lines.extend(["", "## Rủi ro thuế"])
    for item in report["tax_risks"]:
        documents = ", ".join(item["required_documents"]) or "Chưa xác định"
        lines.append(
            f"- **[{item['severity'].upper()}] {item['title']}** — "
            f"Căn cứ: {item['regulation'] or 'chưa đủ căn cứ đã xác minh'} · "
            f"Hồ sơ cần kiểm tra: {documents} · Tin cậy: {float(item['confidence']):.0%}"
        )
    lines.extend(["", "## Kế hoạch hành động"])
    for item in report["recommendations"]:
        deadline = (
            f"{item['deadline_days']} ngày"
            if item.get("deadline_days") is not None
            else "chưa xác định"
        )
        lines.append(
            f"- **{item['priority'].upper()} · {item['owner']} · {deadline}** — "
            f"{item['action']}  \n  Lý do: {item['rationale']} · "
            f"Tác động: {_format(item['estimated_impact_vnd'], 'VND')}"
        )
    lines.extend(["", "## Phụ lục chuyên môn", "### Dữ liệu thiếu"])
    lines.extend(
        f"- **{item['field']}**: {item['impact']}"
        for item in report["missing_data"]
    )
    if not report["missing_data"]:
        lines.append("- Không ghi nhận.")
    lines.extend(["", "### Giả định"])
    lines.extend(f"- {item}" for item in report["assumptions"])
    if not report["assumptions"]:
        lines.append("- Không ghi nhận.")
    lines.extend(["", "### Nguồn và căn cứ"])
    for item in report["sources"]:
        status = "đã xác minh" if item["verified_current"] else "chưa xác minh độ mới"
        lines.append(f"- **{item['id']}** — {item['title']} · {status} · {item['locator']}")
    lines.extend(
        [
            "",
            f"Độ tin cậy tổng thể: **{report_confidence(report):.0%}**",
            "",
            "> TaxSentry cung cấp phân tích hỗ trợ; Giám đốc và chuyên gia đủ thẩm quyền quyết định cuối cùng.",
        ]
    )
    return "\n".join(lines)


def _format(value: Any, unit: Any) -> str:
    if value is None:
        return "n/a"
    number = float(value)
    if unit == "%":
        return f"{number:.1%}"
    if unit == "VND":
        return f"{number:,.0f} VND".replace(",", ".")
    if unit == "days":
        return f"{number:,.1f} ngày"
    return f"{number:,.2f}"


def html_summary(report: dict[str, Any], warning: str = "") -> str:
    report = normalize_report(report)
    notice = f"<p><b>Cảnh báo:</b> {html.escape(warning)}</p>" if warning else ""
    return (
        f"<h2>TaxSentry — Báo cáo tư vấn mới</h2>{notice}"
        f"<p>{html.escape(str(report['executive_summary']))}</p>"
        f"<p><b>Độ tin cậy:</b> {report_confidence(report):.0%}</p>"
        "<p>Chi tiết và phụ lục bằng chứng nằm trong tài liệu đính kèm.</p>"
    )


def render_pdf(report: dict[str, Any], output: Path, warning: str = "") -> Path:
    from .core.pdf_generator import TaxSentryPDFGenerator

    output.parent.mkdir(parents=True, exist_ok=True)
    if not TaxSentryPDFGenerator().generate(markdown(report, warning), str(output)):
        raise RuntimeError("Unable to render PDF report")
    return output
