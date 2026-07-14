from __future__ import annotations

import asyncio
import re
import sys
import webbrowser
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import keyring
from prompt_toolkit.shortcuts import input_dialog, message_dialog, radiolist_dialog
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table

from .gmail import GmailClient
from .providers import CodexAppServerProvider, from_settings, lmstudio_models
from .secrets import get_secret, set_secret

STYLE = Style.from_dict({"dialog": "bg:#0f172a", "dialog.body": "bg:#0f172a #e2e8f0", "dialog frame.label": "#38bdf8 bold", "button": "bg:#1e293b #e2e8f0", "button.focused": "bg:#0ea5e9 #ffffff bold", "radio-selected": "#22c55e bold", "radio-checked": "#22c55e"})
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+$")


class Cancelled(Exception):
    pass


class WizardUI:
    def __init__(self, console: Console):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("`taxsentry setup` cần terminal tương tác / requires an interactive terminal.")
        self.console = console

    def choose(self, title: str, text: str, values, default):
        value = radiolist_dialog(title=title, text=text, values=values, default=default, ok_text="Chọn / Select", cancel_text="Hủy / Cancel", style=STYLE).run()
        if value is None:
            raise Cancelled
        return value

    def text(self, title: str, prompt: str, default: str = "", validate: Callable[[str], bool] | None = None, error: str = "Giá trị không hợp lệ / Invalid value", *, password: bool = False) -> str:
        while True:
            value = input_dialog(title=title, text=prompt, default=default, password=password, ok_text="Tiếp tục / Continue", cancel_text="Hủy / Cancel", style=STYLE).run()
            if value is None:
                raise Cancelled
            value = value.strip()
            if not validate or validate(value):
                return value
            self.message("Không hợp lệ / Invalid", error)

    def message(self, title: str, text: str) -> None:
        message_dialog(title=title, text=text, ok_text="OK", style=STYLE).run()

    def summary(self, rows: list[tuple[str, str]]) -> None:
        table = Table("Mục / Item", "Lựa chọn / Selection", title="TaxSentry Setup")
        for name, value in rows:
            table.add_row(name, value)
        self.console.print(table)


@dataclass
class SetupSelection:
    config: dict[str, Any]
    codex_auth: str = ""
    gmail_auth: str = ""
    telegram_auth: str = ""
    telegram_token: str = ""


def _profile(config: dict[str, Any]) -> str:
    gmail = config.get("gmail", {}).get("enabled", True)
    telegram = config.get("telegram", {}).get("enabled", False)
    return "full" if gmail and telegram else "email" if gmail else "chat"


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _email(value: str) -> bool:
    return bool(EMAIL.fullmatch(value))


async def _codex_catalog() -> tuple[dict[str, Any], list[tuple[str, str]], str]:
    client = CodexAppServerProvider()
    account: dict[str, Any] = {}
    models: list[tuple[str, str]] = []
    errors: list[str] = []
    try:
        try:
            account = await client.account()
        except Exception as exc:
            errors.append(str(exc))
        try:
            models = await client.models()
        except Exception as exc:
            errors.append(str(exc))
        return account, models, "; ".join(dict.fromkeys(errors))
    finally:
        await client.close()


def _pick_model(ui: WizardUI, config: dict[str, Any], kind: str) -> tuple[str, dict[str, Any]]:
    current = str(config["provider"].get("model", ""))
    account: dict[str, Any] = {}
    while True:
        error = ""
        try:
            if kind == "codex":
                account, models, error = asyncio.run(_codex_catalog())
            else:
                models = [(item, item) for item in lmstudio_models(from_settings(config))]
        except Exception as exc:
            models, error = [], str(exc)
        values = [("", "Provider default / Mặc định của provider")]
        values.extend((model_id, f"{label}  [{model_id}]") for model_id, label in models)
        if current and not any(item[0] == current for item in values):
            values.append((current, f"Current custom model / Model tùy chỉnh hiện tại  [{current}]"))
        values.append(("__manual__", "Enter model manually / Nhập model thủ công"))
        if error:
            values.append(("__retry__", f"Retry connection / Thử kết nối lại — {error[:80]}"))
        default = current or (models[0][0] if kind == "lmstudio" and models else "")
        selected = ui.choose("Model", "Chọn model bằng phím mũi tên / Select a model", values, default)
        if selected == "__retry__":
            continue
        if selected == "__manual__":
            return ui.text("Model", "Model ID", current, lambda value: bool(value), "Model ID không được trống / cannot be empty"), account
        return selected, account


