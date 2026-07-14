from __future__ import annotations

import asyncio
import re
import sys
import webbrowser
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

import keyring
from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import Validator
from prompt_toolkit.widgets import Box, Label, RadioList
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .config import save_config
from .gmail import GmailClient
from .providers import CodexAppServerProvider, from_settings, lmstudio_models
from .secrets import get_secret, set_secret

STYLE = Style.from_dict(
    {
        "marker": "#22d3ee bold",
        "title": "bold",
        "description": "#64748b",
        "option": "#cbd5e1",
        "option.selected": "#22d3ee bold",
        "option.checked": "#22c55e bold",
        "hint": "#64748b",
        "prompt": "#22d3ee bold",
        "validation-toolbar": "bg:#7f1d1d #ffffff",
    }
)
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+$")


class Cancelled(Exception):
    pass


class WizardUI:
    def __init__(self, console: Console):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("`taxsentry setup` cần terminal tương tác / requires an interactive terminal.")
        self.console = console
        self.unicode = self._supports_unicode()
        self.marker, self.done, self.line = ("◆", "✓", "│") if self.unicode else (">", "+", "|")
        self.console.print()
        self.console.print(Text(f"{self.marker} TaxSentry Setup", style="bold cyan"))
        self.console.print(Text("  Cấu hình trợ lý của bạn", style="bold"))
        self.console.print(Text("  Configure your assistant", style="dim"))

    @staticmethod
    def _supports_unicode() -> bool:
        try:
            "◆✓│".encode(sys.stdout.encoding or "ascii")
            return True
        except (LookupError, UnicodeEncodeError):
            return False

    @staticmethod
    def _parts(value: str) -> tuple[str, str]:
        parts = value.split(" / ", 1)
        return parts[0], parts[1] if len(parts) == 2 else ""

    @staticmethod
    def _option(label: str):
        primary, _, secondary = label.partition("\n")
        result = [("class:option", primary)]
        if secondary:
            result += [("", "\n   "), ("class:description", secondary)]
        return result

    def _heading(self, title: str, text: str, prompt: str = ""):
        primary, secondary = self._parts(title)
        description, english = self._parts(text)
        result = [
            ("class:marker", f"{self.marker} "),
            ("class:title", primary),
        ]
        if secondary:
            result += [("class:description", f"  {secondary}")]
        result += [("", "\n"), ("class:marker", f"{self.line} "), ("", description)]
        if english:
            result += [("", "\n"), ("class:marker", f"{self.line} "), ("class:description", english)]
        if prompt:
            result += [("", "\n"), ("class:marker", f"{self.line} "), ("class:prompt", f"{prompt}: ")]
        return result

    def _complete(self, title: str, value: str) -> None:
        primary, _ = self._parts(title)
        line = Text()
        line.append(f"{self.done} ", style="green bold")
        line.append(primary, style="bold")
        line.append("  ", style="dim")
        line.append(value.splitlines()[0] or "Mặc định", style="cyan")
        self.console.print(line)

    def choose(self, title: str, text: str, values, default):
        labels = dict(values)
        choices = [(value, self._option(label)) for value, label in values]
        radio = RadioList(
            choices,
            default=default,
            show_numbers=True,
            select_on_focus=True,
            open_character="",
            select_character=self.marker,
            close_character="",
            show_cursor=False,
            show_scrollbar=True,
            container_style="class:option",
            default_style="class:option",
            selected_style="class:option.selected",
            checked_style="class:option.checked",
        )
        keys = KeyBindings()

        @keys.add("enter", eager=True)
        def accept(event) -> None:
            event.app.exit(result=radio.current_value)

        @keys.add("escape", eager=True)
        @keys.add("c-c", eager=True)
        def cancel(event) -> None:
            event.app.exit(exception=Cancelled())

        app = Application(
            layout=Layout(
                HSplit(
                    [
                        Label(self._heading(title, text), dont_extend_height=True),
                        Box(radio, padding_left=2, padding_top=1, padding_bottom=1),
                        Label("  1-9 chọn nhanh  ↑↓ di chuyển  Enter chọn  Esc hủy", style="class:hint", dont_extend_height=True),
                    ]
                ),
                focused_element=radio,
            ),
            key_bindings=keys,
            style=STYLE,
            full_screen=False,
            erase_when_done=True,
        )
        value = app.run()
        self._complete(title, labels[value])
        return value

    async def wait(self, awaitable, timeout: float = 300):
        keys = KeyBindings()

        @keys.add("escape", eager=True)
        @keys.add("c-c", eager=True)
        def cancel(event) -> None:
            event.app.exit(result=False)

        app = Application(
            layout=Layout(
                HSplit(
                    [
                        Label(self._heading("Đăng nhập Codex / Codex Login", "Đang chờ xác thực trên trình duyệt / Waiting for browser authentication"), dont_extend_height=True),
                        Label("  Esc hoặc Ctrl+C để hủy / to cancel", style="class:hint", dont_extend_height=True),
                    ]
                )
            ),
            key_bindings=keys,
            style=STYLE,
            full_screen=False,
            erase_when_done=True,
        )
        task = asyncio.create_task(awaitable)
        app_task = asyncio.create_task(app.run_async())
        done, _ = await asyncio.wait({task, app_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            if not app_task.done():
                app.exit(result=True)
            await app_task
            return await task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if app_task.done():
            await app_task
        else:
            app.exit(result=False)
            await app_task
        if not done:
            raise TimeoutError("Codex OAuth timeout")
        raise Cancelled

    def text(self, title: str, prompt: str, default: str = "", validate: Callable[[str], bool] | None = None, error: str = "Giá trị không hợp lệ / Invalid value", *, password: bool = False) -> str:
        keys = KeyBindings()

        @keys.add("escape", eager=True)
        def cancel(event) -> None:
            event.app.exit(exception=Cancelled())

        validator = None
        if validate:
            validator = Validator.from_callable(
                lambda value: validate(value.strip()), error_message=error, move_cursor_to_end=True
            )
        session = PromptSession(
            self._heading(title, "Nhập giá trị / Enter a value", prompt),
            is_password=password,
            validator=validator,
            validate_while_typing=False,
            key_bindings=keys,
            style=STYLE,
            erase_when_done=True,
        )
        try:
            value = session.prompt(default=default).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise Cancelled from exc
        self._complete(title, "••••••" if password else value)
        return value

    def message(self, title: str, text: str) -> None:
        self.console.print(Text(f"! {title}: {text}", style="bold red"))

    def summary(self, rows: list[tuple[str, str]]) -> None:
        table = Table("Mục", "Lựa chọn", title="Xác nhận cấu hình", title_style="bold cyan", border_style="cyan")
        for name, value in rows:
            table.add_row(name, value)
        self.console.print(table)


@dataclass
class SetupSelection:
    config: dict[str, Any]
    codex_auth: str = ""
    gmail_auth: str = ""
    gmail_password: str = ""
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


def _show_codex_challenge(ui: WizardUI, result: dict[str, Any]) -> None:
    url = str(result.get("authUrl") or result.get("verificationUrl") or "")
    if not url:
        raise RuntimeError("Codex App Server không trả về URL đăng nhập / returned no login URL")
    ui.console.print(f"\n[bold cyan]Mở liên kết để đăng nhập / Open this login URL:[/]\n[link={url}]{url}[/link]")
    if result.get("userCode"):
        ui.console.print(f"Mã thiết bị / Device code: [bold blue]{result['userCode']}[/]\n")
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if not opened:
        ui.console.print("[yellow]Trình duyệt không tự mở; hãy bấm hoặc sao chép liên kết phía trên.[/]")


async def _await_login(ui: WizardUI, client: CodexAppServerProvider, result: dict[str, Any]) -> None:
    login_id = str(result.get("loginId") or "")
    try:
        waiter = client.wait_login(login_id)
        if hasattr(ui, "wait"):
            await ui.wait(waiter)
        else:
            await waiter
    except (Cancelled, TimeoutError):
        await client.cancel_login(login_id)
        raise


async def _login_codex(ui: WizardUI, client: CodexAppServerProvider, mode: str) -> None:
    while True:
        try:
            result = await client.start_login(device_code=mode == "device")
            _show_codex_challenge(ui, result)
            await _await_login(ui, client, result)
            return
        except Cancelled:
            raise
        except Exception as exc:
            ui.message("Codex OAuth", str(exc))
            action = await asyncio.to_thread(
                ui.choose,
                "Lỗi đăng nhập / Login failed",
                "Chọn cách tiếp tục / Choose how to continue",
                [("retry", "Thử lại\nRetry"), ("device", "Dùng mã thiết bị\nUse device code"), ("cancel", "Hủy\nCancel")],
                "device" if mode == "browser" else "retry",
            )
            if action == "cancel":
                raise Cancelled
            mode = "device" if action == "device" else mode


async def _codex_session(ui: WizardUI) -> tuple[dict[str, Any], list[tuple[str, str, tuple[str, ...]]]]:
    client = CodexAppServerProvider()
    try:
        account = await client.account()
        existing = bool(account.get("account")) or account.get("requiresOpenaiAuth") is False
        account_info = account.get("account") or {}
        identity = str(account_info.get("email") or account_info.get("type") or "Codex")
        plan = str(account_info.get("planType") or "").strip()
        values = []
        if existing:
            values.append(("existing", f"Dùng phiên hiện tại — {identity}{f' ({plan})' if plan else ''}\nUse existing session"))
        values.extend([("browser", "Đăng nhập bằng trình duyệt\nBrowser OAuth"), ("device", "Đăng nhập bằng mã thiết bị\nDevice code login"), ("cancel", "Hủy\nCancel")])
        mode = await asyncio.to_thread(ui.choose, "Xác thực Codex / Codex Authentication", "Chọn phương thức đăng nhập / Select authentication method", values, "existing" if existing else "browser")
        if mode == "cancel":
            raise Cancelled
        if mode != "existing":
            await _login_codex(ui, client, mode)
            account = await client.account(refresh=True)

        while True:
            try:
                return account, await client.models()
            except Exception as exc:
                ui.message("Danh sách model / Model list", str(exc))
                action = await asyncio.to_thread(
                    ui.choose,
                    "Không lấy được model / Models unavailable",
                    "Chọn cách tiếp tục / Choose how to continue",
                    [("retry", "Thử lại\nRetry"), ("login", "Đăng nhập lại\nReauthenticate"), ("default", "Dùng mặc định Codex\nUse Codex default"), ("cancel", "Hủy\nCancel")],
                    "retry",
                )
                if action == "retry":
                    continue
                if action == "login":
                    await _login_codex(ui, client, "browser")
                    account = await client.account(refresh=True)
                    continue
                if action == "default":
                    return account, []
                raise Cancelled
    finally:
        await client.close()


def _pick_model(ui: WizardUI, config: dict[str, Any], kind: str, codex_models=()) -> tuple[str, dict[str, Any]]:
    current = str(config["provider"].get("model", ""))
    account: dict[str, Any] = {}
    while True:
        error = ""
        try:
            if kind == "codex":
                models = list(codex_models)
            else:
                models = [(item, item, ()) for item in lmstudio_models(from_settings(config))]
        except Exception as exc:
            models, error = [], str(exc)
        values = [("", "Mặc định của provider\nProvider default")]
        for model_id, label, efforts in models:
            details = [model_id]
            if efforts:
                details.append(f"reasoning: {', '.join(efforts)}")
            if model_id == current:
                details.append("đang dùng / currently in use")
            values.append((model_id, f"{label}\n{' · '.join(details)}"))
        if kind != "codex" and current and not any(item[0] == current for item in values):
            values.append((current, f"Model tùy chỉnh hiện tại  [{current}]\nCurrent custom model"))
        if kind != "codex":
            values.append(("__manual__", "Nhập model thủ công\nEnter model manually"))
        if error:
            values.append(("__retry__", f"Thử kết nối lại — {error[:80]}\nRetry connection"))
        default = current if any(item[0] == current for item in values) else (models[0][0] if kind == "lmstudio" and models else "")
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

    kind = ui.choose("Provider", "Chọn AI provider / Select AI provider", [("codex", "Codex / ChatGPT — official App Server"), ("lmstudio", "LM Studio — local OpenAI-compatible server")], candidate["provider"].get("kind", "lmstudio"))
    candidate["provider"]["kind"] = kind
    candidate["provider"]["auth_mode"] = kind
    if kind == "lmstudio":
        base_url = ui.text("LM Studio", "Base URL", str(candidate["provider"].get("lmstudio_base_url", "http://127.0.0.1:1234/v1")), lambda value: value.startswith(("http://", "https://")), "URL phải bắt đầu bằng http:// hoặc https://")
        candidate["provider"]["lmstudio_base_url"] = base_url
        candidate["provider"]["base_url"] = base_url
    account: dict[str, Any] = {}
    codex_models = ()
    if kind == "codex":
        account, codex_models = asyncio.run(_codex_session(ui))
    model, account = _pick_model(ui, candidate, kind, codex_models) if kind == "codex" else _pick_model(ui, candidate, kind)
    candidate["provider"]["model"] = model

    selection = SetupSelection(candidate, codex_auth="existing" if kind == "codex" else "")

    if candidate["gmail"]["enabled"]:
        gmail = candidate["gmail"]
        gmail["account"] = ui.text("Gmail", "Tài khoản nhận báo cáo / Report inbox", str(gmail.get("account", "")), _email, "Nhập địa chỉ email hợp lệ / Enter a valid email")
        senders = ui.text("Trusted Senders", "Email được phép, phân cách dấu phẩy / Allowed emails, comma-separated", ",".join(gmail.get("trusted_senders", [])), lambda value: bool(_csv(value)) and all(_email(item) for item in _csv(value)), "Cần ít nhất một email hợp lệ / At least one valid email is required")
        gmail["trusted_senders"] = [item.casefold() for item in _csv(senders)]
        candidate["director"]["email"] = ui.text("Director", "Email Giám đốc / Director email", str(candidate["director"].get("email", "")), _email, "Nhập địa chỉ email hợp lệ / Enter a valid email")
        current_poll = int(candidate["worker"].get("poll_seconds", 60))
        poll = ui.choose("Polling", "Chu kỳ quét Gmail / Gmail polling interval", [(30, "30 giây\n30 seconds"), (60, "60 giây — khuyên dùng\n60 seconds — recommended"), (300, "5 phút\n5 minutes"), (0, "Tùy chỉnh\nCustom")], current_poll if current_poll in {30, 60, 300} else 0)
        if poll == 0:
            poll = int(ui.text("Polling", "Số giây, tối thiểu 10 / Seconds, minimum 10", str(current_poll), lambda value: value.isdigit() and int(value) >= 10, "Giá trị phải là số >= 10"))
        candidate["worker"]["poll_seconds"] = poll
        try:
            has_gmail = bool(get_secret(f"gmail-app-password:{gmail['account']}"))
        except keyring.errors.KeyringError:
            has_gmail = False
        if has_gmail:
            selection.gmail_auth = ui.choose("Xác thực Gmail / Gmail Authentication", "Chọn App Password / Select App Password", [("existing", "Dùng App Password hiện có\nUse existing App Password"), ("replace", "Nhập App Password mới\nEnter a new App Password")], "existing")
        else:
            selection.gmail_auth = "replace"
        if selection.gmail_auth == "replace":
            selection.gmail_password = ui.text("Gmail App Password", "App Password 16 ký tự / 16-character App Password", password=True, validate=lambda value: len("".join(value.split())) == 16, error="App Password phải có đúng 16 ký tự / must contain exactly 16 characters")

    if candidate["telegram"]["enabled"]:
        chats = ui.text("Telegram", "Chat ID, phân cách dấu phẩy / Chat IDs, comma-separated", ",".join(map(str, candidate["director"].get("telegram_chat_ids", []))), lambda value: bool(_csv(value)) and all(re.fullmatch(r"-?\d+", item) for item in _csv(value)), "Chat ID phải là số nguyên / must be integers")
        candidate["director"]["telegram_chat_ids"] = _csv(chats)
        try:
            has_token = bool(get_secret("telegram:bot-token"))
        except keyring.errors.KeyringError:
            has_token = False
        selection.telegram_auth = ui.choose("Xác thực Telegram / Telegram Authentication", "Chọn token / Select token", ([('existing', "Dùng token hiện có\nUse existing token")] if has_token else []) + [("replace", "Nhập token mới\nEnter a new token")], "existing" if has_token else "replace")
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
            action = ui.choose("Xác nhận / Confirm", "Lưu cấu hình và xác thực? / Save configuration and authenticate?", [("save", "Lưu và xác thực\nSave & Authenticate"), ("back", "Quay lại\nBack"), ("cancel", "Hủy\nCancel")], "save")
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
            GmailClient(config).authenticate(app_password=selection.gmail_password, store=False)
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
            statuses.append(("Telegram", "OK", detail))
        except Exception as exc:
            statuses.append(("Telegram", "FAIL", f"{exc}; run `taxsentry auth telegram`"))
            failed = True
    else:
        statuses.append(("Telegram", "SKIP", "disabled"))

    if not failed:
        if config["gmail"]["enabled"] and selection.gmail_password:
            account = config["gmail"]["account"]
            set_secret(f"gmail-app-password:{account}", "".join(selection.gmail_password.split()))
        if config["telegram"]["enabled"] and selection.telegram_auth == "replace":
            set_secret("telegram:bot-token", selection.telegram_token)
        config["configured"] = True
        save_config(config)

    table = Table("Service", "Status", "Detail", title="Setup result / Kết quả cấu hình")
    for row in statuses:
        table.add_row(*row)
    console.print(table)
    console.print("Next / Tiếp theo: `taxsentry doctor` rồi chạy / then run `taxsentry`")
    return int(failed)
