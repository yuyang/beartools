"""Google Ping 网络连通性检查

检查到 www.google.com 的网络连通性，用于验证是否能够正常访问Google服务。
"""

from __future__ import annotations

import time

from ping3 import ping

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config


@register_check
class GooglePingCheck(BaseCheck):
    """Google Ping 检查项

    使用 ping3 库发送 ICMP ping 包到 www.google.com，检查网络连通性。
    """

    @property
    def name(self) -> str:
        """检查项名称"""
        return "google_ping"

    @property
    def description(self) -> str:
        """检查项描述"""
        return "检查到www.google.com的网络连通性"

    def run(self) -> CheckResult:
        """执行 Google Ping 检查

        Returns:
            CheckResult: 检查结果
            - SUCCESS: ping 成功，能够连通 Google
            - FAILURE: ping 失败，无法连通 Google
        """
        start_time = time.time()
        config = get_config()

        # 从配置获取超时时间，默认 2 秒
        check_config = config.doctor.checks.get("google_ping")
        timeout: int = check_config.timeout if check_config else 2

        try:
            # 执行 ping，返回值是延迟秒数，如果失败返回 None 或 False
            result_delay: float | None | bool = ping("www.google.com", timeout=timeout)

            if isinstance(result_delay, (float, int)):
                duration = time.time() - start_time
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.SUCCESS,
                    message=f"成功连接到 Google，延迟 {result_delay * 1000:.1f}ms",
                    duration=duration,
                    detail=None,
                )
            elif result_delay is False:
                duration = time.time() - start_time
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.FAILURE,
                    message="无法连接到 Google，请求超时",
                    duration=duration,
                    detail=None,
                )
            else:  # result_delay is None
                duration = time.time() - start_time
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.FAILURE,
                    message="无法连接到 Google，域名解析失败或网络不可达",
                    duration=duration,
                    detail=None,
                )
        except PermissionError:
            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="无法执行 ping 操作：权限不足，请以管理员权限运行",
                duration=duration,
                detail="ICMP 操作需要系统管理员权限才能创建原始套接字",
            )
        except Exception as e:
            duration = time.time() - start_time
            msg: str = str(e)
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message=f"执行 ping 操作出错：{msg}",
                duration=duration,
                detail=msg,
            )
