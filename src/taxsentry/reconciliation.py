"""Deterministic financial tie-outs executed before narrative generation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Mapping):
        measurement = value.get("measurement")
        if value.get("normalized_value") is not None:
            value = value.get("normalized_value")
        elif isinstance(measurement, Mapping) and measurement.get("normalized_value") is not None:
            value = measurement.get("normalized_value")
        else:
            value = value.get("value", value.get("current"))
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _currency(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    measurement = value.get("measurement")
    return str((measurement or value).get("currency") or "") or None


def _measure(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    measurement = value.get("measurement")
    return str((measurement or value).get("measure") or "") or None


def _check(name: str, actual: Decimal | None, expected: Decimal | None, *, tolerance: Decimal, evidence_ids: list[str] | None = None, where_to_fix: str = "") -> dict[str, Any]:
    if actual is None or expected is None:
        return {
            "id": name,
            "status": "WARN",
            "actual": str(actual) if actual is not None else None,
            "expected": str(expected) if expected is not None else None,
            "delta": None,
            "tolerance": str(tolerance),
            "evidence_ids": evidence_ids or [],
            "where_to_fix": where_to_fix,
        }
    delta = actual - expected
    return {
        "id": name,
        "status": "PASS" if abs(delta) <= tolerance else "FAIL",
        "actual": str(actual),
        "expected": str(expected),
        "delta": str(delta),
        "tolerance": str(tolerance),
        "evidence_ids": evidence_ids or [],
        "where_to_fix": where_to_fix,
    }


def _metric(metrics: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in metrics:
            return metrics[name]
    return None


def _evidence_ids(*values: Any) -> list[str]:
    ids: list[str] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        measurement = value.get("measurement")
        candidates = value.get("source_ids", [])
        if not candidates and isinstance(measurement, Mapping):
            candidates = measurement.get("evidence_ids", [])
        for item in candidates or []:
            if str(item) and str(item) not in ids:
                ids.append(str(item))
    return ids


def reconcile_financials(
    metrics: Mapping[str, Any] | list[Mapping[str, Any]],
    *,
    balance_sheet: Mapping[str, Any] | None = None,
    cash_flow: Mapping[str, Any] | None = None,
    scenarios: list[Mapping[str, Any]] | None = None,
    tolerance: Decimal | str = Decimal("0.000001"),
) -> list[dict[str, Any]]:
    """Return PASS/WARN/FAIL checks; never mutates source facts."""
    tolerance = Decimal(str(tolerance))
    if isinstance(metrics, list):
        indexed = {str(item.get("id")): item for item in metrics if isinstance(item, Mapping)}
    else:
        indexed = metrics
    checks: list[dict[str, Any]] = []
    revenue, cogs, gross = (_metric(indexed, name) for name in ("revenue", "cogs", "gross_profit"))
    currencies = {_currency(item) for item in (revenue, cogs, gross) if _currency(item)}
    measures = {_measure(item) for item in (revenue, cogs, gross) if _measure(item)}
    if measures and measures != {"money"}:
        checks.append({"id": "pnl.measure_compatibility", "status": "FAIL", "actual": None, "expected": None, "delta": None, "tolerance": str(tolerance), "evidence_ids": _evidence_ids(revenue, cogs, gross), "where_to_fix": "Không được dùng ratio/percentage thay cho amount tiền trong P&L."})
    if len(currencies) > 1:
        checks.append({"id": "pnl.currency_compatibility", "status": "FAIL", "actual": None, "expected": None, "delta": None, "tolerance": str(tolerance), "evidence_ids": _evidence_ids(revenue, cogs, gross), "where_to_fix": "Chuẩn hóa currency của Revenue/COGS/Gross profit trước khi cộng trừ."})
    elif revenue is not None and cogs is not None and gross is not None:
        amounts = (_decimal(revenue), _decimal(cogs), _decimal(gross))
        if all(value is not None for value in amounts):
            checks.append(_check("pnl.revenue_plus_cogs_equals_gross_profit", amounts[0] + amounts[1], amounts[2], tolerance=tolerance, evidence_ids=_evidence_ids(revenue, cogs, gross), where_to_fix="Đối chiếu P&L gốc và sign convention của COGS."))

    gross_profit, opex, operating = (_metric(indexed, name) for name in ("gross_profit", "total_opex", "operating_profit"))
    if gross_profit is not None and opex is not None and operating is not None:
        amounts = (_decimal(gross_profit), _decimal(opex), _decimal(operating))
        if all(value is not None for value in amounts):
            checks.append(_check("pnl.gross_profit_plus_opex_equals_operating_profit", amounts[0] + amounts[1], amounts[2], tolerance=tolerance, evidence_ids=_evidence_ids(gross_profit, opex, operating), where_to_fix="Đối chiếu tổng OPEX và Operating profit."))

    pbt, tax, net = (_metric(indexed, name) for name in ("ebt", "tax_expense", "net_income"))
    if pbt is not None and tax is not None and net is not None:
        amounts = (_decimal(pbt), _decimal(tax), _decimal(net))
        if all(value is not None for value in amounts):
            checks.append(_check("pnl.pbt_minus_tax_equals_net_income", amounts[0] - amounts[1], amounts[2], tolerance=tolerance, evidence_ids=_evidence_ids(pbt, tax, net), where_to_fix="Đối chiếu PBT, tax expense và net income."))

    for name, numerator in (("pnl.gross_margin", "gross_profit"), ("pnl.net_margin", "net_income")):
        item = _metric(indexed, numerator)
        ratio = _metric(indexed, "gross_margin" if numerator == "gross_profit" else "net_margin")
        numerator_value, revenue_value, ratio_value = _decimal(item), _decimal(revenue), _decimal(ratio)
        if numerator_value is not None and revenue_value not in (None, 0) and ratio_value is not None:
            checks.append(_check(name, numerator_value / revenue_value, ratio_value, tolerance=tolerance, evidence_ids=_evidence_ids(item, revenue, ratio), where_to_fix=f"Tính lại {name} từ amount cùng currency."))

    bs = balance_sheet or {}
    assets = _metric(bs, "assets", "total_assets")
    liabilities = _metric(bs, "liabilities", "total_liabilities")
    equity = _metric(bs, "equity", "total_equity")
    if assets is not None and liabilities is not None and equity is not None:
        amounts = (_decimal(assets), _decimal(liabilities), _decimal(equity))
        if all(value is not None for value in amounts):
            checks.append(_check("balance_sheet.assets_equals_liabilities_plus_equity", amounts[1] + amounts[2], amounts[0], tolerance=tolerance, evidence_ids=_evidence_ids(assets, liabilities, equity), where_to_fix="Đối chiếu Balance Sheet và tổng thành phần."))

    cf = cash_flow or {}
    beginning = _metric(cf, "beginning_cash", "cash_beginning")
    movement = _metric(cf, "net_cash_movement", "net_cash_flow")
    ending = _metric(cf, "ending_cash", "cash_ending")
    if beginning is not None and movement is not None and ending is not None:
        amounts = (_decimal(beginning), _decimal(movement), _decimal(ending))
        if all(value is not None for value in amounts):
            checks.append(_check("cash_flow.beginning_plus_movement_equals_ending", amounts[0] + amounts[1], amounts[2], tolerance=tolerance, evidence_ids=_evidence_ids(beginning, movement, ending), where_to_fix="Đối chiếu roll-forward Cash Flow."))
    bs_cash = _metric(bs, "cash", "cash_and_equivalents")
    if ending is not None and bs_cash is not None:
        ending_value, cash_value = _decimal(ending), _decimal(bs_cash)
        if ending_value is not None and cash_value is not None:
            checks.append(_check("cash_flow.ending_cash_equals_balance_sheet_cash", ending_value, cash_value, tolerance=tolerance, evidence_ids=_evidence_ids(ending, bs_cash), where_to_fix="Đối chiếu ending cash với cash trên Balance Sheet."))

    for index, scenario in enumerate(scenarios or []):
        scenario_currency = None
        if isinstance(scenario, Mapping):
            observation = scenario.get("observation") or {}
            scenario_currency = scenario.get("currency") or (observation.get("currency") if isinstance(observation, Mapping) else None)
        if scenario_currency and currencies and scenario_currency not in currencies:
            checks.append(_check(f"scenario.{index}.currency_compatibility", None, None, tolerance=tolerance, where_to_fix="Scenario phải cùng ISO currency với Actual."))
    return checks


def reconciliation_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [item for item in checks if item.get("status") == "FAIL"]
    warnings = [item for item in checks if item.get("status") == "WARN"]
    return {
        "checks": checks,
        "pass_count": sum(item.get("status") == "PASS" for item in checks),
        "warning_count": len(warnings),
        "failure_count": len(failures),
        "material_failures": [item["id"] for item in failures],
    }
