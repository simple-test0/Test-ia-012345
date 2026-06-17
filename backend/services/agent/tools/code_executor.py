import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from core.config import settings
from services.agent.tool_registry import register_tool


def _build_preexec(max_memory_mb: int, cpu_seconds: int):
    """Return a preexec_fn applying memory/CPU/file-size limits (POSIX only)."""
    try:
        import resource
    except ImportError:
        return None

    def _limit():
        mem_bytes = max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass
        try:
            # Hard CPU cap (defends against busy loops that ignore the wall timeout).
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        except (ValueError, OSError):
            pass
        try:
            # Cap output files at 50MB to prevent disk-fill.
            fsize = 50 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        except (ValueError, OSError):
            pass

    return _limit


@register_tool(
    name="code_executor",
    description="Execute a Python code snippet and return its stdout output. Useful for data processing, calculations, or testing logic.",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {"type": "integer", "description": "Execution timeout in seconds", "default": 15},
        },
        "required": ["code"],
    },
)
def code_executor(code: str, timeout: int = None) -> str:
    if not settings.enable_code_executor:
        return (
            "Code execution is disabled. It runs arbitrary Python without a full "
            "sandbox. To enable it, set ENABLE_CODE_EXECUTOR=true (preferably in an "
            "isolated container)."
        )

    # Clamp the timeout to the configured maximum.
    max_timeout = settings.code_executor_timeout
    if timeout is None:
        timeout = max_timeout
    timeout = max(1, min(int(timeout), max_timeout))

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(textwrap.dedent(code))
        tmp_path = f.name

    try:
        result = subprocess.run(
            # -I: isolated mode (ignore env vars / user site-packages).
            [sys.executable, "-I", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_build_preexec(settings.code_executor_max_memory_mb, timeout + 2),
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
