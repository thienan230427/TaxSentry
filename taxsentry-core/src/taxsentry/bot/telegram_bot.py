import sys
import os
import types
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from taxsentry.utils.runtime import bootstrap_into_venv

if __name__ == "__main__":
    # Tự động kích hoạt môi trường ảo chỉ khi module được chạy như một entrypoint.
    bootstrap_into_venv(["-m", "taxsentry.bot.telegram_bot", *sys.argv[1:]])

"""
🛡️ TaxSentry — Telegram Bot Integration
Kênh giao tiếp và kiểm soát 2 chiều dành cho Giám đốc công ty.
Sử dụng văn phong chuyên nghiệp, trang trọng chuẩn mực kiểm toán.
"""

import asyncio
import json
from datetime import datetime
from threading import Thread

# Load .env from taxsentry-core root
from dotenv import load_dotenv
dotenv_path = Path(__file__).resolve().parent.parent.parent.parent / '.env'
load_dotenv(dotenv_path)

# Nạp cấu hình biến môi trường
os.environ['EMAIL_PASS'] = os.getenv('EMAIL_PASS', '')  # App Password
os.environ['DB_HOST'] = os.getenv('DB_HOST', 'localhost')
os.environ['DB_PORT'] = os.getenv('DB_PORT', '3306')
os.environ['DB_USER'] = os.getenv('DB_USER', 'root')
os.environ['DB_PASS'] = os.getenv('DB_PASS', '')
os.environ['DB_NAME'] = os.getenv('DB_NAME', 'tax_sentry')

# Thêm path của dự án
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))
sys.path.insert(0, str(Path(__file__).parent.absolute()))

try:
    from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
except ModuleNotFoundError:
    TaxSentryAnalysisEngine = None

try:
    from taxsentry.database.db_manager import TaxSentryDBManager
except ModuleNotFoundError:
    TaxSentryDBManager = None

from taxsentry.runtime import MemoryManager
from taxsentry.runtime.copilot_prompt import build_copilot_prompt
from taxsentry.config.paths import DOWNLOAD_DIR, KNOWLEDGE_PATH, JSON_PATH, EVIDENCE_CONTEXT_PATH
from taxsentry.core.evidence_preview import build_evidence_preview_text, load_evidence_context

# Backward-compatible alias for older tests/consumers while the code uses the runtime facade.
TaxSentryMemoryStore = MemoryManager

# Telegram Bot API
try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    if not hasattr(ContextTypes, 'DEFAULT_TYPE'):
        raise AttributeError('telegram.ext.ContextTypes.DEFAULT_TYPE is missing')
    TELEGRAM_AVAILABLE = True
except (ModuleNotFoundError, AttributeError):
    TELEGRAM_AVAILABLE = False
    Update = object
    Application = CommandHandler = MessageHandler = object
    ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    filters = types.SimpleNamespace(TEXT=object(), COMMAND=object())

# --- Cấu hình Bot ---
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')

# --- Hàm định dạng Markdown cho Telegram ---
def format_markdown(text: str) -> str:
    """Định dạng văn bản cho Telegram."""
    return text


def _safe_number(value, default: float | None = 0.0):
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _format_currency(value, fallback: str = 'n/a') -> str:
    number = _safe_number(value, default=None)
    if number is None:
        return fallback
    return f"{number:,.0f} VND"


