# LLFactory 与 LLRuntime 边界收口 TDD Plan

## 背景和目标

用户希望认真判断 `LLFactory` 和 `LLRuntime` 是否需要合并，并按 TDD flow 开发。

核心诉求：

- 统一从一个地方读取 LLM 配置中的 `base_url`、`api_key` 等信息。
- 可以得到所有配置候选列表。
- 调用方不关心具体模型，只关心 `small` / `large` 和 `openai` / `anthropic` 时，可以直接拿到一个合法 SDK client。
- `LLRuntime` 应成为 `LLFactory` 的内部逻辑，不再作为业务调用方的外部入口；是否保留该类，需要基于 codebase 调研后决定。
- 配置中所有 candidate 的 `name` 必须全局唯一：无论 `small` / `large`、`openai` / `anthropic`，一个 `name` 最多对应一个配置。
- `create_client()` / `create_async_client()` 必须执行当前 runtime 的探活机制：
  - 指定 `name`：该候选探活失败就抛异常；探活成功才返回 client。
  - 未指定 `name`：对所有符合 tier/provider 条件的候选按配置顺序依次探活，返回第一个成功的 client；全部失败则抛异常。
- 如果涉及依赖 `LLFactory` / `LLRuntime` 的重构，纳入本轮范围。

## 历史上下文

- `docs/plans/2026-05-16-llmfactory-client-refactor-plan.md` 已把 `LLFactory` 从 PydanticAI model 工厂改为 SDK client 工厂。
- `docs/plans/2026-05-17-llruntime-refactor-plan.md` 已把 `LLRuntime` 收口为 `list_models()`、`create_client()`、`create_async_client()`，并把 `LLFactory` 改成基于 runtime 的薄包装。
- `docs/codemap.md` 当前记录：`llm/runtime.py` 管节点池、探活、去重、故障标记和轮换；`llm/factory.py` 是公开轻量入口。
- 当前代码中 `model_check.py`、`bill/agent.py`、`gmail.py`、`memory/service.py`、`prompt/evaluator.py` 已基本通过 `LLFactory` 或 runtime summary 新链路调用，但仍有业务模块直接导入 `get_llm_runtime()`。
- 当前配置校验已经支持 `openai` / `anthropic`，并移除了 `openrouter` provider。

## 现状调研结论

### 代码现状

- `src/beartools/llm/runtime.py`
  - `RuntimeNode` 保存敏感字段：`base_url`、`api_key`、`extra_headers`、`fingerprint` 等。
  - `LLRuntime` 当前仍公开 `available_nodes`、`available_nodes_for_tier()`、`get_active_node()`、`mark_node_failed()` 等旧接口。
  - `LLRuntime.create_client(name, tier)` 和 `create_async_client(name, tier)` 已有，但只支持指定 `name`，不支持未指定时遍历候选。
  - `create_llm_runtime()` 初始化时会探活并只保留健康节点；这会让“所有配置列表”和“实时按候选探活 fallback”混在一起。
- `src/beartools/llm/factory.py`
  - 已是较薄的公开入口，但候选选择依赖 `get_llm_runtime().list_models()`，这意味着候选列表目前来自健康 runtime，而不是原始配置。
  - `LLFactory.create_client()` 未指定 `name/model` 时会选第一个 summary，再调用 runtime 创建 client；如果该节点二次探活失败，不会继续尝试下一个符合条件候选。
  - 生产代码没有直接调用 `LLFactory.create_client(model=...)` / `create_async_client(model=...)`；只有 `model check --model-name` 支持按候选 `name` 或真实 `model` 过滤，最终仍按 `name` 创建 client。
- `src/beartools/config.py`
  - 解析 `agent.large` / `agent.small`，但目前没有校验跨 tier / provider 的 name 全局唯一。
- 调用方
  - `model_check.py` 通过 `LLRuntime.list_models()` 枚举模型，再用 `LLFactory().create_client(name=...)` 创建 client。
  - `bill/agent.py`、`gmail.py`、`memory/service.py`、`prompt/evaluator.py` 仍不同程度依赖 `get_llm_runtime().list_models()` 先取 summary，再走 factory 创建 client。

### 是否合并的判断

不建议把 `LLFactory` 和 `LLRuntime` 物理合并成一个巨类。

推荐方向是“公开入口合并，内部实现保留”：

- 对外只推荐 `LLFactory`，业务模块不再直接依赖 `LLRuntime`。
- `LLRuntime` 保留为 `LLFactory` 的内部实现类，负责敏感节点、探活、失败原因聚合、SDK client 构建等运行时细节。
- `LLRuntime` 不再作为业务模块公开调用面；可以继续存在于 `runtime.py`，但从 `__all__` 和普通业务导入中移出，测试可通过 factory 行为覆盖。

