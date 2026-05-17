# LLRuntime 重构 TDD Plan

## 背景和目标

本轮按 `docs/workflows/codex-tdd-flow.md` 执行，目标是围绕 `src/beartools/llm/runtime.py` 做一轮收口式重构，重点满足以下需求：

- `RuntimeNode` 继续持有节点密钥等敏感配置，不把这些信息拆到类外的平行结构中。
- `LLRuntime` 对外暴露的数据只保留 `name`、`AgentTier`、`ProviderType`。
- `LLRuntime` 对外暴露的核心接口收敛为：
  - 指定 `name`、`AgentTier` 获取对应 client。
  - 指定 `ProviderType(openai/anthropic/any)`、`AgentTier` 获取 `(name, AgentTier, ProviderType)` 列表。

## 历史上下文

- `docs/plans/2026-05-16-llmfactory-client-refactor-plan.md` 已把 `LLFactory` 收口到 SDK client factory，但当前节点选择、探测、失败切换仍分散在 `LLRuntime` 和 `LLFactory` 之间。
- 当前 `RuntimeNode` 是公开 dataclass，直接暴露 `base_url/api_key/extra_headers/model/fingerprint`。
- 当前配置和实现里仍存在 `openai/openrouter` 双口径，带来 provider 语义二义性。
- 当前 `LLRuntime` 仍对外暴露：
  - `large_nodes` / `small_nodes`
  - `available_nodes` / `available_nodes_for_tier()`
  - `get_active_node()`
  - `mark_node_failed()`
- 当前 `LLFactory` 仍依赖外部可见 `RuntimeNode`，`model_check.py` 也会自己构造 `RuntimeNode`。
- `bill/agent.py` 仍直接拿 `LLRuntime` 做节点轮换。
- `gmail.py`、`memory/service.py`、`prompt/evaluator.py` 仍使用 `get_openai_compatible_node()` + `create_async_client_for_node(node)` 旧链路。

## 现状问题

1. `LLRuntime` 的“对外能力”和“内部节点状态”耦合在一起，调用方不仅能选 client，还能读到敏感配置与故障切换细节。
2. `RuntimeNode` 被多个模块和测试直接引用，导致 runtime 很难收口为稳定 façade。
3. 同一套“节点选择 + 节点探测 + client 构建”能力目前散落在 `runtime.py`、`factory.py`、`bill/agent.py`、`model_check.py`。

## 非目标

- 本轮不改变配置文件格式，不新增新的 provider 配置项。
- 本轮不新增第三种 tier，也不改 `doctor` / `bill` / `model check` 的业务语义。
- 本轮不做跨模块大规模设计翻新，例如把所有 LLM 访问统一为新的 service 层。

## Brainstorm 选项

### 方案 A：以 `LLRuntime` 为主要公开 façade，`RuntimeNode` 退回内部实现，并继续保留 `LLFactory`

- 做法：
  - `RuntimeNode` 继续存在并持有敏感配置，但降为 `runtime.py` 内部实现细节。
  - 新增公开轻量描述类型，只包含 `name`、`tier`、`provider`。
  - `LLRuntime` 直接提供选 client、列节点摘要；`LLFactory` 继续保留，但改成基于 `LLRuntime` 的薄包装。
  - 去掉 `openrouter` provider，统一只保留 `openai` / `anthropic` / `any` 语义，并同步迁移配置。
- 优点：
  - 最贴合本轮需求，外部面最干净。
  - `bill` / `model_check` 不再依赖 `RuntimeNode`。
  - `LLFactory` 继续保留后，外部调用方迁移成本更可控。
- 风险：
  - 会改动 `factory.py`、`model_check.py`、`bill/agent.py`、配置样例和相关测试，影响面较大。

### 方案 B：保留 `LLFactory` 为公开入口，`LLRuntime` 只新增摘要接口

- 做法：
  - `RuntimeNode` 仍公开，但尽量不在新代码里直接使用。
  - `LLRuntime` 只补一层摘要查询；真正 client 创建仍由 `LLFactory` 暴露。
- 优点：
  - 改动更小。
- 风险：
  - 不能真正满足“`LLRuntime` 对外接口就这些”的目标，旧公开面仍残留。

### 方案 C：把敏感配置迁到独立 secrets/store 结构

- 做法：
  - 公开 `RuntimeNode` 只留非敏感字段，敏感字段放外部映射。
- 优点：
  - 更容易做序列化与外部展示。
- 风险：
  - 直接违背“key 信息不要堆外”的要求。

## 推荐方案

采用方案 A。

原因：

