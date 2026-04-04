"""beartools.llm 模块 - 最小可导入骨架

此模块当前仅提供轻量导出，避免在导入时产生副作用。
后续将补充运行时和工厂实现。
"""

from __future__ import annotations

from .factory import LLFactory  # re-export 类型占位
from .runtime import LLRuntime  # re-export 类型占位

__all__ = ["LLRuntime", "LLFactory"]
