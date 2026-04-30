from __future__ import annotations

from pathlib import Path

import pytest


def test_status_mapping_prefers_exact_over_pattern(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text(
        """
exact:
  已退款特殊: REFUND
patterns:
  - pattern: "^已退款"
    normalized_status: PART_REFUND
""".strip(),
        encoding="utf-8",
    )

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("已退款特殊", mapping) == "REFUND"


def test_status_mapping_matches_pattern(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text(
        """
exact: {}
patterns:
  - pattern: "^已退款"
    normalized_status: PART_REFUND
""".strip(),
        encoding="utf-8",
    )

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("已退款￥1.00", mapping) == "PART_REFUND"


def test_status_mapping_accepts_ignore_status(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text(
        """
exact:
  已存入零钱: IGNORE
patterns:
  - pattern: "^已全额退款$"
    normalized_status: IGNORE
""".strip(),
        encoding="utf-8",
    )

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("已存入零钱", mapping) == "IGNORE"
    assert resolve_normalized_status("已全额退款", mapping) == "IGNORE"


def test_status_mapping_returns_none_for_unknown_value(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text("exact: {}\npatterns: []\n", encoding="utf-8")

    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("等待确认收货", mapping) is None


def test_append_exact_mapping_persists_new_status(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import append_exact_mapping, load_status_mapping, resolve_normalized_status

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text("exact: {}\npatterns: []\n", encoding="utf-8")

    append_exact_mapping(config_path, "等待确认收货", "NORMAL_SUCCESS")
    mapping = load_status_mapping(config_path)

    assert resolve_normalized_status("等待确认收货", mapping) == "NORMAL_SUCCESS"


def test_append_exact_mapping_rejects_duplicate_with_different_status(tmp_path: Path) -> None:
    from beartools.bill.status_mapping import append_exact_mapping

    config_path = tmp_path / "bill_status_mapping.yaml"
    config_path.write_text("exact:\n  交易成功: NORMAL_SUCCESS\npatterns: []\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="交易成功"):
        append_exact_mapping(config_path, "交易成功", "REFUND")


def test_calculate_expression_returns_decimal_string() -> None:
    from beartools.bill.calculate_tool import calculate_expression

    assert calculate_expression("10.50 - 2.30") == "8.20"


def test_calculate_expression_rejects_unsafe_syntax() -> None:
    from beartools.bill.calculate_tool import calculate_expression

    with pytest.raises(ValueError, match="非法表达式"):
        calculate_expression("__import__('os').system('pwd')")
