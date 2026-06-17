import email
import imaplib
import os
import sys
from email.header import decode_header
from pathlib import Path
from dotenv import load_dotenv

# Nạp các biến môi trường từ tệp .env
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))
from taxsentry.config.paths import DOWNLOAD_DIR


class TaxSentryEmailPoller:
    """Bộ quét và tải báo cáo tài chính tự động từ Email (IMAP)."""

    def __init__(self):
        self.host = os.getenv("EMAIL_HOST", "imap.gmail.com")
        self.port = int(os.getenv("EMAIL_PORT", 993))
        self.user = os.getenv("EMAIL_USER")
        self.password = os.getenv("EMAIL_PASS")
        self.accountant_email = os.getenv("ACCOUNTANT_EMAIL", "thienan12342007@gmail.com")
        self.mail = None
        self.log_callback = None

    def log(self, message):
        """Helper để ghi log: chuyển hướng sang callback nếu có, nếu không in ra console."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def is_configured(self) -> bool:
        """Kiểm tra xem Sếp đã cấu hình .env đầy đủ chưa."""
        return bool(self.user and self.password and "your_app_password" not in self.password)

    def connect(self) -> bool:
        """Kết nối bảo mật tới máy chủ IMAP."""
        if not self.is_configured():
            self.log("⚠️ Cảnh báo: Chưa cấu hình thông tin Email trong tệp .env!")
            self.log("👉 Hệ thống sẽ chạy ở chế độ GIẢ LẬP (Dry-run mode) để test thử desu~!\n")
            return False
        try:
            # Kết nối SSL bảo mật
            self.mail = imaplib.IMAP4_SSL(self.host, self.port)
            self.mail.login(self.user, self.password)
            return True
        except Exception as e:
            self.log(f"❌ Kết nối IMAP thất bại rồi Sếp ơi: {e}")
            self.log("👉 Chuyển sang chế độ GIẢ LẬP để chạy thử nghiệm desu~!\n")
            return False

    def check_and_download(self) -> list:
        """Quét hòm thư và tải về các báo cáo tài chính hợp lệ."""
        downloaded_files = []

        # Nếu không có cấu hình thực tế, chạy giả lập để không bị đơ ứng dụng
        if not self.mail:
            self.log("[Dry-run] Đang quét hòm thư giả lập...")
            self.log(f"[Dry-run] Kiểm tra thư mới từ Kế toán trưởng: {self.accountant_email}")
            self.log("[Dry-run] Quét hoàn tất. Không có thư mới (Chế độ giả lập).")
            return downloaded_files

        try:
            # Chọn hộp thư đến (Inbox)
            self.mail.select("inbox")

            # Tìm kiếm các email CHƯA ĐỌC (UNSEEN) gửi từ địa chỉ của Kế toán trưởng
            search_query = f'(UNSEEN FROM "{self.accountant_email}")'
            status, messages = self.mail.search(None, search_query)

            if status != "OK":
                self.log("❌ Lỗi khi tìm kiếm email.")
                return downloaded_files

            email_ids = messages[0].split()
            self.log(f"🔎 Tìm thấy {len(email_ids)} email mới chưa đọc từ Kế toán trưởng desu~!")

            for e_id in email_ids:
                # Lấy nội dung email
                status, msg_data = self.mail.fetch(e_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Giải mã tiêu đề email
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8")
                
                self.log(f"📬 Đang xử lý email tiêu đề: '{subject}'")

                # Quét các phần đính kèm (attachments)
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue

                    file_name, encoding = decode_header(part.get_filename())[0]
                    if isinstance(file_name, bytes):
                        file_name = file_name.decode(encoding or "utf-8")

                    # Chỉ chấp nhận file Excel (.xlsx) hoặc PDF (.pdf)
                    if file_name.endswith((".xlsx", ".pdf")):
                        file_path = DOWNLOAD_DIR / file_name
                        with open(file_path, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        
                        self.log(f"💾 Tải thành công file đính kèm: '{file_name}' -> Lưu tại: {file_path}")
                        downloaded_files.append(str(file_path))

                        # Đánh dấu email là ĐÃ ĐỌC (SEEN) sau khi tải xong
                        self.mail.store(e_id, "+FLAGS", "\\Seen")

        except Exception as e:
            self.log(f"❌ Có lỗi phát sinh khi quét email: {e}")

        return downloaded_files

    def disconnect(self):
        """Đóng kết nối an toàn."""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except Exception:
                pass


def main():
    print("=== CHẠY THỬ NGHIỆM EMAIL POLLER ===")
    poller = TaxSentryEmailPoller()
    
    if poller.connect():
        files = poller.check_and_download()
        poller.disconnect()
        print(f"\n🎉 Hoàn thành quét thực tế. Đã tải về {len(files)} tệp tin.")
    else:
        # Chạy giả lập để test
        files = poller.check_and_download()
        print(f"\n🎉 Hoàn thành quét giả lập.")


if __name__ == "__main__":
    main()
