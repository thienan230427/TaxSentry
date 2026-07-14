import asyncio
import json

from taxsentry.events import EventType
from taxsentry.providers import CodexAppServerProvider, _codex_command


class _Reader:
    def __init__(self, messages):
        self.lines = [json.dumps(message).encode() + b"\n" for message in messages]

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class _Writer:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.data = data
        self.writes.append(data)

    async def drain(self):
        pass


class _Process:
    def __init__(self, messages):
        self.stdout, self.stdin, self.returncode = _Reader(messages), _Writer(), None

    def terminate(self):
        self.returncode = 0

    async def wait(self):
        return self.returncode


def test_codex_jsonl_stream_contract():
    provider = CodexAppServerProvider()
    provider.thread_id = "thr_1"
    provider.process = _Process([
        {"id": 1, "result": {"turn": {"id": "turn_1"}}},
        {"method": "item/agentMessage/delta", "params": {"delta": "Xin chào"}},
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ])

    async def collect():
        return [event async for event in provider.stream_turn([{"role": "user", "content": "Chào"}])]

    events = asyncio.run(collect())
    assert [event.type for event in events] == [EventType.TEXT_DELTA, EventType.TURN_COMPLETED]


def test_codex_thread_uses_current_read_only_variant():
    provider = CodexAppServerProvider()
    provider.process = _Process([
        {"id": 1, "result": {"thread": {"id": "thr_1"}}},
        {"id": 2, "result": {"turn": {"id": "turn_1"}}},
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ])

    async def collect():
        return [event async for event in provider.stream_turn([{"role": "user", "content": "Chào"}])]

    asyncio.run(collect())
    request = json.loads(provider.process.stdin.writes[0])
    assert request["method"] == "thread/start" and request["params"]["sandbox"] == "read-only"


def test_codex_account_and_model_catalog_contract():
    provider = CodexAppServerProvider()
    provider.process = _Process([
        {"id": 1, "result": {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}},
        {"id": 2, "result": {"data": [{"id": "gpt-tax", "displayName": "GPT Tax", "hidden": False, "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]}, {"id": "hidden", "hidden": True}], "nextCursor": "page-2"}},
        {"id": 3, "result": {"data": [{"id": "gpt-next", "displayName": "GPT Next", "supportedReasoningEfforts": ["high"]}], "nextCursor": None}},
    ])

    async def inspect():
        return await provider.account(), await provider.models()

    account, models = asyncio.run(inspect())
    assert account["account"]["type"] == "chatgpt"
    assert models == [("gpt-tax", "GPT Tax", ("medium",)), ("gpt-next", "GPT Next", ("high",))]


def test_codex_uses_isolated_home(monkeypatch, tmp_path):
    process = _Process([{"id": 1, "result": {"codexHome": str(tmp_path / "codex")}}])
    captured = {}

    async def create(*args, **kwargs):
        captured.update(kwargs)
        return process

    monkeypatch.setattr("taxsentry.providers.APP_HOME", tmp_path)
    monkeypatch.setattr("taxsentry.providers._codex_command", lambda: "codex")
    monkeypatch.setattr("taxsentry.providers.asyncio.create_subprocess_exec", create)

    provider = CodexAppServerProvider()
    asyncio.run(provider.start())
    assert captured["env"]["CODEX_HOME"] == str(tmp_path / "codex")
    assert provider.codex_home == str(tmp_path / "codex")


def test_codex_login_cancel_uses_login_id():
    provider = CodexAppServerProvider()
    provider.process = _Process([{"id": 1, "result": {}}])
    asyncio.run(provider.cancel_login("login-123"))
    assert b'"method": "account/login/cancel"' in provider.process.stdin.data
    assert b'"loginId": "login-123"' in provider.process.stdin.data


def test_codex_finds_desktop_launcher_when_path_is_stale(monkeypatch, tmp_path):
    launcher = tmp_path / "OpenAI" / "Codex" / "bin" / "release" / "codex.exe"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("taxsentry.providers.shutil.which", lambda _: None)
    assert _codex_command() == str(launcher)
