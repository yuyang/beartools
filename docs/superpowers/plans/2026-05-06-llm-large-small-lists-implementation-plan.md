# LLM Large Small Lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `primary + candidates` 的单路模型配置重构为 `large` 与 `small` 两个独立列表，并按列表顺序选择第一个可用模型；当对应列表全部不可用时明确报错。

**Architecture:** 保留现有单节点配置结构 `AgentNodeConfig`，仅替换聚合配置 `AgentConfig` 的形状，并在运行时增加按模型类别选择节点池的能力。运行时不再使用全局 `primary/candidates` 顺序，而是为 `large` 与 `small` 分别维护探测、健康节点池和失败回退逻辑，保证语义清晰且后续易于扩展。

**Tech Stack:** Python 3.13+, dataclasses, openai/openrouter provider adapters, pytest, uv

---

## 文件结构

- 修改：`src/beartools/config.py`
  - 责任：将 `AgentConfig` 从 `primary/candidates` 改为 `large/small`，并更新配置解析与校验规则。
- 修改：`src/beartools/llm/runtime.py`
  - 责任：将运行时节点收集、探测、健康池和失败回退逻辑改为按 `large/small` 独立处理。
- 修改：`src/beartools/codex.py`
  - 责任：如果当前入口需要区分任务规模，则接入新的 `large/small` 取节点逻辑；如果不依赖 LLM runtime，则只做影响确认，不做无关改动。
- 修改：`config/beartools.yaml.sample`
  - 责任：更新配置样例，移除 `primary/candidates`，改为 `large/small`。
- 修改：`tests/test_config.py`
  - 责任：覆盖新配置结构的解析、缺失字段、列表结构校验。
- 修改：`tests/test_llm_runtime.py`
  - 责任：覆盖 `large/small` 的顺序探测、列表内回退、全失败报错与错误脱敏。
- 可选修改：`tests/test_agent_factory.py`
  - 责任：若工厂测试依赖旧配置结构，同步调整到新结构。
- 可选修改：`src/beartools/commands/doctor/checks/llm.py`
  - 责任：若 doctor 检查直接依赖旧结构，则改为适配新结构。

### Task 1: 用测试锁定 `large/small` 配置结构

**Files:**
- Modify: `tests/test_config.py`
- Modify: `config/beartools.yaml.sample`
- Test: `tests/test_config.py`

- [ ] **Step 1: 新增配置解析测试，约束 `large/small` 的正确结构**

```python
def test_can_parse_full_agent_config_with_large_and_small() -> None:
    config = load_config_from_yaml(
        """
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://api.example.com/v1"
      model: "gpt-5"
      api_key: "test-key"
      timeout_seconds: 30
  small:
    - name: "small-1"
      provider: "openrouter"
      base_url: "https://openrouter.ai/api/v1"
      model: "gpt-4.1-mini"
      api_key: "test-key"
      timeout_seconds: 20
"""
    )

    assert [node.name for node in config.agent.large] == ["large-1"]
    assert [node.name for node in config.agent.small] == ["small-1"]
```

- [ ] **Step 2: 新增缺失字段与结构非法测试**

```python
def test_reject_missing_large() -> None:
    with pytest.raises(RuntimeError, match="agent.large"):
        load_config_from_yaml(
            """
agent:
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://api.example.com/v1"
      model: "gpt-4.1-mini"
      api_key: "test-key"
"""
        )


def test_reject_missing_small() -> None:
    with pytest.raises(RuntimeError, match="agent.small"):
        load_config_from_yaml(
            """
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://api.example.com/v1"
      model: "gpt-5"
      api_key: "test-key"
"""
        )


def test_reject_invalid_large_shape() -> None:
    with pytest.raises(RuntimeError, match="agent.large"):
        load_config_from_yaml(
            """
agent:
  large:
    name: "large-1"
    provider: "openai"
    base_url: "https://api.example.com/v1"
    model: "gpt-5"
    api_key: "test-key"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://api.example.com/v1"
      model: "gpt-4.1-mini"
      api_key: "test-key"
"""
        )


def test_reject_invalid_small_shape() -> None:
    with pytest.raises(RuntimeError, match="agent.small"):
        load_config_from_yaml(
            """
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://api.example.com/v1"
      model: "gpt-5"
      api_key: "test-key"
  small: {}
"""
        )
```

