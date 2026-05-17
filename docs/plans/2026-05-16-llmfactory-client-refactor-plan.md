# LLMFactory Client Refactor TDD Plan

## 目标

按 TDD flow 重构 `LLFactory`：它只负责从 `agent.large/small` 配置中选择有效节点并构建 SDK client，不再返回 PydanticAI model，也不负责关闭 client。需要同步迁移受影响调用方，保持 `model check` 和 `bill` 可验证。

## 当前上下文

- `src/beartools/llm/factory.py` 现在返回 PydanticAI `OpenAIResponsesModel`，并提供 `LLModelBundle(model, client)`。
- `bill/agent.py`、`prompt/evaluator.py`、`memory/service.py`、`gmail.py` 当前依赖 `LLFactory().create()` 或 `create_bundle()` 得到 PydanticAI model。
- `model_check.py` 当前自己枚举 `agent.large/small` 节点并构建 OpenAI client；本轮要改为通过 `LLFactory` 构建已选节点 client，但仍保留自己的枚举和过滤逻辑。
- `config.py` 当前 `provider` 只允许 `openai/openrouter`；本轮扩展到 `anthropic`。
- `uv.lock` 已有 `anthropic==0.97.0`，但 `pyproject.toml` 尚未直接声明。

## 已确认决策

- 采用方案 A：保留 `LLRuntime` 的 large/small 健康节点池、去重、当前活动节点和失败标记；重写 `LLFactory` 为 SDK client factory。
- 沿用配置字段 `provider`，不新增 `provide`。
- 支持的 `type` 值为 `openai/openrouter/anthropic/any`；`type="open"` 不支持，应作为参数校验错误。
- `openrouter` 归一为 OpenAI 兼容族；Anthropic 使用 Anthropic SDK client。
- `model` 有值时仍受 `model_size` 限制，只在指定 `large` 或 `small` 节点池内查找。
- `model` 有值时同时匹配 `node.name` 和 `node.model`。
- 同一 `model_size` 下同名 model 多节点时，按配置顺序选择第一个健康节点。
- `model check` 使用自己枚举出的 `RuntimeNode` 调 `create_client_for_node(node)`，不通过 model 字符串回查，避免同名节点错配。
- 把 `anthropic==0.97.0` 补为项目直接依赖，并保持所有依赖精确版本。
- `bill` 本轮只支持 OpenAI 兼容 client 的 PydanticAI 封装；选到 Anthropic 节点时给清晰错误，不做 Anthropic 结构化输出完整迁移。
- `prompt/evaluator.py`、`memory/service.py`、`gmail.py` 本轮同步做最小迁移，显式选择 OpenAI 兼容 client，并在调用方本地封装 PydanticAI。
- `LLFactory` 直接返回 OpenAI/Anthropic SDK client，不返回 `LLClientBundle`；不提供 close 包装，不自动关闭，调用方直接关闭 SDK client。
- 不保留旧 `LLFactory.create()` / `create_bundle()` 兼容 shim；所有调用方必须迁移到新接口。
- 直接 SDK 调用优先使用同步 client；PydanticAI 封装调用方可按 provider 需要使用 async client，并由调用方关闭。
- 全面真实 E2E 必须执行，即使消耗 token 也无需再次确认。

## LLFactory 接口契约

```python
ProviderType = Literal["openai", "openrouter", "anthropic", "any"]
ProviderFamily = Literal["openai", "anthropic"]
AgentTier = Literal["large", "small"]

class LLFactoryError(RuntimeError):
    """LLM 工厂配置或选择错误。"""

@dataclass
class LLFactory:
    logger: _LoggerProtocol | None = None

    def create_client(
        self,
        *,
        model: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> _SyncLLMClientProtocol:
        """按 model/type/model_size 选择节点并构建同步 SDK client。"""

    def create_client_for_node(self, node: RuntimeNode) -> _SyncLLMClientProtocol:
        """按已选 RuntimeNode 构建同步 SDK client。"""

    async def create_async_client(
        self,
        *,
        model: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> _AsyncLLMClientProtocol:
        """按 model/type/model_size 选择节点并构建异步 SDK client。"""

    async def create_async_client_for_node(self, node: RuntimeNode) -> _AsyncLLMClientProtocol:
        """按已选 RuntimeNode 构建异步 SDK client。"""
```

选择规则：

