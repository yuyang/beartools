from __future__ import annotations

import pytest


def test_calculate_expression_returns_decimal_string() -> None:
    from beartools.bill.calculate_tool import calculate_expression

    assert calculate_expression("10.50 - 2.30") == "8.20"


def test_calculate_expression_rejects_unsafe_syntax() -> None:
    from beartools.bill.calculate_tool import calculate_expression

    with pytest.raises(ValueError, match="非法表达式"):
        calculate_expression("__import__('os').system('pwd')")