- [ ] **Step 3: 运行配置测试，确认当前实现仍绑定旧结构**

Run: `uv run pytest tests/test_config.py -xvs`

Expected: FAIL，至少出现 `agent.primary` 或 `agent.candidates` 相关断言与新结构不匹配。

- [ ] **Step 4: 修改配置数据结构与解析规则，只接受 `large/small` 两个非空列表**

```python
@dataclass
class AgentConfig:
    """智能体配置"""

    large: list[AgentNodeConfig] = field(default_factory=list)
    small: list[AgentNodeConfig] = field(default_factory=list)
```

```python
def _parse_agent_node_list(value: object, path: str) -> list[AgentNodeConfig]:
    node_settings_list = _as_list(value, path)
    if not node_settings_list:
        raise RuntimeError(f"{path} 必须是非空列表")
    return [
        _parse_agent_node_config(node_settings, f"{path}[{index}]")
        for index, node_settings in enumerate(node_settings_list)
    ]
```

```python
def _parse_agent_config(settings: _SettingsLike) -> AgentConfig:
    agent_settings = settings.get("agent")
    if agent_settings is None:
        return AgentConfig()
    agent_dict = _as_dict(agent_settings, "agent")

    if "large" not in agent_dict:
        raise RuntimeError("agent.large 必填")
    if "small" not in agent_dict:
        raise RuntimeError("agent.small 必填")

    large = _parse_agent_node_list(agent_dict["large"], "agent.large")
    small = _parse_agent_node_list(agent_dict["small"], "agent.small")
    return AgentConfig(large=large, small=small)
```

- [ ] **Step 5: 更新配置样例文件，只保留 `large/small` 示例**

```yaml
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://api.example.com/v1"
      model: "gpt-5"
      api_key: "@get agent.large_keys.primary"
      timeout_seconds: 30
  small:
    - name: "small-1"
      provider: "openrouter"
      base_url: "https://openrouter.ai/api/v1"
      model: "gpt-4.1-mini"
      api_key: "@get agent.small_keys.primary"
      timeout_seconds: 20
```

- [ ] **Step 6: 重新运行配置测试，确认新结构通过**

Run: `uv run pytest tests/test_config.py -xvs`

Expected: PASS。

### Task 2: 重构运行时为 `large/small` 独立节点池

**Files:**
- Modify: `src/beartools/llm/runtime.py`
- Test: `tests/test_llm_runtime.py`

- [ ] **Step 1: 先补失败测试，固定按 tier 顺序选择与回退的语义**

```python
def test_runtime_uses_first_healthy_large_node() -> None:
    large_a = create_runtime_node("large-a")
    large_b = create_runtime_node("large-b")

    runtime = runtime_module.LLRuntime(large_nodes=[large_a, large_b], small_nodes=[create_runtime_node("small-a")])

    assert runtime.get_active_node("large") is large_a


def test_runtime_falls_back_to_next_large_node_after_failure() -> None:
    large_a = create_runtime_node("large-a")
    large_b = create_runtime_node("large-b")

    runtime = runtime_module.LLRuntime(large_nodes=[large_a, large_b], small_nodes=[create_runtime_node("small-a")])
    changed = runtime.mark_node_failed("large", large_a, error=StatusCodeError(503, "large-a unavailable"))

    assert changed is True
    assert runtime.get_active_node("large") is large_b


def test_runtime_small_pool_is_independent_from_large_pool() -> None:
    large_a = create_runtime_node("large-a")
    small_a = create_runtime_node("small-a")
    small_b = create_runtime_node("small-b")

    runtime = runtime_module.LLRuntime(large_nodes=[large_a], small_nodes=[small_a, small_b])
    changed = runtime.mark_node_failed("small", small_a, error=StatusCodeError(503, "small-a unavailable"))

    assert changed is True
    assert runtime.get_active_node("large") is large_a
    assert runtime.get_active_node("small") is small_b
```

