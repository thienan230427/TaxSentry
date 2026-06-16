import email
import imaplib
import os
from email.header import decode_header
from pathlib import Path
from dotenv import load_dotenv

# Nạp các biến môi trường từ tệp .env
load_dotenv()

# --- Cấu hình Thư mục ---
DOWNLOAD_DIR = Path("D:/TaxSentry/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


class TaxSentryEmailPoller:
    """Bộ quét và tải báo cáo tài chính tự động từ Email (IMAP)."""

    def __init__(self):
        self.host = os.getenv("EMAIL_HOST", "imap.gmail.com")
        self.port = int(os.getenv("EMAIL_PORT", 993))
        self.user = os.getenv("EMAIL_USER")
        self.password = os.getenv("EMAIL_PASS")
        self.accountant_email = os.getenv("ACCOUNTANT_EMAIL", "bao25800600042@hutech.edu.vn")
        self.mail = None

    def is_configured(self) -> bool:
        """Kiểm tra xem Sếp đã cấu hình .env đầy đủ chưa."""
        return bool(self.user and self.password and "your_app_password" not in self.password)

    def connect(self) -> bool:
        """Kết nối bảo mật tới máy chủ IMAP."""
        if not self.is_configured():
            print("⚠️ Cảnh báo: Chưa cấu hình thông tin Email trong tệp .env!")
            print("👉 Hệ thống sẽ chạy ở chế độ GIẢ LẬP (Dry-run mode) để test thử desu~!\n")
            return False
        try:
            # Kết nối SSL bảo mật
            self.mail = imaplib.IMAP4_SSL(self.host, self.port)
            self.mail.login(self.user, self.password)
            return True
        except Exception as e:
            print(f"❌ Kết nối IMAP thất bại rồi Sếp ơi: {e}")
            print("👉 Chuyển sang chế độ GIẢ LẬP để chạy thử nghiệm desu~!\n")
            return False

    def check_and_download(self) -> list:
        """Quét hòm thư và tải về các báo cáo tài chính hợp lệ."""
        downloaded_files = []

        # Nếu không có cấu hình thực tế, chạy giả lập để không bị đơ ứng dụng
        if not self.mail:
            print("[Dry-run] Đang quét hòm thư giả lập...")
            print(f"[Dry-run] Kiểm tra thư mới từ Kế toán trưởng: {self.accountant_email}")
            print("[Dry-run] Quét hoàn tất. Không có thư mới (Chế độ giả lập).")
            return downloaded_files

        try:
            # Chọn hộp thư đến (Inbox)
            self.mail.select("inbox")

            # Tìm kiếm các email CHƯA ĐỌC (UNSEEN) gửi từ địa chỉ của Kế toán trưởng
            search_query = f'(UNSEEN FROM "{self.accountant_email}")'
            status, messages = self.mail.search(None, search_query)

            if status != "OK":
                print("❌ Lỗi khi tìm kiếm email.")
                return downloaded_files

            email_ids = messages[0].split()
            print(f"🔎 Tìm thấy {len(email_ids)} email mới chưa đọc từ Kế toán trưởng desu~!")

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
                
                print(f"📬 Đang xử lý email tiêu đề: '{subject}'")

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
                        
                        print(f"💾 Tải thành công file đính kèm: '{file_name}' -> Lưu tại: {file_path}")
                        downloaded_files.append(str(file_path))

                        # Đánh dấu email là ĐÃ ĐỌC (SEEN) sau khi tải xong
                        self.mail.store(e_id, "+FLAGS", "\\Seen")

        except Exception as e:
            print(f"❌ Có lỗi phát sinh khi quét email: {e}")

        return downloaded_files

    def disconnect(self):
        """Đóng kết nối an toàn."""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except:
                pass


def main():
    print("=== CHẠY THỬ NGHIỆM EMAIL POLLER ===")
    poller = TaxSentryEmailPoller()
    if poller.connect():
        files = poller.check_and_download()
        print(f"\n🎉 Hoàn thành quét thực tế. Đã tải về {len(files)} tệp tin.")
        poller.disconnect()
    else:
        # Chạy chế độ giả lập nếu chưa có cấu hình thực tế
        files = poller.check_and_download()
        print(f"\n🎉 Hoàn thành quét giả lập.")


if __name__ == "__main__":
    main()