def _collect(config: dict[str, Any], ui: WizardUI) -> SetupSelection:
    candidate = deepcopy(config)
    profile = ui.choose(
        "Hồ sơ / Profile",
        "Chọn cách dùng TaxSentry / Choose how TaxSentry will be used",
        [("full", "Full Agent — AI + Gmail + Telegram"), ("email", "Email Agent — AI + Gmail"), ("chat", "Chat Only — AI terminal cockpit")],
        _profile(candidate),
    )
    candidate["gmail"]["enabled"] = profile != "chat"
    candidate["telegram"]["enabled"] = profile == "full"
    candidate["integrations"]["telegram"]["enabled"] = profile == "full"

    kind = ui.choose("Provider", "Chọn AI provider / Select AI provider", [("codex", "Codex / ChatGPT — official App Server"), ("lmstudio", "LM Studio — local OpenAI-compatible server")], candidate["provider"].get("kind", "lmstudio"))
    candidate["provider"]["kind"] = kind
    candidate["provider"]["auth_mode"] = kind
    if kind == "lmstudio":
        base_url = ui.text("LM Studio", "Base URL", str(candidate["provider"].get("lmstudio_base_url", "http://127.0.0.1:1234/v1")), lambda value: value.startswith(("http://", "https://")), "URL phải bắt đầu bằng http:// hoặc https://")
        candidate["provider"]["lmstudio_base_url"] = base_url
        candidate["provider"]["base_url"] = base_url
    model, account = _pick_model(ui, candidate, kind)
    candidate["provider"]["model"] = model

    selection = SetupSelection(candidate)
    if kind == "codex":
        existing = bool(account.get("account")) or account.get("requiresOpenaiAuth") is False
        values = [("existing", "Use existing credentials / Dùng đăng nhập hiện có")] if existing else []
        values += [("browser", "Browser login / Đăng nhập bằng trình duyệt"), ("device", "Device code login / Đăng nhập bằng mã thiết bị")]
        selection.codex_auth = ui.choose("Codex Authentication / Xác thực Codex", "Chọn phương thức đăng nhập / Select authentication method", values, "existing" if existing else "browser")

    if candidate["gmail"]["enabled"]:
        gmail = candidate["gmail"]
        gmail["account"] = ui.text("Gmail", "Tài khoản nhận báo cáo / Report inbox", str(gmail.get("account", "")), _email, "Nhập địa chỉ email hợp lệ / Enter a valid email")
        client_file = ui.text("Gmail OAuth", "Đường dẫn credentials.json / Path to credentials.json", str(gmail.get("oauth_client_file", "")), lambda value: Path(value.strip("\"'")).expanduser().is_file(), "Không tìm thấy file / File not found")
        gmail["oauth_client_file"] = client_file.strip("\"'")
        senders = ui.text("Trusted Senders", "Email được phép, phân cách dấu phẩy / Allowed emails, comma-separated", ",".join(gmail.get("trusted_senders", [])), lambda value: bool(_csv(value)) and all(_email(item) for item in _csv(value)), "Cần ít nhất một email hợp lệ / At least one valid email is required")
        gmail["trusted_senders"] = [item.casefold() for item in _csv(senders)]
        candidate["director"]["email"] = ui.text("Director", "Email Giám đốc / Director email", str(candidate["director"].get("email", "")), _email, "Nhập địa chỉ email hợp lệ / Enter a valid email")
        current_poll = int(candidate["worker"].get("poll_seconds", 60))
        poll = ui.choose("Polling", "Chu kỳ quét Gmail / Gmail polling interval", [(30, "30 seconds"), (60, "60 seconds — recommended"), (300, "5 minutes"), (0, "Custom / Tùy chỉnh")], current_poll if current_poll in {30, 60, 300} else 0)
        if poll == 0:
            poll = int(ui.text("Polling", "Số giây, tối thiểu 10 / Seconds, minimum 10", str(current_poll), lambda value: value.isdigit() and int(value) >= 10, "Giá trị phải là số >= 10"))
        candidate["worker"]["poll_seconds"] = poll
        try:
            has_gmail = bool(get_secret(f"gmail:{gmail['account']}"))
        except keyring.errors.KeyringError:
            has_gmail = False
        selection.gmail_auth = ui.choose("Gmail Authentication / Xác thực Gmail", "Chọn cách xác thực / Select authentication", ([('existing', "Use existing OAuth / Dùng OAuth hiện có")] if has_gmail else []) + [("reauth", "Authenticate now / Đăng nhập ngay")], "existing" if has_gmail else "reauth")

    if candidate["telegram"]["enabled"]:
        chats = ui.text("Telegram", "Chat ID, phân cách dấu phẩy / Chat IDs, comma-separated", ",".join(map(str, candidate["director"].get("telegram_chat_ids", []))), lambda value: bool(_csv(value)) and all(re.fullmatch(r"-?\d+", item) for item in _csv(value)), "Chat ID phải là số nguyên / must be integers")
        candidate["director"]["telegram_chat_ids"] = _csv(chats)
        try:
            has_token = bool(get_secret("telegram:bot-token"))
        except keyring.errors.KeyringError:
            has_token = False
        selection.telegram_auth = ui.choose("Telegram Authentication / Xác thực Telegram", "Chọn token / Select token", ([('existing', "Use existing token / Dùng token hiện có")] if has_token else []) + [("replace", "Enter a new token / Nhập token mới")], "existing" if has_token else "replace")
        if selection.telegram_auth == "replace":
            selection.telegram_token = ui.text("Telegram Token", "Bot token (hidden / được ẩn)", password=True, validate=lambda value: bool(value), error="Token không được trống / cannot be empty")
    candidate["configured"] = True
    return selection