- [ ] **Step 2: 补充全失败报错测试，要求错误能指明对应列表**

```python
def test_create_large_runtime_raises_when_all_large_nodes_are_unhealthy() -> None:
    large_a = create_agent_node_config("large-a", provider="openai")
    large_b = create_agent_node_config("large-b", provider="openrouter")
    small_a = create_agent_node_config("small-a", provider="openai")
    config = create_config(large=[large_a, large_b], small=[small_a])

    def probe_node(node: _RuntimeNodeProtocol) -> None:
        if node.name.startswith("large"):
            raise TimeoutError("probe timed out")

    with (
        patch.object(runtime_module, "get_config", return_value=config),
        patch.object(runtime_module, "_probe_node", side_effect=probe_node),
    ):
        with pytest.raises(runtime_module.LLMRuntimeNoHealthyNodeError, match="large"):
            runtime_module.create_llm_runtime("large")
```

- [ ] **Step 3: 运行运行时测试，确认当前实现不支持 tier 模式**

Run: `uv run pytest tests/test_llm_runtime.py -xvs`

Expected: FAIL，当前实现只有单路 `healthy_nodes` 与无参 `get_active_node()`。

- [ ] **Step 4: 为运行时引入 tier 类型与双池结构，分别维护健康节点与失败状态**

```python
type AgentTier = Literal["large", "small"]


@dataclass(slots=True)
class LLRuntime:
    large_nodes: list[RuntimeNode]
    small_nodes: list[RuntimeNode]
    _active_fingerprints: dict[AgentTier, str | None] = field(init=False, repr=False)
    _failed_fingerprints: dict[AgentTier, set[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.large_nodes:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时初始化失败：large 没有可用的健康节点")
        if not self.small_nodes:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时初始化失败：small 没有可用的健康节点")
        self._failed_fingerprints = {"large": set(), "small": set()}
        self._active_fingerprints = {
            "large": self._choose_active_fingerprint("large"),
            "small": self._choose_active_fingerprint("small"),
        }
```

- [ ] **Step 5: 将节点收集与探测逻辑拆成按 tier 工作的私有函数**

```python
def _collect_configured_nodes(tier: AgentTier) -> list[RuntimeNode]:
    agent_config = get_config().agent
    config_nodes = agent_config.large if tier == "large" else agent_config.small
    return _deduplicate_nodes(config_nodes)
```

```python
def _build_healthy_node_pool(tier: AgentTier) -> list[RuntimeNode]:
    configured_nodes = _collect_configured_nodes(tier)
    if not configured_nodes:
        raise LLMRuntimeInitializationError(f"LLM 运行时初始化失败：{tier} 未配置任何 agent 节点")

    healthy_nodes: list[RuntimeNode] = []
    failed_reasons: list[str] = []
    for node in configured_nodes:
        try:
            _probe_node(node)
        except (APIConnectionError, APITimeoutError, TimeoutError) as exc:
            failed_reasons.append(f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}")
            continue
        except APIStatusError as exc:
            failed_reasons.append(
                f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}: {str(exc)}"
            )
            continue
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ) as exc:
            failed_reasons.append(f"{node.name}({node.base_url}, {node.model}): {_sanitize_probe_failure_reason(exc)}")
            continue
        healthy_nodes.append(node)

    if not healthy_nodes:
        reason_text = "；".join(failed_reasons) if failed_reasons else "未知原因"
        raise LLMRuntimeNoHealthyNodeError(f"LLM 运行时初始化失败：{tier} 没有可用的健康节点，探测失败原因：{reason_text}")

    return healthy_nodes
```

- [ ] **Step 6: 更新公开接口为按 tier 访问活动节点与标记失败**

```python
def create_llm_runtime(tier: AgentTier | None = None) -> LLRuntime:
    if tier is None:
        return LLRuntime(
            large_nodes=_build_healthy_node_pool("large"),
            small_nodes=_build_healthy_node_pool("small"),
        )
    if tier == "large":
        return LLRuntime(large_nodes=_build_healthy_node_pool("large"), small_nodes=[RuntimeNode(...)])
    return LLRuntime(large_nodes=[RuntimeNode(...)], small_nodes=_build_healthy_node_pool("small"))
```