原因：

- `LLRuntime` 有明确状态职责，包含探活、节点实例、失败状态和 SDK client 构建；直接塞进 `LLFactory` 会让公开类承担过多实现细节。
- 用户真正想合并的是调用方视角和配置入口，而不是删除运行时状态对象。
- 保留内部类可以降低回归风险，也便于未来扩展探活策略、失败原因记录和 provider 差异。

## 非目标

- 不新增 CLI 命令或参数。
- 不改变 `config/beartools.yaml` 的现有 agent 配置结构。
- 不把 `api_key`、`base_url` 等敏感字段暴露给业务调用方或列表返回值。
- 不支持 `openrouter` provider 回退。
- 不做 Anthropic 结构化输出适配；账单等 OpenAI-only 业务仍只选 OpenAI client。

## Brainstorm 选项和推荐方案

### 方案 A：物理合并为一个 `LLFactory` 类

- 做法：删除或基本掏空 `LLRuntime`，把探活、节点池、失败标记、client 构建都放进 `LLFactory`。
- 优点：类数量少，名字上最符合“合并”。
- 风险：`LLFactory` 变成上帝类；公开入口和运行时状态难以隔离；测试会更脆，后续 provider 扩展也更难。

### 方案 B：`LLFactory` 作为唯一公开门面，`LLRuntime` 保留为内部实现

- 做法：新增/调整 `LLFactory` 公共能力，业务调用方只用 factory；runtime 负责内部候选、探活、client 构建。
- 优点：满足用户的三条核心诉求，同时保持职责清晰。
- 风险：需要迁移当前直接导入 `get_llm_runtime()` 的业务模块和测试。

### 方案 C：维持现状，只补 name 唯一和 fallback 探活

- 做法：继续让业务模块同时依赖 factory/runtime，只修行为 bug。
- 优点：改动最小。
- 风险：无法满足“`LLRuntime` 是 `LLFactory` 内部逻辑，不对外”的诉求，后续调用方仍会绕开统一入口。

推荐采用方案 B。

## 推荐设计

### 公开类型

新增或调整公开候选摘要类型，例如：

```python
@dataclass(frozen=True, slots=True)
class LLMCandidate:
    name: str
    tier: AgentTier
    provider: Literal["openai", "anthropic"]
    model: str
```

说明：

- `model` 可公开，因为它本身已经用于 `model check --model-name` 等非敏感筛选。
- 不公开 `base_url`、`api_key`、`extra_headers`、`fingerprint`。

### `LLFactory` 公开接口

保留并收口为：

```python
class LLFactory:
    def list_candidates(
        self,
        *,
        type: ProviderType = "any",
        model_size: AgentTier,
    ) -> list[LLMCandidate]: ...

    def create_client(
        self,
        *,
        name: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> SyncLLMClient: ...

    async def create_async_client(
        self,
        *,
        name: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> AsyncLLMClient: ...
```

兼容说明：

- `LLFactory.create_client()` / `create_async_client()` 不保留 `model` 参数；新业务只能按唯一 `name`，或只指定 `type/model_size` 让 factory 自动选择第一个可探活候选。
- `model check --model-name` 是现有 CLI 行为，继续由 `model_check.py` 在 `list_candidates()` 结果上按候选 `name` 或真实 `model` 过滤，再传 `name` 给 factory 创建 client。
- `type` 继续支持 `openai` / `anthropic` / `any`。
- `model_size` 必须显式指定，继续支持 `small` / `large`；不支持 `None` 或跨 tier 全量查询。

### 候选列表语义

- `LLFactory.list_candidates()` 返回配置中的所有候选，不做探活，不依赖健康 runtime 缓存。
- 过滤逻辑只看配置字段：tier 和 provider。
- 返回顺序保持指定 tier 的配置顺序。

### 创建 client 语义

- 指定 `name`：
  - 因为配置层保证 name 全局唯一，所以只匹配一个配置候选。
  - 若该候选不满足 `type/model_size` 过滤，抛 `LLFactoryError`。
  - 对该候选执行探活；失败则抛异常，不自动 fallback。
  - 探活成功后返回对应 SDK client。
- 未指定 `name`：
  - 在符合 `type/model_size` 的所有候选中按配置顺序逐个探活。
  - 返回第一个探活成功 client。
  - 全部失败则抛异常并包含脱敏后的候选失败原因。

### 配置唯一性

