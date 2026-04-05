from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Protocol, cast
from unittest.mock import patch

pytest = importlib.import_module("pytest")


class _RuntimeNodeProtocol(Protocol):
    name: str
    base_url: str
    model: str


class _LLMRuntimeProtocol(Protocol):
    healthy_nodes: list[_RuntimeNodeProtocol]


class _RuntimeModuleProtocol(Protocol):
    LLMRuntimeInitializationError: type[BaseException]
    LLMRuntimeNoHealthyNodeError: type[BaseException]


class _CheckResultProtocol(Protocol):
    name: str
    status: object
    message: str
    detail: str | None


class _CheckStatusProtocol(Protocol):
    SUCCESS: object
    FAILURE: object


class _DoctorCheckProtocol(Protocol):
    async def run(self) -> _CheckResultProtocol: ...


class _DoctorCheckClass(Protocol):
    def __call__(self) -> _DoctorCheckProtocol: ...


class _CheckModuleProtocol(Protocol):
    CheckStatus: _CheckStatusProtocol
    LLMCheck: _DoctorCheckClass


@dataclass(frozen=True, slots=True)
class _FakeRuntimeNode:
    name: str
    base_url: str
    model: str


@dataclass(frozen=True, slots=True)
class _FakeRuntime:
    healthy_nodes: list[_RuntimeNodeProtocol]


def _load_modules() -> tuple[_CheckModuleProtocol, _RuntimeModuleProtocol]:
    check_module = cast(_CheckModuleProtocol, importlib.import_module("beartools.commands.doctor.checks.llm"))
    runtime_module = cast(_RuntimeModuleProtocol, importlib.import_module("beartools.llm.runtime"))
    return check_module, runtime_module


class TestDoctorLLMCheck:
    @pytest.mark.asyncio
    async def test_single_healthy_node_success(self) -> None:
        check_module, _ = _load_modules()
        runtime = _FakeRuntime(
            healthy_nodes=[_FakeRuntimeNode(name="node-a", base_url="https://a.example.com/v1", model="gpt-4o-mini")]
        )

        with patch("beartools.commands.doctor.checks.llm.create_llm_runtime", return_value=runtime):
            result = await check_module.LLMCheck().run()

        assert result.name == "llm"
        assert result.status == check_module.CheckStatus.SUCCESS
        assert result.message == "检测到 1 个可用 LLM 节点"
        assert result.detail == "node-a | gpt-4o-mini | https://a.example.com/v1"

    @pytest.mark.asyncio
    async def test_multiple_healthy_nodes_success(self) -> None:
        check_module, _ = _load_modules()
        runtime = _FakeRuntime(
            healthy_nodes=[
                _FakeRuntimeNode(name="primary", base_url="https://a.example.com/v1", model="gpt-4.1-mini"),
                _FakeRuntimeNode(name="backup", base_url="https://b.example.com/v1", model="gpt-4o-mini"),
            ]
        )

        with patch("beartools.commands.doctor.checks.llm.create_llm_runtime", return_value=runtime):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.SUCCESS
        assert result.message == "检测到 2 个可用 LLM 节点"
        assert result.detail == (
            "primary | gpt-4.1-mini | https://a.example.com/v1\nbackup | gpt-4o-mini | https://b.example.com/v1"
        )

    @pytest.mark.asyncio
    async def test_initialization_error_returns_failure(self) -> None:
        check_module, runtime_module = _load_modules()

        with patch(
            "beartools.commands.doctor.checks.llm.create_llm_runtime",
            side_effect=runtime_module.LLMRuntimeInitializationError("未配置任何 agent 节点"),
        ):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.FAILURE
        assert result.message == "LLM 健康检查失败"
        assert result.detail == "未配置任何 agent 节点"

    @pytest.mark.asyncio
    async def test_no_healthy_node_returns_failure(self) -> None:
        check_module, runtime_module = _load_modules()

        with patch(
            "beartools.commands.doctor.checks.llm.create_llm_runtime",
            side_effect=runtime_module.LLMRuntimeNoHealthyNodeError("没有可用的健康节点"),
        ):
            result = await check_module.LLMCheck().run()

        assert result.status == check_module.CheckStatus.FAILURE
        assert result.message == "LLM 健康检查失败"
        assert result.detail == "没有可用的健康节点"
