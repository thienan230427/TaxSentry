from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

LABELS = {
    "revenue": "Doanh thu",
    "cogs": "Giá vốn",
    "gross_profit": "Lợi nhuận gộp",
    "total_opex": "Chi phí vận hành",
    "ebt": "Lợi nhuận trước thuế",
    "tax_expense": "Chi phí thuế",
    "net_income": "Lợi nhuận ròng",
    "cash_flow": "Dòng tiền thuần",
}
ALIASES = {
    "revenue": ("doanh thu thuan", "doanh thu", "revenue", "sales"),
    "cogs": ("gia von", "cogs", "cost of goods sold"),
    "gross_profit": ("loi nhuan gop", "gross profit"),
    "total_opex": ("tong chi phi", "opex", "operating expenses"),
    "ebt": ("loi nhuan truoc thue", "ebt", "profit before tax"),
    "tax_expense": ("chi phi thue", "thue tndn", "tax expense"),
    "net_income": ("loi nhuan sau thue", "loi nhuan rong", "net income"),
    "cash_flow": ("dong tien thuan", "luu chuyen tien thuan", "net cash flow"),
}
PERIODS = {
    "current": ("ky nay", "current", "actual", "thuc hien"),
    "previous": ("ky truoc", "previous", "last period", "cung ky"),
    "budget": ("ke hoach", "budget", "plan", "target"),
    "benchmark": ("benchmark", "trung binh nganh", "industry"),
}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join(
        re.sub(r"[^a-z0-9%]+", " ", "".join(ch for ch in text if not unicodedata.combining(ch))).split()
    )


def _key(label: Any) -> str | None:
    text = _norm(label)
    best: tuple[int, str] | None = None
    for key, aliases in ALIASES.items():
        for alias in aliases:
            normalized = _norm(alias)
            if normalized in text:
                candidate = (len(normalized), key)
                best = candidate if best is None or candidate > best else best
    return best[1] if best else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def build_analysis_context(
    extracted: list[dict[str, Any]],
    *,
    history: dict[str, Any] | None = None,
    knowledge_text: str = "",
    knowledge_sources: list[dict] | None = None,
    company: dict | None = None,
    benchmark_max_age_months: int = 24,
) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(extracted, 1):
        source_id = f"input:{index}"
        sources.append(
            {
                "id": source_id,
                "kind": "email" if item.get("email") else "file",
                "title": str(item.get("file") or f"Nguồn {index}"),
                "locator": str(item.get("file") or ""),
                "fetched_at": "",
                "effective_from": "",
                "verified_current": True,
            }
        )
        content = item.get("content")
        if isinstance(content, dict):
            _collect_metrics(content, source_id, metrics)
    if history:
        normalized = history if history.get("schema_version") == 2 else {}
        for item in normalized.get("metrics", []):
            key = str(item.get("id", ""))
            if key in metrics and metrics[key].get("previous") is None:
                metrics[key]["previous"] = _number(item.get("current"))
                metrics[key]["assessment"] = "Kỳ trước lấy từ báo cáo TaxSentry gần nhất."
    values = list(metrics.values())
    _add_ratios(values)
    sources.extend(knowledge_sources or [])
    return {
        "company": company or {},
        "metrics": values,
        "sources": sources,
        "knowledge": knowledge_text,
        "benchmark_max_age_months": benchmark_max_age_months,
    }


def _collect_metrics(content: dict, source_id: str, target: dict[str, dict]) -> None:
    data = content.get("data", content)
    canonical = data.get("canonical_metrics", {}) if isinstance(data, dict) else {}
    for key, item in canonical.items():
        if key not in LABELS or not isinstance(item, dict):
            continue
        target[key] = _metric(key, _number(item.get("value")), source_id)
    for sheet in data.get("sheets", []) if isinstance(data, dict) else []:
        for row in sheet.get("line_items", []):
            key = _key(row.get("label"))
            if not key:
                continue
            metric = target.setdefault(key, _metric(key, None, source_id))
            for heading, value in row.get("values", {}).items():
                number = _number(value)
                if number is None:
                    continue
                period = _period(heading)
                if period and metric.get(period) is None:
                    metric[period] = number