- 在 `config.py` 解析完 `agent.large` 和 `agent.small` 后校验所有 candidate `name` 全局唯一。
- 重复时抛 `RuntimeError`，错误信息明确指出重复 name。

### `LLRuntime` 处理方向

- 保留 `LLRuntime` 类，但它不再是业务调用方入口。
- `LLRuntime` 可以继续留在 `runtime.py`，但建议：
  - 从 `__all__` 中移除 `get_llm_runtime`、`get_active_llm_node`、`mark_active_llm_node_failed` 等旧公开入口。
  - 删除或降级 `available_nodes`、`available_nodes_for_tier()`、`get_active_node()`、`mark_node_failed()` 的业务可见用法。
  - 新增内部方法支持按候选配置创建并探活 client，或由 `LLFactory` 组装候选再调用 runtime 内部函数。

## Grill Gate

已按 `grill-me` skill 做遗漏检查；能通过读代码回答的问题已自行探索。

问题：`LLRuntime` 是否应该彻底删除？

推荐答案：不删除。它承载敏感运行时节点、探活和 SDK 构建，保留为 `LLFactory` 内部实现更稳。

结论：采用“不公开但保留内部类”。

问题：候选列表应该是“所有配置”还是“健康节点”？

推荐答案：所有配置。用户明确要求得到所有配置列表，且 create 阶段另有探活规则；如果列表阶段就过滤健康节点，会混淆配置可见性和运行时可用性。

结论：`LLFactory.list_candidates()` 返回所有配置候选，不探活。

问题：`name` 唯一范围是单个 tier 内还是全局？

推荐答案：全局。用户明确说无论 `small` / `large`、`openai` / `anthropic`，一个 `name` 最多对应一个配置。

结论：在配置解析层做全局唯一校验。

问题：未指定 name 时，探活失败是否应标记节点失败并影响后续调用？

推荐答案：本轮不依赖长期失败状态，按当前调用即时探活并选择第一个成功候选。长期失败缓存可保留为 runtime 内部优化，但不能让“所有配置列表”变成“仅健康列表”。

结论：选择 client 时按候选逐个探活，失败继续下一个；失败原因脱敏聚合。

## 影响范围

- `src/beartools/config.py`
- `src/beartools/llm/runtime.py`
- `src/beartools/llm/factory.py`
- `src/beartools/model_check.py`
- `src/beartools/bill/agent.py`
- `src/beartools/gmail.py`
- `src/beartools/memory/service.py`
- `src/beartools/prompt/evaluator.py`
- `tests/test_config.py`
- `tests/test_llm_runtime.py`
- `tests/test_agent_factory.py`
- `tests/test_model_check.py`
- `tests/test_bill_agent.py`
- `tests/test_memory_service.py`
- `tests/test_prompt_evaluator.py`
- `docs/codemap.md`

## 重要接口变更清单

### 新增接口

- `LLFactory.list_candidates(type="any", model_size=<small|large>)`
- `LLMCandidate`

### 删除接口

- 对业务调用方删除 `get_llm_runtime()` 直接依赖。
- 计划不再推荐 `LLRuntime` 作为公开业务入口。

### 修改接口

- `LLFactory.create_client()` / `create_async_client()`：
  - 指定 `name` 时探活失败即抛。
  - 未指定 `name` 时对符合条件的候选逐个探活，返回第一个成功 client。
  - 若全部探活失败，抛出清晰异常。
  - 移除 `model` 参数。
- `config.py`：
  - `agent.large` + `agent.small` 所有候选 `name` 必须全局唯一。

### 无接口变更

- CLI 命令和参数不变。
- 配置 YAML 结构不变。
- REST API 不涉及。
- 数据库结构不变。

## TDD / 测试策略

Test Writer 先写红灯，重点覆盖：

- `config.py` 拒绝跨 tier 重复 name。
- `config.py` 拒绝同 tier 重复 name。
- `LLFactory.list_candidates()` 返回所有配置候选，不探活，且不泄露 `base_url/api_key/extra_headers`。
- `LLFactory.list_candidates()` 必须显式指定 `model_size`。
- `LLFactory.create_client(name=...)` 指定 name 时只探活该候选，探活失败抛异常，不 fallback。
- `LLFactory.create_client(type="openai", model_size="small")` 未指定 name 时按配置顺序探活，跳过失败候选，返回第一个成功候选。
- `LLFactory.create_async_client(...)` 与同步路径保持一致。
- `LLFactory.create_client(model=...)` / `create_async_client(model=...)` 不再存在；`model check --model-name` 的兼容筛选留在 `model_check.py` 内部完成。
- `model_check.py`、`bill/agent.py`、`gmail.py`、`memory/service.py`、`prompt/evaluator.py` 不再直接依赖 `get_llm_runtime()`。

