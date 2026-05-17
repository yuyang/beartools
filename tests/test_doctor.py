from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from beartools.commands.doctor.base import CheckRegistry, CheckResult, CheckStatus
from beartools.commands.doctor.checks import llm as llm_check_module


def _load_doctor_command_module():
    return importlib.import_module("beartools.commands.doctor.command")


def _load_google_ping_module():
    return importlib.import_module("beartools.commands.doctor.checks.google_ping")


def _load_opencli_module():
    return importlib.import_module("beartools.commands.doctor.checks.opencli")


@dataclass(frozen=True, slots=True)
class _FakeRuntimeNode:
    name: str
    base_url: str
    model: str


class TestDoctorCommand:
    @pytest.mark.asyncio
    async def test_run_single_check_logs_begin_message(self, monkeypatch) -> None:
        module = _load_doctor_command_module()
        observed_before_run: dict[str, bool] = {}
        console_calls: list[tuple[object, ...]] = []
        logger_calls: list[tuple[object, ...]] = []

        class FakeConsole:
            def __init__(self) -> None:
                self.called = False

            def print(self, *args) -> None:
                self.called = True
                console_calls.append(args)

        class FakeLogger:
            def __init__(self) -> None:
                self.called = False

            def info(self, *args) -> None:
                self.called = True
                logger_calls.append(args)

        fake_console = FakeConsole()
        fake_logger = FakeLogger()

        class FakeCheck:
            async def run(self) -> CheckResult:
                observed_before_run["console"] = fake_console.called
                observed_before_run["logger"] = fake_logger.called
                return CheckResult(
                    name="llm",
                    status=CheckStatus.SUCCESS,
                    message="ok",
                    duration=0.0,
                )

        monkeypatch.setattr(CheckRegistry, "get_check", lambda name: FakeCheck())
        monkeypatch.setattr(module, "console", fake_console)
        monkeypatch.setattr(module, "logger", fake_logger)

        result = await module._run_single_check("llm")

        assert result.status == CheckStatus.SUCCESS
        assert observed_before_run == {"console": True, "logger": True}
        assert console_calls == [("begin to check llm",)]
        assert logger_calls == [("begin to check %s", "llm")]

    @pytest.mark.asyncio
    async def test_run_single_check_preserves_valid_duration(self, monkeypatch) -> None:
        module = _load_doctor_command_module()

        class FakeCheck:
            async def run(self) -> CheckResult:
                return CheckResult(
                    name="llm",
                    status=CheckStatus.SUCCESS,
                    message="ok",
                    duration=1.5,
                )

        monkeypatch.setattr(CheckRegistry, "get_check", lambda name: FakeCheck())

        result = await module._run_single_check("llm")

        assert result.duration == 1.5

    def test_print_summary_uses_overview_style(self, monkeypatch) -> None:
        module = _load_doctor_command_module()
        printed: list[object] = []

        class FakeConsole:
            def print(self, *args) -> None:
                printed.extend(args)

        monkeypatch.setattr(module, "console", FakeConsole())

        module.print_summary(success_count=2, failure_count=1, warning_count=1)

        assert len(printed) == 1
        assert str(printed[0]) == "🏁 检查总览：共 4 项 ✓ 2 成功 ✗ 1 失败 ⚠ 1 警告"


