import json
import os
import sys
from pathlib import Path
from typing import Any
import openai
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))
from taxsentry.config.paths import JSON_PATH, KNOWLEDGE_PATH, AUDIT_REPORT_PATH

# Nạp các biến môi trường
load_dotenv()


class TaxSentryAnalysisEngine:
    """Bộ não phân tích AI đối chiếu luật thuế thực tế (TaxSentry AI Engine)."""

    def __init__(self):
        self.auth_mode = os.getenv("TAXSENTRY_AI_AUTH_MODE", "lmstudio") or "lmstudio"
        self.api_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "")
        self.model_name = os.getenv("LM_MODEL_NAME", "google/gemma-4-e4b")
        self.client = None
        self.log_callback = None

    def _load_codex_access_token(self) -> str:
        auth_path = Path.home() / ".codex" / "auth.json"
        if not auth_path.exists():
            raise FileNotFoundError(f"Không tìm thấy Codex OAuth profile tại {auth_path}")

        try:
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Không thể đọc Codex OAuth profile: {exc}") from exc

        access_token = payload.get("tokens", {}).get("access_token") or payload.get("OPENAI_API_KEY", "")
        if not access_token:
            raise RuntimeError("Codex OAuth profile không có access token khả dụng.")
        return str(access_token)

    def log(self, message):
        """Helper để ghi log: chuyển hướng sang callback nếu có, nếu không in ra console."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def connect(self) -> bool:
        """Khởi tạo kết nối tới AI engine hiện được cấu hình."""
        try:
            resolved_key = self.api_key
            if self.auth_mode == "codex_oauth":
                resolved_key = self._load_codex_access_token()
                if not self.api_url or self.api_url == "http://localhost:1234/v1":
                    self.api_url = "https://api.openai.com/v1"

            self.client = openai.OpenAI(base_url=self.api_url, api_key=resolved_key)
            return True
        except Exception as e:
            self.log(f"❌ Khởi tạo kết nối AI engine thất bại [{self.auth_mode}]: {e}")
            return False

    def _extract_message_text(self, response: Any) -> str:

        try:
            message = response.choices[0].message
        except Exception:
            return ""

        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        chunks.append(str(text))
                elif isinstance(item, str):
                    chunks.append(item)
            return "\n".join(part.strip() for part in chunks if str(part).strip()).strip()

        return ""

    def _create_completion_with_retry(self, messages: list[dict], temperature: float) -> str:
        """Gọi AI engine và retry một lần nếu content trả về bị rỗng."""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
        )
        text = self._extract_message_text(response)
        if text:
            return text

        self.log("⚠️ AI Engine trả về content rỗng, đang retry với yêu cầu xuất câu trả lời cuối cùng rõ ràng...")
        retry_messages = list(messages) + [{
            "role": "user",
            "content": "Vui lòng xuất PHẦN TRẢ LỜI CUỐI CÙNG đầy đủ trong message.content. Không để trống và không chỉ trả về suy luận nội bộ."
        }]
        retry_response = self.client.chat.completions.create(
            model=self.model_name,
            messages=retry_messages,
            temperature=temperature,
        )
        return self._extract_message_text(retry_response)

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n\n[TRUNCATED: omitted {len(text) - max_chars} trailing characters to fit local model context]"

    @staticmethod
    def _compact_financial_data(financial_data: dict, max_line_items_per_sheet: int = 8) -> dict:
        data = financial_data.get("data", {}) if isinstance(financial_data, dict) else {}
        sheets = []
        for sheet in data.get("sheets", [])[:8]:
            line_items = sheet.get("line_items", []) or []
            sheets.append({
                "name": sheet.get("name"),
                "type": sheet.get("type"),
                "dimensions": sheet.get("dimensions"),
                "headers": (sheet.get("headers") or [])[:20],
                "sample_line_items": line_items[:max_line_items_per_sheet],
                "sample_count": min(len(line_items), max_line_items_per_sheet),
                "total_line_items": len(line_items),
            })

        compact_payload = {
            "metadata": financial_data.get("metadata", {}),
            "assumptions": financial_data.get("assumptions", {}),
            "data": {
                "workbook_overview": data.get("workbook_overview", {}),
                "canonical_metrics": data.get("canonical_metrics", {}),
                "income_statement": data.get("income_statement", {}),
                "sheets": sheets,
            },
        }
        return compact_payload

    def run_audit(self) -> str:

        if not self.client:
            if not self.connect():
                return ""

        # 1. Đọc dữ liệu JSON tài chính
        if not JSON_PATH.exists():
            return "❌ Lỗi: Chưa có tệp dữ liệu phân tích JSON (Vui lòng chạy parser.py trước!)."
        
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            financial_data = json.load(f)
        compact_financial_data = self._compact_financial_data(financial_data)
        compact_financial_json = json.dumps(compact_financial_data, indent=2, ensure_ascii=False)

        # 2. Đọc Kho Tri Thức Pháp Luật Thuế Việt Nam
        if not KNOWLEDGE_PATH.exists():
            return "❌ Lỗi: Chưa tìm thấy tệp cơ sở tri thức pháp luật thuế (tax_rules_vietnam.md)!"
        
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            tax_knowledge = f.read()
        tax_knowledge = self._truncate_text(tax_knowledge, 8000)

        # 3. Chuẩn bị prompt chuyên gia hệ thống (System Prompt) và Dữ liệu đầu vào (User Prompt)
        system_prompt = """
        Bạn là một Giám đốc Tài chính (CFO) kiêm Chuyên gia Kiểm toán Thuế cấp cao tại Việt Nam.
        Nhiệm vụ của bạn là nhận dữ liệu kế toán/tài chính/thuế thực tế của doanh nghiệp từ nhiều định dạng workbook Excel khác nhau (báo cáo kết quả kinh doanh, bảng lương, tổng hợp thuế-BHXH, bảng số liệu thô, workbook nhiều sheet), đối chiếu nghiêm ngặt với các quy định pháp luật Thuế Việt Nam hiện hành (được cung cấp trong kho tri thức), phát hiện sai sót, bóc tách rủi ro, tính toán lại nghĩa vụ thuế khi có đủ dữ liệu, và viết Báo cáo Đánh giá Hiệu quả Kinh doanh & Rủi ro Thuế chuyên nghiệp cho Giám đốc.

        YÊU CẦU BÁO CÁO CỦA BẠN PHẢI TUÂN THỦ:
        1. Trước tiên hãy nhận diện loại workbook/dữ liệu đang được cung cấp (P&L, payroll, tax summary, balance sheet, raw financial table, workbook hỗn hợp nhiều sheet).
        2. Nếu có dữ liệu kinh doanh: phân tích doanh thu, biên lợi nhuận, cơ cấu chi phí, OPEX và các biến động bất thường.
        3. Nếu có dữ liệu lương/thuế/BHXH: phân tích tổng quỹ lương, thuế TNCN, bảo hiểm bắt buộc, khoản thực lĩnh, điểm bất thường và rủi ro tuân thủ.
        4. Nếu có dữ liệu đủ chi tiết: tính toán lại Thu nhập chịu thuế, thuế phải nộp, các khoản bị loại, truy thu hoặc phạt chậm nộp nếu có.
        5. Nếu dữ liệu KHÔNG đủ để kết luận định lượng hoàn chỉnh, phải nêu rõ phần nào đủ dữ liệu, phần nào thiếu, và các tài liệu cần bổ sung.
        6. Đưa ra kiến nghị, giải pháp khắc phục cụ thể, thiết thực cho doanh nghiệp để tối ưu hóa vận hành và tuân thủ pháp luật thuế.
        7. Trình bày báo cáo rõ ràng, mạch lạc bằng tiếng Việt, sử dụng các đề mục chuyên nghiệp (Markdown).
        """

        user_prompt = f"""
        Chào chuyên gia, dưới đây là dữ liệu hoạt động kinh doanh tháng này của chúng tôi và kho tri thức luật thuế liên quan. Hãy tiến hành kiểm toán và lập báo cáo chi tiết.
        Lưu ý: đây là payload đã được nén để phù hợp context của local model; nếu dữ liệu chưa đủ để kết luận thì phải nêu rõ phần thiếu.

        === 📊 1. DỮ LIỆU BÁO CÁO TÀI CHÍNH MỚI NHẤT (JSON ĐÃ NÉN) ===
        {compact_financial_json}

        === 📖 2. KHO TRI THỨC PHÁP LUẬT THUẾ VIỆT NAM LIÊN QUAN (TRÍCH ĐOẠN) ===
        {tax_knowledge}
        """

        self.log(f"🧾 Audit payload chars: financial={len(compact_financial_json)}, knowledge={len(tax_knowledge)}")
        self.log(f"🧠 Đang truyền dữ liệu và gửi yêu cầu phân tích tới AI engine [{self.auth_mode}] với model {self.model_name}...")


        try:
            audit_result = self._create_completion_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
            )
            if not audit_result:
                return "❌ AI Engine trả về nội dung trống. Vui lòng thử lại hoặc kiểm tra model / cấu hình AI hiện tại."

            # Lưu báo cáo kiểm toán ra tệp Markdown
            AUDIT_REPORT_PATH.write_text(audit_result, encoding="utf-8")
            return audit_result

        except Exception as e:
            return f"❌ Có lỗi phát sinh khi gọi AI engine [{self.auth_mode}] với model {self.model_name}:\n{e}"

    def analyze_report(self, prompt: str) -> str:

        if not self.client:
            if not self.connect():
                return "❌ Lỗi kết nối AI Engine. Vui lòng kiểm tra cấu hình endpoint / auth mode hiện tại."
        try:
            system_prompt = """
            Bạn là TaxSentry Copilot — một trợ lý tài chính/thuế nói tiếng Việt tự nhiên.
            Khi trả lời người dùng:
            - xưng 'em', gọi người dùng là 'Sếp'
            - nói như người thật, ngắn gọn, rõ ràng, có trọng tâm
            - không dùng văn phong máy móc hoặc khuôn mẫu công văn nếu không được yêu cầu
            - ưu tiên nêu chứng cứ/số chính trước rồi mới diễn giải
            - nếu dữ liệu chưa đủ thì nói thẳng phần thiếu thay vì suy đoán
            """
            response_text = self._create_completion_with_retry(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.45,
            )
            if response_text:
                return response_text
            return "❌ AI Engine trả về nội dung trống. Sếp thử lại giúp em hoặc đổi model / auth mode hiện tại."
        except Exception as e:
            return f"❌ Lỗi kết nối AI Server [{self.auth_mode}]: {e}"


def main():

    engine = TaxSentryAnalysisEngine()
    
    # Chạy kiểm toán thực tế
    report = engine.run_audit()
    
    if report and not report.startswith("❌"):
        print("🎉 QUÁ TRÌNH KIỂM TOÁN AI HOÀN THÀNH XUẤT SẮC!")
        print(f"💾 Báo cáo kiểm toán thuế đã được lưu trữ an toàn tại: {AUDIT_REPORT_PATH}\n")
        print("=" * 60)
        print("📬 TRÍCH ĐOẠN ĐẦU CỦA BÁO CÁO KIỂM TOÁN AI:")
        # In 15 dòng đầu tiên của báo cáo ra console để xem thử
        print("\n".join(report.split("\n")[:25]))
        print("\n... (Báo cáo đầy đủ xem tại file audit_report.md) ...")
        print("=" * 60)
    else:
        print(report)


if __name__ == "__main__":
    main()