红灯预期：

- 当前配置层没有 name 全局唯一校验。
- 当前 `LLFactory` 没有 `list_candidates()`。
- 当前 `LLFactory` 未指定 name 时二次探活失败不会继续 fallback。
- 当前 `LLFactory` 仍支持 `model` 参数。
- 当前多个调用方仍直接导入或调用 `get_llm_runtime()`。

## Verify 标准

### 自动化验证

最小验证：

```bash
uv run pytest tests/test_config.py tests/test_agent_factory.py tests/test_llm_runtime.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py -xvs
uv run ruff check src/beartools/config.py src/beartools/llm/runtime.py src/beartools/llm/factory.py src/beartools/model_check.py src/beartools/bill/agent.py src/beartools/gmail.py src/beartools/memory/service.py src/beartools/prompt/evaluator.py tests/test_config.py tests/test_agent_factory.py tests/test_llm_runtime.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py
uv run mypy .
```

完整验证：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

### 冒烟端到端验证

```bash
uv run beartools model check --help
uv run beartools check eval --help
uv run beartools diary summary --help
uv run beartools bill --help
```

预期：CLI 帮助正常显示，证明迁移没有破坏主要命令入口。

### 全面端到端验证

建议执行真实 LLM 小样本：

```bash
uv run beartools model check --id math-1 --model-name <一个small候选name> --output output/llfactory-runtime-small-smoke.md
uv run beartools model check --id math-1 --model-name <一个large候选name> --output output/llfactory-runtime-large-smoke.md
```

预期：

- small 和 large 各至少一个真实候选能完成单题评测。
- 如果真实网关、密钥、套餐或 Responses 兼容性失败，记录具体命令和脱敏错误，作为外部环境阻塞。
- Anthropic 真实 E2E 仅在本地配置存在 Anthropic 候选且不消耗高风险数据时执行；否则记录为不适用。

## 分步实施计划

1. Planner：写入本计划，等待用户确认 Planner Exit。
2. Test Writer：先改测试，跑最小测试确认红灯。
3. Executor：
   - 配置层加入 candidate name 全局唯一校验。
   - `LLFactory` 新增候选列表和逐候选探活 fallback。
   - 将业务调用方从 `get_llm_runtime()` 迁移到 `LLFactory`。
   - 收口 runtime 旧公开入口，保留内部实现。
4. Verify：执行自动化最小验证、完整验证、CLI help 冒烟和真实 model check E2E。
5. Reviewer：按 `docs/checklists/review.md` 做只读审查，重点看接口回归、敏感信息泄露和外部请求错误处理。
6. Fix Loop：修复 Verify/Review 问题并复测。
7. Documentation Sync：更新本计划最终实现记录和 `docs/codemap.md`。

## 风险、回滚和需确认问题

风险：

- 直接移除 `get_llm_runtime()` 可能影响测试或边缘调用方，需要用 `rg` 验证生产代码引用清零。
- `LLMCandidate` 仍公开真实 `model`，用于 SDK 请求、报告展示和 `model check --model-name` 兼容筛选；但 `LLFactory` 创建接口不再支持按 `model` 选择，唯一主键是 `name`。
- 真实 E2E 受外部网关、密钥和额度影响，失败不一定代表代码错误。

回滚：

- 保留 `LLFactory.create_*` 新行为，暂时只把 `get_llm_runtime()` 标记为内部兼容，不立刻删除导出。
- 如果调用方迁移范围过大，可先完成 factory 行为和配置唯一校验，再分批清理业务直接 runtime 引用。

需确认问题：

- 是否确认采用“`LLFactory` 作为唯一公开入口，`LLRuntime` 保留为内部实现”而不是物理删除 `LLRuntime`？
- 是否确认 `list_candidates()` 返回指定 `model_size` 下的所有配置候选、不做探活？
- 是否确认三类 Verify 标准，尤其真实 model check small/large E2E 会调用外部模型并可能消耗 token？

## 用户确认记录

