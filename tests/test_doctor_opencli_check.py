from __future__ import annotations

import importlib
from types import SimpleNamespace

pytest = importlib.import_module("pytest")


def _load_module():
    return importlib.import_module("beartools.commands.doctor.checks.opencli")


class TestOpenCliSummary:
    def test_summary_returns_original_when_short(self) -> None:
        module = _load_module()
        output = "\n".join(f"line {i}" for i in range(1, 31))

        assert module._summarize_output(output) == output

    def test_summary_truncates_long_output(self) -> None:
        module = _load_module()
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
        module = _load_module()

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
        assert result.detail == module._summarize_output(full_output)
        assert captured["msg"] == "opencli doctor 完整输出:\n%s"
        assert captured["args"] == (full_output,)
        assert captured.get("kwargs", {}) == {}

    @pytest.mark.asyncio
    async def test_timeout_uses_summary_detail(self, monkeypatch) -> None:
        module = _load_module()

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

        assert result.detail == module._summarize_output("Timeout after 10 seconds\n")
        assert captured == {}