def _clean_text(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _build_pdf_markdown(report_log: dict) -> str:
    return f"""# Báo cáo kết quả hoạt động kinh doanh

*   **Tên tệp tin:** {_clean_text(report_log.get('file_name')) or 'unknown'}
*   **Ngày nhận báo cáo:** {_clean_text(report_log.get('received_at')) or 'n/a'}
*   **Người gửi:** {_clean_text(report_log.get('sender')) or 'n/a'}

---

## 1. Số liệu tài chính cơ bản
*   **Doanh thu:** {_format_currency(report_log.get('revenue'))}
*   **Lợi nhuận ròng:** {_format_currency(report_log.get('net_income'))}
*   **Đánh giá rủi ro sơ bộ:** {_clean_text(report_log.get('tax_risk_status')) or 'n/a'}

---

## 2. Ghi chú và khuyến nghị của AI
*   Giám đốc có thể sử dụng câu lệnh `/analyze` để kích hoạt AI Engine phân tích rủi ro sâu hơn dựa trên các điều khoản thuế Việt Nam hiện hành.
*   Báo cáo chi tiết đã được tự động tạo lập và lưu trữ cục bộ tại hệ thống.
"""


def _start_automation_loop(interval_seconds: int = 60) -> Thread:
    def worker():
        try:
            from taxsentry.core.automation import TaxSentryAutomationWorkflow
            workflow = TaxSentryAutomationWorkflow()
            workflow.start_loop(interval_seconds)
        except Exception as exc:
            print(f"❌ Automation loop background bị lỗi: {exc}")

    thread = Thread(target=worker, daemon=True, name='taxsentry-automation-loop')
    thread.start()
    return thread


def _split_telegram_text(text: str, limit: int = 4096) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    return [cleaned[i:i+limit] for i in range(0, len(cleaned), limit)]


def _load_financial_json() -> dict:
    if not JSON_PATH.exists():
        return {}
    try:
        return json.loads(JSON_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


async def _send_evidence_preview(bot, chat_id: str, evidence_context: dict) -> None:
    preview_text = build_evidence_preview_text(evidence_context, os.getenv('DIRECTOR_NAME', '') or 'Sếp')
    if preview_text:
        await bot.send_message(chat_id=chat_id, text=preview_text)

    for image in evidence_context.get('image_attachments', [])[:5]:
        image_path = image.get('path')
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as img_file:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=img_file,
                    caption=f"Preview attachment: {image.get('file_name', 'image')}"
                )


def _build_free_chat_prompt(user_query: str, director_name: str, financial_context, tax_rules_snippet: str, evidence_context: dict) -> str:
    financial_json = _load_financial_json()
    memory_manager = TaxSentryMemoryStore()
    recall_compact = getattr(memory_manager, 'recall_compact', None)
    if callable(recall_compact):
        memory_context = recall_compact(user_query, limit=5)
    else:
        memory_context = memory_manager.recall(user_query, limit=5)
    close = getattr(memory_manager, 'close', None)
    if callable(close):
        close()
    return build_copilot_prompt(
        user_query=user_query,
        director_name=director_name,
        financial_context=financial_context,
        tax_rules_snippet=tax_rules_snippet,
        evidence_context=evidence_context,
        financial_json=financial_json,
        memory_context=memory_context,
    )

# --- Helper: Gửi thông báo chủ động từ hệ thống quét chạy ngầm ---
async def send_active_report_to_director(pdf_path: str, summary_text: str, evidence_context_path: str | None = None, trace_context: dict | None = None) -> bool:

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('ADMIN_CHAT_ID')
    
    if not token or not chat_id:
        print("❌ Thiếu cấu hình TELEGRAM_BOT_TOKEN hoặc ADMIN_CHAT_ID để gửi thông báo chủ động!")
        return False

    if not pdf_path or not os.path.exists(pdf_path):
        print("❌ Không tìm thấy file PDF báo cáo để gửi qua Telegram!")
        return False
        
    try:
        from telegram import Bot
    except ModuleNotFoundError:
        print("❌ Thiếu dependency python-telegram-bot để gửi Telegram. Hãy cài đặt package này trước khi chạy.")
        return False

    try:
        bot = Bot(token=token)
        evidence_context = load_evidence_context(Path(evidence_context_path) if evidence_context_path else EVIDENCE_CONTEXT_PATH)

        if evidence_context:
            await _send_evidence_preview(bot, chat_id, evidence_context)

        # Gửi tin nhắn tóm tắt rủi ro sau khi đã show chứng cứ đầu vào
        response_text = (
            "📊 Em bắt đầu phần nhận xét nhanh đây Sếp:\n\n"
            f"{_clean_text(summary_text) or 'Hiện em đã parse xong dữ liệu, nhưng phần tóm tắt ngắn đang trống nên em gửi Sếp PDF chi tiết ngay bên dưới.'}"
        )
        if trace_context:
            trace_bits = []
            if trace_context.get('session_id'):
                trace_bits.append(f"session={trace_context['session_id']}")
            if trace_context.get('event_id'):
                trace_bits.append(f"event={trace_context['event_id']}")
            if trace_context.get('trace_id'):
                trace_bits.append(f"trace={trace_context['trace_id']}")
            if trace_bits:
                response_text += f"\n\nTrace: {' | '.join(trace_bits)}"
        await bot.send_message(
            chat_id=chat_id,
            text=response_text,
        )

        # Gửi kèm tệp tin PDF báo cáo chi tiết của AI
        caption = "📄 Báo cáo đánh giá hiệu quả kinh doanh & kiểm toán rủi ro thuế chi tiết."
        if trace_context:
            trace_bits = []
            if trace_context.get('session_id'):
                trace_bits.append(f"session={trace_context['session_id']}")
            if trace_context.get('event_id'):
                trace_bits.append(f"event={trace_context['event_id']}")
            if trace_context.get('trace_id'):
                trace_bits.append(f"trace={trace_context['trace_id']}")
            if trace_bits:
                caption += f"\nTrace: {' | '.join(trace_bits)}"
        with open(pdf_path, 'rb') as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=os.path.basename(pdf_path),
                caption=caption
            )

        return True
    except Exception as e:
        print(f"❌ Lỗi khi gửi thông báo qua Telegram: {e}")
        return False

