import email
import imaplib
import os
import sys
import subprocess
import json
from email.header import decode_header
from pathlib import Path
from dotenv import load_dotenv

# Nạp các biến môi trường từ tệp .env
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))
from taxsentry.config.paths import DOWNLOAD_DIR


class TaxSentryEmailPoller:
    """Bộ quét và tải báo cáo tài chính tự động từ Email (IMAP).
    Quét cả email đã đọc/chưa đọc, dùng processed_ids để tránh trùng lặp.
    """

    def __init__(self):
        self.host = os.getenv("EMAIL_HOST", "imap.gmail.com")
        self.port = int(os.getenv("EMAIL_PORT", 993))
        self.user = os.getenv("EMAIL_USER")
        self.password = self._resolve_password()
        self.accountant_email = os.getenv("ACCOUNTANT_EMAIL", "")
        self.mail = None
        self.log_callback = None
        # Track processed email IDs để tránh xử lý trùng
        self.processed_file = Path(__file__).resolve().parent.parent.parent.parent / ".processed_ids.json"
        self.processed_ids = self._load_processed_ids()
        # Track email IDs đã download nhưng chưa xử lý xong (chờ automation xác nhận)
        self._pending_email_ids = {}
        self._file_contexts = {}
        self.document_suffixes = {".xlsx", ".pdf"}
        self.image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def _resolve_password(self) -> str:
        """Lấy password: ưu tiên từ .env, fallback sang Bitwarden.
        Không lưu password trong .env — chỉ lưu trong Bitwarden + config.json.
        """
        pwd = os.getenv("EMAIL_PASS", "")
        if pwd and pwd != "YOUR_APP_PASSWORD_HERE" and not pwd.startswith("[LƯU"):
            return pwd

        # Fallback: thử lấy từ Bitwarden (item tên "TaxSentry Gmail App Password")
        try:
            result = subprocess.run(
                ["bw", "list", "items", "--search", "TaxSentry Gmail App Password"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                items = json.loads(result.stdout)
                for item in items:
                    if item.get("login", {}).get("username") == os.getenv("EMAIL_USER"):
                        return item["login"]["password"]
        except Exception:
            pass

        # Thử tìm trong config.json
        try:
            config_path = Path.home() / ".taxsentry" / "config" / "config.json"
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                pwd_from_cfg = cfg.get("values", {}).get("email", {}).get("appPassword", "")
                if pwd_from_cfg:
                    return pwd_from_cfg
        except Exception:
            pass

        return pwd

    def _load_processed_ids(self) -> set:
        """Load danh sách ID email đã xử lý từ file JSON."""
        try:
            if self.processed_file.exists():
                import json
                data = json.loads(self.processed_file.read_text(encoding="utf-8"))
                return set(data.get("ids", []))
        except Exception:
            pass
        return set()

    def _save_processed_ids(self):
        """Lưu danh sách ID email đã xử lý."""
        try:
            import json
            self.processed_file.write_text(
                json.dumps({"ids": list(self.processed_ids)[-500:]}, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def log(self, message):
        """Helper để ghi log: chuyển hướng sang callback nếu có, nếu không in ra console."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def is_configured(self) -> bool:
        """Kiểm tra xem Sếp đã cấu hình .env đầy đủ chưa."""
        return bool(self.user and self.password and "your_app_password" not in self.password.lower() and "bitwarden" not in self.password.lower())

    def connect(self) -> bool:
        """Kết nối bảo mật tới máy chủ IMAP."""
        if not self.is_configured():
            self.log("⚠️ Cảnh báo: Chưa cấu hình thông tin Email trong tệp .env!")
            self.log("👉 Hệ thống sẽ chạy ở chế độ GIẢ LẬP (Dry-run mode) để kiểm thử.\n")
            return False
        try:
            # Kết nối SSL bảo mật
            self.mail = imaplib.IMAP4_SSL(self.host, self.port)
            self.mail.login(self.user, self.password)
            return True
        except Exception as e:
            self.log(f"❌ Kết nối IMAP thất bại rồi Sếp ơi: {e}")
            self.log("👉 Chuyển sang chế độ GIẢ LẬP để chạy thử nghiệm.\n")
            return False

    def check_and_download(self) -> list:
        """Quét hòm thư và tải về các báo cáo tài chính hợp lệ."""
        downloaded_files = []
        self._file_contexts = {}

        # Nếu không có cấu hình thực tế, chạy giả lập để không bị đơ ứng dụng
        if not self.mail:
            self.log("[Dry-run] Đang quét hòm thư giả lập...")
            self.log(f"[Dry-run] Kiểm tra thư mới từ Kế toán trưởng: {self.accountant_email}")
            self.log("[Dry-run] Quét hoàn tất. Không có thư mới (Chế độ giả lập).")
            return downloaded_files

        try:
            # Chọn hộp thư đến (Inbox)
            self.mail.select("inbox")

            # Tìm kiếm tất cả email từ Kế toán trưởng (cả đã đọc và chưa đọc)
            # Dùng processed_ids để tránh xử lý trùng
            search_query = f'(FROM "{self.accountant_email}")'
            status, messages = self.mail.search(None, search_query)

            if status != "OK":
                self.log("❌ Lỗi khi tìm kiếm email.")
                return downloaded_files

            email_ids = messages[0].split()
            # Lọc bỏ các email đã xử lý trước đó
            new_ids = [e_id for e_id in email_ids if e_id.decode() not in self.processed_ids]
            self.log(f"🔎 Tìm thấy {len(email_ids)} email từ Kế toán trưởng ({len(new_ids)} email mới chưa xử lý).")

            for e_id in new_ids:
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
                attachment_manifest = []
                primary_documents = []
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue

                    file_name, encoding = decode_header(part.get_filename())[0]
                    if isinstance(file_name, bytes):
                        file_name = file_name.decode(encoding or "utf-8")
                    if not file_name:
                        continue

                    suffix = Path(file_name).suffix.lower()
                    if suffix not in self.document_suffixes and suffix not in self.image_suffixes:
                        continue

                    file_path = DOWNLOAD_DIR / file_name
                    with open(file_path, "wb") as f:
                        f.write(part.get_payload(decode=True))

                    kind = "image" if suffix in self.image_suffixes else ("excel" if suffix == ".xlsx" else "pdf")
                    manifest_item = {
                        "file_name": file_name,
                        "path": str(file_path),
                        "kind": kind,
                        "suffix": suffix,
                    }
                    attachment_manifest.append(manifest_item)
                    self.log(f"💾 Tải thành công file đính kèm: '{file_name}' -> Lưu tại: {file_path}")

                    if suffix in self.document_suffixes:
                        primary_documents.append(str(file_path))

                for document_path in primary_documents:
                    downloaded_files.append(document_path)
                    self._file_contexts[document_path] = {
                        "email_id": e_id.decode(),
                        "email_subject": subject,
                        "attachments": attachment_manifest,
                    }
                    self._pending_email_ids[e_id.decode()] = True

                if attachment_manifest:
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

    def mark_as_processed(self):
        """Đánh dấu TẤT CẢ email đã download là đã xử lý thành công.
        Chỉ gọi từ automation.py SAU KHI xử lý hoàn tất (parse + AI + PDF + send).
        Nếu không gọi, email sẽ được quét lại ở chu kỳ tiếp theo.
        """
        for e_id in self._pending_email_ids:
            self.processed_ids.add(e_id)
        self._save_processed_ids()
        self._pending_email_ids.clear()

    def get_pending_count(self) -> int:
        """Trả về số lượng email đang chờ xử lý (đã download nhưng chưa mark processed)."""
        return len(self._pending_email_ids)

    def get_file_context(self, file_path: str) -> dict:
        """Lấy ngữ cảnh email/attachment cho một file đã tải về."""
        return dict(self._file_contexts.get(str(file_path), {}))


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
