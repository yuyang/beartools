"""clear 命令测试用例"""

import os
from pathlib import Path
import tempfile

from typer.testing import CliRunner

from beartools.cli import app


class TestClearCommand:
    """clear 命令测试类"""

    def setup_method(self) -> None:
        """每个测试前创建临时目录并切换工作目录"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir.name)

        # 创建data目录结构
        self.data_dir = Path.cwd() / "data"
        self.download_dir = self.data_dir / "download"
        self.format_dir = self.data_dir / "format"
        self.bill_dir = self.data_dir / "bill"

        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.format_dir.mkdir(parents=True, exist_ok=True)
        self.bill_dir.mkdir(parents=True, exist_ok=True)

        self.runner = CliRunner()

    def teardown_method(self) -> None:
        """每个测试后清理，恢复原工作目录"""
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_clear_deletes_files_but_preserves_directories(self) -> None:
        """测试clear命令删除文件但保留目录本身"""
        # 创建测试文件
        (self.download_dir / "file1.txt").write_text("test1")
        (self.download_dir / "file2.txt").write_text("test2")
        (self.format_dir / "file3.md").write_text("test3")
        (self.format_dir / "subdir").mkdir()
        (self.format_dir / "subdir" / "file4.txt").write_text("test4")
        (self.bill_dir / "file5.csv").write_text("test5")

        # 执行命令
        result = self.runner.invoke(app, ["clear"])

        # 验证命令执行成功
        assert result.exit_code == 0
        assert "共删除 5 个文件" in result.output

        # 验证目录仍然存在
        assert self.download_dir.exists()
        assert self.format_dir.exists()
        assert self.bill_dir.exists()
        assert (self.format_dir / "subdir").exists()

        # 验证文件已被删除
        assert not (self.download_dir / "file1.txt").exists()
        assert not (self.download_dir / "file2.txt").exists()
        assert not (self.format_dir / "file3.md").exists()
        assert not (self.format_dir / "subdir" / "file4.txt").exists()
        assert not (self.bill_dir / "file5.csv").exists()

    def test_clear_handles_nonexistent_directories_gracefully(self) -> None:
        """测试clear命令优雅处理不存在的目录"""
        # 删除目录
        self.download_dir.rmdir()
        self.format_dir.rmdir()
        self.bill_dir.rmdir()

        # 执行命令
        result = self.runner.invoke(app, ["clear"])

        # 验证命令执行成功，没有错误
        assert result.exit_code == 0
        assert "共删除 0 个文件" in result.output

    def test_clear_counts_deleted_files_accurately(self) -> None:
        """测试clear命令准确统计删除的文件数量"""
        # 创建不同数量的文件
        for i in range(5):
            (self.download_dir / f"download_{i}.txt").write_text(f"test {i}")
        for i in range(3):
            (self.format_dir / f"format_{i}.txt").write_text(f"test {i}")
        for i in range(2):
            (self.bill_dir / f"bill_{i}.csv").write_text(f"test {i}")

        # 执行命令
        result = self.runner.invoke(app, ["clear"])

        # 验证统计正确
        assert result.exit_code == 0
        assert "共删除 10 个文件" in result.output

    def test_clear_with_no_files_returns_zero(self) -> None:
        """测试目录中没有文件时返回0删除"""
        # 执行命令
        result = self.runner.invoke(app, ["clear"])

        # 验证输出正确
        assert result.exit_code == 0
        assert "共删除 0 个文件" in result.output

    def test_clear_handles_hidden_files(self) -> None:
        """测试clear命令也会删除隐藏文件"""
        # 创建隐藏文件
        (self.download_dir / ".gitignore").write_text("*.log")
        (self.format_dir / ".DS_Store").write_text("")
        (self.bill_dir / ".bill-cache").write_text("")

        # 执行命令
        result = self.runner.invoke(app, ["clear"])

        # 验证隐藏文件也被删除
        assert result.exit_code == 0
        assert "共删除 3 个文件" in result.output
        assert not (self.download_dir / ".gitignore").exists()
        assert not (self.format_dir / ".DS_Store").exists()
        assert not (self.bill_dir / ".bill-cache").exists()
