# LLM Runtime Node Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LLM 运行时节点选择从随机平权改为严格顺序优先，确保默认优先使用 `primary`，候选节点按配置顺序依次回退。

**Architecture:** 保持现有配置收集顺序 `[primary, *candidates]` 不变，只修改 `LLRuntime` 内部活动节点选择算法。通过在 `tests/test_llm_runtime.py` 先补失败测试，约束初始化选择、失效切换和非活动节点失效三类行为，再以最小实现改动替换随机选择逻辑。

**Tech Stack:** Python 3.13、pytest、unittest.mock、ruff、mypy

---

## 文件结构

- 修改：`src/beartools/llm/runtime.py`
  - 责任：LLM 运行时节点选择、失效标记、活动节点切换。
- 修改：`tests/test_llm_runtime.py`
  - 责任：覆盖运行时节点选择与失效切换行为。

### Task 1: 用测试锁定顺序优先选择行为

**Files:**
- Modify: `tests/test_llm_runtime.py:208-258`
- Test: `tests/test_llm_runtime.py`

- [ ] **Step 1: 写失败测试，覆盖初始化默认选 primary**

```python
    def test_runtime_prefers_primary_node_by_default(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate_a, candidate_b])

        assert runtime.get_active_node() is primary
        assert [node.name for node in runtime.available_nodes] == ["primary", "candidate-a", "candidate-b"]
```

- [ ] **Step 2: 运行单测确认它先失败**

Run: `uv run pytest tests/test_llm_runtime.py::TestLLRuntime::test_runtime_prefers_primary_node_by_default -xvs`

Expected: FAIL，当前实现可能命中随机节点，断言 `runtime.get_active_node() is primary` 失败。

- [ ] **Step 3: 写失败测试，覆盖主节点失效后按顺序切到第一个候选节点**

```python
    def test_runtime_falls_back_to_first_candidate_after_primary_failure(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate_a, candidate_b])
        changed = runtime.mark_node_failed(primary, error=StatusCodeError(503, "primary unavailable"))

        assert changed is True
        assert runtime.get_active_node() is candidate_a
        assert [node.name for node in runtime.available_nodes] == ["candidate-a", "candidate-b"]
```

- [ ] **Step 4: 运行单测确认它先失败**

Run: `uv run pytest tests/test_llm_runtime.py::TestLLRuntime::test_runtime_falls_back_to_first_candidate_after_primary_failure -xvs`

Expected: FAIL，当前实现会在剩余候选节点中随机选择，断言 `runtime.get_active_node() is candidate_a` 可能失败。

- [ ] **Step 5: 写失败测试，覆盖前序 candidate 失效后继续顺序回退**

```python
    def test_runtime_skips_failed_candidate_and_uses_next_candidate(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate_a, candidate_b])
        runtime.mark_node_failed(primary, error=StatusCodeError(503, "primary unavailable"))
        changed = runtime.mark_node_failed(candidate_a, error=StatusCodeError(503, "candidate-a unavailable"))

        assert changed is True
        assert runtime.get_active_node() is candidate_b
        assert [node.name for node in runtime.available_nodes] == ["candidate-b"]
```

- [ ] **Step 6: 运行单测确认它先失败**

Run: `uv run pytest tests/test_llm_runtime.py::TestLLRuntime::test_runtime_skips_failed_candidate_and_uses_next_candidate -xvs`

Expected: FAIL，如果前一个测试尚未修复，则这里的顺序回退行为同样不稳定。

- [ ] **Step 7: 写失败测试，覆盖非活动节点失效不改变当前活动节点**

```python
    def test_runtime_keeps_active_node_when_non_active_candidate_fails(self) -> None:
        primary = create_runtime_node("primary")
        candidate_a = create_runtime_node("candidate-a")
        candidate_b = create_runtime_node("candidate-b")

        runtime = runtime_module.LLRuntime(healthy_nodes=[primary, candidate_a, candidate_b])
        changed = runtime.mark_node_failed(candidate_b, error=StatusCodeError(503, "candidate-b unavailable"))

        assert changed is True
        assert runtime.get_active_node() is primary
        assert [node.name for node in runtime.available_nodes] == ["primary", "candidate-a"]
```

- [ ] **Step 8: 运行单测确认它先失败或保持为红灯集合的一部分**

Run: `uv run pytest tests/test_llm_runtime.py -k "prefers_primary_node_by_default or falls_back_to_first_candidate_after_primary_failure or skips_failed_candidate_and_uses_next_candidate or keeps_active_node_when_non_active_candidate_fails" -xvs`