class TestGooglePingCheck:
    def test_default_targets_include_baidu(self) -> None:
        module = _load_google_ping_module()

        assert len(module.DEFAULT_TARGETS) == 6
        assert module.DEFAULT_TARGETS[-1] == "https://www.baidu.com/"

    @pytest.mark.asyncio
    async def test_run_falls_back_to_default_targets_and_threshold(self, monkeypatch) -> None:
        module = _load_google_ping_module()

        async def fake_check_target(self, session, target: str, timeout: int):
            success_labels = {"google", "youtube"}
            label = module._label_for_target(target)
            if label in success_labels:
                return module._TargetCheckResult(label, True, "成功 200")
            return module._TargetCheckResult(label, False, "连接失败")

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)
        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(
                            timeout=2,
                            targets=[],
                            success_threshold=0,
                        )
                    }
                )
            ),
        )

        result = await module.GooglePingCheck().run()

        assert result.status == module.CheckStatus.FAILURE
        assert result.message == "科学上网检查失败：2/6（阈值 3）"
        assert result.detail == "\n".join(
            [
                "汇总：成功 2，失败 4",
                "google: 成功 200",
                "youtube: 成功 200",
                "facebook: 连接失败",
                "wikipedia: 连接失败",
                "instagram: 连接失败",
                "baidu: 连接失败",
            ]
        )

    @pytest.mark.asyncio
    async def test_run_success_when_three_of_six_targets_succeed(self, monkeypatch) -> None:
        module = _load_google_ping_module()

        async def fake_check_target(self, session, target: str, timeout: int):
            mapping = {
                "https://www.google.com/generate_204": module._TargetCheckResult("google", True, "成功 204"),
                "https://www.youtube.com/": module._TargetCheckResult("youtube", True, "成功 200"),
                "https://www.facebook.com/": module._TargetCheckResult("facebook", True, "成功 200"),
                "https://www.wikipedia.org/": module._TargetCheckResult("wikipedia", False, "超时"),
                "https://www.instagram.com/": module._TargetCheckResult("instagram", False, "连接失败"),
                "https://www.baidu.com/": module._TargetCheckResult("baidu", False, "连接失败"),
            }
            return mapping[target]

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)
        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(
                            timeout=2,
                            targets=module.DEFAULT_TARGETS,
                            success_threshold=3,
                        )
                    }
                )
            ),
        )

        result = await module.GooglePingCheck().run()

        assert result.status == module.CheckStatus.SUCCESS
        assert result.message == "科学上网检查通过：3/6（阈值 3）"
        assert result.detail == "\n".join(
            [
                "汇总：成功 3，失败 3",
                "google: 成功 204",
                "youtube: 成功 200",
                "facebook: 成功 200",
                "wikipedia: 超时",
                "instagram: 连接失败",
                "baidu: 连接失败",
            ]
        )

    @pytest.mark.asyncio
    async def test_run_failure_when_only_two_of_six_targets_succeed(self, monkeypatch) -> None:
        module = _load_google_ping_module()

        async def fake_check_target(self, session, target: str, timeout: int):
            mapping = {
                "https://www.google.com/generate_204": module._TargetCheckResult("google", True, "成功 204"),
                "https://www.youtube.com/": module._TargetCheckResult("youtube", True, "成功 200"),
                "https://www.facebook.com/": module._TargetCheckResult("facebook", False, "DNS 解析失败"),
                "https://www.wikipedia.org/": module._TargetCheckResult("wikipedia", False, "超时"),
                "https://www.instagram.com/": module._TargetCheckResult("instagram", False, "连接失败"),
                "https://www.baidu.com/": module._TargetCheckResult("baidu", False, "连接失败"),
            }
            return mapping[target]

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)
        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(
                            timeout=2,
                            targets=module.DEFAULT_TARGETS,
                            success_threshold=3,
                        )
                    }
                )
            ),
        )

        result = await module.GooglePingCheck().run()

        assert result.status == module.CheckStatus.FAILURE
        assert result.message == "科学上网检查失败：2/6（阈值 3）"
        assert result.detail == "\n".join(
            [
                "汇总：成功 2，失败 4",
                "google: 成功 204",
                "youtube: 成功 200",
                "facebook: DNS 解析失败",
                "wikipedia: 超时",
                "instagram: 连接失败",
                "baidu: 连接失败",
            ]
        )

    def test_label_for_target_returns_expected_short_name(self) -> None:
        module = _load_google_ping_module()

        assert module._label_for_target("https://www.google.com/generate_204") == "google"
        assert module._label_for_target("https://www.youtube.com/") == "youtube"
        assert module._label_for_target("https://www.facebook.com/") == "facebook"
        assert module._label_for_target("https://www.wikipedia.org/") == "wikipedia"
        assert module._label_for_target("https://www.instagram.com/") == "instagram"
        assert module._label_for_target("https://www.baidu.com/") == "baidu"

    @pytest.mark.asyncio
    async def test_check_target_classifies_timeout(self, monkeypatch) -> None:
        module = _load_google_ping_module()
        check = module.GooglePingCheck()

        async def raise_timeout(*args, **kwargs):
            raise TimeoutError()

        class FakeRequestContext:
            def __init__(self, func):
                self._func = func

            async def __aenter__(self):
                return await self._func()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self, func):
                self._func = func

            def get(self, *args, **kwargs):
                assert kwargs == {"ssl": True}
                return FakeRequestContext(self._func)

        timeout_result = await check._check_target(FakeSession(raise_timeout), "https://www.youtube.com/", 2)

        assert timeout_result == module._TargetCheckResult(label="youtube", ok=False, summary="超时")

    @pytest.mark.asyncio
    async def test_check_target_classifies_dns_error(self, monkeypatch) -> None:
        module = _load_google_ping_module()
        check = module.GooglePingCheck()

        class FakeDNSError(Exception):
            pass

        monkeypatch.setattr(module.aiohttp, "ClientConnectorDNSError", FakeDNSError)

        async def raise_dns(*args, **kwargs):
            raise FakeDNSError()

        class FakeRequestContext:
            def __init__(self, func):
                self._func = func

            async def __aenter__(self):
                return await self._func()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self, func):
                self._func = func

            def get(self, *args, **kwargs):
                assert kwargs == {"ssl": True}
                return FakeRequestContext(self._func)

        dns_result = await check._check_target(FakeSession(raise_dns), "https://www.facebook.com/", 2)

        assert dns_result == module._TargetCheckResult(label="facebook", ok=False, summary="DNS 解析失败")

    @pytest.mark.asyncio
    async def test_check_target_classifies_connection_error(self, monkeypatch) -> None:
        module = _load_google_ping_module()
        check = module.GooglePingCheck()

        class FakeConnectorError(Exception):
            pass

        monkeypatch.setattr(module.aiohttp, "ClientConnectorError", FakeConnectorError)

        async def raise_connection(*args, **kwargs):
            raise FakeConnectorError()

        class FakeRequestContext:
            def __init__(self, func):
                self._func = func

            async def __aenter__(self):
                return await self._func()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self, func):
                self._func = func

            def get(self, *args, **kwargs):
                assert kwargs == {"ssl": True}
                return FakeRequestContext(self._func)

        connection_result = await check._check_target(FakeSession(raise_connection), "https://www.wikipedia.org/", 2)

        assert connection_result == module._TargetCheckResult(label="wikipedia", ok=False, summary="连接失败")

    @pytest.mark.asyncio
    async def test_run_preserves_target_order_and_uses_concurrent_requests(self, monkeypatch) -> None:
        module = _load_google_ping_module()
        started: list[str] = []
        release = asyncio.Event()
        targets = [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
        ]

        async def fake_check_target(self, session, target: str, timeout: int):
            started.append(target)
            await release.wait()
            return module._TargetCheckResult(module._label_for_target(target), True, "成功 200")

        monkeypatch.setattr(module.GooglePingCheck, "_check_target", fake_check_target)
        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(
                    checks={
                        "google_ping": SimpleNamespace(
                            timeout=2,
                            targets=targets,
                            success_threshold=2,
                            fail_on_error=True,
                        )
                    }
                )
            ),
        )

        task = asyncio.create_task(module.GooglePingCheck().run())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert started == targets
        release.set()
        result = await task

        assert result.detail == "汇总：成功 3，失败 0\ngoogle: 成功 200\nyoutube: 成功 200\nfacebook: 成功 200"


