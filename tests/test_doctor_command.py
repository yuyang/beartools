from __future__ import annotations

import importlib

from beartools.commands.doctor.base import CheckRegistry, CheckResult, CheckStatus

pytest = importlib.import_module("pytest")


def _load_module():
    return importlib.import_module("beartools.commands.doctor.command")


class TestDoctorCommand:
    @pytest.mark.asyncio
    async def test_run_single_check_logs_begin_message(self, monkeypatch) -> None:
        module = _load_module()
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
        module = _load_module()

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
