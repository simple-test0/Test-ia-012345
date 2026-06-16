import math

from services.agent.tool_registry import register_tool


@register_tool(
    name="calculator",
    description="Evaluate a mathematical expression. Supports basic arithmetic, math functions (sin, cos, sqrt, log, etc.).",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Math expression to evaluate, e.g. '2 ** 10 + sqrt(144)'"},
        },
        "required": ["expression"],
    },
)
def calculator(expression: str) -> str:
    allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed["abs"] = abs
    allowed["round"] = round
    allowed["pow"] = pow
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)  # noqa: S307
        return str(result)
    except Exception as exc:
        return f"Calculation error: {exc}"
