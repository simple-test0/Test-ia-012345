---
name: add-agent-tool
description: Add a new Ollama agent tool — creates the file with @register_tool and wires the import in main.py lifespan
disable-model-invocation: false
---

# Add Agent Tool: $ARGUMENTS

## Step 1 — Create the tool file

**File**: `backend/services/agent/tools/<name>.py`

```python
from services.agent.tool_registry import register_tool


@register_tool(
    name="<name>",
    description="<one sentence — sent to Ollama on every call, keep concise>",
    parameters={
        "type": "object",
        "properties": {
            "<param>": {"type": "string", "description": "<desc>"},
        },
        "required": ["<param>"],
    },
)
async def <name>(<param>: str) -> str:  # sync or async both work
    ...
    return str(result)
```

## Step 2 — Register the import

In `backend/main.py` at line 21 (the `# CLAUDE: add new agent tools here` comment):

```python
import services.agent.tools.<name>  # noqa: F401
```

## Step 3 — Verify

```bash
make test
# or specifically:
cd backend && pytest tests/test_tool_registry.py -v
```

## Rules
- Always return `str` — the agent injects the value into LLM context
- Keep `description` short: it's token-loaded on every Ollama call
- Tools self-register on import via `_registry` in `tool_registry.py` — the import IS the registration
- No side effects unless intentional and documented
