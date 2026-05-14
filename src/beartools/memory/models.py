"""记忆系统数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandMemoryInput:
    """单次 CLI 命令记忆输入。"""

    command: str
    help_text: str
    stdout: str
    stderr: str
    exit_code: int
    started_at: datetime
    duration_seconds: float


class CommandSummarizer(Protocol):
    """单次命令摘要器。"""

    def summarize_command(self, memory_input: CommandMemoryInput) -> str:
        """总结单次命令目的和结果。"""


class DailySummarizer(Protocol):
    """日总结摘要器。"""

    def summarize_day(self, day_content: str) -> str:
        """总结一天的命令记忆。"""