Expected: 至少前 3 个新测试失败，说明顺序优先行为尚未实现。

### Task 2: 以最小实现替换随机选择逻辑

**Files:**
- Modify: `src/beartools/llm/runtime.py:66-117`
- Test: `tests/test_llm_runtime.py`

- [ ] **Step 1: 写最小实现，移除随机字段并改为顺序选择第一个可用节点**

```python
@dataclass(slots=True)
class LLRuntime:
    """公开运行时类型，供工厂与后续测试共享状态。"""

    healthy_nodes: list[RuntimeNode]
    _active_fingerprint: str | None = field(init=False, default=None, repr=False)
    _failed_fingerprints: set[str] = field(init=False, default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if not self.healthy_nodes:
            raise LLMRuntimeNoHealthyNodeError("LLM 运行时初始化失败：没有可用的健康节点")
        self._active_fingerprint = self._choose_active_fingerprint()

    def _choose_active_fingerprint(self, exclude_fingerprint: str | None = None) -> str | None:
        for node in self.healthy_nodes:
            if node.fingerprint in self._failed_fingerprints:
                continue
            if node.fingerprint == exclude_fingerprint:
                continue
            return node.fingerprint
        return None
```

- [ ] **Step 2: 运行新增测试，确认它们转绿**

Run: `uv run pytest tests/test_llm_runtime.py -k "prefers_primary_node_by_default or falls_back_to_first_candidate_after_primary_failure or skips_failed_candidate_and_uses_next_candidate or keeps_active_node_when_non_active_candidate_fails" -xvs`

Expected: PASS。

- [ ] **Step 3: 清理旧随机相关测试断言，使其匹配新行为**

将依赖 `random.Random.choice` 的测试改为顺序优先断言，例如把：

```python
    def test_sticky_selection_with_two_healthy_nodes(self) -> None:
        ...
        chosen_node = runtime_module.RuntimeNode.from_config(candidate_a)
        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
            patch("beartools.llm.runtime.random.Random.choice", autospec=True, return_value=chosen_node) as mock_choice,
        ):
            runtime = runtime_module.create_llm_runtime()

        assert [node.name for node in runtime.healthy_nodes] == ["primary", "candidate-a"]
        assert runtime.get_active_node().name == "candidate-a"
        assert mock_choice.call_count == 1
```

改成：

```python
    def test_runtime_prefers_first_healthy_node_during_initialization(self) -> None:
        primary = create_agent_node_config("primary", provider="openai")
        candidate_a = create_agent_node_config("candidate-a", provider="openrouter")
        candidate_b = create_agent_node_config("candidate-b", provider="openai")
        config = create_config(primary, candidate_a, candidate_b)

        def probe_node(node: _RuntimeNodeProtocol) -> None:
            if node.name == "candidate-b":
                raise TimeoutError("probe timed out")

        with (
            patch.object(runtime_module, "get_config", return_value=config),
            patch.object(runtime_module, "_probe_node", side_effect=probe_node),
        ):
            runtime = runtime_module.create_llm_runtime()

        assert [node.name for node in runtime.healthy_nodes] == ["primary", "candidate-a"]
        assert runtime.get_active_node().name == "primary"
        assert runtime.get_active_node().name == "primary"
        assert [node.name for node in runtime.available_nodes] == ["primary", "candidate-a"]
```

- [ ] **Step 4: 运行 `tests/test_llm_runtime.py` 全量测试，确认运行时相关行为全部通过**

Run: `uv run pytest tests/test_llm_runtime.py -xvs`

Expected: PASS。

### Task 3: 做最终静态检查与回归验证

**Files:**
- Modify: `src/beartools/llm/runtime.py`
- Modify: `tests/test_llm_runtime.py`
- Test: `tests/test_llm_runtime.py`

- [ ] **Step 1: 运行 ruff 检查运行时与测试文件**

Run: `uv run ruff check src/beartools/llm/runtime.py tests/test_llm_runtime.py`

Expected: `All checks passed!`

- [ ] **Step 2: 运行 mypy 检查运行时文件**

Run: `uv run mypy src/beartools/llm/runtime.py`

Expected: `Success: no issues found in 1 source file`

- [ ] **Step 3: 运行 LSP diagnostics 检查实现与测试文件**

Check:
- `src/beartools/llm/runtime.py`
- `tests/test_llm_runtime.py`

Expected: 无 diagnostics。

- [ ] **Step 4: 运行最终回归测试**

Run: `uv run pytest tests/test_llm_runtime.py tests/test_agent_factory.py -xvs`

Expected: PASS，确保节点优先级变更与工厂日志行为兼容。