class TestOpenCliSummary:
    def test_summary_returns_original_when_short(self) -> None:
        module = _load_opencli_module()
        output = "\n".join(f"line {i}" for i in range(1, 31))

        assert module._summarize_output(output) == output

    def test_summary_truncates_long_output(self) -> None:
        module = _load_opencli_module()
        output = "\n".join(f"line {i}" for i in range(1, 36))

        assert module._summarize_output(output) == (
            "line 1\n"
            "line 2\n"
            "line 3\n"
            "line 4\n"
            "line 5\n"
            "line 6\n"
            "line 7\n"
            "line 8\n"
            "line 9\n"
            "line 10\n"
            "...(省略 5 行)\n"
            "line 16\n"
            "line 17\n"
            "line 18\n"
            "line 19\n"
            "line 20\n"
            "line 21\n"
            "line 22\n"
            "line 23\n"
            "line 24\n"
            "line 25\n"
            "line 26\n"
            "line 27\n"
            "line 28\n"
            "line 29\n"
            "line 30\n"
            "line 31\n"
            "line 32\n"
            "line 33\n"
            "line 34\n"
            "line 35"
        )


class TestOpenCliRun:
    @pytest.mark.asyncio
    async def test_run_uses_summary_detail_and_logs_full_output(self, monkeypatch) -> None:
        module = _load_opencli_module()

        long_output = "\n".join(f"line {i}" for i in range(1, 36))
        captured: dict[str, object] = {}

        class FakeLogger:
            def info(self, msg: str, *args, **kwargs) -> None:
                captured["msg"] = msg
                captured["args"] = args
                captured["kwargs"] = kwargs

        monkeypatch.setattr(module, "logger", FakeLogger())
        monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/opencli")
        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(checks={"opencli": SimpleNamespace(timeout=10, fail_on_error=True)})
            ),
        )

        async def fake_run_command(self, command, timeout):
            return module.CommandResult(return_code=0, stdout=long_output, stderr="")

        monkeypatch.setattr(module.OpenCliCheck, "_run_command", fake_run_command)

        result = await module.OpenCliCheck().run()

        full_output = f"STDOUT:\n{long_output}"
        assert result.detail == f"汇总：命令执行成功\n{module._summarize_output(full_output)}"
        assert captured["msg"] == "opencli doctor 完整输出:\n%s"
        assert captured["args"] == (full_output,)
        assert captured.get("kwargs", {}) == {}

    @pytest.mark.asyncio
    async def test_timeout_uses_summary_detail(self, monkeypatch) -> None:
        module = _load_opencli_module()

        captured: dict[str, object] = {}

        class FakeLogger:
            def info(self, msg: str, *args, **kwargs) -> None:
                captured["msg"] = msg

        monkeypatch.setattr(module, "logger", FakeLogger())
        monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/opencli")
        monkeypatch.setattr(
            module,
            "get_config",
            lambda: SimpleNamespace(
                doctor=SimpleNamespace(checks={"opencli": SimpleNamespace(timeout=10, fail_on_error=True)})
            ),
        )

        async def fake_run_command(self, command, timeout):
            raise TimeoutError

        monkeypatch.setattr(module.OpenCliCheck, "_run_command", fake_run_command)

        result = await module.OpenCliCheck().run()

        assert result.detail == f"汇总：命令执行超时\n{module._summarize_output('Timeout after 10 seconds\n')}"
        assert captured == {}


