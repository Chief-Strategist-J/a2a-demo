"""Calculator tool — safe AST-based arithmetic evaluator (no eval/exec)."""
from __future__ import annotations

import ast
import operator

from shared.tools.registry import register

_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.Mod:  operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str) -> float:
    tree = ast.parse(expr.strip(), mode="eval")

    def _ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.operand))
        raise ValueError(f"Unsupported expression node: {ast.dump(node)}")

    return _ev(tree)


@register(
    name="calculator",
    description=(
        "Evaluate an arithmetic expression. "
        "Use whenever the user asks for a calculation. "
        "Supports +, -, *, /, **, %, and parentheses."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The expression to evaluate, e.g. '(10 + 5) * 3 / 2'",
            }
        },
        "required": ["expression"],
    },
)
def calculator(expression: str) -> str:
    try:
        result = _safe_eval(expression)
        # Show as int when the result is a whole number
        display = int(result) if result == int(result) else result
        return f"{expression} = {display}"
    except Exception as exc:
        return f"Error evaluating '{expression}': {exc}"
