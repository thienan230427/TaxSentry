"""
📄 TaxSentry PDF Parser Module
Sử dụng pdfplumber để trích xuất văn bản từ báo cáo kinh doanh định dạng PDF,
và gọi AI Local (Gemma 2) để phân tích, chuyển đổi thành dữ liệu JSON cấu trúc chuẩn.
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
import pdfplumber
from dotenv import load_dotenv

# Nạp các biến môi trường
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

try:
    from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
except ModuleNotFoundError:
    TaxSentryAnalysisEngine = None

try:
    from taxsentry.database.db_manager import TaxSentryDBManager
except ModuleNotFoundError:
    TaxSentryDBManager = None


class TaxSentryPDFParser:
    """Bộ đọc và phân tích cấu trúc báo cáo tài chính PDF bằng AI."""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.raw_text = ""
        self.assumptions = {
            "tax_rate": 0.20,
            "hospitality_limit_pct": 0.15,
            "daily_penalty_pct": 0.0003
        }
        self.parsed_data = {}

    def load_and_extract_text(self) -> bool:
        """Đọc và trích xuất text từ tệp PDF."""
        if not self.file_path.exists():
            print(f"❌ Không tìm thấy file PDF: {self.file_path}")
            return False
            
        try:
            text_list = []
            with pdfplumber.open(self.file_path) as pdf:
                for idx, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        text_list.append(text)
            self.raw_text = "\n--- PAGE BREAK ---\n".join(text_list)
            return len(self.raw_text.strip()) > 0
        except Exception as e:
            print(f"❌ Lỗi khi đọc file PDF: {e}")
            return False

    def parse_with_ai(self) -> bool:
        """Gửi text thô PDF qua AI để trích xuất thông tin JSON cấu trúc."""
        if not self.raw_text:
            if not self.load_and_extract_text():
                return False

        # Thiết lập prompt để AI trích xuất thông tin
        system_prompt = """
        Bạn là một chuyên gia phân tích dữ liệu tài chính kế toán tại Việt Nam.
        Nhiệm vụ của bạn là đọc đoạn văn bản thô trích xuất từ báo cáo hoạt động kinh doanh (PDF), trích xuất chính xác các số liệu tài chính của Tháng 05/2026 (hoặc tháng hiện tại được báo cáo) và xuất ra định dạng JSON cấu trúc sạch sẽ.
        
        Bạn CẦN trả về DUY NHẤT một chuỗi JSON hợp lệ (không kèm theo phân tích hay chữ giải thích nào khác ngoài JSON, không đặt trong block markdown ```json...```), cấu trúc như sau:
        {
          "revenue": 0.0,
          "cogs": 0.0,
          "gross_profit": 0.0,
          "marketing_exp": 0.0,
          "salary_exp": 0.0,
          "hospitality_valid_exp": 0.0,
          "hospitality_no_invoice_exp": 0.0,
          "rent_exp": 0.0,
          "total_opex": 0.0,
          "ebt": 0.0,
          "tax_expense": 0.0,
          "net_income": 0.0,
          "notes": {
            "revenue": "ghi chú nếu có",
            "cogs": "ghi chú nếu có",
            "marketing_exp": "ghi chú nếu có",
            "salary_exp": "ghi chú nếu có",
            "hospitality_no_invoice_exp": "ghi chú về chi phí tiếp khách không hóa đơn đỏ nếu có",
            "general": "ghi chú chung từ kế toán trưởng"
          }
        }
        
        Lưu ý: Nếu không tìm thấy chỉ số nào, hãy để giá trị mặc định là 0.0. Hãy tính toán kiểm tra logic (ví dụ: gross_profit = revenue - cogs, net_income = ebt - tax_expense) để đảm bảo dữ liệu trích xuất chính xác nhất.
        """

        user_prompt = f"""
        Dưới đây là văn bản thô trích xuất từ file báo cáo PDF:
        ==================================================
        {self.raw_text}
        ==================================================
        
        Hãy phân tích văn bản này và trả về kết quả JSON theo đúng cấu trúc yêu cầu!
        """

        if TaxSentryAnalysisEngine is None:
            print("❌ Không thể parse PDF vì thiếu dependency hoặc engine AI không khả dụng.")
            return False

        engine = TaxSentryAnalysisEngine()
        if not engine.connect():
            print("❌ Không thể kết nối tới LM Studio Server để parse PDF!")
            return False

        try:

            response = engine.client.chat.completions.create(
                model=engine.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0
            )
            
            ai_content = engine._extract_message_text(response)
            if not ai_content:
                raise ValueError("AI parser trả về nội dung rỗng")
            
            # Sử dụng Regex trích xuất chuỗi JSON nằm giữa các dấu ngoặc nhọn ngoài cùng
            json_match = re.search(r'(\{.*\})', ai_content, re.DOTALL)

            if json_match:
                ai_content = json_match.group(1)
            else:

                if ai_content.startswith("```"):
                    lines = ai_content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].startswith("```"):
                        lines = lines[:-1]
                    ai_content = "\n".join(lines).strip()
            
            # Parse JSON
            self.parsed_data = json.loads(ai_content)
            engine.close() if hasattr(engine, 'close') else None
            return True
        except Exception as e:
            print(f"❌ Lỗi khi phân tích bằng AI: {e}")
            if 'engine' in locals():
                engine.close() if hasattr(engine, 'close') else None
            return False

    def export_json(self, output_path: str = None) -> str:
        """Xuất kết quả phân tích JSON."""
        if not self.parsed_data:
            return ""

        result = {
            "metadata": {
                "project": "TaxSentry",
                "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_name": self.file_path.name,
                "file_type": "pdf"
            },
            "assumptions": self.assumptions,
            "data": {
                "income_statement": {
                    "T4_Actual": {k: 0.0 for k in self.parsed_data.keys() if k != "notes"},  # PDF thường chỉ có 1 tháng
                    "T5_Actual": {k: v for k, v in self.parsed_data.items() if k != "notes"},
                    "notes": self.parsed_data.get("notes", {})
                }
            }
        }
        
        # Đồng bộ cấu trúc tên ghi chú của excel_parser
        # Trong Excel notes ghi chú có cấu trúc dẹt: {"hospitality_no_invoice_exp": "..."}
        # Ở đây ta chuyển đổi ghi chú dẹt
        flat_notes = {}
        for k, v in self.parsed_data.get("notes", {}).items():
            flat_notes[k] = v
        result["data"]["income_statement"]["notes"] = flat_notes

        json_str = json.dumps(result, indent=4, ensure_ascii=False)
        if output_path:
            Path(output_path).write_text(json_str, encoding="utf-8")
        return json_str

    def log_to_database(self, trace_context: dict | None = None, job_id: str | None = None) -> bool:
        """Ghi kết quả phân tích vào Database."""
        if not self.parsed_data:
            return False

        if TaxSentryDBManager is None:
            print("❌ Không thể ghi database vì thiếu dependency hoặc DB manager không khả dụng.")
            return False

        db = TaxSentryDBManager()
        if not db.connect():
            return False

        t5_data = {k: v for k, v in self.parsed_data.items() if k != "notes"}
        revenue = t5_data.get("revenue", 0.0)
        gross_profit = t5_data.get("gross_profit", 0.0)
        total_opex = t5_data.get("total_opex", 0.0)
        net_income = t5_data.get("net_income", 0.0)
        no_invoice = t5_data.get("hospitality_no_invoice_exp", 0.0)
        valid_hosp = t5_data.get("hospitality_valid_exp", 0.0)
        
        limit = revenue * self.assumptions["hospitality_limit_pct"]
        total_hosp = valid_hosp + no_invoice

        risks = []
        if no_invoice > 0:
            risks.append("Chi phí không hóa đơn")
        if total_hosp > limit:
            risks.append("Vượt hạn mức")
            
        if risks:
            tax_risk_status = "🚨 Rủi ro (" + " & ".join(risks) + ")"
        else:
            tax_risk_status = "✅ An toàn"

        sender_email = os.getenv("ACCOUNTANT_EMAIL", "") or os.getenv("EMAIL_USER", "") or "unknown"

        success = db.log_report(
            received_at=datetime.now(),
            sender=sender_email,
            file_name=self.file_path.name,
            revenue=revenue,
            gross_profit=gross_profit,
            total_opex=total_opex,
            net_income=net_income,
            hospitality_no_invoice=no_invoice,
            tax_risk_status=tax_risk_status,
            status="Processed",
            job_id=job_id,
        )
        db.close()
        return success

def main():
    print("--- CHẠY THỬ NGHIỆM PDF PARSER ---")
    # Để kiểm tra, chúng ta cần một file PDF thực tế hoặc kiểm tra lỗi import.
    # Module này sẽ được gọi từ automation pipeline khi kế toán gửi file PDF.
    print("PDF Parser module loaded successfully.")

if __name__ == "__main__":
    main()
