import email
import imaplib
import os
import sys
import subprocess
import json
from email.header import decode_header
from email.utils import parseaddr
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
        self.allowed_report_senders = self._load_allowed_report_senders()
        self.mail = None
        self.log_callback = None
        # Track processed email IDs để tránh xử lý trùng
        self.processed_file = Path(__file__).resolve().parent.parent.parent.parent / ".processed_ids.json"
        self.processed_ids = self._load_processed_ids()

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

    def _load_allowed_report_senders(self) -> set[str]:
        senders: list[str] = []
        if self.accountant_email:
            senders.append(self.accountant_email)

        extra_senders = os.getenv("ALLOWED_REPORT_SENDERS", "")
        if extra_senders:
            senders.extend(part.strip() for part in extra_senders.split(","))

        normalized = {self._normalize_email(sender) for sender in senders if self._normalize_email(sender)}
        return normalized

    @staticmethod
    def _normalize_email(value: str) -> str:
        if not value:
            return ""
        _, address = parseaddr(str(value).strip())
        return address.strip().lower()

    @staticmethod
    def _decode_mime_header(raw_value) -> str:
        if not raw_value:
            return ""
        decoded_parts = []
        for part, encoding in decode_header(raw_value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded_parts.append(str(part))
        return "".join(decoded_parts).strip()

    def _is_allowed_sender(self, sender_value: str) -> bool:
        normalized = self._normalize_email(sender_value)
        return bool(normalized and normalized in self.allowed_report_senders)

    def _allowed_senders_display(self) -> str:
        if not self.allowed_report_senders:
            return "[chưa cấu hình]"
        return ", ".join(sorted(self.allowed_report_senders))

    def _build_sender_search_criteria(self) -> tuple[str, ...]:
        senders = sorted(self.allowed_report_senders)
        if not senders:
            return ("ALL",)
        if len(senders) == 1:
            return ("FROM", f'"{senders[0]}"')

        criteria: list[str] = ["OR"] * (len(senders) - 1)
        for sender in senders:
            criteria.extend(["FROM", f'"{sender}"'])
        return tuple(criteria)

    def _remove_processed_id(self, email_id: str) -> None:
        if email_id in self.processed_ids:
            self.processed_ids.remove(email_id)
            self._save_processed_ids()

    def _remove_processed_ids(self, email_ids: list[str]) -> int:
        removed = 0
        for email_id in email_ids:
            if email_id in self.processed_ids:
                self.processed_ids.remove(email_id)
                removed += 1
        if removed:
            self._save_processed_ids()
        return removed

    def mark_email_ids_as_processed(self, email_ids: list[str]) -> int:
        """Đánh dấu một tập email ID cụ thể là đã xử lý thành công.

        Chỉ những email ID đã được download trong chu kỳ hiện tại mới được commit
        vào processed_ids. Các email còn thất bại sẽ tiếp tục được quét lại ở
        chu kỳ sau.
        """
        marked: list[str] = []
        for email_id in email_ids:
            if email_id in self._pending_email_ids:
                self.processed_ids.add(email_id)
                marked.append(email_id)
        if marked:
            self._save_processed_ids()
            for email_id in marked:
                self._pending_email_ids.pop(email_id, None)
        return len(marked)

    def _requeue_latest_allowed_email(self) -> str | None:
        if not self.mail or not self.allowed_report_senders:
            return None
        try:
            self.mail.select("inbox")
            status, messages = self.mail.search(None, "ALL")
            if status != "OK":
                return None
            for e_id in reversed(messages[0].split()):
                email_id = e_id.decode()
                if email_id not in self.processed_ids:
                    continue
                status, msg_data = self.mail.fetch(e_id, "(RFC822)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                if self._is_allowed_sender(msg.get("From", "")):
                    self._remove_processed_id(email_id)
                    self.log(f"🔁 Re-queue email gần nhất hợp lệ để xử lý lại: ID {email_id}")
                    return email_id
        except Exception as exc:
            self.log(f"⚠️ Không thể re-queue email gần nhất: {exc}")
        return None

    def _resolve_subject(self, msg) -> str:
        return self._decode_mime_header(msg.get("Subject", ""))

    def _load_processed_ids(self) -> set:
        """Load danh sách ID email đã xử lý từ file JSON."""
        try:
            if self.processed_file.exists():
                data = json.loads(self.processed_file.read_text(encoding="utf-8"))
                return set(data.get("ids", []))
        except Exception:
            pass
        return set()

    def _save_processed_ids(self):
        """Lưu danh sách ID email đã xử lý."""
        try:
            self.processed_file.write_text(
                json.dumps({"ids": sorted(self.processed_ids)}, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def log(self, message):

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

            # Quét hộp thư theo allowlist sender để tránh fetch toàn bộ inbox không liên quan
            status, messages = self.mail.search(None, *self._build_sender_search_criteria())

            if status != "OK":
                self.log("❌ Lỗi khi tìm kiếm email.")
                return downloaded_files

            email_ids = messages[0].split()
            candidate_ids = [e_id for e_id in email_ids if e_id.decode() not in self.processed_ids]
            self.log(
                f"🔎 Quét email theo allowlist sender: {self._allowed_senders_display()} | "
                f"{len(email_ids)} email khớp query | {len(candidate_ids)} email chưa processed."
            )

            for e_id in candidate_ids:

                status, msg_data = self.mail.fetch(e_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                sender = msg.get("From", "")
                if not self._is_allowed_sender(sender):
                    self.log(f"⏭️ Bỏ qua email ID {e_id.decode()} từ sender không nằm trong allowlist: {sender}")
                    continue

                # Giải mã tiêu đề email
                subject = self._resolve_subject(msg)
                
                self.log(f"📬 Đang xử lý email tiêu đề: '{subject}' | sender: {sender}")

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