# --- Handler: /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Chào mừng Giám đốc đến với hệ thống TaxSentry."""
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text(
            f"⚠️ *Thông báo hệ thống: Quyền truy cập bị từ chối.*\n\n"
            f"Chỉ có Giám đốc công ty mới được phép truy cập dữ liệu của TaxSentry.\n"
            f"Chat ID hiện tại của bạn là: `{user_id}`.\n"
            f"Vui lòng cập nhật biến môi trường `ADMIN_CHAT_ID={user_id}` trong cấu hình hệ thống!"
        )
        return

    director_name = os.getenv('DIRECTOR_NAME', '') or 'Sếp'
    await update.message.reply_text(
        f"🛡️ **Chào mừng Giám đốc {director_name} đến với Hệ thống Giám sát Tài chính & Thuế TaxSentry!**\n\n"
        f"Tôi là Trợ lý AI Kiểm toán của Giám đốc {director_name}. Hệ thống đã kích hoạt thành công.\n\n"
        f"📋 **Các lệnh chức năng khả dụng:**\n"
        f"1️⃣ `/reports` hoặc `/tiendo` — Truy vấn dữ liệu các báo cáo tài chính gần nhất\n"
        f"2️⃣ `/analyze` — Gọi AI phân tích đánh giá rủi ro thuế dựa trên báo cáo mới nhất\n"
        f"3️⃣ `/audit_history` — Xem lịch sử đánh giá kiểm toán và trạng thái rủi ro thuế\n"
        f"4️⃣ `/report_pdf` hoặc `/baocao` — Tạo và tải file PDF báo cáo phân tích mới nhất\n\n"
        f"💬 **Tương tác trực tiếp:** Giám đốc có thể gửi câu hỏi trực tiếp bằng tin nhắn văn bản thông thường để hỏi về tiến độ xử lý thư, truy vấn doanh thu, chi phí, hoặc giải thích các luật thuế Việt Nam. Hệ thống sẽ phân tích và phản hồi ngay lập tức."
    )

# --- Handler: /reports ---
async def get_reports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lấy danh sách các báo cáo tài chính gần nhất từ MySQL Database."""
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ Yêu cầu bị từ chối: Quyền truy cập không hợp lệ.")
        return

    db = TaxSentryDBManager()
    if not db.connect():
        await update.message.reply_text("❌ Lỗi hệ thống: Không thể kết nối cơ sở dữ liệu MySQL.")
        return
        
    try:
        logs = db.get_recent_logs(limit=5)
        db.close()
        
        if not logs:
            await update.message.reply_text("📊 Hệ thống chưa ghi nhận báo cáo tài chính nào trong Database.")
            return
            
        response_text = "📁 **DANH SÁCH BÁO CÁO TÀI CHÍNH ĐÃ GHI NHẬN:**\n\n"
        for log in logs:
            received_at_str = log['received_at'].strftime('%d/%m/%Y %H:%M') if isinstance(log['received_at'], datetime) else str(log['received_at'])

            response_text += (
                f"🔹 **Tệp tin:** `{_clean_text(log.get('file_name')) or 'unknown'}`\n"
                f"  • Thời điểm nhận: {received_at_str}\n"
                f"  • Người gửi: {_clean_text(log.get('sender')) or 'n/a'}\n"
                f"  • Doanh thu: {_format_currency(log.get('revenue'))}\n"
                f"  • Lợi nhuận gộp: {_format_currency(log.get('gross_profit'))}\n"
                f"  • Tổng OPEX: {_format_currency(log.get('total_opex'))}\n"
                f"  • Lợi nhuận ròng: {_format_currency(log.get('net_income'))}\n"
                f"  • Tiếp khách không hóa đơn: {_format_currency(log.get('hospitality_no_invoice'))}\n"
                f"  • Trạng thái rủi ro thuế: *{_clean_text(log.get('tax_risk_status')) or 'n/a'}*\n"
                f"  • Trạng thái xử lý: `{_clean_text(log.get('status')) or 'n/a'}`\n\n"
            )
        await update.message.reply_text(response_text, parse_mode="Markdown")

    except Exception as e:

        await update.message.reply_text(f"❌ Lỗi hệ thống khi tải báo cáo tài chính: {e}")

# --- Handler: /analyze ---
async def analyze_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gọi TaxSentryAnalysisEngine để phân tích rủi ro thuế cho báo cáo gần nhất."""
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ Yêu cầu bị từ chối: Quyền truy cập không hợp lệ.")
        return

    model_name = os.getenv('LM_MODEL_NAME', 'AI') or 'AI'
    await update.message.reply_text(f"🧠 Hệ thống đang kết nối tới AI Engine ({model_name}) để phân tích báo cáo và rủi ro thuế. Vui lòng chờ...")

    engine = TaxSentryAnalysisEngine()
    if not engine.connect():
        await update.message.reply_text("❌ Lỗi kết nối: Không thể khởi chạy AI Engine. Vui lòng kiểm tra lại trạng thái máy chủ LM Studio.")
        return
        
    try:
        report_markdown = _clean_text(engine.run_audit())
        engine.close() if hasattr(engine, 'close') else None

        if not report_markdown:
            await update.message.reply_text("❌ AI Engine đã phản hồi nhưng nội dung báo cáo đang rỗng. Em chưa dám gửi kết quả sai cho Sếp.")
            return

        if report_markdown.startswith("❌"):
            await update.message.reply_text(report_markdown)
            return

        for part in _split_telegram_text(report_markdown):
            await update.message.reply_text(part)

    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi hệ thống trong quá trình AI phân tích báo cáo: {e}")

