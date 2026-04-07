from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

pytest = importlib.import_module("pytest")


def _load_module():
    return importlib.import_module("beartools.commands.doctor.checks.google_ping")


class TestGooglePingCheck:
    def test_default_targets_include_baidu(self) -> None:
        module = _load_module()

        assert len(module.DEFAULT_TARGETS) == 6
        assert module.DEFAULT_TARGETS[-1] == "https://www.baidu.com/"

    @pytest.mark.asyncio
    async def test_run_falls_back_to_default_targets_and_threshold(self, monkeypatch) -> None:
        module = _load_module()

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
        assert result.message == "科学上网检查失败（2/6）"
        assert result.detail == "\n".join(
            [
                "google: 成功 200",
                "youtube: 成功 200",
                "facebook: 连接失败",
                "x: 连接失败",
                "instagram: 连接失败",
                "baidu: 连接失败",
            ]
        )

    @pytest.mark.asyncio
    async def test_run_success_when_three_of_six_targets_succeed(self, monkeypatch) -> None:
        module = _load_module()

        async def fake_check_target(self, session, target: str, timeout: int):
            mapping = {
                "https://www.google.com/generate_204": module._TargetCheckResult("google", True, "成功 204"),
                "https://www.youtube.com/": module._TargetCheckResult("youtube", True, "成功 200"),
                "https://www.facebook.com/": module._TargetCheckResult("facebook", True, "成功 200"),
                "https://x.com/": module._TargetCheckResult("x", False, "超时"),
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
        assert result.message == "科学上网检查通过（3/6）"
        assert result.detail == "\n".join(
            [
                "google: 成功 204",
                "youtube: 成功 200",
                "facebook: 成功 200",
                "x: 超时",
                "instagram: 连接失败",
                "baidu: 连接失败",
            ]
        )

    @pytest.mark.asyncio
    async def test_run_failure_when_only_two_of_six_targets_succeed(self, monkeypatch) -> None:
        module = _load_module()

        async def fake_check_target(self, session, target: str, timeout: int):
            mapping = {
                "https://www.google.com/generate_204": module._TargetCheckResult("google", True, "成功 204"),
                "https://www.youtube.com/": module._TargetCheckResult("youtube", True, "成功 200"),
                "https://www.facebook.com/": module._TargetCheckResult("facebook", False, "DNS 解析失败"),
                "https://x.com/": module._TargetCheckResult("x", False, "超时"),
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
        assert result.message == "科学上网检查失败（2/6）"
        assert result.detail == "\n".join(
            [
                "google: 成功 204",
                "youtube: 成功 200",
                "facebook: DNS 解析失败",
                "x: 超时",
                "instagram: 连接失败",
                "baidu: 连接失败",
            ]
        )

    def test_label_for_target_returns_expected_short_name(self) -> None:
        module = _load_module()

        assert module._label_for_target("https://www.google.com/generate_204") == "google"
        assert module._label_for_target("https://www.youtube.com/") == "youtube"
        assert module._label_for_target("https://www.facebook.com/") == "facebook"
        assert module._label_for_target("https://x.com/") == "x"
        assert module._label_for_target("https://www.instagram.com/") == "instagram"
        assert module._label_for_target("https://www.baidu.com/") == "baidu"

    @pytest.mark.asyncio
    async def test_check_target_classifies_timeout(self, monkeypatch) -> None:
        module = _load_module()
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
        module = _load_module()
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
        module = _load_module()
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

        connection_result = await check._check_target(FakeSession(raise_connection), "https://x.com/", 2)

        assert connection_result == module._TargetCheckResult(label="x", ok=False, summary="连接失败")

    @pytest.mark.asyncio
    async def test_run_preserves_target_order_and_uses_concurrent_requests(self, monkeypatch) -> None:
        module = _load_module()
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

        assert result.detail == "google: 成功 200\nyoutube: 成功 200\nfacebook: 成功 200"
