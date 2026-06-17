import sys
import os
import subprocess

def bootstrap_venv():
    """Tự động phát hiện và khởi chạy lại chương trình bằng Python của môi trường ảo .venv nếu đang chạy ngoài venv."""
    in_venv = (sys.prefix != sys.base_prefix) or ('VIRTUAL_ENV' in os.environ)
    
    if not in_venv:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        venv_python = os.path.join(root_dir, ".venv", "Scripts", "python.exe")
        
        if not os.path.exists(venv_python):
            venv_python = os.path.join(root_dir, ".venv", "bin", "python")
            
        if os.path.exists(venv_python):
            args = [venv_python] + sys.argv
            try:
                sys.exit(subprocess.run(args).returncode)
            except Exception as e:
                print(f"Không thể tự động chuyển hướng sang môi trường ảo: {e}")
                sys.exit(1)

# Tự động kích hoạt môi trường ảo nếu cần thiết
bootstrap_venv()

"""
🛡️ TaxSentry — Telegram Bot Integration
Kênh giao tiếp và kiểm soát 2 chiều dành cho Giám đốc công ty.
Sử dụng văn phong chuyên nghiệp, trang trọng chuẩn mực kiểm toán.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

# Nạp cấu hình biến môi trường
os.environ['EMAIL_PASS'] = os.getenv('EMAIL_PASS', '')  # App Password
os.environ['DB_HOST'] = os.getenv('DB_HOST', 'localhost')
os.environ['DB_PORT'] = os.getenv('DB_PORT', '3306')
os.environ['DB_USER'] = os.getenv('DB_USER', 'root')
os.environ['DB_PASS'] = os.getenv('DB_PASS', '')
os.environ['DB_NAME'] = os.getenv('DB_NAME', 'tax_sentry')

# Thêm path của dự án
sys.path.insert(0, str(Path(__file__).parent.absolute()))
from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
from taxsentry.database.db_manager import TaxSentryDBManager
from taxsentry.config.paths import DOWNLOAD_DIR, KNOWLEDGE_PATH

# Telegram Bot API
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- Cấu hình Bot ---
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '')

# --- Hàm định dạng Markdown cho Telegram ---
def format_markdown(text: str) -> str:
    """Định dạng văn bản cho Telegram."""
    return text

# --- Helper: Gửi thông báo chủ động từ hệ thống quét chạy ngầm ---
async def send_active_report_to_director(pdf_path: str, summary_text: str) -> bool:
    """Gửi báo cáo chủ động kèm file PDF tới Telegram của Giám đốc."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('ADMIN_CHAT_ID')
    
    if not token or not chat_id:
        print("❌ Thiếu cấu hình TELEGRAM_BOT_TOKEN hoặc ADMIN_CHAT_ID để gửi thông báo chủ động!")
        return False
        
    try:
        from telegram import Bot
        bot = Bot(token=token)
        
        # Gửi tin nhắn tóm tắt rủi ro
        await bot.send_message(
            chat_id=chat_id,
            text=f"📊 **[THÔNG BÁO TỰ ĐỘNG] CẬP NHẬT BÁO CÁO TÀI CHÍNH MỚI**\n\n{summary_text}"
        )
        
        # Gửi kèm tệp tin PDF báo cáo chi tiết của AI
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                await bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=os.path.basename(pdf_path),
                    caption="📄 Báo cáo đánh giá hiệu quả kinh doanh & Kiểm toán rủi ro thuế chi tiết."
                )
        print("✅ Đã gửi thông báo và PDF báo cáo thành công qua Telegram!")
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

    director_name = os.getenv('DIRECTOR_NAME', 'Thiên Ân')
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
            
            # Lấy thông tin tài chính an toàn
            gross_profit = log.get('gross_profit', 0.0) or 0.0
            total_opex = log.get('total_opex', 0.0) or 0.0
            hospitality_no_invoice = log.get('hospitality_no_invoice', 0.0) or 0.0
            
            response_text += (
                f"🔹 **Tệp tin:** `{log['file_name']}`\n"
                f"  • Thời điểm nhận: {received_at_str}\n"
                f"  • Người gửi: {log['sender']}\n"
                f"  • Doanh thu: {log['revenue']:,.0f} VND\n"
                f"  • Lợi nhuận gộp: {gross_profit:,.0f} VND\n"
                f"  • Tổng OPEX: {total_opex:,.0f} VND\n"
                f"  • Lợi nhuận ròng: {log['net_income']:,.0f} VND\n"
                f"  • Tiếp khách không hóa đơn: {hospitality_no_invoice:,.0f} VND\n"
                f"  • Trạng thái rủi ro thuế: *{log['tax_risk_status']}*\n"
                f"  • Trạng thái xử lý: `{log['status']}`\n\n"
            )
        await update.message.reply_text(response_text, parse_mode="Markdown")
    except Exception as e:
        db.close()
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

    await update.message.reply_text("🧠 Hệ thống đang kết nối tới AI Engine (Local Gemma 2) để phân tích báo cáo và rủi ro thuế. Vui lòng chờ...")

    engine = TaxSentryAnalysisEngine()
    if not engine.connect():
        await update.message.reply_text("❌ Lỗi kết nối: Không thể khởi chạy AI Engine. Vui lòng kiểm tra lại trạng thái máy chủ LM Studio.")
        return
        
    try:
        report_markdown = engine.run_audit()
        engine.close() if hasattr(engine, 'close') else None
        
        if report_markdown.startswith("❌"):
            await update.message.reply_text(report_markdown)
            return
            
        # Gửi báo cáo phân đoạn nếu vượt quá giới hạn ký tự
        if len(report_markdown) > 4096:
            parts = [report_markdown[i:i+4096] for i in range(0, len(report_markdown), 4096)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(report_markdown)
            
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
                f"*{idx}. {log['file_name']}*\n"
                f"  • Nhận lúc: {received_at_str}\n"
                f"  • Doanh thu: {log['revenue']:,.0f} VND\n"
                f"  • Trạng thái rủi ro thuế: *{log['tax_risk_status']}*\n\n"
            )
        await update.message.reply_text(response_text, parse_mode="Markdown")
    except Exception as e:
        db.close()
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
            
            md_content = f"""# Báo cáo kết quả hoạt động kinh doanh

*   **Tên tệp tin:** {report_log['file_name']}
*   **Ngày nhận báo cáo:** {report_log['received_at']}
*   **Người gửi:** {report_log['sender']}

---

## 1. Số liệu tài chính cơ bản
*   **Doanh thu:** {report_log['revenue']:,.0f} VND
*   **Lợi nhuận ròng:** {report_log['net_income']:,.0f} VND
*   **Đánh giá rủi ro sơ bộ:** {report_log['tax_risk_status']}

---

## 2. Ghi chú và khuyến nghị của AI
*   Giám đốc có thể sử dụng câu lệnh `/analyze` để kích hoạt AI Engine phân tích rủi ro sâu hơn dựa trên các điều khoản thuế Việt Nam hiện hành.
*   Báo cáo chi tiết đã được tự động tạo lập và lưu trữ cục bộ tại hệ thống.
"""
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

    # 3. Tạo Prompt chi tiết gửi cho LLM Local
    director_name = os.getenv('DIRECTOR_NAME', 'Thiên Ân')
    prompt = f"""# Role: Trợ lý AI Kiểm toán của Giám đốc {director_name}
Nhiệm vụ của bạn là giải đáp câu hỏi của Giám đốc {director_name} một cách trang trọng, lịch sự, chuẩn mực và khách quan (xưng hô 'Tôi/Hệ thống' và gọi 'Giám đốc').
Bạn được cung cấp thông tin tài chính mới nhất của doanh nghiệp và trích lục pháp luật thuế để làm ngữ cảnh trả lời.

## Dữ liệu báo cáo tài chính gần đây trong cơ sở dữ liệu:
{json.dumps(financial_context, default=str, indent=2, ensure_ascii=False)}

## Trích lục quy định pháp luật Thuế Việt Nam:
{tax_rules_snippet}

## Yêu cầu/Câu hỏi của Giám đốc:
"{user_query}"

Hãy phân tích và trả lời Giám đốc một cách chuyên nghiệp, chính xác dựa trên dữ liệu ngữ cảnh được cung cấp.
Nếu Giám đốc hỏi về tiến độ, hãy báo cáo rằng hệ thống tự động hóa đang hoạt động chạy ngầm liên tục để quét hòm thư của Kế toán trưởng và sẽ tự động xử lý ngay khi phát hiện báo cáo mới.
"""

    engine = TaxSentryAnalysisEngine()
    if engine.connect():
        try:
            ai_response = engine.analyze_report(prompt)
            engine.close() if hasattr(engine, 'close') else None
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

    # Khởi tạo Application
    app = Application.builder().token(token).build()
    
    # Đăng ký lệnh điều hướng (kèm alias tiếng Việt cho phù hợp Obsidian plan)
    app.add_handler(CommandHandler(['start'], start))
    app.add_handler(CommandHandler(['reports', 'tiendo'], get_reports))
    app.add_handler(CommandHandler(['analyze'], analyze_report))
    app.add_handler(CommandHandler(['audit_history'], audit_history))
    app.add_handler(CommandHandler(['report_pdf', 'baocao'], generate_report_pdf))
    
    # Đăng ký xử lý tin nhắn chat tự do
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_chat))
    
    print(f"✅ Telegram Bot online thành công! Admin Chat ID: {ADMIN_CHAT_ID}")
    
    # Chạy bot polling
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("\n👋 Bot đang dừng an toàn...")

if __name__ == '__main__':
    main()