- 它和你给的接口目标对齐，同时保留 `LLFactory` 这个现有入口，迁移风险更可控。
- 可以把“敏感配置仍在 `RuntimeNode` 内部持有”和“外部只看见摘要/客户端”同时满足。
- 顺手去掉 `openrouter` / `openai` 二义性，避免后续接口和配置继续扩散双口径。

## 推荐设计草案

### 1. 公开数据模型

- 保留 `AgentTier`。
- `ProviderType` 以 runtime 层统一复用，允许 `openai`、`anthropic`、`any`；其中节点摘要只返回真实 provider，不返回 `any`。
- 新增公开轻量描述，例如：

```python
@dataclass(frozen=True, slots=True)
class RuntimeNodeSummary:
    name: str
    tier: AgentTier
    provider: ProviderType
```

### 2. 内部节点模型

- `RuntimeNode` 继续保存：
  - `name`
  - `provider`
  - `base_url`
  - `model`
  - `api_key`
  - `extra_headers`
  - `timeout_seconds`
  - `fingerprint`
- 但它不再作为 runtime 对外契约暴露给业务模块和普通测试。

### 3. LLRuntime 对外接口

计划收敛为以下公开方法：

- `create_client(name: str, tier: AgentTier) -> SyncLLMClient`
- `create_async_client(name: str, tier: AgentTier) -> AsyncLLMClient`
- `list_models(provider: ProviderType, tier: AgentTier) -> list[RuntimeNodeSummary]`

### 4. LLFactory 的处理方向

- 继续保留 `LLFactory` 作为公开入口。
- `LLFactory` 的角色改为基于 `LLRuntime` 的薄包装，不再自行暴露 `RuntimeNode`。
- 目标是不让新业务继续依赖 `RuntimeNode`，同时减少现有调用方震荡。

### 5. 节点选择规则

- `create_client(name, tier)`：
  - 只在指定 tier 内按 `name` 精确匹配节点。
  - 若同名节点重复，沿用配置顺序取第一个健康节点。
  - 构建前仍做 probe；探测失败沿用失败标记和切换逻辑。
- `list_models(provider, tier)`：
  - 只返回指定 tier 的健康节点摘要。
  - `provider="any"` 返回该 tier 所有健康节点。
  - `provider="openai"` 只匹配 `openai`。

### 6. provider 收口与配置迁移

- 去掉 `openrouter` provider 兼容和归一逻辑，只保留 `openai` / `anthropic` / `any`。
- 主要修改 `config/beartools.yaml`，把现有 `openrouter` provider 改成 `openai`。
- 更新 `config/beartools.yaml.sample`，去掉 `openrouter` 示例和说明。
- 更新 `config/beartools.secrets.yaml.sample`，把 `agent.openrouter.key` 改成 `agent.openai.key`。
- 同步调整 `config.py` 校验逻辑，不再接受 `openrouter`。
- 同步调整相关 secrets 引用命名和测试数据，避免 provider 已改但配置语义仍残留 `openrouter`。

## Grill Gate

### 已通过代码探索回答的问题

- `RuntimeNode` 目前已直接暴露敏感配置，且被 `factory.py`、`model_check.py`、`bill/agent.py` 和多组测试直接依赖。
- `model_check.py` 当前自己从配置构造 `RuntimeNode`，并把完整节点对象传给 `LLFactory.create_client_for_node()`。
- `bill/agent.py` 当前自己驱动 `runtime.get_active_node()` + `runtime.mark_node_failed()`。

### 已确认的关键决策

1. 采用方案 A。
2. 不需要 `utils` 公开接口。
3. 继续保留 `LLFactory`。
4. 去掉 `openrouter` 与 `openai` 的二义性，只保留 `openai`。
5. 把配置迁移纳入本轮范围，重点修改 `config/beartools.yaml`，并同步覆盖 `config.py` 与 `config/beartools.yaml.sample`。
6. `model check` 改成完全走 `LLRuntime.list_models(...)` 的公开链路，不再自己构造/持有 `RuntimeNode`。
7. `bill/agent.py` 也只走公开链路，不再直接操作 runtime 内部节点状态。
8. `gmail.py`、`memory/service.py`、`prompt/evaluator.py` 一起迁到新的公开链路。
9. `config/beartools.secrets.yaml.sample` 和相关测试中的 `agent.openrouter.key` 一起改成 `agent.openai.key`。

### 遗漏检查结论

- 最大风险不是 client 构建本身，而是“旧的 `RuntimeNode` 公开引用”会导致测试和调用方大面积断裂。
- 因为 `doctor` 的 LLM 检查只读 `name/base_url/model`，它大概率只需要轻量适配，不是主风险点。
- `bill` 是当前最依赖 runtime 内部状态的业务模块，需要优先纳入测试。

