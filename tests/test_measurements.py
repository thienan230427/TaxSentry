from decimal import Decimal

from taxsentry.measurements import (
    detect_currency,
    detect_scale,
    infer_measure,
    make_measurement,
    parse_decimal,
)


def test_measurement_keeps_raw_and_normalizes_scale_without_fx():
    item = make_measurement("43.5", unit="USD billion", currency="USD")
    assert item.raw_value == "43.5"
    assert item.normalized_value == "43500000000"
    assert item.currency == "USD"
    assert item.scale_multiplier == "1000000000"


def test_measurement_rejects_ambiguous_currency_symbol():
    item = make_measurement("500", unit="¥ million")
    assert item.status == "conflict"
    assert item.currency is None
    assert item.normalized_value is None


def test_explicit_currency_context_resolves_shared_symbol():
    item = make_measurement("500", unit="$", label="Revenue", currency="CAD")
    assert item.status == "reported"
    assert item.currency == "CAD"
    assert item.normalized_value == "500"


def test_number_parser_handles_localized_and_accounting_values():
    assert parse_decimal("(1.234,50)-") == Decimal("-1234.50")
    assert detect_currency("EUR 4.5m") == ("EUR", False)
    assert detect_currency("US$ 4.5m") == ("USD", False)


def test_measurement_does_not_treat_ratio_or_vietnamese_labels_as_money_scale():
    assert infer_measure("Biên lợi nhuận gộp", "2025E") == "percentage"
    assert infer_measure("Doanh thu", "Tăng trưởng") == "percentage"
    assert infer_measure("Tổng nợ phải trả", "Thay đổi") == "percentage"
    assert detect_scale("Tài sản ngắn hạn")[0] == Decimal("1")
    assert detect_currency("Dùng để hiệu chỉnh dữ liệu")[0] is None
    assert make_measurement("43.5", unit="tỷ USD").display_unit == "USD billion"


def test_unknown_explicit_currency_is_a_conflict_without_normalized_amount():
    item = make_measurement("10", currency="ZZZ", label="Revenue")
    assert item.status == "conflict"
    assert item.currency is None
    assert item.normalized_value is None


def test_float_formula_noise_is_removed_before_decimal_normalization():
    item = make_measurement(-7.539999999999999, unit="USD billion")
    assert item.raw_value == "-7.54"
    assert item.normalized_value == "-7540000000"