- 用户通过 diff comment 确认采用方案 B：`LLFactory` 作为唯一公开入口，`LLRuntime` 保留为内部实现。
- 用户要求 `model_size` 不可以是 `None`，必须指定一个 tier。
- 用户判断 `LLFactory.create_client()` / `create_async_client()` 应该不保留 `model` 参数；代码搜索确认生产调用方没有直接按 `model` 创建 client。
- 现有 `model check --model-name` 仍支持按真实 `model` 过滤，这是 CLI 既有行为；实现上保留在 `model_check.py` 内部，最终仍按唯一 `name` 调 factory。
- 用户确认其他模块中引用 `LLRuntime` 的地方需要删除。
- 用户在后续 diff review 中要求去掉 `ClientT` 泛型抽象，并将核心流程收为“匹配配置 -> for 配置探活 -> 成功即创建并返回 client -> 全部失败抛异常”。
- 用户进一步指出 `LLRuntime` 可以大幅压缩，SDK client 创建应只在 `LLFactory` 中完成。
- 用户继续指出 `probe_runtime_node(node)` 中的 `node` 类型应为已经创建好的 `SyncLLMClient`，即探活对象应是 client，而不是 `RuntimeNode`。

## 最终实现记录

- `config.py` 新增 agent candidate `name` 全局唯一校验，覆盖 large/small 和 openai/anthropic 全部候选。
- `LLFactory` 新增 `LLMCandidate` 和 `list_candidates(type=..., model_size=...)`；`model_size` 为必填，列表不探活、不暴露 `base_url/api_key/extra_headers`。
- `LLFactory.create_client()` / `create_async_client()` 移除 `model` 参数；指定 `name` 时只创建并探活该节点 client，失败时抛出原异常；未指定 `name` 时按配置顺序逐个创建 client、探活并返回第一个成功 client。
- `LLFactory` 内部已去掉 `ClientT`/`Callable` 泛型 helper；同步和异步入口都显式执行同一条流程：匹配配置、创建 SDK client、用该 client 探活、成功后返回同一个 client。
- `model_check.py`、`bill/agent.py`、`gmail.py`、`memory/service.py`、`prompt/evaluator.py`、`commands/doctor/checks/llm.py` 均已迁移为通过 `LLFactory` 获取候选或 client，不再直接依赖 `get_llm_runtime()` / `LLRuntime`。
- `beartools.llm.__init__` 不再 re-export `LLRuntime`；`runtime.py` 已移除 `LLRuntime` 节点池、active node、runtime singleton 和 SDK client 构建函数，仅保留 `RuntimeNode`、同步/异步 SDK client 探活和探活响应校验等底层工具。
- `docs/codemap.md` 已同步 LLM factory/runtime 新职责边界。

## 最终 Verify 结果

Test Writer 红灯：

```bash
uv run pytest tests/test_config.py tests/test_agent_factory.py tests/test_llm_runtime.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py -xvs
```

结果：失败在 `ImportError: cannot import name 'LLMCandidate' from 'beartools.llm.factory'`，证明新公开候选接口尚未实现。

自动化验证：

```bash
uv run pytest tests/test_config.py tests/test_agent_factory.py tests/test_llm_runtime.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py -xvs
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

结果：

- 最小测试：120 passed。
- 全量测试：386 passed。
- `ruff check .`：通过。
- `mypy .`：通过，71 source files。

后续 diff review 补充验证：

```bash
uv run pytest tests/test_agent_factory.py tests/test_llm_runtime.py -xvs
uv run ruff check src/beartools/llm/factory.py src/beartools/llm/runtime.py tests/test_agent_factory.py tests/test_llm_runtime.py
uv run mypy .
```

结果：

- factory/runtime 聚焦测试：14 passed。
- 聚焦 ruff：通过。
- `mypy .`：通过。

冒烟端到端验证：

```bash
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools model check --help
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools check eval --help
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools diary summary --help
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools bill --help
```

结果：四条 help 冒烟均通过。

全面端到端验证：

```bash
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools model check --id math-1 --model-name aiba-1 --output output/llfactory-runtime-small-smoke.md
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools model check --id math-1 --model-name naiba --output output/llfactory-runtime-large-smoke.md
```

结果：

- `small`：`aiba-1 / gpt-5.4-mini`，1/1 correct，0 errors，报告写入 `output/llfactory-runtime-small-smoke.md`。
- `large`：`naiba / gpt-5.4`，1/1 correct，0 errors，报告写入 `output/llfactory-runtime-large-smoke.md`。
- 当前本地配置未包含 Anthropic 候选，因此 Anthropic 真实 E2E 不适用。

## Documentation Sync 结果

- 已更新本计划文档，记录最终实现、验证结果、用户确认和偏离点。
- 已更新 `docs/codemap.md`，同步 `LLFactory` 作为统一公开入口、`LLRuntime` 作为内部实现、`list_candidates()` 与 `model_size` 必填等稳定事实。
