from __future__ import annotations

import shutil

import pytest
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont

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


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is a system prerequisite")
def test_real_image_ocr(tmp_path):
    path = tmp_path / "scan.png"
    image = Image.new("RGB", (900, 180), "white")
    ImageDraw.Draw(image).text((30, 50), "REVENUE 120000 PROFIT 18000", fill="black", font=ImageFont.load_default(size=38))
    image.save(path)
    result = extract(path, ["eng"])
    assert result.source == "ocr"
    assert "120000" in result.content