- `model is None`：在 `model_size` 对应健康节点池中，按配置顺序选择第一个符合 `type` 的节点。
- `model` 有值：只在 `model_size` 对应健康节点池中按 `node.model == model or node.name == model` 查找，再按 `type` 过滤。
- `type="any"` 不限制 provider family。
- `type in {"openai", "openrouter"}` 匹配 OpenAI 兼容族。
- `type="anthropic"` 只匹配 Anthropic。
- `type="open"` 非法。
- 选择到的节点会先探测；探测失败且可失效时沿用 runtime 失败标记与切换逻辑继续找下一个节点。
- `create_client_for_node(node)` / `create_async_client_for_node(node)` 也会在构建前调用 `probe_runtime_node(node)`。

构建映射：

- OpenAI 兼容族同步：`openai.OpenAI(...)`
- OpenAI 兼容族异步：`openai.AsyncOpenAI(...)`
- Anthropic 同步：`anthropic.Anthropic(...)`
- Anthropic 异步：`anthropic.AsyncAnthropic(...)`

## 影响范围

- `pyproject.toml`：新增 `anthropic==0.97.0` 直接依赖。
- `src/beartools/config.py`、`config/beartools.yaml.sample`：扩展 provider 合法值和说明。
- `src/beartools/llm/factory.py`：移除 PydanticAI 依赖，提供同步/异步 SDK client 接口。
- `src/beartools/model_check.py`：保留自身节点枚举/过滤，通过 `create_client_for_node(node)` 构建 client。
- `src/beartools/bill/agent.py`：调用方侧创建 PydanticAI OpenAI Responses model；非 OpenAI 兼容节点给清晰错误。
- `src/beartools/prompt/evaluator.py`、`src/beartools/memory/service.py`、`src/beartools/gmail.py`：同步迁移为显式 OpenAI client + 调用方侧 PydanticAI 封装。
- 测试：`tests/test_config.py`、`tests/test_agent_factory.py`、`tests/test_model_check.py`、`tests/test_bill_agent.py`，必要时补充 prompt/memory/gmail 相关测试。

## TDD 策略

Test Writer 先写红灯：

- config 接受 `provider: anthropic`，非法 provider 错误包含 `anthropic`。
- factory 有 `create_client/create_async_client/create_client_for_node/create_async_client_for_node`，直接返回 SDK client，不返回 bundle，不提供 close 包装。
- factory 选择规则覆盖 `type`、`model_size`、同名 model 多节点、`openrouter` 归一、Anthropic client 构建、`type="open"` 非法。
- `model_check` 通过 factory 为已选 node 构建 client，但节点列表仍由自己过滤。
- `bill` 从 factory 获取 OpenAI client 后自行封装 PydanticAI；选到 Anthropic 给清晰错误。
- prompt eval、memory、gmail 的最小回归覆盖旧调用方不再依赖 `LLFactory().create()`。

红灯预期：当前代码拒绝 Anthropic provider，factory 没有新接口且仍返回 PydanticAI model，model check 直接构建 OpenAI client。

## Verify 标准

自动化最小验证：

```bash
uv run pytest tests/test_config.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py -xvs
uv run ruff check src/beartools/config.py src/beartools/llm/factory.py src/beartools/model_check.py src/beartools/bill/agent.py tests/test_config.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py
uv run mypy .
```

自动化完整验证：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

冒烟 E2E：

```bash
uv run beartools model check --help
uv run beartools bill --help
uv run beartools model check --id math-1 --model-name <可用small模型> --output output/llmfactory-refactor-small-smoke.md
uv run beartools model check --id math-1 --model-name <可用large模型> --output output/llmfactory-refactor-large-smoke.md
```

全面真实 E2E：

- `model check` 至少覆盖一个 small 节点和一个 large 节点。
- 若真实配置中有 Anthropic 节点，只验证 `LLFactory.create_client(..., type="anthropic")` 构建和 probe 路径，不跑 bill/model check 等业务调用。
- `bill` 暂不执行真实 E2E；由用户后续手工测试。自动化测试和 `beartools bill --help` 冒烟仍需覆盖 bill 调用方迁移。
- 真实节点若因网关、密钥、套餐或 API 兼容性失败，记录具体命令、错误和 provider，进入 Fix Loop 或标记为外部环境阻塞。

## 执行步骤

