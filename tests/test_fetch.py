"""Fetch 模块测试用例"""

import asyncio
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from beartools.cli import app
from beartools.fetch import (
    FetchResult,
    WeixinFetchHandler,
    XDotComFetchHandler,
    fetch_handler_factory,
    fetch_url,
    url_to_id,
)

runner = CliRunner()


def create_mock_process(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> Mock:
    """创建模拟子进程对象。"""

    async def communicate() -> tuple[bytes, bytes]:
        return stdout, stderr

    proc = Mock()
    proc.communicate = Mock(side_effect=communicate)
    proc.kill = Mock()
    proc.returncode = returncode
    return proc


def create_mock_file_context() -> tuple[Mock, Mock]:
    """创建模拟 aiofiles 上下文管理器。"""

    async def write(content: str) -> None:
        del content

    async def aenter() -> Mock:
        return file_handle

    async def aexit(exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb

    write_mock = Mock(side_effect=write)
    file_handle = Mock()
    file_handle.write = write_mock

    context_manager = Mock()
    context_manager.__aenter__ = Mock(side_effect=aenter)
    context_manager.__aexit__ = Mock(side_effect=aexit)
    return context_manager, write_mock


def run_awaitable(awaitable: object) -> object:
    """同步执行 awaitable，供命令测试替换 asyncio.run 使用。"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(awaitable)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def raise_timeout_and_close(awaitable: object, timeout: float) -> object:
    """模拟 wait_for 超时，同时关闭传入协程避免未等待告警。"""
    del timeout
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()
    raise TimeoutError()


class TestUrlToId:
    """url_to_id 函数测试"""

    def test_url_to_id_returns_consistent_hash(self) -> None:
        """测试相同 URL 生成一致的 ID，长度为16位"""
        url = "https://example.com/test"
        id1 = url_to_id(url)
        id2 = url_to_id(url)

        assert id1 == id2
        assert len(id1) == 16
        assert all(c in "0123456789abcdef" for c in id1)

    def test_url_to_id_different_urls_different_ids(self) -> None:
        """测试不同 URL 生成不同的 ID"""
        id1 = url_to_id("https://example.com/test1")
        id2 = url_to_id("https://example.com/test2")

        assert id1 != id2


class TestFetchUrl:
    """fetch_url 函数测试"""

    @pytest.mark.asyncio
    async def test_unsupported_domain_raises_value_error(self) -> None:
        """测试不支持的域名抛出 ValueError"""
        with pytest.raises(ValueError, match="暂不支持域名"):
            await fetch_url("https://example.com/test")

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_supported_domain_without_opencli_raises_file_not_found(self, mock_create_proc: Mock) -> None:
        """测试支持的域名但没有 opencli 抛出 FileNotFoundError"""
        # 模拟 opencli 不存在
        mock_create_proc.side_effect = FileNotFoundError()

        with pytest.raises(FileNotFoundError, match="未找到 opencli 命令"):
            await fetch_url("https://weixin.qq.com/test")

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_weixin_fetch_success_with_mock(self, mock_create_proc: Mock) -> None:
        """测试微信文章抓取成功（mock opencli 调用）"""
        # 模拟 asyncio.create_subprocess_exec 返回
        mock_proc = create_mock_process(stdout=b"Download success completed\n")
        mock_create_proc.return_value = mock_proc

        # 模拟 embed_images
        async def embed_images_stub(source_dir: str, output_dir: str) -> list[object]:
            del source_dir, output_dir
            return []

        mock_embed = Mock(side_effect=embed_images_stub)
        with patch("beartools.fetch.embed_images", new=mock_embed):
            # 执行抓取
            result = await fetch_url("https://weixin.qq.com/s/abc123")

            # 验证结果
            assert isinstance(result, FetchResult)
            assert "success" in result.output.lower()
            assert len(result.embed_results) == 0

            # 验证 opencli 调用参数正确
            mock_create_proc.assert_called_once()
            call_args = mock_create_proc.call_args
            assert call_args[0][0] == "opencli"
            assert call_args[0][1] == "weixin"
            assert call_args[0][2] == "download"
            assert call_args[0][3] == "--url"
            assert call_args[0][4] == "https://weixin.qq.com/s/abc123"

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_weixin_fetch_failure_raises_runtime_error(self, mock_create_proc: Mock) -> None:
        """测试微信文章抓取失败抛出 RuntimeError 并输出错误信息"""
        mock_proc = create_mock_process(stderr=b"error: download failed\n")
        mock_create_proc.return_value = mock_proc

        with pytest.raises(RuntimeError) as exc_info:
            await fetch_url("https://weixin.qq.com/s/failure")

        assert "error: download failed" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch("asyncio.wait_for")
    @patch("asyncio.create_subprocess_exec")
    async def test_weixin_fetch_timeout_raises_timeout_error(self, mock_create_proc: Mock, mock_wait_for: Mock) -> None:
        """测试微信文章抓取超时抛出 TimeoutError"""
        mock_proc = create_mock_process()
        mock_create_proc.return_value = mock_proc

        # asyncio.wait_for 超时抛出 TimeoutError
        mock_wait_for.side_effect = raise_timeout_and_close

        with pytest.raises(TimeoutError, match="命令执行超时"):
            await fetch_url("https://weixin.qq.com/s/timeout")

        # 验证超时后会杀死进程
        mock_proc.kill.assert_called_once()

    def test_fetch_result_dataclass_structure(self) -> None:
        """测试 FetchResult 数据类结构正确"""
        result = FetchResult(
            original_url="https://weixin.qq.com/test",
            target_dir=Path("/tmp/test"),
            markdown_dir=Path("/tmp/test-md"),
            output="test output",
            embed_results=[],
        )

        assert result.original_url == "https://weixin.qq.com/test"
        assert result.target_dir == Path("/tmp/test")
        assert result.markdown_dir == Path("/tmp/test-md")
        assert result.output == "test output"
        assert result.embed_results == []


class TestWechatFunctionRegression:
    """微信功能回归测试 - 验证核心接口行为保持一致"""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_weixin_url_without_scheme_adds_https(self, mock_create_proc: Mock) -> None:
        """测试不带协议的微信 URL 会自动添加 https"""
        # 模拟 opencli 不存在，这样就能验证到域名检查已经通过，不会抛出 ValueError
        mock_create_proc.side_effect = FileNotFoundError()

        with pytest.raises(FileNotFoundError, match="未找到 opencli 命令"):
            await fetch_url("weixin.qq.com/s/abc123")

        # 如果走到这里说明域名检查通过（没有抛出 ValueError），测试通过


class TestWeixinFetchHandler:
    """WeixinFetchHandler 处理器测试类

    验证微信抓取逻辑正确迁移到策略类，行为保持一致
    """

    def test_initialization_sets_properties_correctly(self) -> None:
        """测试初始化正确设置所有属性"""
        url = "https://mp.weixin.qq.com/s/test123"
        handler = WeixinFetchHandler(url)

        assert handler.url == url
        assert handler.url_id == url_to_id(url)
        assert len(handler.url_id) == 16
        assert "download" in str(handler.download_dir)
        assert "format" in str(handler.format_dir)
        assert handler.url_id in str(handler.download_dir)
        assert handler.url_id in str(handler.format_dir)

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_success_mock(self, mock_create_proc: Mock) -> None:
        """测试成功抓取场景，所有逻辑一致"""
        mock_proc = create_mock_process(stdout=b"Download success completed\n")
        mock_create_proc.return_value = mock_proc

        async def embed_images_stub(source_dir: str, output_dir: str) -> list[object]:
            del source_dir, output_dir
            return []

        mock_embed = Mock(side_effect=embed_images_stub)
        with patch("beartools.fetch.embed_images", new=mock_embed):
            handler = WeixinFetchHandler("https://mp.weixin.qq.com/s/test123")
            result = await handler.fetch()

            assert isinstance(result, FetchResult)
            assert result.original_url == "https://mp.weixin.qq.com/s/test123"
            assert "success" in result.output.lower()
            assert len(result.embed_results) == 0
            assert result.target_dir == handler.download_dir
            assert result.markdown_dir == handler.format_dir

            # 验证调用参数正确
            mock_create_proc.assert_called_once()
            call_args = mock_create_proc.call_args
            assert call_args[0][0] == "opencli"
            assert call_args[0][1] == "weixin"
            assert call_args[0][2] == "download"
            assert call_args[0][3] == "--url"
            assert call_args[0][4] == "https://mp.weixin.qq.com/s/test123"
            # cwd 是关键字参数，在 call_args[1] 中
            assert call_args[1]["cwd"] == str(handler.download_dir)
            mock_embed.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_failure_no_success_raises_runtime_error(self, mock_create_proc: Mock) -> None:
        """测试下载失败场景，输出无 success 时抛出 RuntimeError"""
        mock_proc = create_mock_process(stderr=b"download failed\n")
        mock_create_proc.return_value = mock_proc

        handler = WeixinFetchHandler("https://mp.weixin.qq.com/s/failure")

        async def embed_images_stub(source_dir: str, output_dir: str) -> list[object]:
            del source_dir, output_dir
            return []

        mock_embed = Mock(side_effect=embed_images_stub)
        with patch("beartools.fetch.embed_images", new=mock_embed):
            with pytest.raises(RuntimeError) as exc_info:
                await handler.fetch()
            assert "download failed" in str(exc_info.value)
            mock_embed.assert_not_called()

    @pytest.mark.asyncio
    @patch("asyncio.wait_for")
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_timeout_kills_process(self, mock_create_proc: Mock, mock_wait_for: Mock) -> None:
        """测试命令超时会杀死进程并抛出 TimeoutError"""
        mock_proc = create_mock_process()
        mock_create_proc.return_value = mock_proc

        # asyncio.wait_for 超时抛出 TimeoutError
        mock_wait_for.side_effect = raise_timeout_and_close

        handler = WeixinFetchHandler("https://mp.weixin.qq.com/s/timeout")

        async def embed_images_stub(source_dir: str, output_dir: str) -> list[object]:
            del source_dir, output_dir
            return []

        with patch("beartools.fetch.embed_images", new=Mock(side_effect=embed_images_stub)):
            with pytest.raises(TimeoutError, match="命令执行超时"):
                await handler.fetch()

    @pytest.mark.asyncio
    async def test_opencli_not_found_raises_file_not_found(self) -> None:
        """测试 opencli 不存在时抛出 FileNotFoundError"""
        handler = WeixinFetchHandler("https://mp.weixin.qq.com/s/test")
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            with pytest.raises(FileNotFoundError, match="未找到 opencli 命令"):
                await handler.fetch()


class TestFetchHandlerFactory:
    """fetch_handler_factory 工厂函数测试"""

    def test_weixin_domain_returns_weixin_handler(self) -> None:
        """测试微信域名返回 WeixinFetchHandler 实例"""
        handler = fetch_handler_factory("https://weixin.qq.com/s/test")
        assert isinstance(handler, WeixinFetchHandler)

        handler = fetch_handler_factory("https://mp.weixin.qq.com/s/test")
        assert isinstance(handler, WeixinFetchHandler)

        handler = fetch_handler_factory("weixin.qq.com/s/test")
        assert isinstance(handler, WeixinFetchHandler)

    def test_x_domain_returns_xdotcom_handler(self) -> None:
        """测试x.com和twitter.com域名返回XDotComFetchHandler实例"""
        handler = fetch_handler_factory("https://x.com/user/status/123456")
        assert isinstance(handler, XDotComFetchHandler)

        handler = fetch_handler_factory("https://twitter.com/user/status/123456")
        assert isinstance(handler, XDotComFetchHandler)

        handler = fetch_handler_factory("x.com/user/status/123456")
        assert isinstance(handler, XDotComFetchHandler)

        handler = fetch_handler_factory("twitter.com/user/status/123456")
        assert isinstance(handler, XDotComFetchHandler)

    def test_unsupported_domain_raises_value_error(self) -> None:
        """测试不支持的域名抛出ValueError"""
        with pytest.raises(ValueError, match="暂不支持域名"):
            fetch_handler_factory("https://example.com/test")


class TestXDotComFetchHandler:
    """XDotComFetchHandler 处理器测试类"""

    def test_initialization_sets_properties_correctly(self) -> None:
        """测试初始化正确设置所有属性"""
        url = "https://x.com/user/status/123456"
        handler = XDotComFetchHandler(url)

        assert handler.url == url
        assert handler.url_id == url_to_id(url)
        assert len(handler.url_id) == 16
        assert "download" in str(handler.download_dir)
        assert "format" in str(handler.format_dir)
        assert handler.url_id in str(handler.download_dir)
        assert handler.url_id in str(handler.format_dir)

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_success_writes_correct_file(self, mock_create_proc: Mock) -> None:
        """测试成功抓取场景，文件写入正确"""
        mock_stdout = b"Test tweet content\nThis is a test tweet\n"
        mock_proc = create_mock_process(stdout=mock_stdout)
        mock_create_proc.return_value = mock_proc

        # 模拟aiofiles.open
        mock_file_context, write_mock = create_mock_file_context()
        with patch("aiofiles.open", return_value=mock_file_context) as mock_open:
            handler = XDotComFetchHandler("https://x.com/user/status/123456")
            result = await handler.fetch()

            # 验证结果
            assert isinstance(result, FetchResult)
            assert result.original_url == "https://x.com/user/status/123456"
            assert result.output == mock_stdout.decode()
            assert result.embed_results == []  # 不需要嵌入图片
            assert result.target_dir == handler.download_dir
            assert result.markdown_dir == handler.format_dir

            # 验证opencli调用参数正确
            mock_create_proc.assert_called_once()
            call_args = mock_create_proc.call_args
            assert call_args[0][0] == "opencli"
            assert call_args[0][1] == "twitter"
            assert call_args[0][2] == "article"
            assert call_args[0][3] == "-f"
            assert call_args[0][4] == "md"
            assert call_args[0][5] == "https://x.com/user/status/123456"
            assert call_args[1]["cwd"] == str(handler.download_dir)

            # 验证文件写入正确
            mock_open.assert_called_once()
            open_args = mock_open.call_args
            assert open_args[0][0] == handler.format_dir / "Test tweet.md"  # 前10字符是"Test tweet"
            assert open_args[0][1] == "w"
            assert open_args[1]["encoding"] == "utf-8"

            # 验证写入内容正确
            expected_content = "https://x.com/user/status/123456\n\nTest tweet content\nThis is a test tweet\n"
            write_mock.assert_called_once_with(expected_content)

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_failure_writes_error_file_and_raises_runtime_error(self, mock_create_proc: Mock) -> None:
        """测试抓取失败场景，写入错误文件后抛出 RuntimeError"""
        mock_stderr = b"error: tweet not found\n"
        mock_proc = create_mock_process(stderr=mock_stderr, returncode=1)
        mock_create_proc.return_value = mock_proc

        # 模拟aiofiles.open
        mock_file_context, write_mock = create_mock_file_context()
        with patch("aiofiles.open", return_value=mock_file_context) as mock_open:
            handler = XDotComFetchHandler("https://x.com/user/status/invalid")
            with pytest.raises(RuntimeError, match="error: tweet not found"):
                await handler.fetch()

            # 验证文件写入正确
            mock_open.assert_called_once()
            open_args = mock_open.call_args
            assert open_args[0][0] == handler.format_dir / f"{handler.url_id}.md"

            expected_content = "https://x.com/user/status/invalid\n\n下载失败：error: tweet not found"
            write_mock.assert_called_once_with(expected_content)

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_url_x_failure_writes_error_file_and_raises_runtime_error(self, mock_create_proc: Mock) -> None:
        """测试 fetch_url 调用时 X 失败仍落盘并走 RuntimeError 路径"""
        mock_stderr = b"error: tweet not found\n"
        mock_proc = create_mock_process(stderr=mock_stderr, returncode=1)
        mock_create_proc.return_value = mock_proc

        mock_file_context, write_mock = create_mock_file_context()
        with patch("aiofiles.open", return_value=mock_file_context):
            with pytest.raises(RuntimeError, match="error: tweet not found"):
                await fetch_url("https://x.com/user/status/invalid")

        expected_content = "https://x.com/user/status/invalid\n\n下载失败：error: tweet not found"
        write_mock.assert_called_once_with(expected_content)

    @pytest.mark.asyncio
    @patch("asyncio.wait_for")
    @patch("asyncio.create_subprocess_exec")
    async def test_fetch_timeout_kills_process(self, mock_create_proc: Mock, mock_wait_for: Mock) -> None:
        """测试命令超时会杀死进程并抛出TimeoutError"""
        mock_proc = create_mock_process()
        mock_create_proc.return_value = mock_proc

        # 模拟超时
        mock_wait_for.side_effect = raise_timeout_and_close

        handler = XDotComFetchHandler("https://x.com/user/status/123456")
        with pytest.raises(TimeoutError, match="命令执行超时"):
            await handler.fetch()

        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_opencli_not_found_raises_file_not_found(self) -> None:
        """测试opencli不存在时抛出FileNotFoundError"""
        handler = XDotComFetchHandler("https://x.com/user/status/123456")
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            with pytest.raises(FileNotFoundError, match="未找到 opencli 命令"):
                await handler.fetch()


class TestFetchCommand:
    """fetch 命令测试"""

    def test_command_success_prints_markdown_output_directory(self) -> None:
        """测试命令成功时输出真实 Markdown 目录"""
        result = FetchResult(
            original_url="https://x.com/user/status/123456",
            target_dir=Path("/tmp/download"),
            markdown_dir=Path("/tmp/format"),
            output="tweet markdown",
            embed_results=[],
        )

        async def fake_fetch_url(url: str) -> FetchResult:
            assert url == "https://x.com/user/status/123456"
            return result

        with patch("beartools.commands.fetch.command.fetch_url", new=fake_fetch_url):
            with patch("beartools.commands.fetch.command.asyncio.run", side_effect=run_awaitable):
                cli_result = runner.invoke(app, ["fetch", "https://x.com/user/status/123456"])

        assert cli_result.exit_code == 0
        assert "Markdown 输出目录: /tmp/format" in cli_result.stdout
        assert "下载目录: /tmp/download" in cli_result.stdout
        assert "✅ 下载成功" in cli_result.stdout

    def test_command_runtime_error_shows_failure_message(self) -> None:
        """测试命令遇到 RuntimeError 时显示失败信息"""

        async def fake_fetch_url(url: str) -> FetchResult:
            assert url == "https://x.com/user/status/invalid"
            raise RuntimeError("error: tweet not found")

        with patch("beartools.commands.fetch.command.fetch_url", new=fake_fetch_url):
            with patch("beartools.commands.fetch.command.asyncio.run", side_effect=run_awaitable):
                cli_result = runner.invoke(app, ["fetch", "https://x.com/user/status/invalid"])

        assert cli_result.exit_code == 1
        assert "error: tweet not found" in cli_result.stdout
        assert "❌ 下载失败" in cli_result.stdout
