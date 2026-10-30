"""Tests for the robustness/comfort improvements (no torch required)."""
import asyncio

import pytest

import services.agent.tools.calculator  # noqa: F401  (registers the tool)
from core.config import Settings
from services.agent.planner import ReactAgent, _maybe_tool_block
from services.labs.dataset_manager import safe_filename

# ── Agent ─────────────────────────────────────────────────────────────────────


class StreamingFake:
    """Fake Ollama that streams content through on_token like the real client."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def chat(self, model, messages, tools=None, on_token=None, **kw):
        self.calls.append(messages)
        msg = self.responses[len(self.calls) - 1]
        if on_token and msg.get("content"):
            for i in range(0, len(msg["content"]), 3):
                await on_token(msg["content"][i:i + 3])
        return msg


async def test_streaming_tokens_are_forwarded_in_order():
    fake = StreamingFake([{"content": "Hello there, friend!", "tool_calls": []}])
    agent = ReactAgent(client=fake, model="x")
    events = []
    result = await agent.run([{"role": "user", "content": "hi"}], on_event=events.append)
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert result == tokens == "Hello there, friend!"
    assert events[-1]["type"] == "message_complete"


async def test_streamed_legacy_tool_block_is_not_shown():
    block = '```tool\n{"tool": "calculator", "args": {"expression": "6*7"}}\n```'
    fake = StreamingFake([
        {"content": block, "tool_calls": []},
        {"content": "42", "tool_calls": []},
    ])
    agent = ReactAgent(client=fake, model="x")
    events = []
    result = await agent.run([{"role": "user", "content": "6*7"}], on_event=events.append)
    assert result == "42"
    shown = "".join(e["content"] for e in events if e["type"] == "token")
    assert "```tool" not in shown
    assert any(e["type"] == "tool_result" and "42" in e["result"] for e in events)


async def test_async_event_callback_and_system_prompt():
    fake = StreamingFake([{"content": "ok", "tool_calls": []}])
    agent = ReactAgent(client=fake, model="x", system_prompt="Answer in French.")
    seen = []

    async def on_event(e):
        await asyncio.sleep(0)
        seen.append(e["type"])

    await agent.run([{"role": "user", "content": "hi"}], on_event=on_event)
    assert "message_complete" in seen
    system = fake.calls[0][0]
    assert system["role"] == "system" and "Answer in French." in system["content"]


def test_maybe_tool_block():
    assert _maybe_tool_block("")
    assert _maybe_tool_block("``")
    assert _maybe_tool_block('{"tool": "x"')
    assert not _maybe_tool_block("Hello")
    assert not _maybe_tool_block("Sure, the answer")


# ── Config / security ─────────────────────────────────────────────────────────


def test_paths_derive_from_data_dir(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert s.images_dir == tmp_path / "images"
    assert s.db_path == tmp_path / "db" / "app.db"


def test_cors_extra_origins():
    s = Settings(cors_origins="http://192.168.1.5:5173, https://studio.local/")
    assert "http://192.168.1.5:5173" in s.cors_origin_list
    assert "https://studio.local" in s.cors_origin_list
    assert "http://localhost:5173" in s.cors_origin_list


async def test_query_token_dependency(monkeypatch):
    from fastapi import HTTPException

    from core import security
    from core.config import settings

    monkeypatch.setattr(settings, "api_token", "secret")
    await security.require_api_token_or_query(x_api_token="", token="secret")
    await security.require_api_token_or_query(x_api_token="secret", token="")
    with pytest.raises(HTTPException):
        await security.require_api_token_or_query(x_api_token="", token="nope")


# ── Files / uploads ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\win.ini", "win.ini"),
    ("a b/c?.png", "c_.png"),
    ("", "file"),
    ("...", "file"),
])
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


async def test_save_uploads_streams_and_limits(tmp_path, monkeypatch):
    from core.config import settings
    from services.labs.dataset_manager import save_uploads

    class FakeUpload:
        def __init__(self, name, data):
            self.filename, self._data = name, data

        async def read(self, n=-1):
            chunk, self._data = self._data[:n], self._data[n:]
            return chunk

    count, total = await save_uploads(
        tmp_path, [FakeUpload("../x.txt", b"abc"), FakeUpload("x.txt", b"de")]
    )
    assert (count, total) == (2, 5)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.txt", "x_1.txt"]

    monkeypatch.setattr(settings, "max_upload_mb", 0)
    with pytest.raises(ValueError):
        await save_uploads(tmp_path / "big", [FakeUpload("y", b"z")])


def test_image_name_validation_and_urls():
    from services.image_gen.images import image_urls, is_valid_image_name

    good = "0f8fad5b-d9cb-469f-a165-70867728950e_0.png"
    assert is_valid_image_name(good)
    assert not is_valid_image_name("../app.db")
    assert not is_valid_image_name("x.png")
    urls = image_urls([f"/data/images/{good}", "/etc/passwd"], thumbnail=True)
    assert urls == [f"/api/v1/image/files/{good}?thumb=1"]


# ── Generation queue ──────────────────────────────────────────────────────────


async def test_worker_queue_positions_and_cancel():
    from services.image_gen.worker import GenerationWorker

    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    w = GenerationWorker(q)
    assert w.enqueue({"id": "a"}) == 1
    assert w.enqueue({"id": "b"}) == 2
    with pytest.raises(asyncio.QueueFull):
        w.enqueue({"id": "c"})
    assert w.status("b") == {"type": "queued", "job_id": "b", "position": 2}
    assert w.cancel("a") == "queued"
    assert w.position("b") == 1
    assert w.cancel("zzz") is None


def test_generate_request_normalizes_input():
    from api.routes.image_gen import GenerateRequest

    req = GenerateRequest(prompt="  a cat  ", width=513, height=1000, sampler="??", lora="  ")
    assert req.prompt == "a cat"
    assert req.width == 512 and req.height == 1000
    assert req.sampler == "DPM++ 2M"
    assert req.lora is None
    with pytest.raises(ValueError):
        GenerateRequest(prompt="   ")


# ── Restart recovery ──────────────────────────────────────────────────────────


async def test_recover_interrupted_work(monkeypatch, db_session):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import core.database as database
    from models.image_job import ImageJob
    from models.training_run import TrainingRun

    db_session.add_all([
        ImageJob(id="j1", status="running", model_id="sd15", prompt="p"),
        ImageJob(id="j2", status="completed", model_id="sd15", prompt="p"),
        TrainingRun(id="r1", name="r", status="paused", architecture="cnn"),
    ])
    await db_session.commit()

    maker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    await database.recover_interrupted_work()

    async with maker() as s:
        jobs = {j.id: j.status for j in (await s.execute(select(ImageJob))).scalars()}
        run = (await s.execute(select(TrainingRun))).scalar_one()
    assert jobs == {"j1": "failed", "j2": "completed"}
    assert run.status == "failed" and "restart" in run.error_message


async def test_run_detached_returns_and_raises():
    import threading

    from core.tasks import run_detached

    def work(x):
        assert threading.current_thread().daemon  # never blocks shutdown
        return x * 2

    assert await run_detached(work, 21) == 42

    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await run_detached(boom)
