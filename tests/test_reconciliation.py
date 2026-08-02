from taxsentry.reconciliation import reconcile_financials, reconciliation_summary


def test_cash_flow_reconciliation_surfaces_material_mismatch():
    checks = reconcile_financials(
        {"revenue": {"value": 43.5}, "cogs": {"value": -25.407}, "gross_profit": {"value": 18.093}},
        balance_sheet={"cash": {"value": 8.918}},
        cash_flow={"ending_cash": {"value": 20.859}},
        tolerance="0.000001",
    )
    result = next(item for item in checks if item["id"] == "cash_flow.ending_cash_equals_balance_sheet_cash")
    assert result["status"] == "FAIL"
    assert result["delta"] == "11.941"
    assert reconciliation_summary(checks)["failure_count"] == 1


def test_reconciliation_accepts_v3_observations_directly():
    def observation(value):
        return {"normalized_value": value, "measure": "money", "currency": "USD", "evidence_ids": ["s"]}
    checks = reconcile_financials(
        {"revenue": observation("43"), "cogs": observation("-25"), "gross_profit": observation("18")}
    )
    result = next(item for item in checks if item["id"] == "pnl.revenue_plus_cogs_equals_gross_profit")
    assert result["status"] == "PASS"


def test_mixed_currency_pnl_is_blocked():
    def observation(value, currency):
        return {"normalized_value": value, "measure": "money", "currency": currency, "evidence_ids": ["s"]}

    checks = reconcile_financials(
        {
            "revenue": observation("43", "USD"),
            "cogs": observation("-25", "EUR"),
            "gross_profit": observation("18", "USD"),
        }
    )
    result = next(item for item in checks if item["id"] == "pnl.currency_compatibility")
    assert result["status"] == "FAIL"
