"""beartools.llm 模块。

避免包导入阶段触发工厂初始化等副作用。
"""

from __future__ import annotations

from .runtime import LLRuntime  # re-export 类型占位

__all__ = ["LLRuntime"]
