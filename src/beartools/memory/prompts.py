"""记忆系统 Prompt 构造。"""

from __future__ import annotations

from beartools.memory.models import CommandMemoryInput
from beartools.prompt import PromptManager


def build_command_memory_prompt(memory_input: CommandMemoryInput) -> str:
    """构造单次命令记忆 prompt。"""

    return PromptManager().render(
        "cli_command_memory",
        {
            "command": memory_input.command,
            "help_text": memory_input.help_text,
            "exit_code": memory_input.exit_code,
            "duration_seconds": f"{memory_input.duration_seconds:.2f}",
            "stdout": memory_input.stdout,
            "stderr": memory_input.stderr,
        },
    )


def build_daily_summary_prompt(day_content: str) -> str:
    """构造每日总结 prompt。"""

    return PromptManager().render("cli_daily_summary", {"day_content": day_content})
