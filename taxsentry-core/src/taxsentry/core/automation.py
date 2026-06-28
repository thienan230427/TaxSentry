"""
🤖 TaxSentry Automation Workflow Co-ordinator
Điều phối toàn bộ quy trình: Quét hòm thư -> Tải file -> Parse dữ liệu -> AI Phân tích -> Tạo PDF -> Gửi Email & Telegram.
"""

import os
import sys
import time
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Thêm path dự án
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from taxsentry.core.email_poller import TaxSentryEmailPoller
from taxsentry.core.excel_parser import TaxSentryParser

try:
    from taxsentry.core.pdf_parser import TaxSentryPDFParser
except ModuleNotFoundError:
    class _UnavailablePDFParser:
        def __init__(self, *args, **kwargs):
            self.file_path = Path(args[0]) if args else Path('.')
        def load_and_extract_text(self):
            return False
        def parse_with_ai(self):
            return False
        def export_json(self, *args, **kwargs):
            return False
        def parse_assumptions(self):
            return None
        def parse_income_statement(self):
            return None
        def has_meaningful_data(self):
            return False
        def log_to_database(self, *args, **kwargs):
            return False
    TaxSentryPDFParser = _UnavailablePDFParser

try:
    from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
except ModuleNotFoundError:
    class _UnavailableAnalysisEngine:
        def __init__(self, *args, **kwargs):
            self.log_callback = None
        def connect(self):
            return False
        def close(self):
            return None
        def run_audit(self, *args, **kwargs):
            return ''
        def analyze_report(self, *args, **kwargs):
            return ''
    TaxSentryAnalysisEngine = _UnavailableAnalysisEngine

from taxsentry.core.pdf_generator import TaxSentryPDFGenerator
from taxsentry.core.email_sender import TaxSentryEmailSender
from taxsentry.core.evidence_preview import build_trace_context, build_evidence_context, save_evidence_context
from taxsentry.config.paths import DOWNLOAD_DIR, JSON_PATH, EVIDENCE_CONTEXT_PATH
from taxsentry.database import TaxSentryArtifactStore

# Toàn cục lưu logs hoạt động để main.py hiển thị trên TUI
AUTOMATION_LOGS = []