def run_setup_wizard(config: dict[str, Any], console: Console, ui: WizardUI | None = None) -> SetupSelection | None:
    try:
        ui = ui or WizardUI(console)
        while True:
            selection = _collect(config, ui)
            selected = selection.config
            rows = [
                ("Profile / Hồ sơ", _profile(selected)),
                ("Provider", f"{selected['provider']['kind']} / {selected['provider'].get('model') or 'default'}"),
                ("Gmail", selected["gmail"].get("account", "") if selected["gmail"]["enabled"] else "disabled"),
                ("Telegram", ", ".join(selected["director"].get("telegram_chat_ids", [])) if selected["telegram"]["enabled"] else "disabled"),
            ]
            ui.summary(rows)
            action = ui.choose("Xác nhận / Confirm", "Lưu cấu hình và xác thực? / Save configuration and authenticate?", [("save", "Save & Authenticate / Lưu và xác thực"), ("back", "Back / Quay lại"), ("cancel", "Cancel / Hủy")], "save")
            if action == "save":
                return selection
            if action == "cancel":
                return None
            config = selected
    except Cancelled:
        return None


async def _codex_auth(mode: str, model: str, console: Console) -> str:
    client = CodexAppServerProvider(model=model)
    try:
        if mode == "existing":
            state = await client.account(refresh=True)
            if not state.get("account") and state.get("requiresOpenaiAuth", True):
                raise RuntimeError("Không có Codex credentials / No Codex credentials found")
        else:
            def challenge(result):
                if result.get("authUrl"):
                    console.print(f"Open / Mở: {result['authUrl']}")
                    webbrowser.open(result["authUrl"])
                elif result.get("verificationUrl"):
                    console.print(f"Open / Mở: {result['verificationUrl']}  Code / Mã: [bold]{result['userCode']}[/]")
            await client.login(device_code=mode == "device", challenge=challenge)
        return "connected"
    finally:
        await client.close()


async def _telegram_auth(token: str) -> str:
    from telegram import Bot

    async with Bot(token) as bot:
        identity = await bot.get_me()
        return f"@{identity.username}" if getattr(identity, "username", None) else str(identity.id)


def authenticate_selection(selection: SetupSelection, console: Console) -> int:
    statuses: list[tuple[str, str, str]] = []
    failed = False
    config = selection.config
    try:
        if config["provider"]["kind"] == "codex":
            detail = asyncio.run(_codex_auth(selection.codex_auth, config["provider"].get("model", ""), console))
        else:
            models = lmstudio_models(from_settings(config))
            detail = f"connected ({len(models)} models)"
        statuses.append(("Provider", "OK", detail))
    except Exception as exc:
        statuses.append(("Provider", "FAIL", str(exc)))
        failed = True

    if config["gmail"]["enabled"]:
        try:
            GmailClient(config).authenticate(force=selection.gmail_auth == "reauth")
            statuses.append(("Gmail", "OK", config["gmail"]["account"]))
        except Exception as exc:
            statuses.append(("Gmail", "FAIL", f"{exc}; run `taxsentry auth gmail`"))
            failed = True
    else:
        statuses.append(("Gmail", "SKIP", "disabled"))

    if config["telegram"]["enabled"]:
        try:
            token = selection.telegram_token if selection.telegram_auth == "replace" else get_secret("telegram:bot-token")
            detail = asyncio.run(_telegram_auth(token))
            if selection.telegram_auth == "replace":
                set_secret("telegram:bot-token", token)
            statuses.append(("Telegram", "OK", detail))
        except Exception as exc:
            statuses.append(("Telegram", "FAIL", f"{exc}; run `taxsentry auth telegram`"))
            failed = True
    else:
        statuses.append(("Telegram", "SKIP", "disabled"))

    table = Table("Service", "Status", "Detail", title="Setup result / Kết quả cấu hình")
    for row in statuses:
        table.add_row(*row)
    console.print(table)
    console.print("Next / Tiếp theo: `taxsentry doctor` rồi / then `taxsentry start`")
    return int(failed)
