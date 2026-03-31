"""OpenCli 安装状态检查

检查 opencli 是否已安装并执行 opencli doctor 命令验证其可用性。
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import NamedTuple

from beartools.commands.doctor.base import BaseCheck, CheckResult, CheckStatus, register_check
from beartools.config import get_config


class CommandResult(NamedTuple):
    """命令执行结果"""

    return_code: int
    stdout: str
    stderr: str


@register_check
class OpenCliCheck(BaseCheck):
    """OpenCli 检查项

    检查系统是否已安装 opencli 工具，并执行 opencli doctor 命令验证可用性。
    """

    @property
    def name(self) -> str:
        """检查项名称"""
        return "opencli"

    @property
    def description(self) -> str:
        """检查项描述"""
        return "检查opencli是否已安装并运行opencli doctor"

    async def _run_command(self, command: list[str], timeout: int) -> CommandResult:
        """执行外部命令并捕获输出

        Args:
            command: 命令及参数列表
            timeout: 超时时间（秒）

        Returns:
            CommandResult: 包含返回码、标准输出和标准错误
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)  # type: ignore[misc]
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            return CommandResult(return_code=process.returncode or 0, stdout=stdout, stderr=stderr)
        except TimeoutError:
            if process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
            raise

    async def run(self) -> CheckResult:
        """执行 OpenCli 检查

        Returns:
            CheckResult: 检查结果
            - SUCCESS: opencli 已安装且 doctor 命令执行成功
            - FAILURE: opencli 未安装或 doctor 命令执行失败
        """
        start_time = time.time()
        config = get_config()

        # 检查 opencli 是否已安装
        if shutil.which("opencli") is None:
            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message="opencli 未安装，请先安装 opencli",
                duration=duration,
                detail="opencli 命令未在 PATH 中找到，请确认安装完成后将其加入环境变量",
            )

        # 从配置获取超时和失败配置
        check_config = config.doctor.checks.get("opencli", None)
        timeout = check_config.timeout if check_config else 10
        fail_on_error = check_config.fail_on_error if check_config else True

        try:
            # 执行 opencli doctor
            result = await self._run_command(["opencli", "doctor"], timeout=timeout)
            duration = time.time() - start_time

            # 合并输出
            full_output = ""
            if result.stdout.strip():
                full_output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr.strip():
                full_output += f"STDERR:\n{result.stderr}"
            full_output = full_output.strip()

            if result.return_code == 0:
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.SUCCESS,
                    message="opencli 已安装且 doctor 执行成功",
                    duration=duration,
                    detail=full_output or None,
                )

            # 非零返回码
            if fail_on_error:
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.FAILURE,
                    message=f"opencli doctor 执行失败，返回码 {result.return_code}",
                    duration=duration,
                    detail=full_output or None,
                )
            else:
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.WARNING,
                    message=f"opencli doctor 返回非零码 {result.return_code}，但配置为不强制失败",
                    duration=duration,
                    detail=full_output or None,
                )

        except TimeoutError:
            duration = time.time() - start_time
            full_output = f"Timeout after {timeout} seconds\n"

            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE if fail_on_error else CheckStatus.WARNING,
                message=f"opencli doctor 执行超时（{timeout} 秒）",
                duration=duration,
                detail=full_output or None,
            )
        except Exception as e:
            duration = time.time() - start_time
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILURE,
                message=f"检查 opencli 时发生错误：{str(e)}",
                duration=duration,
                detail=str(e),
            )
