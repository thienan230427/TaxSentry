from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from .config import DOWNLOAD_DIR
from .secrets import get_secret, set_secret

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
LABELS = ("TaxSentry/Processing", "TaxSentry/Completed", "TaxSentry/NeedsReview", "TaxSentry/Failed")
ALLOWED_EXTENSIONS = {".xlsx", ".pdf", ".png", ".jpg", ".jpeg"}


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
    def __init__(self, settings: dict[str, Any], service=None):
        self.settings = settings
        self.service = service
        self.labels: dict[str, str] = {}

    def authenticate(self) -> None:
        if self.service is not None:
            return
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        account = self.settings["gmail"].get("account") or "default"
        raw = get_secret(f"gmail:{account}")
        credentials = Credentials.from_authorized_user_info(json.loads(raw), SCOPES) if raw else None
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            client_file = self.settings["gmail"].get("oauth_client_file", "")
            if not client_file:
                raise RuntimeError("Missing gmail.oauth_client_file. Run `taxsentry setup`.")
            credentials = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES).run_local_server(port=0)
        set_secret(f"gmail:{account}", credentials.to_json())
        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        self._ensure_labels()

    def _ensure_labels(self) -> None:
        existing = self.service.users().labels().list(userId="me").execute().get("labels", [])
        self.labels = {item["name"]: item["id"] for item in existing}
        for name in LABELS:
            if name not in self.labels:
                item = self.service.users().labels().create(userId="me", body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()
                self.labels[name] = item["id"]

    def messages(self) -> list[GmailMessage]:
        self.authenticate()
        refs = self.service.users().messages().list(userId="me", q='has:attachment -label:"TaxSentry/Completed" -label:"TaxSentry/Processing"').execute().get("messages", [])
        return [self._message(ref["id"]) for ref in refs]

    def _message(self, message_id: str) -> GmailMessage:
        payload = self.service.users().messages().get(userId="me", id=message_id, format="full").execute()["payload"]
        headers = {item["name"].lower(): item["value"] for item in payload.get("headers", [])}
        attachments: list[GmailAttachment] = []
        for part in _parts(payload):
            name = Path(part.get("filename", "")).name
            if not name or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            body = part.get("body", {})
            data = body.get("data")
            if not data and body.get("attachmentId"):
                data = self.service.users().messages().attachments().get(userId="me", messageId=message_id, id=body["attachmentId"]).execute().get("data")
            if data:
                attachments.append(GmailAttachment(name, part.get("mimeType", "application/octet-stream"), base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))))
        return GmailMessage(message_id, headers.get("from", ""), headers.get("subject", ""), attachments)

    def save(self, job_id: str, attachment: GmailAttachment, max_mb: int = 25) -> Path:
        if len(attachment.data) > max_mb * 1024 * 1024:
            raise ValueError(f"Attachment exceeds {max_mb} MB")
        folder = DOWNLOAD_DIR / job_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / Path(attachment.name).name
        path.write_bytes(attachment.data)
        return path

    def label(self, message_id: str, label: str) -> None:
        self.authenticate()
        add = self.labels[label]
        remove = [self.labels[name] for name in LABELS if name != label and name in self.labels]
        self.service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": [add], "removeLabelIds": remove}).execute()

    def send_report(self, to: str, subject: str, html: str, pdf_path: Path) -> str:
        self.authenticate()
        message = EmailMessage()
        message["To"], message["Subject"] = to, subject
        message.set_content("Báo cáo TaxSentry được đính kèm.")
        message.add_alternative(html, subtype="html")
        message.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return str(self.service.users().messages().send(userId="me", body={"raw": raw}).execute().get("id", ""))


def _parts(payload: dict[str, Any]):
    for part in payload.get("parts", []):
        yield part
        yield from _parts(part)
