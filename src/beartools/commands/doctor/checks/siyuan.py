"""Siyuan 笔记端口检查

检查 127.0.0.1:6806 端口是否开放，验证思源笔记服务是否正常运行。
"""

from __future__ import annotations

import asyncio
import time

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config


@register_check
class SiyuanCheck(BaseCheck):
    """Siyuan 检查项

    检查本地 127.0.0.1:6806 端口是否开放，验证思源笔记服务是否正常运行。
    """

    @property
    def name(self) -> str:
        """检查项名称"""
        return "siyuan"

    @property
    def description(self) -> str:
        """检查项描述"""
        return "检查思源笔记服务端口 127.0.0.1:6806 是否开放"

    async def _is_port_open(self, host: str, port: int, timeout: int) -> bool:
        """检查指定端口是否开放

        Args:
            host: 主机地址
            port: 端口号
            timeout: 超时时间（秒）

        Returns:
            bool: 端口开放返回True，否则返回False
        """
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False

    async def run(self) -> CheckResult:
        """执行 Siyuan 端口检查

        Returns:
            CheckResult: 检查结果
            - SUCCESS: 端口开放，思源笔记服务运行正常
            - FAILURE: 端口未开放，思源笔记服务未运行或端口被占用
        """
        start_time = time.time()
        config = get_config()

        # 从配置获取超时和失败配置
        check_config = config.doctor.checks.get("siyuan", None)
        timeout = check_config.timeout if check_config else 2
        fail_on_error = check_config.fail_on_error if check_config else True

        try:
            is_open = await self._is_port_open("127.0.0.1", 6806, timeout)
            duration = time.time() - start_time

            if is_open:
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.SUCCESS,
                    message="思源笔记服务运行正常，端口 6806 已开放",
                    duration=duration,
                    detail="127.0.0.1:6806 端口连接成功",
                )
            else:
                if fail_on_error:
                    return CheckResult(
                        name=self.name,
                        status=CheckStatus.FAILURE,
                        message="思源笔记服务未运行，端口 6806 未开放",
                        duration=duration,
                        detail="无法连接到 127.0.0.1:6806，请检查思源笔记是否已启动",
                    )
                else:
                    return CheckResult(
                        name=self.name,
                        status=CheckStatus.WARNING,
                        message="思源笔记服务未运行，端口 6806 未开放",
                        duration=duration,
                        detail="无法连接到 127.0.0.1:6806，请检查思源笔记是否已启动",
                    )

        except Exception as e:
            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message=f"检查思源笔记端口时发生错误：{str(e)}",
                duration=duration,
                detail=str(e),
            )
