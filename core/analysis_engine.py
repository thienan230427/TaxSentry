import json
import os
import sys
from pathlib import Path
import openai
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))
from utils.path_helper import JSON_PATH, KNOWLEDGE_PATH, AUDIT_REPORT_PATH

# Nạp các biến môi trường
load_dotenv()


class TaxSentryAnalysisEngine:
    """Bộ não phân tích AI đối chiếu luật thuế thực tế (TaxSentry AI Engine)."""

    def __init__(self):
        # Đọc cấu hình từ biến môi trường .env
        self.api_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "sk-lm-sVlR2otW:D3EDq8EiXWYdmvAhYsgY")
        self.model_name = os.getenv("LM_MODEL_NAME", "google/gemma-4-e4b")
        self.client = None
        self.log_callback = None

    def log(self, message):
        """Helper để ghi log: chuyển hướng sang callback nếu có, nếu không in ra console."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def connect(self) -> bool:
        """Khởi tạo kết nối tới máy chủ Local LM Studio."""
        try:
            self.client = openai.OpenAI(base_url=self.api_url, api_key=self.api_key)
            return True
        except Exception as e:
            self.log(f"❌ Khởi tạo kết nối LM Studio thất bại: {e}")
            return False

    def run_audit(self) -> str:
        """Đọc dữ liệu tài chính + luật thuế, gọi Gemma 4 để lập báo cáo kiểm toán."""
        if not self.client:
            if not self.connect():
                return ""

        # 1. Đọc dữ liệu JSON tài chính
        if not JSON_PATH.exists():
            return "❌ Lỗi: Chưa có tệp dữ liệu phân tích JSON (Vui lòng chạy parser.py trước!)."
        
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            financial_data = json.load(f)

        # 2. Đọc Kho Tri Thức Pháp Luật Thuế Việt Nam
        if not KNOWLEDGE_PATH.exists():
            return "❌ Lỗi: Chưa tìm thấy tệp cơ sở tri thức pháp luật thuế (tax_rules_vietnam.md)!"
        
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            tax_knowledge = f.read()

        # 3. Chuẩn bị prompt chuyên gia hệ thống (System Prompt) và Dữ liệu đầu vào (User Prompt)
        system_prompt = """
        Bạn là một Giám đốc Tài chính (CFO) kiêm Chuyên gia Kiểm toán Thuế cấp cao tại Việt Nam.
        Nhiệm vụ của bạn là nhận dữ liệu hoạt động kinh doanh thực tế của doanh nghiệp, đối chiếu nghiêm ngặt với các quy định pháp luật Thuế Việt Nam hiện hành (được cung cấp trong kho tri thức), phát hiện các sai sót, bóc tách các chi phí rủi ro, tính toán lại tiền thuế/tiền phạt, và viết một Báo cáo Đánh giá Hiệu quả Kinh doanh & Rủi ro Thuế cực kỳ chuyên nghiệp, sắc sảo cho Giám đốc.

        YÊU CẦU BÁO CÁO CỦA BẠN PHẢI TUÂN THỦ:
        1. Phân tích cụ thể các chỉ số: Doanh thu tăng trưởng thế nào? Biên lợi nhuận gộp ra sao? Chi phí OPEX có bất thường không?
        2. Bóc tách chi tiết các rủi ro thuế dựa trên số liệu thực tế: Chỉ ra chính xác dòng chi phí nào vi phạm luật thuế (ví dụ: Chi phí tiếp khách không hóa đơn đỏ).
        3. Tính toán lại Thu nhập chịu thuế thực tế sau khi loại bỏ chi phí rủi ro, tính lại số Thuế TNDN thực tế phải nộp, và số tiền thuế bị truy thu/bị phạt chậm nộp nếu có.
        4. Đưa ra các kiến nghị, giải pháp khắc phục cụ thể, thiết thực cho doanh nghiệp để tối ưu hóa vận hành và tuân thủ pháp luật thuế.
        5. Trình bày báo cáo rõ ràng, mạch lạc bằng tiếng Việt, sử dụng các đề mục chuyên nghiệp (Markdown).
        """

        user_prompt = f"""
        Chào chuyên gia, dưới đây là dữ liệu hoạt động kinh doanh tháng này của chúng tôi và kho tri thức luật thuế liên quan. Hãy tiến hành kiểm toán và lập báo cáo chi tiết:

        === 📊 1. DỮ LIỆU BÁO CÁO TÀI CHÍNH THÁNG 05/2026 (JSON) ===
        {json.dumps(financial_data, indent=2, ensure_ascii=False)}

        === 📖 2. KHO TRI THỨC PHÁP LUẬT THUẾ VIỆT NAM LIÊN QUAN ===
        {tax_knowledge}
        """

        self.log("🧠 Đang truyền dữ liệu và gửi yêu cầu phân tích tới Local Gemma 4 qua LM Studio...")
        self.log("💡 Quá trình suy luận và đối chiếu tri thức (RAG) đang diễn ra cục bộ, vui lòng chờ trong giây lát desu~!\n")

        try:
            # Gọi API của LM Studio để bắt đầu suy luận
            response = self.client.chat.completions.create(
                model=self.model_name,  # Sử dụng mô hình cấu hình từ .env desu~!
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2  # Giữ nhiệt độ thấp để AI phân tích số liệu chuẩn xác, logic và nghiêm túc desu~!
            )
            
            audit_result = response.choices[0].message.content
            
            # Lưu báo cáo kiểm toán ra tệp Markdown
            AUDIT_REPORT_PATH.write_text(audit_result, encoding="utf-8")
            return audit_result

        except Exception as e:
            return f"❌ Có lỗi phát sinh khi gọi mô hình Gemma 4 trên LM Studio:\n{e}\n(Sếp nhớ đảm bảo đã Start Server trong LM Studio tại cổng 1234 nha Sếp ơi~!)"

    def analyze_report(self, prompt: str) -> str:
        """Gửi prompt tùy chỉnh tới LM Studio AI Server và nhận kết quả (Dùng cho Chat 2 chiều)."""
        if not self.client:
            if not self.connect():
                return "❌ Lỗi kết nối AI Engine. Vui lòng kiểm tra LM Studio."
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ Lỗi kết nối AI Server (LM Studio): {e}"


def main():
    print("=== CHẠY THỬ NGHIỆM BỘ NÃO AI ANALYSIS ENGINE ===")
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
