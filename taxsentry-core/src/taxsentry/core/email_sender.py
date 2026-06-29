"""
📬 TaxSentry Email Sender Module
Kết nối SMTP Gmail để gửi email đính kèm báo cáo PDF cho Giám đốc công ty.
"""

import os
import smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.encoders import encode_base64
from dotenv import load_dotenv

from taxsentry.utils.runtime import _safe_console_print

# Nạp các biến môi trường
load_dotenv()

class TaxSentryEmailSender:
    """Bộ gửi email báo cáo tự động cho Giám đốc."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 465))  # Mặc định cổng SSL 465
        self.user = os.getenv("EMAIL_USER")
        self.password = os.getenv("EMAIL_PASS")
        self.director_email = os.getenv("DIRECTOR_EMAIL", "")
        self.director_name = os.getenv("DIRECTOR_NAME", "Giám đốc")

    def is_configured(self) -> bool:
        """Kiểm tra cấu hình email trong .env."""
        return bool(
            self.user
            and self.password
            and self.director_email.strip()
            and "your_app_password" not in self.password.lower()
        )

    def send_report(self, pdf_path: str, summary_text: str = "", trace_context: dict | None = None) -> bool:
        """Gửi email chứa file PDF báo cáo đính kèm tới Giám đốc."""
        if not self.is_configured():
            _safe_console_print("⚠️ Cấu hình email không đầy đủ hoặc đang để mặc định! Không thể gửi email thực tế.")
            _safe_console_print("[Dry-run] Bỏ qua gửi email vì chưa có cấu hình hợp lệ.")
            return False

        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            _safe_console_print(f"❌ Không tìm thấy file PDF để gửi email: {pdf_path}")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = self.director_email
            msg["Subject"] = f"🛡️ [TAXSENTRY CO-PILOT] Báo cáo đánh giá hiệu quả kinh doanh & Rủi ro thuế mới nhất"

            if trace_context:
                if trace_context.get('session_id'):
                    msg["X-TaxSentry-Session-ID"] = str(trace_context['session_id'])
                if trace_context.get('event_id'):
                    msg["X-TaxSentry-Event-ID"] = str(trace_context['event_id'])
                if trace_context.get('trace_id'):
                    msg["X-TaxSentry-Trace-ID"] = str(trace_context['trace_id'])

            trace_lines = []
            if trace_context:
                if trace_context.get('session_id'):
                    trace_lines.append(f"session={trace_context['session_id']}")
                if trace_context.get('event_id'):
                    trace_lines.append(f"event={trace_context['event_id']}")
                if trace_context.get('trace_id'):
                    trace_lines.append(f"trace={trace_context['trace_id']}")

            body_parts = [
                f"Kính gửi Giám đốc {self.director_name},",
                "",
                "Hệ thống TaxSentry vừa quét hòm thư email của Kế toán trưởng và phát hiện báo cáo kinh doanh mới.",
                f"AI Agent đã phân tích chi tiết dữ liệu, đối chiếu quy định thuế và biên soạn báo cáo gửi Giám đốc {self.director_name}.",
            ]
            if trace_lines:
                body_parts.extend([
                    "",
                    f"Trace: {' | '.join(trace_lines)}",
                ])
            body_parts.extend([
                "",
                "📋 TÓM TẮT ĐÁNH GIÁ CỦA AI:",
                summary_text if summary_text else "Vui lòng xem báo cáo chi tiết được đính kèm trong file PDF.",
                "",
                "---",
                "Trân trọng,",
                "Hệ thống giám sát tài chính và kiểm toán thuế TaxSentry.",
            ])
            msg.attach(MIMEText("\n".join(body_parts), "plain", "utf-8"))

            with open(pdf_file, "rb") as f:
                attachment = MIMEBase("application", "octet-stream")
                attachment.set_payload(f.read())
                encode_base64(attachment)
                attachment.add_header(
                    "Content-Disposition",
                    f"attachment; filename={pdf_file.name}"
                )
                msg.attach(attachment)

            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()

            server.login(self.user, self.password)
            server.sendmail(self.user, self.director_email, msg.as_string())
            server.quit()

            _safe_console_print(f"📧 Gửi email báo cáo thành công tới Giám đốc: {self.director_email}")
            return True

        except Exception as e:
            _safe_console_print(f"❌ Lỗi khi gửi email: {e}")
            return False

def main():
    _safe_console_print("--- CHẠY THỬ NGHIỆM EMAIL SENDER ---")
    sender = TaxSentryEmailSender()
    if sender.is_configured():
        _safe_console_print("✅ Email sender has been configured properly.")
    else:
        _safe_console_print("⚠️ Email sender is not configured yet. Run in simulation mode.")

if __name__ == "__main__":
    main()
