"""Google Ping 网络连通性检查

检查到 www.google.com 的网络连通性，用于验证是否能够正常访问Google服务。
"""

from __future__ import annotations

import asyncio
import time

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config


@register_check
class GooglePingCheck(BaseCheck):
    """Google Ping 检查项

    使用TCP连接到www.google.com:443检查网络连通性，无需管理员权限。
    """

    @property
    def name(self) -> str:
        """检查项名称"""
        return "google_ping"

    @property
    def description(self) -> str:
        """检查项描述"""
        return "检查到www.google.com的网络连通性"

    async def run(self) -> CheckResult:
        """执行 Google 连通性检查

        Returns:
            CheckResult: 检查结果
            - SUCCESS: 连接成功，能够连通 Google
            - FAILURE: 连接失败，无法连通 Google
        """
        start_time = time.time()
        config = get_config()

        # 从配置获取超时时间，默认 2 秒
        check_config = config.doctor.checks.get("google_ping")
        timeout: int = check_config.timeout if check_config else 2

        try:
            # 建立TCP连接到Google 443端口，模拟HTTPS握手
            conn_start = time.time()
            _, writer = await asyncio.wait_for(asyncio.open_connection("www.google.com", 443), timeout=timeout)  # type: ignore[misc]
            latency = (time.time() - conn_start) * 1000
            writer.close()
            await writer.wait_closed()

            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.SUCCESS,
                message=f"成功连接到 Google，延迟 {latency:.1f}ms",
                duration=duration,
                detail=None,
            )

        except TimeoutError:
            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="无法连接到 Google，请求超时",
                duration=duration,
                detail=None,
            )
        except (ConnectionRefusedError, OSError) as e:
            duration = time.time() - start_time
            if "Name or service not known" in str(e) or "nodename nor servname provided" in str(e):
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.FAILURE,
                    message="无法连接到 Google，域名解析失败或网络不可达",
                    duration=duration,
                    detail=None,
                )
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message=f"连接 Google 出错：{str(e)}",
                duration=duration,
                detail=str(e),
            )
        except Exception as e:
            duration = time.time() - start_time
            msg: str = str(e)
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message=f"检查 Google 连通性出错：{msg}",
                duration=duration,
                detail=msg,
            )
