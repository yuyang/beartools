"""检查类工具命令。"""

from __future__ import annotations

import typer

from beartools.commands.prompt.command import check as prompt_check_command
from beartools.commands.prompt.command import eval_command as prompt_eval_command

check_app = typer.Typer(help="检查工具", add_completion=False)

check_app.command("prompt", help="静态检查 Prompt 资产")(prompt_check_command)
check_app.command("eval", help="运行用户指定 YAML 中的 Prompt golden eval")(prompt_eval_command)
