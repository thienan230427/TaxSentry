from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from openai import AsyncOpenAI, OpenAI

from . import __version__
from .config import APP_HOME, get_value
from .events import AgentEvent, EventType

CodexModel = tuple[str, str, tuple[str, ...]]


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class ProviderConfig:
    kind: str
    base_url: str
    model: str
    api_key: str = ""
    auth_mode: str = ""


def from_settings(settings: dict[str, Any]) -> ProviderConfig:
    provider = get_value(settings, "provider", {}) or {}
    kind = str(provider.get("kind", "lmstudio"))
    base_url = str(provider.get("lmstudio_base_url") or provider.get("base_url") or "http://127.0.0.1:1234/v1")
    return ProviderConfig(kind=kind, base_url=base_url, model=str(provider.get("model", "")), api_key=str(provider.get("api_key", "")), auth_mode=str(provider.get("auth_mode", kind)))


def build_client(spec: ProviderConfig) -> OpenAI:
    if spec.kind == "codex" or spec.auth_mode == "codex_oauth":
        raise ProviderError("Codex v2 uses the official app-server, not direct OAuth tokens.")
    if not spec.base_url.strip():
        raise ProviderError("LM Studio requires a base URL.")
    return OpenAI(api_key=spec.api_key or "lm-studio", base_url=spec.base_url, timeout=5, max_retries=0)


def provider_label(spec: ProviderConfig) -> str:
    return "Codex / ChatGPT" if spec.kind == "codex" else "LM Studio"


def health_check(spec: ProviderConfig) -> tuple[bool, str]:
    try:
        if spec.kind == "codex":
            command = _codex_command()
            result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10, check=False)
            return (result.returncode == 0, result.stdout.strip() or result.stderr.strip() or command)
        models = list(build_client(spec).models.list().data)
        return True, f"LM Studio reachable ({len(models)} model(s))"
    except Exception as exc:
        return False, str(exc)


def lmstudio_models(spec: ProviderConfig) -> list[str]:
    client = build_client(spec)
    try:
        return sorted({str(item.id) for item in client.models.list().data if getattr(item, "id", None)})
    finally:
        client.close()


def generate_chat(spec: ProviderConfig, messages: list[dict[str, str]], temperature: float = 0.3) -> str:
    response = build_client(spec).chat.completions.create(model=spec.model, messages=messages, temperature=temperature)
    return str(response.choices[0].message.content or "").strip()


class LMStudioProvider:
    def __init__(self, spec: ProviderConfig):
        self.spec = spec
        self.client = AsyncOpenAI(api_key=spec.api_key or "lm-studio", base_url=spec.base_url, timeout=30, max_retries=0)

    async def stream_turn(self, messages: list[dict[str, str]], *, output_schema: dict[str, Any] | None = None) -> AsyncIterator[AgentEvent]:
        del output_schema  # LM Studio compatibility varies; schema is enforced by the workflow parser.
        try:
            stream = await self.client.chat.completions.create(model=self.spec.model, messages=messages, stream=True)
            async for chunk in stream:
                text = chunk.choices[0].delta.content or ""
                if text:
                    yield AgentEvent(EventType.TEXT_DELTA, text=text)
            yield AgentEvent(EventType.TURN_COMPLETED)
        except Exception as exc:
            yield AgentEvent(EventType.ERROR, text=str(exc))

    async def close(self) -> None:
        await self.client.close()


