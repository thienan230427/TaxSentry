"""
🤖 TaxSentry Automation Workflow Co-ordinator
Điều phối toàn bộ quy trình: Quét hòm thư -> Tải file -> Parse dữ liệu -> AI Phân tích -> Tạo PDF -> Gửi Email & Telegram.
"""

import sys
import time
import inspect
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
from taxsentry.database.session_store import TaxSentrySessionStore
from taxsentry.runtime.session import JobManager, SessionManager
from taxsentry.core.workflow_service import TaxSentryWorkflowService

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


def _call_with_supported_kwargs(func, *args, **kwargs):
    """Giữ tương thích với parser cũ/test double chưa nhận trace kwargs."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)

    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return func(*args, **kwargs)

    supported_kwargs = {
        name: value
        for name, value in kwargs.items()
        if name in signature.parameters
    }
    return func(*args, **supported_kwargs)

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
        self.session_store = TaxSentrySessionStore()
        self.session_store.connect()
        self.session_manager = SessionManager(self.session_store)
        self.job_manager = JobManager()
        self.workflow_service = TaxSentryWorkflowService(
            session_manager=self.session_manager,
            job_manager=self.job_manager,
            log_callback=log_activity,
        )
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> int:
        """Thực hiện một chu kỳ quét và xử lý báo cáo. Trả về số lượng tệp đã xử lý."""
        log_activity("🔄 Bắt đầu chu kỳ quét hòm thư Kế toán trưởng...")

        session_store = getattr(self, 'session_store', None)
        if session_store is not None and getattr(session_store, 'connection', None) is None:
            session_store.connect()
        session_manager = SessionManager(session_store) if session_store is not None else getattr(self, 'session_manager', None)
        if session_manager is None:
            session_manager = SessionManager()
        self.session_manager = session_manager

        session = session_manager.start_session(
            entry_point='automation',
            mode='run_once',
            title='Automation cycle',
        )
        session_id = session.session_id
        
        # 1. Kết nối hòm thư
        connected = self.poller.connect()
        if not connected:
            log_activity("⚠️ Không thể kết nối hòm thư thực tế. Chạy ở chế độ GIẢ LẬP.")
            
        # 2. Quét và tải các file đính kèm mới
        downloaded_files = self.poller.check_and_download()
        self.poller.disconnect()

        if not downloaded_files:
            log_activity("✅ Không phát hiện báo cáo mới nào chưa đọc.")
            session_manager.finish_session(
                session_id,
                outcome='success',
                summary='No new reports found',
                event_result='empty',
            )
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
            job = self.workflow_service.create_job_for_file(
                session_id=session_id,
                file_path=file_path,
                file_context=file_context,
                trace_context=trace_context,
            )

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
                        self.workflow_service.mark_missing_data(session_id=session_id, job=job, file_path=file_path)
                        continue
                    self.workflow_service.mark_processing(job, phase="excel_parse")
                    _call_with_supported_kwargs(
                        parser.export_json,
                        json_output_path,
                        trace_context=trace_context,
                        artifact_store=self.artifact_store,
                    )
                    evidence_context = _call_with_supported_kwargs(
                        build_evidence_context,
                        parser,
                        file_context,
                        trace_context=trace_context,
                    )
                    save_evidence_context(evidence_context, EVIDENCE_CONTEXT_PATH, artifact_store=self.artifact_store)
                    db_success = _call_with_supported_kwargs(
                        parser.log_to_database,
                        trace_context=trace_context,
                        job_id=job.job_id if job else None,
                    )
                elif is_pdf:

                    pdf_parser = TaxSentryPDFParser(str(file_path))
                    if pdf_parser.parse_with_ai():
                        self.workflow_service.mark_processing(job, phase="pdf_parse")
                        _call_with_supported_kwargs(
                            pdf_parser.export_json,
                            json_output_path,
                            trace_context=trace_context,
                            artifact_store=self.artifact_store,
                        )
                        db_success = _call_with_supported_kwargs(
                            pdf_parser.log_to_database,
                            trace_context=trace_context,
                            job_id=job.job_id if job else None,
                        )
                    else:
                        raise ValueError("AI không thể đọc hiểu cấu trúc file PDF báo cáo!")
                else:
                    log_activity(f"⚠️ Định dạng file không được hỗ trợ: {file_path.suffix}")
                    continue

                if db_success:
                    log_activity("✅ Đã chuẩn hóa dữ liệu thành công và lưu vào MySQL Database.")
                else:
                    log_activity("⚠️ Dữ liệu trích xuất thành công nhưng không thể đồng bộ MySQL DB.")
                    self.workflow_service.mark_db_failure(session_id=session_id, job=job, file_path=file_path)
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
                pdf_success = _call_with_supported_kwargs(
                    self.generator.generate,
                    ai_report_markdown,
                    str(pdf_report_path),
                    trace_context=trace_context,
                    artifact_store=self.artifact_store,
                )

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
                email_success = self.workflow_service.send_email_report(self.sender, pdf_report_path, summary_text)
                if email_success:
                    log_activity("✅ Đã gửi Email báo cáo thành công.")
                else:
                    log_activity("❌ Gửi Email báo cáo thất bại.")

                # 7. Gửi tin nhắn tóm tắt và PDF qua Telegram Bot cho Giám đốc
                log_activity("📡 Đang gửi preview attachment, tóm tắt và PDF báo cáo qua Telegram Bot...")
                
                # Để tránh chặn tiến trình chính, chạy async qua loop
                try:
                    tele_success = self.workflow_service.send_telegram_report(
                        pdf_report_path=pdf_report_path,
                        summary_text=summary_text,
                        evidence_context_path=str(EVIDENCE_CONTEXT_PATH),
                    )
                    if tele_success:
                        log_activity("✅ Đã gửi thông báo Telegram thành công.")
                    else:
                        log_activity("❌ Gửi thông báo Telegram thất bại.")
                except Exception as tele_err:
                    log_activity(f"❌ Lỗi tích hợp Telegram: {tele_err}")
                    self.workflow_service.mark_notification_failure(
                        session_id=session_id,
                        job=job,
                        file_path=file_path,
                        error=tele_err,
                        channel="telegram",
                    )
                    if email_id:
                        failed_email_ids.add(email_id)
                    continue

                processed_count += 1
                if email_id:
                    successful_email_ids.add(email_id)
                self.workflow_service.mark_completed(
                    session_id=session_id,
                    job=job,
                    file_path=file_path,
                    pdf_report_path=pdf_report_path,
                    email_sent=email_success,
                    telegram_sent=tele_success,
                )

                log_activity(f"🎉 Hoàn thành xử lý tự động hoàn toàn cho file: '{file_path.name}'!")

            except Exception as ex:
                log_activity(f"❌ Lỗi nghiêm trọng khi xử lý file '{file_path.name}': {ex}")
                log_activity(f"⚠️ Email này sẽ được QUÉT LẠI ở chu kỳ tiếp theo (chưa đánh dấu processed).")
                self.workflow_service.mark_notification_failure(
                    session_id=session_id,
                    job=job,
                    file_path=file_path,
                    error=ex,
                    channel="exception",
                )
                if email_id:
                    failed_email_ids.add(email_id)

        # Chỉ đánh dấu những email thật sự hoàn thành toàn bộ chuỗi xử lý.
        email_ids_to_mark = sorted(successful_email_ids - failed_email_ids)
        if email_ids_to_mark:
            marked = self.poller.mark_email_ids_as_processed(email_ids_to_mark)
            log_activity(f"✅ Đã đánh dấu {marked} email là đã xử lý thành công.")

        outcome = 'success' if processed_count > 0 or not failed_email_ids else 'failed'
        summary = (
            f"Processed {processed_count} report(s)"
            if processed_count > 0
            else 'No reports completed successfully'
        )
        event_result = 'success' if processed_count > 0 else ('failed' if failed_email_ids else 'empty')
        session_manager.finish_session(
            session_id,
            outcome=outcome,
            summary=summary,
            event_result=event_result,
        )
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
