"""PART_REFUND 场景的计算工具。"""

from __future__ import annotations

import ast
from decimal import Decimal


def calculate_expression(expression: str) -> str:
    """执行安全的四则运算表达式。"""

    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("非法表达式") from exc
    value = _eval_node(node.body)
    return format(value.quantize(Decimal("0.01")), "f")


def _eval_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise ValueError("非法表达式")