class CodexAppServerProvider:
    """Small JSONL client; Codex owns login, refresh, history and sandboxing."""

    def __init__(self, *, cwd: Path | None = None, model: str = ""):
        self.cwd = cwd or APP_HOME
        self.model = model
        self.process: asyncio.subprocess.Process | None = None
        self.thread_id = ""
        self.codex_home = ""
        self._request_id = 0

    async def start(self) -> None:
        try:
            command = _codex_command()
            codex_home = APP_HOME / "codex"
            codex_home.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            self.process = await asyncio.create_subprocess_exec(command, "app-server", "--listen", "stdio://", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
        except (OSError, PermissionError) as exc:
            raise ProviderError("Codex CLI không chạy được. Đặt CODEX_CLI_PATH tới codex.exe hợp lệ.") from exc
        initialized = await self._request("initialize", {"clientInfo": {"name": "taxsentry", "title": "TaxSentry", "version": __version__}, "capabilities": {"experimentalApi": False}})
        self.codex_home = str(initialized.get("codexHome", ""))
        if self.codex_home and os.path.normcase(os.path.abspath(self.codex_home)) != os.path.normcase(os.path.abspath(codex_home)):
            await self.close()
            raise ProviderError(f"Codex App Server dùng sai CODEX_HOME: {self.codex_home}")
        await self._notify("initialized", {})

    async def close(self) -> None:
        process, self.process = self.process, None
        self.thread_id = ""
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def start_login(self, *, device_code: bool = False) -> dict[str, Any]:
        if not self.process:
            await self.start()
        params = {"type": "chatgptDeviceCode"} if device_code else {"type": "chatgpt", "useHostedLoginSuccessPage": True, "appBrand": "codex"}
        return await self._request("account/login/start", params)

    async def wait_login(self, login_id: str) -> None:
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            message = json.loads(line)
            if message.get("method") != "account/login/completed":
                continue
            payload = message.get("params", {})
            if payload.get("loginId") not in {None, login_id}:
                continue
            if not payload.get("success"):
                raise ProviderError(str(payload.get("error") or "Codex login failed"))
            return
        raise ProviderError("Codex app-server closed during login")

    async def cancel_login(self, login_id: str) -> None:
        if login_id:
            await self._request("account/login/cancel", {"loginId": login_id})

    async def login(self, *, device_code: bool = False, challenge=None) -> dict[str, Any]:
        result = await self.start_login(device_code=device_code)
        if challenge:
            challenge(result)
        elif result.get("authUrl"):
            webbrowser.open(result["authUrl"])
        login_id = str(result.get("loginId", ""))
        try:
            await self.wait_login(login_id)
        except asyncio.CancelledError:
            await self.cancel_login(login_id)
            raise
        return result

    async def account(self, *, refresh: bool = False) -> dict[str, Any]:
        if not self.process:
            await self.start()
        return await self._request("account/read", {"refreshToken": refresh})

    async def logout(self) -> None:
        if not self.process:
            await self.start()
        await self._request("account/logout", {})

    async def models(self) -> list[CodexModel]:
        if not self.process:
            await self.start()
        models: list[CodexModel] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            result = await self._request("model/list", params)
            for item in result.get("data", []):
                model_id = str(item.get("id") or item.get("model") or item.get("slug") or "").strip()
                if not model_id or item.get("hidden", False) or model_id in seen:
                    continue
                efforts = tuple(str(value.get("reasoningEffort") or value.get("effort") or value) if isinstance(value, dict) else str(value) for value in item.get("supportedReasoningEfforts", []) if value)
                label = str(item.get("displayName") or item.get("display_name") or model_id)
                models.append((model_id, label, efforts))
                seen.add(model_id)
            cursor = str(result.get("nextCursor") or "") or None
            if not cursor:
                break
        return models

    async def stream_turn(self, messages: list[dict[str, str]], *, output_schema: dict[str, Any] | None = None) -> AsyncIterator[AgentEvent]:
        if not self.process:
            await self.start()
        new_thread = not self.thread_id
        if not self.thread_id:
            result = await self._request("thread/start", {"cwd": str(self.cwd), "approvalPolicy": "never", "sandbox": "read-only", "serviceName": "taxsentry" , **({"model": self.model} if self.model else {})})
            self.thread_id = result["thread"]["id"]
        prompt = messages[-1]["content"]
        if new_thread and messages and messages[0].get("role") == "system":
            prompt = f"{messages[0]['content']}\n\n{prompt}"
        params: dict[str, Any] = {"threadId": self.thread_id, "input": [{"type": "text", "text": prompt}], "cwd": str(self.cwd), "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"}}
        if output_schema:
            params["outputSchema"] = output_schema
        await self._send_request("turn/start", params)
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            message = json.loads(line)
            method, payload = message.get("method", ""), message.get("params", {})
            if method == "item/agentMessage/delta":
                yield AgentEvent(EventType.TEXT_DELTA, text=str(payload.get("delta", "")))
            elif method == "item/reasoning/summaryTextDelta":
                yield AgentEvent(EventType.REASONING, text=str(payload.get("delta", "")))
            elif method == "item/started":
                item = payload.get("item", {})
                yield AgentEvent(EventType.TOOL_STARTED, name=str(item.get("type", "tool")), data=item)
            elif method == "item/completed":
                item = payload.get("item", {})
                yield AgentEvent(EventType.TOOL_COMPLETED, name=str(item.get("type", "tool")), data=item)
            elif method == "turn/completed":
                turn = payload.get("turn", {})
                if turn.get("status") == "failed":
                    yield AgentEvent(EventType.ERROR, text=str(turn.get("error", {}).get("message") or "Codex turn failed"), data=payload)
                else:
                    yield AgentEvent(EventType.TURN_COMPLETED, data=payload)
                return
            elif method in {"turn/failed", "error"}:
                yield AgentEvent(EventType.ERROR, text=str(payload.get("error") or payload))
                return
        raise ProviderError("Codex app-server closed before the turn completed.")

    async def _send_request(self, method: str, params: dict[str, Any]) -> int:
        self._request_id += 1
        await self._write({"id": self._request_id, "method": method, "params": params})
        return self._request_id

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = await self._send_request(method, params)
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            message = json.loads(line)
            if message.get("id") == request_id:
                if "error" in message:
                    raise ProviderError(str(message["error"]))
                return message.get("result", {})
        raise ProviderError("Codex app-server closed unexpectedly.")

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"method": method, "params": params})

    async def _write(self, payload: dict[str, Any]) -> None:
        assert self.process and self.process.stdin
        self.process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()


def create_provider(settings: dict[str, Any]):
    spec = from_settings(settings)
    return CodexAppServerProvider(model=spec.model) if spec.kind == "codex" else LMStudioProvider(spec)


def _codex_command() -> str:
    command = os.getenv("CODEX_CLI_PATH") or ""
    if not command and (local_app_data := os.getenv("LOCALAPPDATA")):
        launchers = sorted((Path(local_app_data) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"), key=lambda path: path.stat().st_mtime, reverse=True)
        command = str(launchers[0]) if launchers else ""
    command = command or shutil.which("codex") or ""
    if not command:
        raise ProviderError("Codex CLI not found. Install Codex or set CODEX_CLI_PATH.")
    return command