def _metric(key: str, current: float | None, source_id: str) -> dict[str, Any]:
    return {
        "id": key,
        "label": LABELS[key],
        "current": current,
        "previous": None,
        "budget": None,
        "benchmark": None,
        "unit": "VND",
        "source_ids": [source_id],
        "assessment": "",
    }


def _period(heading: Any) -> str | None:
    value = _norm(heading)
    for period, aliases in PERIODS.items():
        if any(_norm(alias) in value for alias in aliases):
            return period
    return None


def _add_ratios(metrics: list[dict[str, Any]]) -> None:
    indexed = {item["id"]: item for item in metrics}
    revenue = indexed.get("revenue", {}).get("current")
    for key, numerator, label in (
        ("gross_margin", "gross_profit", "Biên lợi nhuận gộp"),
        ("net_margin", "net_income", "Biên lợi nhuận ròng"),
        ("opex_ratio", "total_opex", "Chi phí vận hành / doanh thu"),
    ):
        value = indexed.get(numerator, {}).get("current")
        if revenue not in (None, 0) and value is not None:
            metrics.append(
                {
                    "id": key,
                    "label": label,
                    "current": value / revenue,
                    "previous": None,
                    "budget": None,
                    "benchmark": None,
                    "unit": "%",
                    "source_ids": list(
                        dict.fromkeys(
                            indexed[numerator]["source_ids"] + indexed["revenue"]["source_ids"]
                        )
                    ),
                    "assessment": "Tính bằng Python từ dữ liệu nguồn.",
                }
            )
    revenue_metric = indexed.get("revenue")
    if revenue_metric and revenue_metric.get("previous") not in (None, 0):
        metrics.append(
            {
                "id": "revenue_growth",
                "label": "Tăng trưởng doanh thu",
                "current": revenue_metric["current"] / revenue_metric["previous"] - 1,
                "previous": None,
                "budget": None,
                "benchmark": None,
                "unit": "%",
                "source_ids": revenue_metric["source_ids"],
                "assessment": "So với kỳ trước, tính bằng Python.",
            }
        )
    if revenue_metric and revenue_metric.get("budget") not in (None, 0):
        metrics.append(
            {
                "id": "revenue_budget_variance",
                "label": "Chênh lệch doanh thu so với kế hoạch",
                "current": revenue_metric["current"] / revenue_metric["budget"] - 1,
                "previous": None,
                "budget": None,
                "benchmark": None,
                "unit": "%",
                "source_ids": revenue_metric["source_ids"],
                "assessment": "So với ngân sách, tính bằng Python.",
            }
        )


