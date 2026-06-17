import ast
import math
import operator

from services.agent.tool_registry import register_tool

# Allowed binary / unary operators.
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Allowed names: math functions/constants + a few safe builtins.
_NAMES = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_NAMES.update({"abs": abs, "round": round, "min": min, "max": max})

# Guard against trivial CPU/memory DoS like (9**9)**9.
_MAX_POW_EXP = 1000


def _eval(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("only numeric constants are allowed")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError("operator not allowed")
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and right > _MAX_POW_EXP:
            raise ValueError("exponent too large")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("unary operator not allowed")
        return op(_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _NAMES:
            raise ValueError("function not allowed")
        func = _NAMES[node.func.id]
        if not callable(func):
            raise ValueError("not callable")
        return func(*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name):
        if node.id in _NAMES and not callable(_NAMES[node.id]):
            return _NAMES[node.id]
        raise ValueError(f"unknown name: {node.id}")
    raise ValueError("unsupported expression")


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
    try:
        tree = ast.parse(expression, mode="eval")
        return str(_eval(tree.body))
    except Exception as exc:
        return f"Calculation error: {exc}"
