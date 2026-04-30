"""账单状态映射配置。"""

from __future__ import annotations

from pathlib import Path
import re
from typing import cast

import yaml

from .models import BillNormalizedStatus, BillStatusMappingConfig, BillStatusPatternRule

DEFAULT_STATUS_MAPPING_PATH = Path(__file__).resolve().parents[3] / "config" / "bill_status_mapping.yaml"


def load_status_mapping(config_path: Path | None = None) -> BillStatusMappingConfig:
    """加载账单状态映射配置。"""

    path = config_path or DEFAULT_STATUS_MAPPING_PATH
    with path.open(encoding="utf-8") as file:
        loaded: object = yaml.safe_load(file)
    raw: object = loaded if loaded is not None else {}
    if not isinstance(raw, dict):
        raise RuntimeError(f"状态映射配置格式错误: {path}")
    exact_raw: object = raw.get("exact", {})
    patterns_raw: object = raw.get("patterns", [])
    if not isinstance(exact_raw, dict):
        raise RuntimeError(f"状态映射 exact 配置格式错误: {path}")
    if not isinstance(patterns_raw, list):
        raise RuntimeError(f"状态映射 patterns 配置格式错误: {path}")

    exact = {str(key): _normalize_status(str(value)) for key, value in exact_raw.items()}
    patterns: list[BillStatusPatternRule] = []
    for item in patterns_raw:
        if not isinstance(item, dict):
            raise RuntimeError(f"状态映射 pattern 项格式错误: {path}")
        pattern_value = item.get("pattern")
        normalized_value = item.get("normalized_status")
        if not isinstance(pattern_value, str) or not isinstance(normalized_value, str):
            raise RuntimeError(f"状态映射 pattern 字段缺失: {path}")
        patterns.append(
            BillStatusPatternRule(
                pattern=pattern_value,
                normalized_status=_normalize_status(normalized_value),
            )
        )
    return BillStatusMappingConfig(exact=exact, patterns=patterns)


def resolve_normalized_status(raw_status: str, config: BillStatusMappingConfig) -> BillNormalizedStatus | None:
    """将原始状态解析为标准状态。"""

    if raw_status in config.exact:
        return config.exact[raw_status]
    for rule in config.patterns:
        if re.search(rule.pattern, raw_status):
            return rule.normalized_status
    return None


def append_exact_mapping(config_path: Path, raw_status: str, normalized_status: BillNormalizedStatus) -> None:
    """追加精确状态映射。"""

    config = load_status_mapping(config_path)
    existing = config.exact.get(raw_status)
    if existing is not None and existing != normalized_status:
        raise RuntimeError(f"状态 {raw_status} 已存在映射 {existing}，不能覆盖为 {normalized_status}")
    config.exact[raw_status] = normalized_status
    payload = {
        "exact": dict(sorted(config.exact.items())),
        "patterns": [
            {
                "pattern": rule.pattern,
                "normalized_status": rule.normalized_status,
            }
            for rule in config.patterns
        ],
    }
    with config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)


def _normalize_status(value: str) -> BillNormalizedStatus:
    if value not in {"NORMAL_SUCCESS", "REFUND", "PART_REFUND"}:
        raise RuntimeError(f"非法标准状态: {value}")
    return cast(BillNormalizedStatus, value)
