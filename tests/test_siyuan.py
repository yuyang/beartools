"""思源笔记命令测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from beartools.cli import app
from beartools.siyuan import NotebookInfo, SiyuanError

runner = CliRunner()


@dataclass
class _FakeSiyuanConfig:
    """测试用思源配置。"""

    default_note: str = ""
    notebook: str = ""
    path: str = ""


@dataclass
class _FakeConfig:
    """测试用配置对象。"""

    siyuan: _FakeSiyuanConfig


class _FakeSiyuanHandler:
    """测试用思源处理器。"""

    def __init__(self) -> None:
        self.export_note_ids: list[str] = []
        self.upload_calls: list[tuple[str, str, str]] = []
        self.notebooks_error: SiyuanError | None = None

    async def list_notebooks(self) -> list[NotebookInfo]:
        """返回固定笔记本列表。"""

        if self.notebooks_error is not None:
            raise self.notebooks_error
        return [
            {"id": "nb-1", "name": "工作", "icon": "📘", "closed": False, "sort": 1},
            {"id": "nb-2", "name": "归档", "icon": "📦", "closed": True, "sort": 2},
        ]

    async def export_md(self, note_id: str) -> str:
        """记录导出参数并返回 Markdown。"""

        self.export_note_ids.append(note_id)
        return "# 测试文档\n"

    async def upload_md(self, md_path: str, notebook: str, path: str) -> str:
        """记录上传参数并返回文档 ID。"""

        self.upload_calls.append((md_path, notebook, path))
        return "doc-123"


@pytest.fixture
def fake_handler(monkeypatch: pytest.MonkeyPatch) -> _FakeSiyuanHandler:
    """替换命令层全局思源处理器。"""

    from beartools.commands.siyuan import command

    handler = _FakeSiyuanHandler()
    monkeypatch.setattr(command, "_handler", handler)
    return handler


def _patch_config(monkeypatch: pytest.MonkeyPatch, siyuan_config: _FakeSiyuanConfig) -> None:
    """替换命令层配置读取。"""

    from beartools.commands.siyuan import command

    monkeypatch.setattr(command, "get_config", lambda: _FakeConfig(siyuan=siyuan_config))


def test_siyuan_help_registers_commands() -> None:
    result = runner.invoke(app, ["siyuan", "--help"])

    assert result.exit_code == 0
    assert "ls-notebooks" in result.stdout
    assert "export-md" in result.stdout
    assert "upload-md" in result.stdout


def test_ls_notebooks_prints_notebook_fields(fake_handler: _FakeSiyuanHandler) -> None:
    del fake_handler

    result = runner.invoke(app, ["siyuan", "ls-notebooks"])

    assert result.exit_code == 0
    assert "工作" in result.stdout
    assert "nb-1" in result.stdout
    assert "归档" in result.stdout
    assert "nb-2" in result.stdout
    assert "🔒" in result.stdout


def test_ls_notebooks_connection_error_prints_hint(fake_handler: _FakeSiyuanHandler) -> None:
    fake_handler.notebooks_error = SiyuanError("连接思源笔记失败: refused")

    result = runner.invoke(app, ["siyuan", "ls-notebooks"])

    assert result.exit_code == 1
    assert "连接思源笔记失败" in result.stdout
    assert "请检查思源笔记是否已启动" in result.stdout


def test_export_md_uses_default_note_and_writes_output_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_handler: _FakeSiyuanHandler,
) -> None:
    _patch_config(monkeypatch, _FakeSiyuanConfig(default_note="note-from-config"))
    output_file = tmp_path / "export.md"

    result = runner.invoke(app, ["siyuan", "export-md", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.read_text(encoding="utf-8") == "# 测试文档\n"
    assert "导出成功" in result.stdout
    assert fake_handler.export_note_ids == ["note-from-config"]


def test_export_md_output_write_error_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_handler: _FakeSiyuanHandler,
) -> None:
    _patch_config(monkeypatch, _FakeSiyuanConfig(default_note="note-from-config"))
    output_dir = tmp_path / "dir.md"
    output_dir.mkdir()

    result = runner.invoke(app, ["siyuan", "export-md", "--output", str(output_dir)])

    assert result.exit_code == 1
    assert "写入文件失败" in result.stdout
    assert fake_handler.export_note_ids == ["note-from-config"]


def test_upload_md_uses_config_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_handler: _FakeSiyuanHandler,
) -> None:
    _patch_config(monkeypatch, _FakeSiyuanConfig(notebook="nb-from-config", path="/目标路径"))
    md_file = tmp_path / "input.md"
    md_file.write_text("content", encoding="utf-8")

    result = runner.invoke(app, ["siyuan", "upload-md", str(md_file)])

    assert result.exit_code == 0
    assert "文档 ID: doc-123" in result.stdout
    assert fake_handler.upload_calls == [(str(md_file), "nb-from-config", "/目标路径")]


@pytest.mark.parametrize(
    ("siyuan_config", "expected_message"),
    [
        (_FakeSiyuanConfig(path="/目标路径"), "未指定笔记本 ID"),
        (_FakeSiyuanConfig(notebook="nb-from-config"), "未指定目标路径"),
    ],
)
def test_upload_md_requires_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_handler: _FakeSiyuanHandler,
    siyuan_config: _FakeSiyuanConfig,
    expected_message: str,
) -> None:
    _patch_config(monkeypatch, siyuan_config)
    md_file = tmp_path / "input.md"
    md_file.write_text("content", encoding="utf-8")

    result = runner.invoke(app, ["siyuan", "upload-md", str(md_file)])

    assert result.exit_code == 1
    assert expected_message in result.stdout
    assert fake_handler.upload_calls == []
