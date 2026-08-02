from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from .reconciliation import reconcile_financials

LABELS = {
    "revenue": "Doanh thu",
    "cogs": "Giá vốn",
    "gross_profit": "Lợi nhuận gộp",
    "total_opex": "Chi phí vận hành",
    "ebt": "Lợi nhuận trước thuế",
    "tax_expense": "Chi phí thuế",
    "net_income": "Lợi nhuận ròng",
    "operating_profit": "Lợi nhuận hoạt động",
    "assets": "Tổng tài sản",
    "liabilities": "Tổng nợ phải trả",
    "equity": "Vốn chủ sở hữu",
    "cash": "Tiền và tương đương tiền",
    "beginning_cash": "Tiền đầu kỳ",
    "net_cash_movement": "Lưu chuyển tiền thuần",
    "ending_cash": "Tiền cuối kỳ",
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
    "operating_profit": ("loi nhuan hoat dong", "operating profit", "ebit"),
    "assets": ("tong tai san", "total assets", "assets"),
    "liabilities": ("tong no phai tra", "total liabilities", "liabilities"),
    "equity": ("von chu so huu", "total equity", "equity"),
    "cash": ("tien va tuong duong tien", "cash and cash equivalents", "cash"),
    "beginning_cash": ("tien dau ky", "beginning cash", "opening cash"),
    "net_cash_movement": ("luu chuyen tien thuan", "net cash flow", "net cash movement"),
    "ending_cash": ("tien cuoi ky", "ending cash", "closing cash"),
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
    if isinstance(value, dict):
        measurement = value.get("measurement")
        if isinstance(measurement, dict):
            normalized = measurement.get("normalized_value")
            if normalized is None:
                return None
            value = normalized
        else:
            value = value.get("value", value.get("current"))
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
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
    conflicts: list[dict[str, Any]] = []
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
        metadata = content.get("metadata", {}) if isinstance(content, dict) else {}
        if metadata.get("file_hash"):
            sources[-1]["file_hash"] = str(metadata["file_hash"])
        if isinstance(content, dict):
            _collect_metrics(
                content,
                source_id,
                metrics,
                sources,
                conflicts,
                title=str(item.get("file") or f"Nguồn {index}"),
                kind="email" if item.get("email") else "file",
            )
    report_context = _report_context(extracted, metrics)
    if history and _history_compatible(history, report_context):
        normalized = history
        for item in normalized.get("metrics", []):
            key = str(item.get("id", ""))
            if key in metrics and metrics[key].get("previous") is None:
                metrics[key]["previous"] = _number(item.get("current"))
                metrics[key]["assessment"] = "Kỳ trước lấy từ báo cáo TaxSentry gần nhất."
    values = list(metrics.values())
    _add_ratios(values)
    sources.extend(knowledge_sources or [])
    balance_sheet = {key: metrics[key] for key in ("assets", "liabilities", "equity", "cash") if key in metrics}
    cash_flow = {key: metrics[key] for key in ("beginning_cash", "net_cash_movement", "ending_cash") if key in metrics}
    checks = reconcile_financials(metrics, balance_sheet=balance_sheet, cash_flow=cash_flow)
    quality = _data_quality(extracted, values, conflicts, checks)
    return {
        "company": company or {},
        "metrics": values,
        "sources": sources,
        "conflicts": conflicts,
        "reconciliation_checks": checks,
        "data_quality": quality,
        "report_context": report_context,
        "knowledge": knowledge_text,
        "benchmark_max_age_months": benchmark_max_age_months,
    }


def _report_context(extracted: list[dict[str, Any]], metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    hashes: list[str] = []
    periods: list[str] = []
    currencies: list[str] = []
    bases: list[str] = []
    for item in extracted:
        content = item.get("content") if isinstance(item, dict) else None
        metadata = content.get("metadata", {}) if isinstance(content, dict) else {}
        if metadata.get("file_hash"):
            hashes.append(str(metadata["file_hash"]))
        for metric in metrics.values():
            if metric.get("period"):
                periods.append(str(metric["period"]))
            if metric.get("currency"):
                currencies.append(str(metric["currency"]))
            if metric.get("basis") and metric.get("current") is not None:
                bases.append(str(metric["basis"]))
    return {
        "source_hashes": sorted(set(hashes)),
        "period": sorted(set(periods))[-1] if periods else "",
        "currency": sorted(set(currencies))[0] if len(set(currencies)) == 1 else "",
        "cadence": "",
        "basis": sorted(set(bases))[0] if len(set(bases)) == 1 else "",
    }


def _history_compatible(history: dict[str, Any], current: dict[str, Any]) -> bool:
    if not isinstance(history, dict):
        return False
    previous = history.get("report_context") if isinstance(history.get("report_context"), dict) else {}
    previous_period = str(previous.get("primary_period") or previous.get("period") or history.get("period", {}).get("label", ""))
    current_period = str(current.get("period", ""))
    if set(previous.get("source_hashes", [])) & set(current.get("source_hashes", [])):
        return False
    previous_currency = str(previous.get("currency") or _report_currency(history))
    if previous_currency and current.get("currency") and previous_currency != current.get("currency"):
        return False
    if previous.get("cadence") and current.get("cadence") and previous.get("cadence") != current.get("cadence"):
        return False
    if str(previous.get("basis") or _report_basis(history)) != "actual":
        return False
    return _is_immediately_prior_period(previous_period, current_period)


def _report_currency(report: dict[str, Any]) -> str:
    values = {
        str(role.get("currency"))
        for metric in report.get("metrics", [])
        for role in (metric.get("current"),)
        if isinstance(role, dict) and role.get("currency")
    }
    if len(values) == 1:
        return next(iter(values))
    values = {str(item.get("unit")) for item in report.get("metrics", []) if re.fullmatch(r"[A-Z]{3}", str(item.get("unit", "")))}
    return next(iter(values)) if len(values) == 1 else ""


def _report_basis(report: dict[str, Any]) -> str:
    values = {
        str(role.get("period", {}).get("basis", ""))
        for metric in report.get("metrics", [])
        for role in (metric.get("current"),)
        if isinstance(role, dict)
    }
    return next(iter(values)) if len(values) == 1 else ""


def _is_immediately_prior_period(previous: str, current: str) -> bool:
    def period_key(value: str):
        match = re.search(r"(?:19|20)\d{2}", value)
        if not match:
            return None
        year = int(match.group(0))
        quarter = re.search(r"(?:q|quy)\s*([1-4])", value.casefold())
        month = re.search(r"(?:thang|month)\s*(\d{1,2})", _norm(value))
        if quarter:
            return (year, 3, int(quarter.group(1)))
        if month:
            return (year, 2, int(month.group(1)))
        return (year, 1, 0)

    old_key, new_key = period_key(previous), period_key(current)
    if not old_key or not new_key or old_key[1:] != new_key[1:]:
        return False
    if old_key[1] == 3:
        return new_key[0] * 4 + new_key[2] == old_key[0] * 4 + old_key[2] + 1
    if old_key[1] == 2:
        return new_key[0] * 12 + new_key[2] == old_key[0] * 12 + old_key[2] + 1
    return new_key[0] == old_key[0] + 1


def _data_quality(extracted, metrics, conflicts, checks):
    failures = [item for item in checks if item.get("status") == "FAIL"]
    missing = [item.get("id") for item in metrics if item.get("current") is None]
    caps = []
    if conflicts:
        caps.append(0.49)
    if failures:
        caps.append(0.49)
    if missing:
        caps.append(0.69)
    coverage = 1.0 if not metrics else max(0.0, (len(metrics) - len(missing)) / len(metrics))
    return {
        "coverage": {
            "ratio": coverage,
            "documents": len(extracted),
            "metrics": len(metrics),
            "missing_metrics": missing,
        },
        "conflict_count": len(conflicts),
        "missing_material_fields": missing,
        "confidence_caps": caps,
        "review_reasons": [
            reason
            for reason, present in (
                ("reconciliation failure", bool(failures)),
                ("conflicting source values", bool(conflicts)),
                ("missing material data", bool(missing)),
            )
            if present
        ],
    }


def _collect_metrics(
    content: dict,
    source_id: str,
    target: dict[str, dict],
    sources: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    *,
    title: str,
    kind: str,
) -> None:
    data = content.get("data", content)
    canonical = data.get("canonical_metrics", {}) if isinstance(data, dict) else {}
    file_hash = str(content.get("metadata", {}).get("file_hash", "")) if isinstance(content, dict) else ""
    for key, item in canonical.items():
        if key not in LABELS or not isinstance(item, dict):
            continue
        metric_source = _evidence_source(
            sources,
            root_id=source_id,
            title=title,
            kind=kind,
            sheet=item.get("source_sheet"),
            row=item.get("source_row"),
            label=item.get("source_label"),
            cell=item.get("source_cell"),
            formula=item.get("source_formula"),
            number_format=item.get("source_number_format"),
            file_hash=file_hash,
            effective_at=item.get("source_period"),
        )
        value = _number(item)
        if item.get("status") == "conflict" or (item.get("measurement") or {}).get("status") == "conflict":
            conflicts.append(
                {
                    "metric": key,
                    "reason": "ambiguous currency/scale or unresolved source conflict",
                    "source_ids": [metric_source],
                }
            )
        existing = target.get(key)
        candidate_rank = _fact_source_rank(item.get("source_type"), title)
        if (
            existing
            and existing.get("current") is not None
            and value is not None
            and not _numbers_equal(existing["current"], value)
        ):
            if candidate_rank > int(existing.get("source_rank", 0)):
                target[key] = _metric(key, value, metric_source, observation=item, source_rank=candidate_rank)
            else:
                conflicts.append(
                    {
                        "metric": key,
                        "kept_value": existing["current"],
                        "conflicting_value": value,
                        "source_ids": [*existing["source_ids"], metric_source],
                    }
                )
                if metric_source not in existing["source_ids"]:
                    existing["source_ids"].append(metric_source)
        else:
            target[key] = _metric(key, value, metric_source, observation=item, source_rank=candidate_rank)
    for sheet in data.get("sheets", []) if isinstance(data, dict) else []:
        for row in sheet.get("line_items", []):
            key = _key(row.get("label"))
            if not key:
                continue
            metric_source = _evidence_source(
                sources,
                root_id=source_id,
                title=title,
                kind=kind,
                sheet=sheet.get("name"),
                row=row.get("row"),
                label=row.get("label"),
                cell="",
                formula="",
                number_format="",
                file_hash=file_hash,
            )
            metric = target.setdefault(key, _metric(key, None, metric_source))
            if metric_source not in metric["source_ids"]:
                metric["source_ids"].append(metric_source)
            for heading, value in row.get("values", {}).items():
                number = _number(value)
                if number is None:
                    continue
                period = _period(heading)
                if period and metric.get(period) is None:
                    metric[period] = number


def _evidence_source(
    sources: list[dict[str, Any]],
    *,
    root_id: str,
    title: str,
    kind: str,
    sheet: Any,
    row: Any,
    label: Any,
    cell: Any = "",
    formula: Any = "",
    number_format: Any = "",
    file_hash: Any = "",
    effective_at: Any = "",
) -> str:
    if not sheet:
        return root_id
    locator = f"{title}#sheet={sheet}"
    if row:
        locator += f";row={row}"
    evidence_id = f"{root_id}:{len(sources) + 1}"
    if any(item.get("locator") == locator for item in sources):
        return next(
            str(item["id"]) for item in sources if item.get("locator") == locator
        )
    sources.append(
        {
            "id": evidence_id,
            "kind": kind,
            "title": str(label or title),
            "locator": locator,
            "sheet": str(sheet),
            "cell": str(cell or ""),
            "formula": str(formula or ""),
            "number_format": str(number_format or ""),
            "file_hash": str(file_hash or ""),
            "effective_at": str(effective_at or ""),
            "fetched_at": "",
            "effective_from": "",
            "verified_current": True,
        }
    )
    return evidence_id


def _fact_source_rank(source_type: Any, title: str = "") -> int:
    return {
        "income_statement": 100,
        "balance_sheet": 90,
        "cash_flow": 90,
        "tax_summary": 80,
        "generic_table": 60,
        "dashboard": 40,
        "scenario": 20,
        "valuation": 10,
    }.get(str(source_type), 100 if re.search(r"statement|bctc|bao cao tai chinh", title, re.IGNORECASE) else 50)


def _numbers_equal(left: Any, right: Any) -> bool:
    try:
        first, second = float(left), float(right)
        return abs(first - second) <= max(1e-9, max(abs(first), abs(second), 1.0) * 1e-12)
    except (TypeError, ValueError):
        return left == right


def _metric(key: str, current: float | None, source_id: str, observation: dict[str, Any] | None = None, source_rank: int = 0) -> dict[str, Any]:
    measurement = observation.get("measurement") if isinstance(observation, dict) else None
    currency = (measurement or observation or {}).get("currency") if isinstance(measurement or observation, dict) else None
    if not currency and isinstance(observation, dict):
        declared_unit = str(observation.get("unit") or "")
        currency = declared_unit if re.fullmatch(r"[A-Z]{3}", declared_unit) else None
        if not currency and "value" in observation and not measurement:
            # Compatibility for the pre-v3 generic extractor; structured parser
            # facts always carry a Measurement and never take this fallback.
            currency = "VND"
    return {
        "id": key,
        "label": LABELS[key],
        "current": current,
        "previous": None,
        "budget": None,
        "benchmark": None,
        "unit": str(currency or ("VND" if observation is None else "")),
        "currency": currency,
        "measurement": measurement,
        "period": (measurement or {}).get("period", {}).get("label", "") if isinstance(measurement, dict) else "",
        "basis": (measurement or {}).get("period", {}).get("basis", "actual") if isinstance(measurement, dict) else "actual",
        "source_ids": [source_id],
        "assessment": "",
        "source_rank": source_rank,
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
    if report.get("schema_version") == 3:
        from .reporting import normalize_report_v3, v3_to_v2

        grounded_v2 = apply_grounding(v3_to_v2(report), context)
        grounded_v3 = normalize_report_v3(grounded_v2)
        context_meta = context.get("report_context", {})
        grounded_v3["report_context"] = {
            "company_id": str(context.get("company", {}).get("id", context.get("company", {}).get("company_id", ""))),
            "jurisdiction": str(context.get("jurisdiction", "")),
            "primary_period": str(context_meta.get("period", "")),
            "basis": str(context_meta.get("basis") or "actual"),
            "scenario": "none",
            "source_hashes": list(context_meta.get("source_hashes", [])),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        grounded_v3["reconciliation_checks"] = list(context.get("reconciliation_checks", []))
        quality = context.get("data_quality", {})
        grounded_v3["data_quality"] = {
            "coverage": float(quality.get("coverage", {}).get("ratio", 0.0)),
            "conflict_count": int(quality.get("conflict_count", 0)),
            "missing_material_fields": list(quality.get("missing_material_fields", [])),
            "confidence_caps": list(quality.get("confidence_caps", [])),
            "review_reasons": list(quality.get("review_reasons", [])),
        }
        review = list(grounded_v3.get("data_quality", {}).get("review_reasons", []))
        if any(item.get("status") == "FAIL" for item in grounded_v3["reconciliation_checks"]):
            review.append("Reconciliation FAIL")
        if review:
            grounded_v3["approval"] = {"status": "needs_review", "reasons": list(dict.fromkeys(review))}
        if grounded_v3["data_quality"]["confidence_caps"]:
            grounded_v3["overall_confidence"] = min(
                float(grounded_v3.get("overall_confidence", 0)),
                *grounded_v3["data_quality"]["confidence_caps"],
            )
        return grounded_v3
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
        benchmark_ids = {
            source_id
            for source_id in verified_benchmarks & set(narrative.get("source_ids", []))
            if _valid_benchmark(sources[source_id], context, metric_id=calculated.get("id"))
        }
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
    guarded_risks = []
    for risk in grounded.get("tax_risks", []):
        legal_ids = list(risk.get("legal_source_ids", []))
        if risk.get("regulation") and legal_ids and not all(
            sources.get(source_id, {}).get("kind") == "knowledge"
            and sources.get(source_id, {}).get("verified_current")
            for source_id in legal_ids
        ):
            missing.append({"field": "missing_knowledge", "impact": f"{risk.get('title', '')}: thiếu nguồn pháp lý chính thức đang hiệu lực.", "material": True})
            guarded_risks.append({**risk, "regulation": "", "legal_source_ids": []})
        else:
            guarded_risks.append(risk)
    grounded["tax_risks"] = guarded_risks
    grounded["missing_data"] = _unique_missing(missing)
    grounded["scenario_model"] = _scenario_model(grounded["metrics"])
    caps = context.get("data_quality", {}).get("confidence_caps", [])
    if caps:
        grounded["overall_confidence"] = min(float(grounded.get("overall_confidence", 0)), *caps)
    return grounded


def _valid_benchmark(source: dict[str, Any], context: dict[str, Any], *, metric_id: str = "") -> bool:
    if source.get("kind") != "benchmark" or not source.get("verified_current"):
        return False
    company_industry = _norm(context.get("company", {}).get("industry"))
    source_industry = _norm(source.get("industry"))
    if not company_industry or source_industry != company_industry:
        return False
    if not str(source.get("scope", "")).strip():
        return False
    if source.get("metric_id") and str(source.get("metric_id")) != metric_id:
        return False
    company_scope = _norm(context.get("company", {}).get("geography") or context.get("company", {}).get("country_code"))
    source_scope = _norm(source.get("geography") or source.get("country_code"))
    if company_scope and source_scope and company_scope != source_scope:
        return False
    company_currency = str(context.get("company", {}).get("currency") or "").upper()
    source_currency = str(source.get("currency") or "").upper()
    if company_currency and source_currency and company_currency != source_currency:
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
    scenario_currency = str(values.get("revenue", {}).get("currency") or values.get("revenue", {}).get("unit") or "VND")
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
            "unit": scenario_currency,
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
                "unit": scenario_currency,
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
    original = report
    if report.get("schema_version") == 3:
        from .reporting import v3_to_v2

        report = v3_to_v2(report)
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
    for check in original.get("reconciliation_checks", []):
        if check.get("status") == "FAIL":
            reasons.append(f"Reconciliation FAIL: {check.get('id', 'unknown')}.")
    for reason in original.get("data_quality", {}).get("review_reasons", []):
        if reason:
            reasons.append(str(reason))
    return list(dict.fromkeys(reasons))