## 影响范围

- `src/beartools/llm/runtime.py`
- `src/beartools/llm/factory.py`
- `src/beartools/config.py`
- `src/beartools/model_check.py`
- `src/beartools/bill/agent.py`
- `src/beartools/gmail.py`
- `src/beartools/memory/service.py`
- `src/beartools/prompt/evaluator.py`
- `config/beartools.yaml`
- `config/beartools.yaml.sample`
- `config/beartools.secrets.yaml.sample`
- `tests/test_llm_runtime.py`
- `tests/test_agent_factory.py`
- `tests/test_model_check.py`
- `tests/test_bill_agent.py`
- `tests/test_memory_service.py`
- `tests/test_prompt_evaluator.py`
- `tests/test_config.py`
- 可能波及 `tests/test_doctor.py`
- `docs/codemap.md`

## 重要接口变更清单

### 新增接口

- `LLRuntime.create_client(name, tier)`
- `LLRuntime.create_async_client(name, tier)`
- `LLRuntime.list_models(provider, tier)`
- `RuntimeNodeSummary`

### 删除接口

- `LLRuntime.get_active_node()`
- `LLRuntime.available_nodes`
- `LLRuntime.available_nodes_for_tier()`
- `LLFactory.create_client_for_node(node)`
- `LLFactory.create_async_client_for_node(node)`

### 修改接口

- `LLRuntime` 的公开数据面从完整 `RuntimeNode` 改为轻量摘要。
- `LLFactory` 改为继续保留，但内部改走 `LLRuntime`。
- `ProviderType` 统一收敛为 `openai` / `anthropic` / `any`。

### 无接口变更

- CLI 命令和参数面预计无变化。
- 配置文件结构预计无变化，但 provider 可选值会变化。

## TDD / 测试策略

Test Writer 先写红灯，优先覆盖：

- `LLRuntime.list_models(provider, tier)` 只返回 `(name, tier, provider)` 摘要。
- `LLRuntime.create_client(name, tier)` 不要求调用方持有 `RuntimeNode`。
- `RuntimeNode` 的敏感字段不再通过 runtime 公开接口直接暴露。
- `LLFactory` 继续保留，但不再要求外部传 `RuntimeNode`。
- `openrouter` provider 被移除，`config.py` 和 sample 配置同步收口到 `openai`。
- `config/beartools.secrets.yaml.sample` 与测试里的 `agent.openrouter.key` 改成 `agent.openai.key`。
- `bill/agent.py` 不再直接操作 `get_active_node()` / `mark_node_failed()`。
- `model_check.py` 不再在业务路径上依赖外部可见 `RuntimeNode`，改走 `LLRuntime.list_models(...)`。
- `gmail.py`、`memory/service.py`、`prompt/evaluator.py` 不再依赖 `get_openai_compatible_node()` + `create_async_client_for_node(node)` 旧链路。

红灯预期：

- 当前代码没有 `LLRuntime.create_client(name, tier)` / `list_models(provider, tier)`。
- 当前代码仍公开 `available_nodes*` / `get_active_node()`。
- 当前 `LLFactory` 仍要求 `RuntimeNode` 参与部分调用。
- 当前 `model_check.py` / `bill/agent.py` 仍直接依赖 `RuntimeNode` 或 runtime 内部状态。
- 当前 `gmail.py`、`memory/service.py`、`prompt/evaluator.py` 仍依赖旧 OpenAI 节点选择链路。

## Verify 标准

### 自动化验证

最小验证：

```bash
uv run pytest tests/test_llm_runtime.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py tests/test_config.py -xvs
uv run ruff check src/beartools/llm/runtime.py src/beartools/llm/factory.py src/beartools/config.py src/beartools/model_check.py src/beartools/bill/agent.py src/beartools/gmail.py src/beartools/memory/service.py src/beartools/prompt/evaluator.py tests/test_llm_runtime.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py tests/test_config.py
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
uv run beartools bill --help
uv run beartools model check --id <某个题目ID> --model-name <某个可用模型名>
```

说明：

- 本轮先把 help 冒烟作为强制项。
- 使用 `model check` 做真实单题 smoke，验证重构后的 runtime/client 选择链路可用。
- `bill --help` 继续保留为 CLI 调用面冒烟，但不作为真实 LLM E2E 证据主体。

### 全面端到端验证

- 使用 `model check` 做真实 E2E 验证。
- 至少覆盖：
  - 一个 `small` tier 模型
  - 一个 `large` tier 模型
