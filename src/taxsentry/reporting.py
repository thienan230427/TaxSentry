from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

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
        "unit": {"type": "string", "enum": ["VND", "%", "days", "count", "ratio"]},
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
        "unit": {"type": "string", "enum": ["VND", "%", "days", "count", "ratio"]},
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


def parse_report(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Provider did not return a JSON report")
    report = json.loads(text[start : end + 1])
    if not isinstance(report, dict):
        raise ValueError("Provider report must be an object")
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


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    allowed_types = schema.get("type")
    if allowed_types:
        choices = allowed_types if isinstance(allowed_types, list) else [allowed_types]
        if not any(_matches_type(value, choice) for choice in choices):
            raise ValueError(f"{path} must be {' or '.join(choices)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
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