def apply_grounding(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    grounded = {**report}
    model_metrics = {item.get("id"): item for item in report.get("metrics", [])}
    sources = {
        item["id"]: item
        for item in [*report.get("sources", []), *context.get("sources", [])]
        if item.get("id")
    }
    grounded["sources"] = list(sources.values())
    verified_benchmarks = {
        item["id"]
        for item in grounded["sources"]
        if _valid_benchmark(item, context)
    }
    metrics = []
    context_source_ids = {
        item.get("id") for item in context.get("sources", []) if item.get("id")
    }
    for calculated in context.get("metrics", []):
        narrative = model_metrics.get(calculated["id"], {})
        benchmark_ids = verified_benchmarks & set(narrative.get("source_ids", []))
        metrics.append(
            {
                **calculated,
                "benchmark": (
                    narrative.get("benchmark")
                    if narrative.get("benchmark") is not None and benchmark_ids
                    else None
                ),
                "source_ids": list(
                    dict.fromkeys(
                        [
                            *calculated.get("source_ids", []),
                            *sorted(benchmark_ids),
                        ]
                    )
                ),
                "assessment": str(
                    narrative.get("assessment") or calculated.get("assessment") or ""
                ),
            }
        )
    calculated_ids = {item["id"] for item in metrics}
    metrics.extend(
        item
        for item in report.get("metrics", [])
        if item.get("id") not in calculated_ids
        and item.get("source_ids")
        and set(item["source_ids"]) <= context_source_ids
    )
    grounded["metrics"] = metrics
    missing = list(grounded.get("missing_data", []))
    for item in report.get("metrics", []):
        if item.get("benchmark") is not None and not (
            verified_benchmarks & set(item.get("source_ids", []))
        ):
            missing.append(
                {
                    "field": f"benchmark:{item.get('id', 'unknown')}",
                    "impact": "Không có benchmark ngành đủ mới và được xác minh.",
                    "material": False,
                }
            )
    for item in grounded["metrics"]:
        if item.get("benchmark") is not None and not (
            verified_benchmarks & set(item.get("source_ids", []))
        ):
            item["benchmark"] = None
            missing.append(
                {
                    "field": f"benchmark:{item['id']}",
                    "impact": "Không có benchmark ngành đủ mới và được xác minh.",
                    "material": False,
                }
            )
    grounded["missing_data"] = _unique_missing(missing)
    grounded["scenario_model"] = _scenario_model(grounded["metrics"])
    return grounded


def _valid_benchmark(source: dict[str, Any], context: dict[str, Any]) -> bool:
    if source.get("kind") != "benchmark" or not source.get("verified_current"):
        return False
    company_industry = _norm(context.get("company", {}).get("industry"))
    source_industry = _norm(source.get("industry"))
    if not company_industry or source_industry != company_industry:
        return False
    if not str(source.get("scope", "")).strip():
        return False
    try:
        period_end = datetime.fromisoformat(
            str(source.get("data_period_end") or source.get("effective_from"))
        )
    except ValueError:
        return False
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    max_months = int(context.get("benchmark_max_age_months", 24))
    age = datetime.now(timezone.utc) - period_end
    return timedelta(0) <= age <= timedelta(days=max_months * 31)


def _unique_missing(items: list[Any]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        normalized = (
            item
            if isinstance(item, dict)
            else {"field": str(item), "impact": str(item), "material": False}
        )
        result[str(normalized.get("field", ""))] = {
            "field": str(normalized.get("field", "")),
            "impact": str(normalized.get("impact", "")),
            "material": bool(normalized.get("material")),
        }
    return list(result.values())


def _scenario_model(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    values = {item["id"]: item for item in metrics}
    revenue = _number(values.get("revenue", {}).get("current"))
    if revenue is None:
        return {
            "model_type": "none",
            "drivers": [],
            "primary_output": "",
            "scenarios": [],
        }
    cogs = _number(values.get("cogs", {}).get("current"))
    opex = _number(values.get("total_opex", {}).get("current"))
    ebt = _number(values.get("ebt", {}).get("current"))
    tax = _number(values.get("tax_expense", {}).get("current"))
    cogs_ratio = cogs / revenue if cogs is not None and revenue else None
    tax_rate = tax / ebt if tax is not None and ebt not in (None, 0) else None
    source_ids = list(
        dict.fromkeys(
            source_id
            for key in ("revenue", "cogs", "total_opex", "ebt", "tax_expense")
            for source_id in values.get(key, {}).get("source_ids", [])
        )
    )
    drivers = [
        {
            "key": "revenue",
            "label": "Doanh thu",
            "base": revenue,
            "downside": revenue * 0.9,
            "upside": revenue * 1.1,
            "unit": "VND",
            "source_ids": values.get("revenue", {}).get("source_ids", []),
        }
    ]
    if cogs_ratio is not None:
        drivers.append(
            {
                "key": "cogs_ratio",
                "label": "Tỷ lệ giá vốn",
                "base": cogs_ratio,
                "downside": min(1.0, cogs_ratio * 1.1),
                "upside": max(0.0, cogs_ratio * 0.9),
                "unit": "%",
                "source_ids": source_ids,
            }
        )
    if opex is not None:
        drivers.append(
            {
                "key": "opex",
                "label": "Chi phí vận hành",
                "base": opex,
                "downside": opex * 1.1,
                "upside": opex * 0.9,
                "unit": "VND",
                "source_ids": values.get("total_opex", {}).get("source_ids", []),
            }
        )
    if tax_rate is not None:
        drivers.append(
            {
                "key": "tax_rate",
                "label": "Thuế suất mô hình",
                "base": tax_rate,
                "downside": tax_rate,
                "upside": tax_rate,
                "unit": "%",
                "source_ids": source_ids,
            }
        )
    scenarios = []
    for name, revenue_value, cogs_value, opex_value in (
        (
            "downside",
            revenue * 0.9,
            min(1.0, cogs_ratio * 1.1) if cogs_ratio is not None else None,
            opex * 1.1 if opex is not None else None,
        ),
        ("base", revenue, cogs_ratio, opex),
        (
            "upside",
            revenue * 1.1,
            max(0.0, cogs_ratio * 0.9) if cogs_ratio is not None else None,
            opex * 0.9 if opex is not None else None,
        ),
    ):
        complete = None not in (cogs_value, opex_value, tax_rate)
        ebit = (
            revenue_value * (1 - cogs_value) - opex_value
            if complete
            else None
        )
        net = (
            ebit - max(0.0, ebit * tax_rate)
            if ebit is not None and tax_rate is not None
            else None
        )
        scenarios.append(
            {
                "name": name,
                "assumptions": (
                    "Mô hình P&L từ doanh thu, tỷ lệ giá vốn, OPEX và thuế suất."
                    if complete
                    else "Chưa tính lợi nhuận vì thiếu đầu vào P&L có nguồn."
                ),
                "revenue_vnd": revenue_value,
                "net_income_vnd": net,
                "cash_effect_vnd": net,
            }
        )
    return {
        "model_type": "pnl_driver" if all(
            value is not None for value in (cogs_ratio, opex, tax_rate)
        ) else "percentage_change",
        "drivers": drivers,
        "primary_output": (
            "net_income"
            if all(value is not None for value in (cogs_ratio, opex, tax_rate))
            else "revenue"
        ),
        "scenarios": scenarios,
    }


def review_reasons(report: dict[str, Any], settings: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    threshold = float(settings.get("report", {}).get("minimum_confidence", 0.7))
    if float(report.get("overall_confidence", 0)) < threshold:
        reasons.append(f"Độ tin cậy dưới {threshold:.0%}.")
    if any(item.get("severity") == "high" for item in report.get("tax_risks", [])):
        reasons.append("Có rủi ro thuế mức cao.")
    if any(item.get("material") for item in report.get("missing_data", [])):
        reasons.append("Thiếu dữ liệu trọng yếu.")
    revenue = next(
        (
            item.get("current")
            for item in report.get("metrics", [])
            if item.get("id") == "revenue"
        ),
        None,
    )
    if revenue in (None, 0):
        reasons.append("Không xác định được doanh thu để đo tính trọng yếu.")
    else:
        ratio = float(
            settings.get("advisor", {}).get("company", {}).get("materiality_ratio", 0.05)
        )
        impacts = [
            abs(float(item["estimated_impact_vnd"]))
            for group in ("findings", "recommendations")
            for item in report.get(group, [])
            if item.get("estimated_impact_vnd") is not None
        ]
        if impacts and max(impacts) >= abs(float(revenue)) * ratio:
            reasons.append(f"Tác động ước tính từ {ratio:.0%} doanh thu kỳ.")
    sources = {item.get("id"): item for item in report.get("sources", [])}
    for risk in report.get("tax_risks", []):
        if risk.get("legal_source_ids") and any(
            not sources.get(source_id, {}).get("verified_current")
            for source_id in risk["legal_source_ids"]
        ):
            reasons.append("Căn cứ pháp lý chưa được xác minh còn hiệu lực.")
            break
    return list(dict.fromkeys(reasons))