1. Planner：完成 Grill Gate，获得 Planner Exit 确认。
2. Test Writer：写红灯测试并运行最小测试。
3. Executor：实现 config/provider、factory SDK client、调用方迁移、依赖声明。
4. Verify：执行自动化、冒烟和全面真实 E2E。
5. Reviewer：按 `docs/checklists/review.md` 做只读审查，并轻量参考 `docs/checklists/audit.md` 的外部请求、密钥和账单数据风险。
6. Fix Loop：修复 Verify/Review 问题并复测。
7. Documentation Sync：更新本计划最终结果和 `docs/codemap.md` 的稳定职责变化。

## 已确认补充

- 全面 E2E 的 small/large 真实模型由 Codex 从本地配置自动选择第一个可用节点。
- bill 暂不做真实 E2E，由用户后续手工测试；本轮只做自动化测试和 CLI help 冒烟。
- `type="open"` 非法只在 `LLFactory` 层抛 `LLFactoryError`，本轮不新增 CLI/Typer 参数表面。
- `create_client_for_node(node)` 构建前也需要探测节点，沿用旧 `LLFactory.create(node=node)` 的安全行为。
- `model` 参数同时匹配配置节点的 `name` 和真实 `model` 字段。
- 同步/异步接口按用途选择：`model_check` 这类直接 SDK 调用用同步 client；PydanticAI 调用方如需 `AsyncOpenAI`，使用 async factory 接口并自行关闭。
- Anthropic 全面 E2E 只验证 factory 构建和 probe 路径，不纳入 bill/model check 业务调用。
- 不保留旧 `LLFactory.create()` / `create_bundle()` 兼容 shim，避免 PydanticAI 继续隐藏在 factory 内。

## 最终实现记录

- `LLFactory` 已改为纯 SDK client factory，提供 `create_client()`、`create_client_for_node()`、`create_async_client()`、`create_async_client_for_node()`。
- `LLFactory.create()` / `create_bundle()` 已移除，不保留兼容 shim。
- `provider` 支持 `openai/openrouter/anthropic`；`type="open"` 在 factory 层报 `LLFactoryError`。
- `openrouter` 归一为 OpenAI 兼容族；`anthropic` 构建 Anthropic SDK client。
- `llm/runtime.py` 增加 Anthropic Messages API 探测路径。
- `model_check.py` 保留自身节点枚举/过滤，改用 `LLFactory.create_client_for_node(node)` 获取同步 OpenAI 兼容 client。
- `bill/agent.py`、`prompt/evaluator.py`、`memory/service.py`、`gmail.py` 已迁移为调用方侧 OpenAI 兼容 client + PydanticAI 封装，并由调用方关闭 client。
- 新增 `llm/pydantic_openai.py` 作为调用方侧 PydanticAI OpenAI Responses model 封装工具。
- `pyproject.toml` 已新增直接依赖 `anthropic==0.97.0`；`uv.lock` 已同步。
- `docs/codemap.md` 已同步 LLM factory、runtime、model check 和 bill agent 的稳定职责变化。

## 最终 Verify 结果

Test Writer 红灯：

```bash
uv run pytest tests/test_config.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py -xvs
```

结果：失败在 `test_reject_invalid_provider_value`，当前实现仍只允许 `openai/openrouter`，证明测试暴露了本轮重构缺口。

自动化验证：

```bash
uv run pytest tests/test_config.py tests/test_agent_factory.py tests/test_model_check.py tests/test_bill_agent.py tests/test_memory_service.py tests/test_prompt_evaluator.py tests/test_prompt_command.py tests/test_gmail.py -xvs
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

结果：

- 扩展最小测试：108 passed。
- 完整测试：378 passed。
- `ruff check .`：通过。
- `mypy .`：通过，71 source files。

冒烟与全面 E2E：

```bash
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools model check --help
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools bill --help
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools model check --id math-1 --model-name aiba-1 --output output/llmfactory-refactor-small-smoke.md
BEARTOOLS_MEMORY_FAKE_SUMMARY='verify smoke' uv run beartools model check --id math-1 --model-name naiba --output output/llmfactory-refactor-large-smoke.md
```

结果：

- `model check --help`：通过。
- `bill --help`：通过。
- small E2E：`aiba-1 / gpt-5.4-mini`，1/1 correct，0 errors，报告写入 `output/llmfactory-refactor-small-smoke.md`。
- large E2E：`naiba / gpt-5.4`，1/1 correct，0 errors，报告写入 `output/llmfactory-refactor-large-smoke.md`。
- 本地配置没有 Anthropic 节点，因此 Anthropic factory/probe 真实 E2E 不适用。
- bill 真实 E2E 按用户确认省略，由用户后续手工测试。
