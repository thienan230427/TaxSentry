from pathlib import Path

import pytest
from openpyxl import load_workbook

from taxsentry.artifacts import ArtifactService, detect_artifact_kind, render_artifact


def test_artifact_renderers_create_safe_office_files(tmp_path: Path):
    plan = {
        "title": "Báo cáo tháng 6",
        "subtitle": "Đơn vị: VND",
        "executive_summary": "Doanh thu tăng, cần đối chiếu hóa đơn.",
        "sections": [{"heading": "Nhận định", "paragraphs": ["Dữ liệu đã được tổng hợp."], "bullets": ["Kiểm tra chứng từ"]}],
        "tables": [{"title": "Chỉ tiêu", "headers": ["Chỉ tiêu", "Giá trị VND"], "rows": [["Doanh thu", "1200000000"], ["Ghi chú", "=HYPERLINK(\"bad\")"]]}],
        "slides": [{"title": "Kết quả", "bullets": ["Doanh thu 1,2 tỷ VND"]}],
    }
    paths = [render_artifact(kind, plan, tmp_path) for kind in ("docx", "xlsx", "pptx", "pdf")]
    assert all(path.is_file() and path.stat().st_size for path in paths)
    assert detect_artifact_kind("hãy tạo PowerPoint") == "powerpoint"
    workbook = load_workbook(paths[1], data_only=False)
    assert workbook["Chỉ tiêu"]["B2"].value == 1_200_000_000
    assert workbook["Chỉ tiêu"]["B3"].data_type == "s"
    custom = render_artifact("docx", plan, tmp_path, paths[0])
    assert custom.is_file() and custom != paths[0]


@pytest.mark.asyncio
async def test_artifact_service_saves_and_auto_sends(tmp_path: Path):
    plan = {
        "title": "Biên bản",
        "subtitle": "16/07/2026",
        "executive_summary": "Nội dung đã xác nhận.",
        "sections": [],
        "tables": [],
        "slides": [],
    }

    class Chat:
        async def structured(self, prompt, schema): return plan

    class Telegram:
        def __init__(self): self.sent = []
        async def notify(self, text, document=None):
            self.sent.append(document)
            return ["1"]

    telegram = Telegram()
    service = ArtifactService({"artifacts": {"output_dir": str(tmp_path), "auto_send_telegram": True}}, Chat(), telegram)
    path = await service.create("docx", "Tạo biên bản")
    assert path.is_file() and telegram.sent == [path]
