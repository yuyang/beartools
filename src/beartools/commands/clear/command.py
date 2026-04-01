"""Clear 清除临时文件命令主模块

删除 ./data/download/ 和 ./data/format/ 目录下的所有文件，保留目录结构。
"""

from pathlib import Path

from rich.console import Console
from rich.text import Text

from beartools.logger import get_logger

# 初始化控制台和日志
console = Console()
logger = get_logger(__name__)

# 目录路径定义（基于项目根目录，此文件向上4级）
_DATA_ROOT = Path(__file__).parents[4] / "data"
_TARGET_DIRECTORIES = [
    _DATA_ROOT / "download",
    _DATA_ROOT / "format",
]


def _clear_directory_contents(dir_path: Path) -> int:
    """递归删除目录下的所有文件，保留目录结构

    Args:
        dir_path: 要清理的目录路径

    Returns:
        int: 成功删除的文件数量
    """
    deleted_count = 0

    if not dir_path.exists() or not dir_path.is_dir():
        return 0

    for item in dir_path.iterdir():
        if item.is_file():
            try:
                item.unlink()
                deleted_count += 1
                logger.debug("删除文件: %s", item)
            except Exception as e:
                logger.warning("删除文件失败: %s, 错误: %s", item, str(e))
        elif item.is_dir():
            # 递归处理子目录
            deleted_count += _clear_directory_contents(item)

    return deleted_count


def clear_command() -> None:
    """Clear 命令入口

    删除 ./data/download/ 和 ./data/format/ 目录下的所有文件，
    保留目录结构，并输出删除的文件总数。
    """
    total_deleted = 0

    console.print("🧹 正在清理临时文件...\n", style="bold blue")

    for dir_path in _TARGET_DIRECTORIES:
        count = _clear_directory_contents(dir_path)
        total_deleted += count
        if count > 0:
            console.print(
                Text.assemble(
                    Text("✅ ", style="green"), Text(f"已清理 {dir_path.name}/ 目录下的 {count} 个文件", style="green")
                )
            )
        else:
            console.print(
                Text.assemble(Text("ℹ️  ", style="blue"), Text(f"{dir_path.name}/ 目录没有需要清理的文件", style="blue"))
            )

    console.print()
    summary_text = Text.assemble(
        Text("🏁 清理完成: ", style="bold blue"), Text(f"共删除 {total_deleted} 个文件", style="bold cyan")
    )
    console.print(summary_text)

    logger.info("清理完成: 共删除 %d 个文件", total_deleted)
