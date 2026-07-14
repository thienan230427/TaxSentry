import asyncio
import json

from taxsentry.events import EventType
from taxsentry.providers import CodexAppServerProvider


class _Reader:
    def __init__(self, messages):
        self.lines = [json.dumps(message).encode() + b"\n" for message in messages]

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""


class _Writer:
    def write(self, data):
        self.data = data

    async def drain(self):
        pass


class _Process:
    def __init__(self, messages):
        self.stdout, self.stdin, self.returncode = _Reader(messages), _Writer(), None


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


def test_codex_account_and_model_catalog_contract():
    provider = CodexAppServerProvider()
    provider.process = _Process([
        {"id": 1, "result": {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}},
        {"id": 2, "result": {"data": [{"id": "gpt-tax", "displayName": "GPT Tax", "hidden": False}, {"id": "hidden", "hidden": True}]}},
    ])

    async def inspect():
        return await provider.account(), await provider.models()

    account, models = asyncio.run(inspect())
    assert account["account"]["type"] == "chatgpt"
    assert models == [("gpt-tax", "GPT Tax")]