def log_activity(message: str):
    """Ghi nhận log hoạt động kèm dấu thời gian."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_str = f"[{timestamp}] {message}"
    # Đã tắt print trực tiếp ra console để tránh vỡ giao diện TUI và CLI Chat
    AUTOMATION_LOGS.append(log_str)
    # Giới hạn số lượng logs
    if len(AUTOMATION_LOGS) > 50:
        AUTOMATION_LOGS.pop(0)

class TaxSentryAutomationWorkflow:
    """Hệ thống điều phối tự động hoạt động kinh doanh & thuế."""

    def __init__(self):
        self.poller = TaxSentryEmailPoller()
        self.poller.log_callback = log_activity
        self.engine = TaxSentryAnalysisEngine()
        self.engine.log_callback = log_activity
        self.generator = TaxSentryPDFGenerator()
        self.sender = TaxSentryEmailSender()
        self.artifact_store = TaxSentryArtifactStore()
        self.artifact_store.connect()
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> int:
        """Thực hiện một chu kỳ quét và xử lý báo cáo. Trả về số lượng tệp đã xử lý."""
        log_activity("🔄 Bắt đầu chu kỳ quét hòm thư Kế toán trưởng...")
        
        # 1. Kết nối hòm thư
        connected = self.poller.connect()
        if not connected:
            log_activity("⚠️ Không thể kết nối hòm thư thực tế. Chạy ở chế độ GIẢ LẬP.")
            
        # 2. Quét và tải các file đính kèm mới
        downloaded_files = self.poller.check_and_download()
        self.poller.disconnect()

        if not downloaded_files:
            log_activity("✅ Không phát hiện báo cáo mới nào chưa đọc.")
            return 0

        log_activity(f"📬 Phát hiện {len(downloaded_files)} báo cáo mới cần xử lý.")
        processed_count = 0
        successful_email_ids: set[str] = set()
        failed_email_ids: set[str] = set()

        for file_path_str in downloaded_files:
            file_path = Path(file_path_str)
            file_context = self.poller.get_file_context(str(file_path))
            email_id = file_context.get('email_id') if file_context else None
            trace_context = build_trace_context(source_file=file_path.name, source_path=str(file_path))
            log_activity(f"📂 Đang xử lý tệp tin: '{file_path.name}'...")

            try:
                # 3. Phân tích dữ liệu tài chính (Parser)
                is_excel = file_path.suffix.lower() == '.xlsx'
                is_pdf = file_path.suffix.lower() == '.pdf'
                
                json_output_path = str(JSON_PATH)
                
                if is_excel:
                    log_activity("📊 Trích xuất dữ liệu từ bảng tính Excel...")
                    parser = TaxSentryParser(str(file_path))
                    parser.load()
                    parser.parse_assumptions()
                    parser.parse_income_statement()
                    # Parser mới đọc linh hoạt nhiều workbook; chỉ bỏ qua nếu thật sự không trích xuất được dữ liệu nào.
                    if not parser.has_meaningful_data():
                        log_activity("⚠️ File Excel không có đủ dữ liệu kế toán/tài chính để phân tích. Bỏ qua.")
                        continue
                    parser.export_json(json_output_path, trace_context=trace_context, artifact_store=self.artifact_store)
                    evidence_context = build_evidence_context(parser, file_context, trace_context=trace_context)
                    save_evidence_context(evidence_context, EVIDENCE_CONTEXT_PATH, artifact_store=self.artifact_store)
                    db_success = parser.log_to_database(trace_context=trace_context)
                elif is_pdf:
                    log_activity("📊 Trích xuất dữ liệu từ tài liệu PDF bằng AI...")
                    pdf_parser = TaxSentryPDFParser(str(file_path))
                    if pdf_parser.parse_with_ai():
                        pdf_parser.export_json(json_output_path, trace_context=trace_context, artifact_store=self.artifact_store)
                        db_success = pdf_parser.log_to_database(trace_context=trace_context)
                    else:
                        raise ValueError("AI không thể đọc hiểu cấu trúc file PDF báo cáo!")
                else:
                    log_activity(f"⚠️ Định dạng file không được hỗ trợ: {file_path.suffix}")
                    continue

                if db_success:
                    log_activity("✅ Đã chuẩn hóa dữ liệu thành công và lưu vào MySQL Database.")
                else:
                    log_activity("⚠️ Dữ liệu trích xuất thành công nhưng không thể đồng bộ MySQL DB.")
                    if email_id:
                        failed_email_ids.add(email_id)
                    continue

                # 4. Chạy phân tích AI chuyên sâu đối chiếu luật thuế

                ai_report_markdown = self.engine.run_audit()
                
                if not ai_report_markdown or ai_report_markdown.startswith("❌"):
                    raise ValueError(f"AI Engine báo lỗi: {ai_report_markdown}")

                log_activity("✅ AI đã hoàn tất báo cáo kiểm toán tài chính và thuế.")

                # 5. Tạo file PDF báo cáo chuyên nghiệp
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_report_path = self.download_dir / f"BaoCao_KiemToan_{timestamp_str}.pdf"
                
                log_activity("📄 Đang sinh tệp PDF báo cáo chuyên nghiệp hỗ trợ tiếng Việt...")
                pdf_success = self.generator.generate(ai_report_markdown, str(pdf_report_path), trace_context=trace_context, artifact_store=self.artifact_store)

                if not pdf_success:
                    raise ValueError("Không thể tạo file PDF báo cáo!")

                # Tạo tóm tắt ngắn từ báo cáo AI
                summary_lines = []
                for line in ai_report_markdown.split('\n'):
                    if line.strip().startswith('🚨') or line.strip().startswith('⚠️') or 'rủi ro' in line.lower() or 'tóm tắt' in line.lower():
                        summary_lines.append(line.strip())
                summary_text = "\n".join(summary_lines[:8])  # Lấy tối đa 8 dòng cảnh báo chính

                # 6. Gửi báo cáo PDF qua Email cho Giám đốc
                log_activity("📧 Đang gửi email đính kèm báo cáo PDF cho Giám đốc...")
                email_success = self.sender.send_report(str(pdf_report_path), summary_text)
                if email_success:
                    log_activity("✅ Đã gửi Email báo cáo thành công.")
                else:
                    log_activity("❌ Gửi Email báo cáo thất bại.")

                # 7. Gửi tin nhắn tóm tắt và PDF qua Telegram Bot cho Giám đốc
                log_activity("📡 Đang gửi preview attachment, tóm tắt và PDF báo cáo qua Telegram Bot...")
                
                # Để tránh chặn tiến trình chính, chạy async qua loop
                try:
                    from taxsentry.bot.telegram_bot import send_active_report_to_director
                    tele_success = asyncio.run(
                        send_active_report_to_director(
                            str(pdf_report_path),
                            summary_text,
                            evidence_context_path=str(EVIDENCE_CONTEXT_PATH),
                        )
                    )
                    if tele_success:
                        log_activity("✅ Đã gửi thông báo Telegram thành công.")
                    else:
                        log_activity("❌ Gửi thông báo Telegram thất bại.")
                except Exception as tele_err:
                    log_activity(f"❌ Lỗi tích hợp Telegram: {tele_err}")
                    if email_id:
                        failed_email_ids.add(email_id)
                    continue

                processed_count += 1
                if email_id:
                    successful_email_ids.add(email_id)

                log_activity(f"🎉 Hoàn thành xử lý tự động hoàn toàn cho file: '{file_path.name}'!")

            except Exception as ex:
                log_activity(f"❌ Lỗi nghiêm trọng khi xử lý file '{file_path.name}': {ex}")
                log_activity(f"⚠️ Email này sẽ được QUÉT LẠI ở chu kỳ tiếp theo (chưa đánh dấu processed).")
                if email_id:
                    failed_email_ids.add(email_id)

        # Chỉ đánh dấu những email thật sự hoàn thành toàn bộ chuỗi xử lý.
        email_ids_to_mark = sorted(successful_email_ids - failed_email_ids)
        if email_ids_to_mark:
            marked = self.poller.mark_email_ids_as_processed(email_ids_to_mark)
            log_activity(f"✅ Đã đánh dấu {marked} email là đã xử lý thành công.")

        return processed_count

    def start_loop(self, interval_seconds: int = 60):
        """Khởi chạy vòng lặp quét tự động liên tục."""
        log_activity(f"🚀 Khởi động tiến trình giám sát tự động TaxSentry (Chu kỳ: {interval_seconds}s)...")
        while True:
            try:
                self.run_once()
            except Exception as e:
                log_activity(f"❌ Lỗi vòng lặp chính: {e}")
            time.sleep(interval_seconds)

def main():
    print("=== CHẠY THỬ NGHIỆM AUTOMATION WORKFLOW ===")
    workflow = TaxSentryAutomationWorkflow()
    workflow.run_once()

if __name__ == "__main__":
    main()
