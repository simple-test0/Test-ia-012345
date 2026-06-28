import subprocess
import sys
import tempfile
from pathlib import Path

from services.agent.tool_registry import register_tool


@register_tool(
    name="code_executor",
    description="Execute a Python code snippet and return its stdout output. Useful for data processing, calculations, or testing logic.",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {
                "type": "integer",
                "description": "Execution timeout in seconds (default 15)",
                "default": 15,
            },
        },
        "required": ["code"],
    },
)
def code_executor(code: str, timeout: int = 15) -> str:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code {result.returncode}]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Execution timed out after {timeout}s"
    except Exception as exc:
        return f"Execution error: {exc}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
