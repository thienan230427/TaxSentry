from __future__ import annotations

import asyncio
import re
import sys
import webbrowser
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

import keyring
from rich.console import Console
from rich.table import Table
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .config import save_config
from .gmail import GmailClient
from .providers import CodexAppServerProvider, from_settings, lmstudio_models
from .secrets import get_secret, set_secret
from .ui_text import language

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+$")


class Cancelled(Exception):
    pass


class WizardUI:
    """Compatibility surface for the pure collection tests."""

    def __init__(self, console: Console):
        self.console = console

    @staticmethod
    def _supports_unicode() -> bool:
        try:
            "◆✓│".encode(getattr(sys.stdout, "encoding", None) or "ascii")
            return True
        except (LookupError, UnicodeEncodeError):
            return False

    def choose(self, title: str, text: str, values, default):
        raise RuntimeError("Use SetupWizardApp for interactive setup")

    async def wait(self, awaitable, timeout: float = 300):
        return await asyncio.wait_for(awaitable, timeout)

    def text(self, title: str, prompt: str, default: str = "", validate: Callable[[str], bool] | None = None, error: str = "Giá trị không hợp lệ / Invalid value", *, password: bool = False) -> str:
        raise RuntimeError("Use SetupWizardApp for interactive setup")

    def message(self, title: str, text: str) -> None:
        self.console.print(f"[red]! {title}: {text}[/]")

    def summary(self, rows: list[tuple[str, str]]) -> None:
        return None


@dataclass
class SetupSelection:
    config: dict[str, Any]
    codex_auth: str = ""
    gmail_auth: str = ""
    gmail_password: str = ""
    gmail_reset_uid: bool = False
    telegram_auth: str = ""
    telegram_token: str = ""
    validated: bool = False


