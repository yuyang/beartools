"""Google Ping 网络连通性检查。

检查科学上网所需的 HTTPS 连通性。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

import aiohttp

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config

DEFAULT_TARGETS: list[str] = [
    "https://www.google.com/generate_204",
    "https://www.youtube.com/",
    "https://www.facebook.com/",
    "https://x.com/",
    "https://www.instagram.com/",
    "https://www.baidu.com/",
]
DEFAULT_SUCCESS_THRESHOLD = 3


@dataclass(frozen=True)
class _TargetCheckResult:
    """单个目标检查结果。"""

    label: str
    ok: bool
    summary: str


def _label_for_target(target: str) -> str:
    """将目标域名映射为展示标签。"""
    if "google.com" in target:
        return "google"
    if "youtube.com" in target:
        return "youtube"
    if "facebook.com" in target:
        return "facebook"
    if "x.com" in target:
        return "x"
    if "instagram.com" in target:
        return "instagram"
    if "baidu.com" in target:
        return "baidu"
    return target


def _summary_for_error(error: Exception) -> str:
    """将异常转换为简短错误摘要。"""
    error_name = error.__class__.__name__
    if isinstance(error, TimeoutError):
        return "超时"
    if "DNS" in error_name:
        return "DNS 解析失败"
    if "CertificateError" in error_name:
        return "HTTPS 请求失败"
    if "SSLError" in error_name:
        return "HTTPS 请求失败"
    if "ConnectorError" in error_name:
        return "连接失败"
    if error_name.endswith("ClientError"):
        return "HTTPS 请求失败"
    if isinstance(error, OSError):
        return "连接失败"
    return "请求失败"


@register_check
class GooglePingCheck(BaseCheck):
    """Google Ping 检查项。

    依次检查多个 Google HTTPS 目标的连通性，并汇总成功数量。
    """

    _targets: list[str] = DEFAULT_TARGETS

    @property
    def name(self) -> str:
        """检查项名称"""
        return "google_ping"

    @property
    def description(self) -> str:
        """检查项描述"""
        return "检查科学上网所需的 HTTPS 连通性"

    async def _check_target(self, session: aiohttp.ClientSession, target: str, timeout: int) -> _TargetCheckResult:
        """检查单个目标的 HTTPS 连通性。"""
        label = _label_for_target(target)
        try:
            _request_timeout = aiohttp.ClientTimeout(total=timeout)
            async with session.get(target, ssl=True) as response:
                _ = _request_timeout
                return _TargetCheckResult(label=label, ok=True, summary=f"成功 {response.status}")
        except (TimeoutError, OSError, Exception) as error:
            return _TargetCheckResult(label=label, ok=False, summary=_summary_for_error(error))

    async def run(self) -> CheckResult:
        """执行 Google 连通性检查并汇总结果。"""
        start_time = time.time()
        config = get_config()

        check_config = config.doctor.checks.get("google_ping")
        if check_config is not None:
            timeout = check_config.timeout
            targets = check_config.targets if check_config.targets else DEFAULT_TARGETS
            success_threshold = (
                check_config.success_threshold if check_config.success_threshold > 0 else DEFAULT_SUCCESS_THRESHOLD
            )
        else:
            timeout = 2
            targets = DEFAULT_TARGETS
            success_threshold = DEFAULT_SUCCESS_THRESHOLD

        timeout_config = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_config, trust_env=False) as session:
            tasks = [asyncio.create_task(self._check_target(session, target, timeout)) for target in targets]
            results = await asyncio.gather(*tasks)
        success_count = sum(1 for result in results if result.ok)
        detail = "\n".join(f"{result.label}: {result.summary}" for result in results)

        duration = time.time() - start_time
        if success_count >= success_threshold:
            return CheckResult(
                name=self.name,
                status=CheckStatus.SUCCESS,
                message=f"科学上网检查通过（{success_count}/{len(results)}）",
                duration=duration,
                detail=detail,
            )

        return CheckResult(
            name=self.name,
            status=CheckStatus.FAILURE,
            message=f"科学上网检查失败（{success_count}/{len(results)}）",
            duration=duration,
            detail=detail,
        )
