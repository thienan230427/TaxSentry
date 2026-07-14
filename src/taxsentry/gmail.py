from __future__ import annotations

import hashlib
import imaplib
import smtplib
import zipfile
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from io import BytesIO
from pathlib import Path
from typing import Any

from .config import DOWNLOAD_DIR
from .secrets import get_secret, set_secret

LABELS = ("TaxSentry/Processing", "TaxSentry/Completed", "TaxSentry/NeedsReview", "TaxSentry/Failed")
ALLOWED_EXTENSIONS = {".xlsx", ".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_MIME = {
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".png": {"image/png", "application/octet-stream"},
    ".jpg": {"image/jpeg", "application/octet-stream"},
    ".jpeg": {"image/jpeg", "application/octet-stream"},
}


@dataclass(slots=True)
class GmailAttachment:
    name: str
    mime_type: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(slots=True)
class GmailMessage:
    id: str
    sender: str
    subject: str
    attachments: list[GmailAttachment]


def normalize_email(value: str) -> str:
    return parseaddr(value)[1].strip().casefold()


def trusted_sender(sender: str, allowlist: list[str]) -> bool:
    normalized = normalize_email(sender)
    return bool(normalized and normalized in {normalize_email(item) for item in allowlist})


class GmailClient:
    def __init__(self, settings: dict[str, Any], imap=None):
        self.settings = settings
        self.imap = imap

    def authenticate(self, *, app_password: str = "", store: bool = True) -> None:
        if self.imap is not None:
            return
        gmail = self.settings["gmail"]
        account = gmail.get("account") or ""
        password = "".join(app_password.split()) or get_secret(f"gmail-app-password:{account}")
        if not account or len(password) != 16:
            raise RuntimeError("Gmail App Password phải có đúng 16 ký tự / must contain exactly 16 characters.")
        self.imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        try:
            self.imap.login(account, password)
        except imaplib.IMAP4.error as exc:
            self.imap = None
            raise RuntimeError("Gmail từ chối App Password. Hãy bật xác minh 2 bước và tạo App Password mới / Gmail rejected the App Password.") from exc
        if app_password and store:
            set_secret(f"gmail-app-password:{account}", password)

    def messages(self) -> list[GmailMessage]:
        self.authenticate()
        self._imap_select()
        status, data = self.imap.uid("search", None, "X-GM-RAW", '"has:attachment -label:TaxSentry/Completed"')
        if status != "OK":
            raise RuntimeError("Gmail IMAP search failed")
        return [self._imap_message(uid.decode()) for uid in (data[0] or b"").split()]

    def _imap_select(self) -> None:
        status, _ = self.imap.select("INBOX")
        if status != "OK":
            raise RuntimeError("Gmail IMAP inbox is unavailable")

    def _imap_message(self, uid: str) -> GmailMessage:
        status, data = self.imap.uid("fetch", uid, "(RFC822)")
        if status != "OK":
            raise RuntimeError(f"Gmail IMAP fetch failed: {uid}")
        raw = next((item[1] for item in data if isinstance(item, tuple)), b"")
        message = BytesParser(policy=policy.default).parsebytes(raw)
        attachments = []
        for part in message.walk():
            name = Path(part.get_filename() or "").name
            if name and Path(name).suffix.lower() in ALLOWED_EXTENSIONS:
                attachments.append(GmailAttachment(name, part.get_content_type(), part.get_payload(decode=True) or b""))
        return GmailMessage(uid, str(message.get("From", "")), str(message.get("Subject", "")), attachments)

    def save(self, job_id: str, attachment: GmailAttachment, max_mb: int = 25) -> Path:
        validate_attachment(attachment)
        if len(attachment.data) > max_mb * 1024 * 1024:
            raise ValueError(f"Attachment exceeds {max_mb} MB")
        folder = DOWNLOAD_DIR / job_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / Path(attachment.name).name
        path.write_bytes(attachment.data)
        return path

    def label(self, message_id: str, label: str) -> None:
        self.authenticate()
        self._imap_select()
        for name in LABELS:
            operation = "+X-GM-LABELS" if name == label else "-X-GM-LABELS"
            status, _ = self.imap.uid("store", message_id, operation, f'("{name}")')
            if status != "OK":
                raise RuntimeError(f"Gmail IMAP label failed: {name}")

    def send_report(self, to: str, subject: str, html: str, pdf_path: Path, *, idempotency_key: str = "") -> str:
        self.authenticate()
        message_id = f"<{idempotency_key}@taxsentry.local>" if idempotency_key else ""
        if message_id:
            self._imap_select()
            status, data = self.imap.uid("search", None, "X-GM-RAW", f'"in:sent rfc822msgid:{message_id}"')
            if status == "OK" and (data[0] or b"").split():
                return (data[0] or b"").split()[0].decode()
        message = EmailMessage()
        message["From"] = self.settings.get("gmail", {}).get("account", "")
        message["To"], message["Subject"] = to, subject
        if message_id:
            message["Message-ID"] = message_id
        message.set_content("Báo cáo TaxSentry được đính kèm.")
        message.add_alternative(html, subtype="html")
        message.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
        account = self.settings["gmail"]["account"]
        password = get_secret(f"gmail-app-password:{account}")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(account, password)
            smtp.send_message(message)
        return message_id or str(message["Message-ID"] or "sent")


def validate_attachment(attachment: GmailAttachment) -> None:
    suffix = Path(attachment.name).suffix.casefold()
    mime = attachment.mime_type.split(";", 1)[0].strip().casefold()
    if suffix not in ALLOWED_EXTENSIONS or mime not in ALLOWED_MIME[suffix]:
        raise ValueError(f"Unsupported attachment type: {attachment.name} ({attachment.mime_type})")
    valid = False
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(BytesIO(attachment.data)) as workbook:
                names = set(workbook.namelist())
                valid = {"[Content_Types].xml", "xl/workbook.xml"} <= names and sum(item.file_size for item in workbook.infolist()) <= 200 * 1024 * 1024
        except zipfile.BadZipFile:
            pass
    elif suffix == ".pdf":
        valid = b"%PDF-" in attachment.data[:1024]
    elif suffix == ".png":
        valid = attachment.data.startswith(b"\x89PNG\r\n\x1a\n")
    else:
        valid = attachment.data.startswith(b"\xff\xd8\xff")
    if not valid:
        raise ValueError(f"Attachment content does not match extension: {attachment.name}")
