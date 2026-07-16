from __future__ import annotations

import hashlib
import imaplib
import re
import smtplib
import zipfile
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from .config import DOWNLOAD_DIR
from .secrets import get_secret, set_secret

LABELS = ("TaxSentry/Processing", "TaxSentry/Completed", "TaxSentry/NeedsReview", "TaxSentry/Failed")
ALLOWED_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".png", ".jpg", ".jpeg"}
ALLOWED_MIME = {
    ".doc": {"application/msword", "application/octet-stream"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream"},
    ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"},
    ".ppt": {"application/vnd.ms-powerpoint", "application/octet-stream"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/octet-stream"},
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
    recipient: str = ""
    date: str = ""
    body: str = ""
    mailbox: str = "INBOX"
    gmail_id: str = ""


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def natural_gmail_query(text: str, *, now: datetime | None = None) -> str:
    """Translate the small, predictable Vietnamese/English inbox vocabulary used by chat."""
    lowered = text.casefold()
    parts = ["in:anywhere"]
    if "hôm nay" in lowered or "today" in lowered:
        parts.append(f"after:{(now or datetime.now()).strftime('%Y/%m/%d')}")
    if "chưa đọc" in lowered or "unread" in lowered:
        parts.append("is:unread")
    if any(word in lowered for word in ("đính kèm", "attachment", "có file")):
        parts.append("has:attachment")
    sender = re.search(r"(?:\btừ\b|\bfrom\b)\s+([^,?.]+)", text, re.IGNORECASE)
    if sender:
        value = sender.group(1).strip().replace('"', "")
        if value:
            parts.append(f'from:"{value}"')
    if len(parts) == 1:
        parts.append("newer_than:30d")
    return " ".join(parts)


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
        markers = self.settings.get("gmail", {}).setdefault("process_after_uids", {})
        legacy_marker = self.settings.get("gmail", {}).get("process_after_uid")
        if not markers and legacy_marker is not None:
            markers["INBOX"] = int(legacy_marker)
        messages: list[GmailMessage] = []
        for mailbox in self.mailboxes():
            marker = markers.get(mailbox)
            if marker is None:
                continue
            self._imap_select(mailbox)
            status, data = self.imap.uid(
                "search",
                None,
                "UID",
                f"{int(marker) + 1}:*",
                "X-GM-RAW",
                '"has:attachment -in:sent -in:drafts -label:TaxSentry/Completed -label:TaxSentry/Failed"',
            )
            if status != "OK":
                raise RuntimeError(f"Gmail IMAP search failed: {mailbox}")
            uids = (data[0] or b"").split()
            if uids:
                markers[mailbox] = max(int(uid) for uid in uids)
            messages.extend(self._imap_message(uid.decode(), mailbox) for uid in uids)
        unique: dict[str, GmailMessage] = {}
        for message in messages:
            unique.setdefault(message.gmail_id or f"{message.mailbox}:{message.id}", message)
        return [message for message in unique.values() if message.attachments]

    def mailboxes(self) -> list[str]:
        self.authenticate()
        if not hasattr(self.imap, "list"):
            return ["INBOX"]
        status, data = self.imap.list()
        if status != "OK":
            return ["INBOX"]
        found: dict[str, str] = {}
        for raw in data or []:
            text = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
            match = re.search(r'\s(?:"((?:\\.|[^"])*)"|([^\s]+))$', text)
            if not match:
                continue
            mailbox = (match.group(1) or match.group(2) or "").replace(r'\"', '"')
            lowered = text.casefold()
            if r"\all" in lowered:
                found["all"] = mailbox
            elif r"\junk" in lowered:
                found["junk"] = mailbox
            elif r"\trash" in lowered:
                found["trash"] = mailbox
        return [found[key] for key in ("all", "junk", "trash") if key in found] or ["INBOX"]

    def latest_uids(self) -> dict[str, int]:
        self.authenticate()
        latest: dict[str, int] = {}
        for mailbox in self.mailboxes():
            self._imap_select(mailbox)
            status, data = self.imap.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError(f"Gmail IMAP search failed: {mailbox}")
            latest[mailbox] = max((int(uid) for uid in (data[0] or b"").split()), default=0)
        return latest

    def latest_uid(self) -> int:
        self.authenticate()
        self._imap_select("INBOX")
        status, data = self.imap.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("Gmail IMAP search failed")
        return max((int(uid) for uid in (data[0] or b"").split()), default=0)

    def search(self, query: str = "in:anywhere newer_than:30d", limit: int = 20) -> list[GmailMessage]:
        self.authenticate()
        found: list[GmailMessage] = []
        escaped = query.replace(chr(34), chr(92) + chr(34))
        for mailbox in self.mailboxes():
            self._imap_select(mailbox)
            status, data = self.imap.uid("search", None, "X-GM-RAW", f'"{escaped}"')
            if status != "OK":
                raise RuntimeError(f"Gmail IMAP search failed: {mailbox}")
            uids = (data[0] or b"").split()[-max(1, min(limit, 20)):]
            found.extend(self._imap_message(uid.decode(), mailbox) for uid in reversed(uids))
        unique: dict[str, GmailMessage] = {}
        for message in found:
            unique.setdefault(message.gmail_id or f"{message.mailbox}:{message.id}", message)
        return list(unique.values())[: max(1, min(limit, 20))]

    def read(self, uid: str, mailbox: str = "INBOX") -> GmailMessage:
        if not uid.isdigit():
            raise ValueError("Gmail UID must be numeric")
        self.authenticate()
        self._imap_select(mailbox)
        return self._imap_message(uid, mailbox)

    def _imap_select(self, mailbox: str = "INBOX") -> None:
        escaped = mailbox.replace("\\", "\\\\").replace('"', '\\"')
        status, _ = self.imap.select(f'"{escaped}"')
        if status != "OK":
            raise RuntimeError(f"Gmail IMAP mailbox is unavailable: {mailbox}")

    def _imap_message(self, uid: str, mailbox: str = "INBOX") -> GmailMessage:
        status, data = self.imap.uid("fetch", uid, "(RFC822 X-GM-MSGID)")
        if status != "OK":
            raise RuntimeError(f"Gmail IMAP fetch failed: {uid}")
        item = next((item for item in data if isinstance(item, tuple)), (b"", b""))
        metadata, raw = item[0], item[1]
        match = re.search(rb"X-GM-MSGID\s+(\d+)", metadata if isinstance(metadata, bytes) else b"")
        gmail_id = match.group(1).decode() if match else ""
        message = BytesParser(policy=policy.default).parsebytes(raw)
        attachments = []
        for part in message.walk():
            name = Path(part.get_filename() or "").name
            if name and Path(name).suffix.lower() in ALLOWED_EXTENSIONS:
                attachments.append(GmailAttachment(name, part.get_content_type(), part.get_payload(decode=True) or b""))
        body = ""
        selected = message.get_body(preferencelist=("plain", "html")) if message.is_multipart() else message
        if selected:
            try:
                content = selected.get_content()
                if selected.get_content_type() == "text/html":
                    parser = _HTMLText()
                    parser.feed(str(content))
                    body = "\n".join(parser.parts)
                else:
                    body = str(content)
            except (LookupError, UnicodeError):
                body = ""
        raw_date = str(message.get("Date", ""))
        try:
            date = parsedate_to_datetime(raw_date).isoformat() if raw_date else ""
        except (TypeError, ValueError, OverflowError):
            date = raw_date
        return GmailMessage(uid, str(message.get("From", "")), str(message.get("Subject", "")), attachments, str(message.get("To", "")), date, body.strip()[:50000], mailbox, gmail_id)

    def save(self, job_id: str, attachment: GmailAttachment, max_mb: int = 25) -> Path:
        validate_attachment(attachment)
        if len(attachment.data) > max_mb * 1024 * 1024:
            raise ValueError(f"Attachment exceeds {max_mb} MB")
        folder = DOWNLOAD_DIR / job_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / Path(attachment.name).name
        path.write_bytes(attachment.data)
        return path

    def label(self, message_id: str, label: str, *, mailbox: str = "INBOX") -> None:
        self.authenticate()
        self._imap_select(mailbox)
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
    if suffix in {".docx", ".xlsx", ".pptx"}:
        try:
            with zipfile.ZipFile(BytesIO(attachment.data)) as document:
                names = set(document.namelist())
                required = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml"}[suffix]
                valid = {"[Content_Types].xml", required} <= names and sum(item.file_size for item in document.infolist()) <= 200 * 1024 * 1024
        except zipfile.BadZipFile:
            pass
    elif suffix in {".doc", ".xls", ".ppt"}:
        valid = attachment.data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif suffix == ".pdf":
        valid = b"%PDF-" in attachment.data[:1024]
    elif suffix == ".png":
        valid = attachment.data.startswith(b"\x89PNG\r\n\x1a\n")
    else:
        valid = attachment.data.startswith(b"\xff\xd8\xff")
    if not valid:
        raise ValueError(f"Attachment content does not match extension: {attachment.name}")