class SetupWizardApp(App[SetupSelection | None]):
    TITLE = "TaxSentry Setup"
    BINDINGS = [Binding("escape", "back", "Back"), Binding("ctrl+c", "cancel", "Cancel", priority=True)]
    CSS = """
    Screen { background: ansi_default; color: ansi_default; layout: vertical; }
    #wizard { width: 72; max-width: 100%; height: auto; padding: 0 1; }
    #wizard-title { height: 1; color: #d4af37; text-style: bold; }
    #history { height: auto; max-height: 6; margin-top: 1; color: #6b7280; }
    #step { height: 1; margin-top: 1; color: #6b7280; }
    #question { height: auto; margin-top: 1; text-style: bold; }
    #content { width: 100%; height: auto; max-height: 12; margin-top: 1; }
    OptionList { width: 100%; height: auto; max-height: 12; padding: 0; border: none; background: transparent; }
    OptionList:focus { border: none; }
    OptionList > .option-list--option-highlighted { color: #d4af37; background: transparent; text-style: bold; }
    Input { width: 100%; height: 2; padding: 0; border: none; border-bottom: solid #4b5563; background: transparent; color: ansi_default; }
    Input:focus { border-bottom: solid #d4af37; }
    #error { height: auto; min-height: 1; margin-top: 1; color: #ef4444; }
    #hint { height: 1; margin-top: 1; color: #6b7280; }
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.original = deepcopy(config)
        self.candidate = deepcopy(config)
        self.candidate.setdefault("ui", {})["language"] = language(config)
        self.selection = SetupSelection(self.candidate)
        self.step = 0
        self.returning = bool(config.get("configured"))
        self.steps = ["mode"] if self.returning else ["language", "mode"]
        self.model_options: list[tuple[str, str, tuple[str, ...]]] = []
        self.gmail_was_enabled = bool(config.get("gmail", {}).get("enabled", True))
        self.history: list[str] = []
        self.snapshots: list[tuple[Any, ...]] = []

    @property
    def en(self) -> bool:
        return self.candidate["ui"].get("language") == "en"

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard"):
            yield Static("TaxSentry setup", id="wizard-title")
            yield Static("", id="history")
            yield Static("", id="step")
            yield Static("", id="question")
            yield Vertical(id="content")
            yield Static("", id="error")
            yield Static("↑/↓ select · Enter confirm · Esc back · Ctrl+C cancel", id="hint")

    async def on_mount(self) -> None:
        await self._render_step()

    def _label(self, vi: str, en: str) -> str:
        return en if self.en else vi

    async def _render_step(self) -> None:
        content = self.query_one("#content", Vertical)
        await content.remove_children()
        self.query_one("#error", Static).update("")
        key = self.steps[self.step]
        self.query_one("#history", Static).update("\n".join(self.history[-6:]))
        self.query_one("#step", Static).update(self._label(f"Bước {self.step + 1} / {len(self.steps)}", f"Step {self.step + 1} of {len(self.steps)}"))
        question = ""
        widget: Any
        if key == "language":
            question = "Chọn ngôn ngữ / Choose your language"
            widget = self._picker([("vi", "Tiếng Việt", "Giao diện tiếng Việt"), ("en", "English", "English interface")])
        elif key == "mode":
            question = self._label("Sếp muốn cấu hình theo cách nào?", "How would you like to set up TaxSentry?")
            options = [("quick", "Quick Setup", self._label("Provider và model, vào chat ngay", "Provider and model, start chatting quickly")), ("full", "Full Setup", self._label("Cấu hình đầy đủ dịch vụ", "Configure every service"))]
            if self.returning:
                options.append(("section", "Configure a section", self._label("Chỉ thay phần được chọn", "Change one section only")))
            widget = self._picker(options)
        elif key == "section":
            question = self._label("Sếp muốn cấu hình phần nào?", "Which section would you like to configure?")
            widget = self._picker([("language", "Language", "Tiếng Việt / English"), ("provider", "Provider & Model", "Codex or LM Studio"), ("gmail", "Gmail", self._label("Tài khoản và App Password", "Account and App Password")), ("telegram", "Telegram", self._label("Chat IDs và bot token", "Chat IDs and bot token")), ("poll", "Polling", self._label("Chu kỳ kiểm tra Gmail", "Gmail polling interval"))])
        elif key == "profile":
            question = self._label("TaxSentry sẽ dùng những dịch vụ nào?", "Which services should TaxSentry use?")
            widget = self._picker([("full", "Full Agent", "AI + Gmail + Telegram"), ("email", "Email Agent", "AI + Gmail"), ("chat", "Chat Only", self._label("Chỉ chat trong terminal", "Terminal chat only"))])
        elif key == "provider":
            question = self._label("Chọn AI provider", "Choose an AI provider")
            widget = self._picker([("codex", "Codex / ChatGPT", self._label("Đăng nhập bằng Codex App Server", "Authenticate with Codex App Server")), ("lmstudio", "LM Studio", self._label("Chạy model cục bộ", "Run a local model"))])
        elif key == "provider_detail":
            if self.candidate["provider"].get("kind") == "codex":
                question = self._label("Xác thực Codex", "Codex authentication")
                widget = self._picker([("existing", self._label("Phiên hiện tại", "Existing session"), self._label("Dùng đăng nhập đang có", "Use the current sign-in")), ("browser", "Browser OAuth", self._label("Mở trình duyệt để đăng nhập", "Open a browser to sign in"))])
            else:
                question = "LM Studio Base URL"
                widget = Input(str(self.candidate["provider"].get("lmstudio_base_url", "http://127.0.0.1:1234/v1")), id="answer")
        elif key == "model":
            current = str(self.candidate["provider"].get("model", ""))
            question = self._label("Chọn model", "Choose a model")
            options = [("", self._label("Mặc định provider", "Provider default"), self._label("Để provider tự chọn", "Let the provider decide"))]
            options += [(model_id, label, model_id) for model_id, label, _ in self.model_options]
            if current and current not in {item[0] for item in options}:
                options.append((current, current, self._label("Model hiện tại", "Current model")))
            options.append(("__custom__", self._label("Nhập model ID", "Enter model ID"), self._label("Dùng model tùy chỉnh", "Use a custom model")))
            widget = self._picker(options)
        elif key == "custom_model":
            question = "Model ID"
            widget = Input(str(self.candidate["provider"].get("model", "")), id="answer")
        elif key in {"gmail_enabled", "telegram_enabled"}:
            service = "Gmail" if key.startswith("gmail") else "Telegram"
            question = self._label(f"Bật {service}?", f"Enable {service}?")
            widget = self._picker([("yes", self._label("Bật", "Enable"), service), ("no", self._label("Tắt", "Disable"), service)])
        elif key == "gmail_account":
            question = self._label("Tài khoản Gmail nhận báo cáo", "Gmail report inbox")
            widget = Input(str(self.candidate["gmail"].get("account", "")), placeholder="name@gmail.com", id="answer")
        elif key == "poll":
            question = self._label("Chu kỳ quét Gmail (giây, tối thiểu 10)", "Gmail polling interval (seconds, minimum 10)")
            widget = Input(str(self.candidate["worker"].get("poll_seconds", 30)), id="answer")
        elif key == "gmail_password":
            question = self._label("Gmail App Password (để trống để giữ secret hiện tại)", "Gmail App Password (leave blank to keep the existing secret)")
            widget = Input("", password=True, id="answer")
        elif key == "telegram_chats":
            question = "Telegram Chat IDs"
            widget = Input(",".join(map(str, self.candidate["director"].get("telegram_chat_ids", []))), id="answer")
        elif key == "telegram_token":
            question = self._label("Telegram bot token (để trống để giữ secret hiện tại)", "Telegram bot token (leave blank to keep the existing secret)")
            widget = Input("", password=True, id="answer")
        else:
            question = self._label("Kiểm tra và lưu cấu hình?", "Validate and save this configuration?")
            provider = self.candidate["provider"]
            summary = [
                f"Provider: {provider['kind']} / {provider.get('model') or 'default'}",
                f"Gmail: {self.candidate['gmail'].get('account') if self.candidate['gmail'].get('enabled') else 'disabled'}",
                f"Telegram: {', '.join(self.candidate['director'].get('telegram_chat_ids', [])) if self.candidate['telegram'].get('enabled') else 'disabled'}",
            ]
            widget = Vertical(Static("\n".join(summary), markup=False), self._picker([("save", self._label("Lưu và xác thực", "Save and validate"), self._label("Không ghi gì nếu kiểm tra thất bại", "Nothing is written if validation fails"))]))
        self.query_one("#question", Static).update(question)
        await content.mount(widget)
        focusable = list(content.query("Input, OptionList"))
        if focusable:
            focusable[0].focus()

    @staticmethod
    def _picker(options: list[tuple[str, str, str]]) -> OptionList:
        return OptionList(*(Option(f"{label}\n[dim]{description}[/]", id=value) for value, label, description in options), id="answers", compact=True)

    def _snapshot(self) -> None:
        saved = deepcopy(self.selection)
        saved.gmail_password = ""
        saved.telegram_token = ""
        self.snapshots.append((self.step, deepcopy(self.steps), deepcopy(self.candidate), saved, deepcopy(self.history), deepcopy(self.model_options)))

    def _finish_step(self, label: str) -> None:
        self.history.append(("✓" if WizardUI._supports_unicode() else "+") + " " + label)
        self.step += 1

    def _provider_steps(self) -> list[str]:
        return ["provider", "provider_detail", "model"]

    def _set_mode(self, mode: str) -> None:
        prefix = self.steps[: self.step + 1]
        if mode == "quick":
            if not self.returning:
                self.candidate["gmail"]["enabled"] = False
                self.candidate["telegram"]["enabled"] = False
            self.steps = prefix + self._provider_steps() + ["confirm"]
        elif mode == "full":
            self.steps = prefix + ["profile"]
        else:
            self.steps = prefix + ["section"]

    def _set_profile(self, profile: str) -> None:
        self.candidate["gmail"]["enabled"] = profile != "chat"
        self.candidate["telegram"]["enabled"] = profile == "full"
        tail = self._provider_steps()
        if self.candidate["gmail"]["enabled"]:
            tail += ["gmail_account", "poll", "gmail_password"]
        if self.candidate["telegram"]["enabled"]:
            tail += ["telegram_chats", "telegram_token"]
        self.steps = self.steps[: self.step + 1] + tail + ["confirm"]

    def _set_section(self, section: str) -> None:
        mapping = {"language": ["language"], "provider": self._provider_steps(), "gmail": ["gmail_enabled"], "telegram": ["telegram_enabled"], "poll": ["poll"]}
        self.steps = self.steps[: self.step + 1] + mapping[section] + ["confirm"]

    @on(OptionList.OptionSelected)
    async def option_selected(self, event: OptionList.OptionSelected) -> None:
        await self._accept(str(event.option.id))

    @on(Input.Submitted, "#answer")
    async def input_submitted(self, event: Input.Submitted) -> None:
        await self._accept(event.value)

    async def _accept(self, value: str) -> None:
        key = self.steps[self.step]
        self._snapshot()
        try:
            if key == "language":
                self.candidate["ui"]["language"] = value
                label = f"Language · {'English' if value == 'en' else 'Tiếng Việt'}"
            elif key == "mode":
                self._set_mode(value)
                label = value.replace("_", " ").title()
            elif key == "section":
                self._set_section(value)
                label = f"Section · {value.title()}"
            elif key == "profile":
                self._set_profile(value)
                label = f"Profile · {value.title()}"
            elif key == "provider":
                self.candidate["provider"].update({"kind": value, "auth_mode": value})
                label = f"Provider · {'Codex' if value == 'codex' else 'LM Studio'}"
            elif key == "provider_detail":
                kind = self.candidate["provider"]["kind"]
                self.query_one("#error", Static).update(self._label("Đang kết nối…", "Connecting…"))
                if kind == "lmstudio":
                    base_url = value.strip()
                    if not base_url.startswith(("http://", "https://")):
                        raise ValueError(self._label("URL phải bắt đầu bằng http:// hoặc https://", "URL must begin with http:// or https://"))
                    self.candidate["provider"].update({"lmstudio_base_url": base_url, "base_url": base_url})
                    try:
                        models = await asyncio.to_thread(lmstudio_models, from_settings(self.candidate))
                        self.model_options = [(item, item, ()) for item in models]
                    except Exception:
                        self.model_options = []
                else:
                    self.selection.codex_auth = value
                    await self._prepare_codex(value)
                label = self._label("Xác thực · sẵn sàng", "Authentication · ready")
            elif key == "model":
                if value == "__custom__":
                    self.steps.insert(self.step + 1, "custom_model")
                    label = self._label("Model · tùy chỉnh", "Model · custom")
                else:
                    self.candidate["provider"]["model"] = value
                    label = f"Model · {value or 'default'}"
            elif key == "custom_model":
                if not value.strip():
                    raise ValueError("Model ID cannot be empty")
                self.candidate["provider"]["model"] = value.strip()
                label = f"Model · {value.strip()}"
            elif key in {"gmail_enabled", "telegram_enabled"}:
                service = "gmail" if key.startswith("gmail") else "telegram"
                enabled = value == "yes"
                self.candidate[service]["enabled"] = enabled
                extra = (["gmail_account", "gmail_password"] if service == "gmail" else ["telegram_chats", "telegram_token"]) if enabled else []
                self.steps = self.steps[: self.step + 1] + extra + ["confirm"]
                label = f"{service.title()} · {'on' if enabled else 'off'}"
            elif key == "gmail_account":
                account = value.strip()
                if not _email(account):
                    raise ValueError(self._label("Địa chỉ Gmail không hợp lệ", "Invalid Gmail address"))
                previous = str(self.original.get("gmail", {}).get("account", "")).casefold()
                self.candidate["gmail"]["account"] = account
                self.selection.gmail_reset_uid = not self.gmail_was_enabled or previous != account.casefold() or (not self.candidate["gmail"].get("process_after_uids") and self.candidate["gmail"].get("process_after_uid") is None)
                label = f"Gmail · {account}"
            elif key == "poll":
                if not value.isdigit() or int(value) < 10:
                    raise ValueError(self._label("Polling phải là số từ 10 trở lên", "Polling must be a number of at least 10"))
                self.candidate["worker"]["poll_seconds"] = int(value)
                label = f"Polling · {value}s"
            elif key == "gmail_password":
                if value and len("".join(value.split())) != 16:
                    raise ValueError(self._label("App Password phải có đúng 16 ký tự", "App Password must contain exactly 16 characters"))
                self.selection.gmail_password = value
                self.selection.gmail_auth = "replace" if value else "existing"
                label = self._label("Gmail App Password · đã cấu hình", "Gmail App Password · configured")
            elif key == "telegram_chats":
                chats = _csv(value)
                if not chats or not all(re.fullmatch(r"-?\d+", item) for item in chats):
                    raise ValueError(self._label("Chat ID phải là số nguyên", "Chat IDs must be integers"))
                self.candidate["director"]["telegram_chat_ids"] = chats
                label = f"Telegram · {', '.join(chats)}"
            elif key == "telegram_token":
                self.selection.telegram_token = value.strip()
                self.selection.telegram_auth = "replace" if value.strip() else "existing"
                label = self._label("Telegram token · đã cấu hình", "Telegram token · configured")
            elif key == "confirm":
                self.candidate["configured"] = True
                self.query_one("#error", Static).update(self._label("Đang kiểm tra kết nối…", "Validating connections…"))
                statuses = await preflight_selection(self.selection)
                failed = next((row for row in statuses if row[1] == "FAIL"), None)
                if failed:
                    target = "provider_detail" if failed[0] == "Provider" else "gmail_password" if failed[0] == "Gmail" else "telegram_token"
                    self.step = self.steps.index(target) if target in self.steps else max(0, len(self.steps) - 2)
                    await self._render_step()
                    self.query_one("#error", Static).update(f"{failed[0]}: {failed[2]}")
                    return
                self.selection.validated = True
                self.history.append(self._label("✓ Cấu hình hợp lệ", "✓ Configuration validated"))
                self.query_one("#history", Static).update("\n".join(self.history[-6:]))
                self.query_one("#question", Static).update(self._label("Sẵn sàng lưu TaxSentry.", "TaxSentry is ready to save."))
                await self.query_one("#content", Vertical).remove_children()
                self.call_after_refresh(self.exit, self.selection)
                return
        except Exception as exc:
            self.snapshots.pop()
            self.query_one("#error", Static).update(str(exc))
            return
        self._finish_step(label)
        await self._render_step()

    async def _prepare_codex(self, mode: str) -> None:
        client = CodexAppServerProvider()
        try:
            account = await client.account()
            if mode != "existing":
                result = await client.start_login(device_code=False)
                url = str(result.get("authUrl") or result.get("verificationUrl") or "")
                if not url:
                    raise RuntimeError("Codex returned no login URL")
                self.query_one("#error", Static).update(f"Open: {url}" + (f" · Code: {result.get('userCode')}" if result.get("userCode") else ""))
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
                await client.wait_login(str(result.get("loginId") or ""))
                account = await client.account(refresh=True)
                self.selection.codex_auth = "existing"
            if not account.get("account") and account.get("requiresOpenaiAuth", True):
                raise RuntimeError(self._label("Không tìm thấy phiên Codex", "No Codex session found"))
            self.model_options = await client.models()
        finally:
            await client.close()

    async def action_back(self) -> None:
        if self.snapshots:
            self.step, self.steps, self.candidate, self.selection, self.history, self.model_options = self.snapshots.pop()
            self.selection.config = self.candidate
            await self._render_step()

    def action_cancel(self) -> None:
        self.exit(None)


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
            result = await client.start_login(device_code=False)
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
                [("retry", "Thử lại\nRetry"), ("cancel", "Hủy\nCancel")],
                "retry",
            )
            if action == "cancel":
                raise Cancelled


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
        values.extend([("browser", "Đăng nhập bằng trình duyệt\nBrowser OAuth"), ("cancel", "Hủy\nCancel")])
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
    gmail_was_enabled = bool(candidate.get("gmail", {}).get("enabled", True))
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
        previous_account = str(gmail.get("account", "")).casefold()
        gmail["account"] = ui.text("Gmail", "Tài khoản nhận báo cáo / Report inbox", str(gmail.get("account", "")), _email, "Nhập địa chỉ email hợp lệ / Enter a valid email")
        selection.gmail_reset_uid = not gmail_was_enabled or previous_account != gmail["account"].casefold() or (not gmail.get("process_after_uids") and gmail.get("process_after_uid") is None)
        current_poll = int(candidate["worker"].get("poll_seconds", 30))
        poll = ui.choose("Polling", "Chu kỳ quét Gmail / Gmail polling interval", [(30, "30 giây — khuyên dùng\n30 seconds — recommended"), (60, "60 giây\n60 seconds"), (300, "5 phút\n5 minutes"), (0, "Tùy chỉnh\nCustom")], current_poll if current_poll in {30, 60, 300} else 0)
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


def run_setup_wizard(config: dict[str, Any], console: Console | None, ui: WizardUI | None = None) -> SetupSelection | None:
    if ui is None:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("`taxsentry setup` requires an interactive terminal.")
        return SetupWizardApp(config).run(inline=True, inline_no_clear=True)
    try:
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
            await client.login(device_code=False, challenge=challenge)
        return "connected"
    finally:
        await client.close()


async def _telegram_auth(token: str) -> str:
    from telegram import Bot

    async with Bot(token) as bot:
        identity = await bot.get_me()
        return f"@{identity.username}" if getattr(identity, "username", None) else str(identity.id)


async def preflight_selection(selection: SetupSelection) -> list[tuple[str, str, str]]:
    statuses: list[tuple[str, str, str]] = []
    config = selection.config
    try:
        if config["provider"]["kind"] == "codex":
            client = CodexAppServerProvider(model=config["provider"].get("model", ""))
            try:
                state = await client.account(refresh=True)
                if not state.get("account") and state.get("requiresOpenaiAuth", True):
                    raise RuntimeError("No Codex credentials found")
                detail = "connected"
            finally:
                await client.close()
        else:
            models = await asyncio.to_thread(lmstudio_models, from_settings(config))
            detail = f"connected ({len(models)} models)"
        statuses.append(("Provider", "OK", detail))
    except Exception as exc:
        statuses.append(("Provider", "FAIL", str(exc)))

    if config["gmail"]["enabled"]:
        try:
            gmail = GmailClient(config)
            await asyncio.to_thread(gmail.authenticate, app_password=selection.gmail_password, store=False)
            if selection.gmail_reset_uid:
                latest = gmail.latest_uids if hasattr(gmail, "latest_uids") else lambda: {"INBOX": gmail.latest_uid()}
                config["gmail"]["process_after_uids"] = await asyncio.to_thread(latest)
                config["gmail"]["process_after_uid"] = None
            statuses.append(("Gmail", "OK", config["gmail"]["account"]))
        except Exception as exc:
            statuses.append(("Gmail", "FAIL", str(exc)))
    else:
        statuses.append(("Gmail", "SKIP", "disabled"))

    if config["telegram"]["enabled"]:
        try:
            token = selection.telegram_token if selection.telegram_auth == "replace" else get_secret("telegram:bot-token")
            detail = await _telegram_auth(token)
            statuses.append(("Telegram", "OK", detail))
        except Exception as exc:
            statuses.append(("Telegram", "FAIL", str(exc)))
    else:
        statuses.append(("Telegram", "SKIP", "disabled"))
    return statuses


def commit_selection(selection: SetupSelection) -> None:
    config = selection.config
    if config["gmail"]["enabled"] and selection.gmail_password:
        account = config["gmail"]["account"]
        set_secret(f"gmail-app-password:{account}", "".join(selection.gmail_password.split()))
    if config["telegram"]["enabled"] and selection.telegram_auth == "replace":
        set_secret("telegram:bot-token", selection.telegram_token)
    config["configured"] = True
    save_config(config)


def authenticate_selection(selection: SetupSelection, console: Console) -> int:
    statuses = (
        [("Provider", "OK", "validated"), ("Gmail", "OK" if selection.config["gmail"]["enabled"] else "SKIP", selection.config["gmail"].get("account") or "disabled"), ("Telegram", "OK" if selection.config["telegram"]["enabled"] else "SKIP", "validated" if selection.config["telegram"]["enabled"] else "disabled")]
        if selection.validated
        else asyncio.run(preflight_selection(selection))
    )
    failed = any(status == "FAIL" for _, status, _ in statuses)
    if not failed:
        try:
            commit_selection(selection)
        except Exception as exc:
            statuses.append(("Save", "FAIL", str(exc)))
            failed = True

    en = selection.config.get("ui", {}).get("language") == "en"
    table = Table("Service" if en else "Dịch vụ", "Status" if en else "Trạng thái", "Detail" if en else "Chi tiết", title="Setup result" if en else "Kết quả cấu hình")
    for row in statuses:
        table.add_row(*row)
    console.print(table)
    console.print("Next: run `taxsentry doctor`, then `taxsentry`." if en else "Tiếp theo: chạy `taxsentry doctor`, sau đó `taxsentry`.")
    return int(failed)
