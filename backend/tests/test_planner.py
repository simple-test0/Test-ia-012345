import services.agent.tools.calculator  # noqa: F401  (registers the tool)
from services.agent.planner import ReactAgent


class FakeOllama:
    """Returns scripted assistant messages, like Ollama's /api/chat."""

    def __init__(self, responses):
        self.responses = responses
        self.i = 0

    async def chat(self, model, messages, tools=None, **kw):
        msg = self.responses[self.i]
        self.i += 1
        return msg


async def test_native_tool_call_then_final_answer():
    fake = FakeOllama([
        {"content": "", "tool_calls": [
            {"function": {"name": "calculator", "arguments": {"expression": "2 + 2"}}}
        ]},
        {"content": "The answer is 4.", "tool_calls": []},
    ])
    agent = ReactAgent(client=fake, model="x")

    events = []
    result = await agent.run(messages=[{"role": "user", "content": "2+2?"}], on_event=events.append)

    assert result == "The answer is 4."
    kinds = [e["type"] for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds and "message_complete" in kinds
    # tool_result carries the calculator output
    res = next(e for e in events if e["type"] == "tool_result")
    assert "4" in res["result"]
    # call/result share a correlating id
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["id"] == res["id"]


async def test_legacy_block_fallback():
    fake = FakeOllama([
        {"content": "```tool\n{\"tool\": \"calculator\", \"args\": {\"expression\": \"3*3\"}}\n```",
         "tool_calls": []},
        {"content": "It is 9.", "tool_calls": []},
    ])
    agent = ReactAgent(client=fake, model="x")
    events = []
    result = await agent.run(messages=[{"role": "user", "content": "3*3?"}], on_event=events.append)
    assert result == "It is 9."
    assert any(e["type"] == "tool_result" and "9" in e["result"] for e in events)


async def test_direct_answer_no_tools():
    fake = FakeOllama([{"content": "Hello!", "tool_calls": []}])
    agent = ReactAgent(client=fake, model="x")
    events = []
    result = await agent.run(messages=[{"role": "user", "content": "hi"}], on_event=events.append)
    assert result == "Hello!"
    assert [e["type"] for e in events if e["type"] == "token"]  # content emitted as a token