- 验证目标：
  - `LLRuntime.list_models()` 返回的模型可被 `model check` 识别和过滤
  - `LLRuntime.create_client(name, tier)` / `LLFactory` 薄包装链路能拿到正确 client
  - provider 收口到 `openai/anthropic/any` 后，`model check` 主路径无回归
- 若本地配置里存在 `anthropic` 节点，则尽量补一条 `anthropic` 的 `model check` 或至少补 factory/runtime 选择证据；若受网关能力限制失败，要记录失败命令和错误。
- 风险：
  - 真实 E2E 仍受本地密钥、网关兼容性、套餐额度影响。
  - 若 `model check` 题库或远端模型不稳定，可能出现与本次重构无关的波动。

## 分步实施计划

1. Planner：确认重要接口变更清单和三类 Verify 标准。
2. Test Writer：先写 runtime/factory/model_check/bill 的红灯测试。
3. Executor：
   - 收口 runtime 公开接口。
   - 保留并瘦身 `LLFactory`。
   - 收口 provider 语义，修改 `config.py` 与 sample 配置。
   - 迁移 `bill` / `model_check`。
   - 修正其余受影响测试和调用方。
4. Verify：先最小验证，再完整验证，再做 CLI help 冒烟。
   - 再用 `model check` 跑真实 E2E（至少 small/large 各一条）。
5. Reviewer：按 `docs/checklists/review.md` 做只读审查。
6. Documentation Sync：更新本计划与 `docs/codemap.md`。

## 风险和回滚

- 风险：
  - `RuntimeNode` 被多个测试直接引用，改动后测试重写量会偏大。
  - 去掉 `openrouter` 后，旧配置若未迁移会直接校验失败。
  - 若一次性删掉过多旧接口，可能让 `doctor` 或其他边缘路径跟着断裂。
- 回滚：
  - 如发现外部调用面收缩过快，可先保留旧接口为内部兼容层，但不让新业务继续调用，并在计划中记录偏离。

## 需确认问题

当前已无阻塞性设计问题；若你认可下面这版 Planner Exit 摘要，就可以进入 Test Writer。

## 最终实现记录

- `LLRuntime` 新增 `RuntimeNodeSummary`，公开数据面收敛为 `name`、`tier`、`provider`。
- `LLRuntime` 新增 `list_models()`、`create_client()`、`create_async_client()` 作为公开主链路。
- `RuntimeNode` 继续持有 `base_url/model/api_key/extra_headers/timeout_seconds/fingerprint` 等敏感或实现字段。
- `LLFactory` 保留，但改成基于 `LLRuntime` 的薄包装；`create_client_for_node()` / `create_async_client_for_node()` 已移除。
- `model check` 改为通过 `LLRuntime.list_models()` 枚举公开模型，再按 `name + tier` 创建 client。
- `bill`、`gmail`、`memory/service`、`prompt/evaluator` 已迁到新的公开链路。
- `provider` 收口为 `openai` / `anthropic` / `any`；`openrouter` 已从配置校验与样例中移除。
- `config/beartools.yaml`、`config/beartools.yaml.sample`、`config/beartools.secrets.yaml.sample` 已同步改为 `openai` 口径。

## 最终 Verify 结果

自动化验证：

```bash
uv run pytest tests/test_llm_runtime.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py tests/test_config.py -xvs
uv run ruff check src/beartools/llm/runtime.py src/beartools/llm/factory.py src/beartools/config.py src/beartools/model_check.py src/beartools/bill/agent.py src/beartools/gmail.py src/beartools/memory/service.py src/beartools/prompt/evaluator.py tests/test_llm_runtime.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py tests/test_config.py
uv run mypy .
uv run pytest tests/ -xvs
```

结果：

- 最小测试：116 passed
- `ruff check`：通过
- `mypy .`：通过，71 source files
- 全量测试：382 passed

冒烟端到端验证：

```bash
uv run beartools model check --help
uv run beartools bill --help
```

结果：两条 help 命令均通过。

全面端到端验证：

```bash
uv run beartools model check --id math-1 --model-name aiba-1 --output output/llruntime-refactor-small-smoke.md
uv run beartools model check --id math-1 --model-name naiba --output output/llruntime-refactor-large-smoke.md
```

结果：

- `small`：`aiba-1 / gpt-5.4-mini`，1/1 correct，0 errors，报告写入 `output/llruntime-refactor-small-smoke.md`
- `large`：`naiba / gpt-5.4`，1/1 correct，0 errors，报告写入 `output/llruntime-refactor-large-smoke.md`
- 当前本地配置未包含可验证的 `anthropic` 节点，因此 `anthropic` 真实 E2E 本轮不适用。
