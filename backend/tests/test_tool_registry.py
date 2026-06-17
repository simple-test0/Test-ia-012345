from services.agent import tool_registry as tr


def test_register_and_get():
    @tr.register_tool(name="t_sync", description="d", parameters={"type": "object", "properties": {}})
    def _t(x: int = 1):
        return x + 1

    assert tr.get_tool("t_sync") is not None
    assert any(t.name == "t_sync" for t in tr.list_tools())


async def test_execute_sync_tool():
    @tr.register_tool(name="t_add", description="d", parameters={"type": "object", "properties": {}})
    def _add(a: int, b: int):
        return a + b

    assert await tr.execute_tool("t_add", {"a": 2, "b": 3}) == 5


async def test_execute_async_tool():
    @tr.register_tool(name="t_aio", description="d", parameters={"type": "object", "properties": {}})
    async def _aio(v: int):
        return v * 10

    assert await tr.execute_tool("t_aio", {"v": 4}) == 40


async def test_execute_unknown_tool():
    out = await tr.execute_tool("does_not_exist", {})
    assert "not found" in str(out).lower()


async def test_execute_tool_error_is_caught():
    @tr.register_tool(name="t_boom", description="d", parameters={"type": "object", "properties": {}})
    def _boom():
        raise RuntimeError("boom")

    out = await tr.execute_tool("t_boom", {})
    assert "boom" in str(out)


def test_ollama_schema_shape():
    schema = tr.tools_as_ollama_schema()
    assert all(s["type"] == "function" and "function" in s for s in schema)
