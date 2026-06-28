import services.agent.tools.calculator  # noqa: F401  (registers the tool)
from services.agent.planner import ReactAgent


class FakeOllama:
    """Scripted stand-in for OllamaClient.stream_chat.

    Streams each scripted response character-by-character through ``on_token``
    (like Ollama's streaming /api/chat) and returns the full text.
    """

    def __init__(self, responses):
        self.responses = responses
        self.i = 0

    async def stream_chat(self, model, messages, on_token=None, **kw):
        text = self.responses[self.i]
        self.i += 1
        if on_token:
            for ch in text:
                on_token(ch)
        return text


async def test_tool_call_then_final_answer():
    fake = FakeOllama([
        '```tool\n{"tool": "calculator", "args": {"expression": "2 + 2"}}\n```',
        "The answer is 4.",
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


async def test_bare_json_tool_call():
    fake = FakeOllama([
        '{"tool": "calculator", "args": {"expression": "3*3"}}',
        "It is 9.",
    ])
    agent = ReactAgent(client=fake, model="x")
    events = []
    result = await agent.run(messages=[{"role": "user", "content": "3*3?"}], on_event=events.append)
    assert result == "It is 9."
    assert any(e["type"] == "tool_result" and "9" in e["result"] for e in events)


async def test_direct_answer_no_tools():
    fake = FakeOllama(["Hello!"])
    agent = ReactAgent(client=fake, model="x")
    events = []
    result = await agent.run(messages=[{"role": "user", "content": "hi"}], on_event=events.append)
    assert result == "Hello!"
    assert any(e["type"] == "token" for e in events)  # content streamed as tokens
    assert any(e["type"] == "message_complete" for e in events)