# --- Handler: /audit_history ---
async def audit_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem lịch sử các lần AI đã phân tích và kết quả."""
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ Yêu cầu bị từ chối: Quyền truy cập không hợp lệ.")
        return

    db = TaxSentryDBManager()
    if not db.connect():
        await update.message.reply_text("❌ Lỗi hệ thống: Không thể kết nối cơ sở dữ liệu MySQL.")
        return
        
    try:
        logs = db.get_recent_logs(limit=10)
        db.close()
        
        if not logs:
            await update.message.reply_text("📊 Chưa ghi nhận lịch sử kiểm toán tài chính nào trong Database.")
            return
            
        response_text = "📊 **LỊCH SỬ KIỂM TOÁN VÀ ĐÁNH GIÁ THUẾ:**\n\n"
        for idx, log in enumerate(logs, 1):
            received_at_str = log['received_at'].strftime('%d/%m/%Y %H:%M') if isinstance(log['received_at'], datetime) else str(log['received_at'])
            response_text += (
                f"*{idx}. {_clean_text(log.get('file_name')) or 'unknown'}*\n"
                f"  • Nhận lúc: {received_at_str}\n"
                f"  • Doanh thu: {_format_currency(log.get('revenue'))}\n"
                f"  • Trạng thái rủi ro thuế: *{_clean_text(log.get('tax_risk_status')) or 'n/a'}*\n\n"
            )
        await update.message.reply_text(response_text, parse_mode="Markdown")

    except Exception as e:

        await update.message.reply_text(f"❌ Lỗi hệ thống khi tải lịch sử kiểm toán: {e}")

# --- Handler: /report_pdf ---
async def generate_report_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xuất báo cáo tài chính sang PDF."""
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ Yêu cầu bị từ chối: Quyền truy cập không hợp lệ.")
        return

    await update.message.reply_text("⏳ Hệ thống đang xuất báo cáo phân tích ra file PDF. Vui lòng chờ...")

    db = TaxSentryDBManager()
    if not db.connect():
        await update.message.reply_text("❌ Lỗi hệ thống: Kết nối MySQL thất bại.")
        return
        
    try:
        logs = db.get_recent_logs(limit=1)
        db.close()
        
        if not logs:
            await update.message.reply_text("❌ Không tìm thấy dữ liệu báo cáo trong DB để sinh PDF.")
            return
            
        report_log = logs[0]
        
        try:
            from taxsentry.core.pdf_generator import TaxSentryPDFGenerator
            pdf_path = str(DOWNLOAD_DIR / "report_tele_temp.pdf")
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

            md_content = _build_pdf_markdown(report_log)
            generator = TaxSentryPDFGenerator()
            generator.generate(md_content, pdf_path)

            with open(pdf_path, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=f"BaoCao_TaxSentry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    caption="📄 Báo cáo tài chính đã được thiết lập dưới dạng PDF thành công."
                )
        except Exception as pdf_err:
            await update.message.reply_text(f"❌ Lỗi khi xuất tệp PDF: {pdf_err}.")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi hệ thống: {e}")

