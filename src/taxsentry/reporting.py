from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "performance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "value": {"type": "string"},
                    "assessment": {"type": "string"},
                },
                "required": ["metric", "value", "assessment"],
                "additionalProperties": False,
            },
        },
        "tax_risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string"},
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                    "regulation": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["severity", "title", "evidence", "regulation", "confidence"],
                "additionalProperties": False,
            },
        },
        "missing_data": {"type": "array", "items": {"type": "string"}},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"priority": {"type": "string"}, "action": {"type": "string"}},
                "required": ["priority", "action"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["executive_summary", "performance", "tax_risks", "missing_data", "recommendations", "confidence"],
    "additionalProperties": False,
}


def parse_report(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Provider did not return a JSON report")
    report = json.loads(text[start : end + 1])
    missing = [key for key in REPORT_SCHEMA["required"] if key not in report]
    if missing:
        raise ValueError(f"Report is missing: {', '.join(missing)}")
    for key in ("performance", "tax_risks", "missing_data", "recommendations"):
        if not isinstance(report[key], list):
            raise ValueError(f"Report field must be an array: {key}")
    for key in ("performance", "tax_risks", "recommendations"):
        required = REPORT_SCHEMA["properties"][key]["items"]["required"]
        for index, item in enumerate(report[key]):
            if not isinstance(item, dict) or any(name not in item for name in required):
                raise ValueError(f"Invalid {key} item at index {index}")
    report["confidence"] = max(0.0, min(1.0, float(report["confidence"])))
    return report


def markdown(report: dict[str, Any], warning: str = "") -> str:
    lines = ["# Báo cáo Đánh giá Hiệu quả Kinh doanh & Rủi ro Thuế"]
    if warning:
        lines.extend(["", f"> CẢNH BÁO ĐỘ TIN CẬY: {warning}"])
    lines.extend(["", "## Tóm tắt điều hành", str(report["executive_summary"]), "", "## Hiệu quả kinh doanh"])
    for item in report["performance"]:
        lines.append(f"- **{item.get('metric', 'Chỉ số')}**: {item.get('value', 'n/a')} — {item.get('assessment', '')}")
    lines.extend(["", "## Rủi ro thuế"])
    for item in report["tax_risks"]:
        lines.append(f"- **[{str(item.get('severity', 'unknown')).upper()}] {item.get('title', 'Rủi ro')}**: {item.get('evidence', '')}  \n  Căn cứ: {item.get('regulation', 'Chưa đủ căn cứ')} · Tin cậy: {item.get('confidence', 'n/a')}")
    lines.extend(["", "## Dữ liệu thiếu và giả định"])
    lines.extend(f"- {item}" for item in report["missing_data"] or ["Không ghi nhận."])
    lines.extend(["", "## Khuyến nghị cho Giám đốc"])
    for item in report["recommendations"]:
        lines.append(f"- **{item.get('priority', 'medium')}** — {item.get('action', item)}")
    lines.extend(["", f"Độ tin cậy tổng thể: **{float(report['confidence']):.0%}**", "", "> TaxSentry cung cấp khuyến nghị hỗ trợ; Giám đốc là người quyết định cuối cùng."])
    return "\n".join(lines)


def html_summary(report: dict[str, Any], warning: str = "") -> str:
    notice = f"<p><b>Cảnh báo:</b> {html.escape(warning)}</p>" if warning else ""
    return f"<h2>TaxSentry — Báo cáo mới</h2>{notice}<p>{html.escape(str(report['executive_summary']))}</p><p><b>Độ tin cậy:</b> {float(report['confidence']):.0%}</p><p>Chi tiết nằm trong PDF đính kèm.</p>"


def render_pdf(report: dict[str, Any], output: Path, warning: str = "") -> Path:
    from .core.pdf_generator import TaxSentryPDFGenerator

    output.parent.mkdir(parents=True, exist_ok=True)
    if not TaxSentryPDFGenerator().generate(markdown(report, warning), str(output)):
        raise RuntimeError("Unable to render PDF report")
    return output
