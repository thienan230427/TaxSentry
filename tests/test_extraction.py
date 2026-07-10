from __future__ import annotations

from openpyxl import Workbook

from taxsentry.extraction import extract


def test_xlsx_extraction_uses_existing_financial_parser(tmp_path):
    path = tmp_path / "report.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Chỉ tiêu", "Tháng 4", "Tháng 5"])
    sheet.append(["Doanh thu", 100_000_000, 120_000_000])
    sheet.append(["Lợi nhuận ròng", 20_000_000, 18_000_000])
    workbook.save(path)
    result = extract(path, ["vie", "eng"])
    assert result.source == "xlsx"
    assert result.confidence == 1.0
    assert result.content["data"]["canonical_metrics"]