# --- Handler: Chat tự do 2 chiều với Giám đốc ---
async def handle_free_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý hội thoại tự do của Giám đốc bằng AI và RAG dữ liệu từ Database."""
    if not update.message or not update.message.from_user or not update.message.text:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ Yêu cầu bị từ chối: Quyền truy cập không hợp lệ.")
        return

    user_query = update.message.text
    await update.message.reply_chat_action(action="typing")
    
    # 1. Truy xuất dữ liệu báo cáo tài chính gần nhất làm ngữ cảnh
    db = TaxSentryDBManager()
    financial_context = {}
    if db.connect():
        logs = db.get_recent_logs(limit=3)
        db.close()
        if logs:
            financial_context = logs
            
    # 2. Đọc một phần luật thuế Việt Nam bổ sung tri thức
    tax_rules_snippet = ""
    tax_rules_path = KNOWLEDGE_PATH
    if tax_rules_path.exists():
        tax_rules_snippet = tax_rules_path.read_text(encoding='utf-8')[:2000]

    evidence_context = load_evidence_context(EVIDENCE_CONTEXT_PATH)
    if evidence_context:
        await _send_evidence_preview(context.bot, update.effective_chat.id, evidence_context)

    # 3. Tạo Prompt chi tiết gửi cho LLM Local
    director_name = os.getenv('DIRECTOR_NAME', '') or 'Sếp'
    prompt = _build_free_chat_prompt(
        user_query=user_query,
        director_name=director_name,
        financial_context=financial_context,
        tax_rules_snippet=tax_rules_snippet,
        evidence_context=evidence_context,
    )

    engine = TaxSentryAnalysisEngine()
    if engine.connect():
        try:
            ai_response = _clean_text(engine.analyze_report(prompt))
            engine.close() if hasattr(engine, 'close') else None
            if not ai_response:
                await update.message.reply_text("❌ AI Engine đã phản hồi nhưng nội dung đang rỗng. Em chưa dám trả lời bừa cho Sếp.")
                return
            await update.message.reply_text(ai_response)
        except Exception as e:
            await update.message.reply_text(f"❌ Lỗi hệ thống: Gặp sự cố khi gọi AI Engine để xử lý câu hỏi: {e}")
    else:
        await update.message.reply_text("❌ Lỗi kết nối: AI Engine không phản hồi. Vui lòng kiểm tra trạng thái máy chủ LM Studio.")

# --- Main ---
def main():
    """Khởi tạo và chạy Telegram Bot."""
    import argparse
    parser = argparse.ArgumentParser(description='TaxSentry Telegram Bot')
    parser.add_argument('--admin-chat-id', type=str, default=os.getenv('ADMIN_CHAT_ID'), 
                        help='Chat ID của Giám đốc')
    parser.add_argument('--with-automation-loop', action='store_true',
                        help='Chạy kèm automation loop quét email nền trong cùng process bot')
    args = parser.parse_args()

    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = args.admin_chat_id if args.admin_chat_id else os.getenv('ADMIN_CHAT_ID', '')
    
    print("🛡️ TaxSentry Telegram Bot đang khởi chạy...")
    
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token or token == 'YOUR_BOT_TOKEN_HERE':
        print("❌ Lỗi khởi động: Chưa cấu hình TELEGRAM_BOT_TOKEN trong file .env!")
        return
        
    if not ADMIN_CHAT_ID:
        print("❌ Lỗi khởi động: Chưa cấu hình ADMIN_CHAT_ID trong file .env!")
        return

    if not TELEGRAM_AVAILABLE:
        print("❌ Lỗi khởi động: Thiếu dependency python-telegram-bot. Hãy cài đặt gói này trước khi chạy Telegram Bot.")
        return

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(['start'], start))
    app.add_handler(CommandHandler(['reports', 'tiendo'], get_reports))
    app.add_handler(CommandHandler(['analyze'], analyze_report))
    app.add_handler(CommandHandler(['audit_history'], audit_history))
    app.add_handler(CommandHandler(['report_pdf', 'baocao'], generate_report_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_chat))
    
    print(f"✅ Telegram Bot online thành công! Admin Chat ID: {ADMIN_CHAT_ID}")
    if args.with_automation_loop:
        _start_automation_loop(interval_seconds=60)
        print("🔁 Automation loop quét email nền đã được bật cùng Telegram Bot.")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n👋 Bot đang dừng an toàn...")

if __name__ == '__main__':
    main()
