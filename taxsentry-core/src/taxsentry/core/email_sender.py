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
        return bool(self.user and self.password and "your_app_password" not in self.password)

    def send_report(self, pdf_path: str, summary_text: str = "") -> bool:
        """Gửi email chứa file PDF báo cáo đính kèm tới Giám đốc."""
        if not self.is_configured():
            print("⚠️ Cấu hình email không đầy đủ hoặc đang để mặc định! Không thể gửi email thực tế.")
            print("[Dry-run] Giả lập gửi email thành công.")
            return True

        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            print(f"❌ Không tìm thấy file PDF để gửi email: {pdf_path}")
            return False

        try:
            # Tạo thư điện tử đa phần (Multipart)
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = self.director_email
            msg["Subject"] = f"🛡️ [TAXSENTRY CO-PILOT] Báo cáo đánh giá hiệu quả kinh doanh & Rủi ro thuế mới nhất"

            # Nội dung email dạng văn bản
            body_content = f"""Kính gửi Giám đốc {self.director_name},

Hệ thống TaxSentry vừa quét hòm thư email của Kế toán trưởng và phát hiện báo cáo kinh doanh mới.
AI Agent đã phân tích chi tiết dữ liệu, đối chiếu quy định thuế và biên soạn báo cáo gửi Giám đốc {self.director_name}.

📋 TÓM TẮT ĐÁNH GIÁ CỦA AI:
{summary_text if summary_text else "Vui lòng xem báo cáo chi tiết được đính kèm trong file PDF."}

---
Trân trọng,
Hệ thống giám sát tài chính và kiểm toán thuế TaxSentry.
"""
            msg.attach(MIMEText(body_content, "plain", "utf-8"))

            # Đính kèm file PDF
            with open(pdf_file, "rb") as f:
                attachment = MIMEBase("application", "octet-stream")
                attachment.set_payload(f.read())
                encode_base64(attachment)
                attachment.add_header(
                    "Content-Disposition",
                    f"attachment; filename={pdf_file.name}"
                )
                msg.attach(attachment)

            # Kết nối SMTP Server và gửi mail
            # Sử dụng SSL
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()

            server.login(self.user, self.password)
            server.sendmail(self.user, self.director_email, msg.as_string())
            server.quit()
            
            print(f"📧 Gửi email báo cáo thành công tới Giám đốc: {self.director_email}")
            return True

        except Exception as e:
            print(f"❌ Lỗi khi gửi email: {e}")
            return False

def main():
    print("--- CHẠY THỬ NGHIỆM EMAIL SENDER ---")
    sender = TaxSentryEmailSender()
    if sender.is_configured():
        print("✅ Email sender has been configured properly.")
    else:
        print("⚠️ Email sender is not configured yet. Run in simulation mode.")

if __name__ == "__main__":
    main()