class TestDoctorLLMCheck:
    @pytest.mark.asyncio
    async def test_single_healthy_node_success(self) -> None:
        check_module = llm_check_module
        large_node = _FakeRuntimeNode(name="large-a", base_url="https://a.example.com/v1", model="gpt-5")
        small_node = _FakeRuntimeNode(name="small-a", base_url="https://b.example.com/v1", model="gpt-4o-mini")

        with (
            patch(
                "beartools.commands.doctor.checks.llm._collect_configured_nodes",
                side_effect=[[large_node], [small_node]],
            ),
            patch("beartools.commands.doctor.checks.llm._probe_node", return_value=None),
        ):
            result = await check_module.LLMCheck().run()

        assert result.name == "llm"
        assert result.status == check_module.CheckStatus.SUCCESS
        assert result.message == "LLM 节点检查通过：large 1/1，small 1/1"
        assert result.detail == (
            "汇总：可用 2，不可用 0\n"
            "✅ large 可用节点：\n"
            "  large-a | gpt-5 | https://a.example.com/v1\n"
            "✅ small 可用节点：\n"
            "  small-a | gpt-4o-mini | https://b.example.com/v1"
        )

    @pytest.mark.asyncio
    async def test_multiple_healthy_nodes_success(self) -> None:
        check_module = llm_check_module
        large_nodes = [_FakeRuntimeNode(name="primary", base_url="https://a.example.com/v1", model="gpt-4.1-mini")]
        small_nodes = [_FakeRuntimeNode(name="backup", base_url="https://b.example.com/v1", model="gpt-4o-mini")]

        with (
            patch(
                "beartools.commands.doctor.checks.llm._collect_configured_nodes",
                side_effect=[large_nodes, small_nodes],
            ),
            patch("beartools.commands.doctor.checks.llm._probe_node", return_value=None),
        ):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.SUCCESS
        assert result.message == "LLM 节点检查通过：large 1/1，small 1/1"
        assert result.detail == (
            "汇总：可用 2，不可用 0\n"
            "✅ large 可用节点：\n"
            "  primary | gpt-4.1-mini | https://a.example.com/v1\n"
            "✅ small 可用节点：\n"
            "  backup | gpt-4o-mini | https://b.example.com/v1"
        )

    @pytest.mark.asyncio
    async def test_initialization_error_returns_failure(self) -> None:
        check_module = llm_check_module

        with patch(
            "beartools.commands.doctor.checks.llm._collect_configured_nodes",
            side_effect=[[], []],
        ):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.FAILURE
        assert result.message == "LLM 健康检查失败：未配置任何 LLM 节点"
        assert result.detail is None

    @pytest.mark.asyncio
    async def test_no_healthy_node_returns_failure(self) -> None:
        check_module = llm_check_module
        large_node = _FakeRuntimeNode(name="large-a", base_url="https://a.example.com/v1", model="gpt-5")
        small_node = _FakeRuntimeNode(name="small-a", base_url="https://b.example.com/v1", model="gpt-4o-mini")

        with (
            patch(
                "beartools.commands.doctor.checks.llm._collect_configured_nodes",
                side_effect=[[large_node], [small_node]],
            ),
            patch(
                "beartools.commands.doctor.checks.llm._probe_node",
                side_effect=RuntimeError("没有可用的健康节点"),
            ),
        ):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.FAILURE
        assert result.message == "LLM 节点检查失败：large 0/1，small 0/1"
        assert result.detail == (
            "汇总：可用 0，不可用 2\n"
            "❌ large 不可用节点：\n"
            "  large-a(https://a.example.com/v1, gpt-5): 没有可用的健康节点\n"
            "❌ small 不可用节点：\n"
            "  small-a(https://b.example.com/v1, gpt-4o-mini): 没有可用的健康节点"
        )

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self) -> None:
        check_module = llm_check_module
        node = _FakeRuntimeNode(name="small-a", base_url="https://a.example.com/v1", model="gpt-4o-mini")

        with (
            patch(
                "beartools.commands.doctor.checks.llm._collect_configured_nodes",
                side_effect=[[], [node]],
            ),
            patch(
                "beartools.commands.doctor.checks.llm._probe_node",
                side_effect=RuntimeError("Error code: 429 - rate limit exceeded"),
            ),
        ):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.FAILURE
        assert result.message == "LLM 节点检查失败：large 0/0，small 0/1"
        assert (
            result.detail
            == "汇总：可用 0，不可用 1\n❌ small 不可用节点：\n  small-a(https://a.example.com/v1, gpt-4o-mini): Error code: 429 - rate limit exceeded"
        )