```python
def get_active_llm_node(tier: AgentTier) -> RuntimeNode:
    return get_llm_runtime().get_active_node(tier)


def mark_active_llm_node_failed(tier: AgentTier, error: BaseException | None = None) -> bool:
    runtime = get_llm_runtime()
    return runtime.mark_node_failed(tier, runtime.get_active_node(tier), error=error)
```

- [ ] **Step 7: 重新运行运行时测试，确认 `large/small` 顺序选择与回退正确**

Run: `uv run pytest tests/test_llm_runtime.py -xvs`

Expected: PASS。

### Task 3: 接入调用方并清理旧术语

**Files:**
- Modify: `src/beartools/codex.py`
- Modify: `tests/test_agent_factory.py`
- Optional Modify: `src/beartools/commands/doctor/checks/llm.py`

- [ ] **Step 1: 先确认调用链是否真实依赖 `beartools.llm.runtime`，如依赖则补测试锁定 tier 选择入口**

```python
def test_runtime_client_uses_large_tier_for_large_requests() -> None:
    runtime = FakeRuntime()
    client = build_runtime_client(runtime=runtime)

    client.run_large_request("请分析并重构")

    assert runtime.requested_tiers == ["large"]


def test_runtime_client_uses_small_tier_for_small_requests() -> None:
    runtime = FakeRuntime()
    client = build_runtime_client(runtime=runtime)

    client.run_small_request("帮我润色一句话")

    assert runtime.requested_tiers == ["small"]
```

- [ ] **Step 2: 运行调用方相关测试，确认是否存在旧结构耦合**

Run: `uv run pytest tests/test_agent_factory.py -xvs`

Expected: 若调用方依赖旧结构则 FAIL；若与 runtime 无耦合，则 PASS，且本任务仅记录“无需改动”。

- [ ] **Step 3: 若 `codex.py` 或其他入口确实使用 runtime，则接入显式 tier 选择；否则不做无关修改**

```python
def _get_runtime_node_for_task(self, tier: AgentTier) -> RuntimeNode:
    return self._runtime.get_active_node(tier)


def _mark_runtime_node_failed_for_task(self, tier: AgentTier, error: BaseException) -> bool:
    return self._runtime.mark_node_failed(tier, self._runtime.get_active_node(tier), error=error)
```

- [ ] **Step 4: 若 doctor 检查直接读取 `primary/candidates`，则更新为新结构并补充断言**

```python
summary = {
    "large_count": len(config.agent.large),
    "small_count": len(config.agent.small),
}
```

- [ ] **Step 5: 运行受影响测试集合，确认旧术语已被替换或限制在历史 plan 中**

Run: `uv run pytest tests/test_config.py tests/test_llm_runtime.py tests/test_agent_factory.py -xvs`

Expected: PASS。

### Task 4: 运行静态检查并做最终验证

**Files:**
- Modify: `src/beartools/config.py`
- Modify: `src/beartools/llm/runtime.py`
- Modify: `config/beartools.yaml.sample`
- Modify: `tests/test_config.py`
- Modify: `tests/test_llm_runtime.py`

- [ ] **Step 1: 运行 ruff 检查本次相关文件**

Run: `uv run ruff check src/beartools/config.py src/beartools/llm/runtime.py src/beartools/codex.py tests/test_config.py tests/test_llm_runtime.py tests/test_agent_factory.py`

Expected: `All checks passed!`

- [ ] **Step 2: 运行 mypy 检查项目类型正确性**

Run: `uv run mypy .`

Expected: `Success: no issues found`

- [ ] **Step 3: 运行本次改动核心测试集**

Run: `uv run pytest tests/test_config.py tests/test_llm_runtime.py tests/test_agent_factory.py -xvs`

Expected: PASS。

- [ ] **Step 4: 手工检查配置文案与错误信息**

```text
检查项：
1. `config/beartools.yaml.sample` 中不再出现 `primary` 与 `candidates`
2. 错误文案能明确指出失败的是 `large` 还是 `small`
3. 代码注释、测试命名、异常信息尽量统一使用 `large/small` 术语
```
