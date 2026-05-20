# Memory Anthropic 与写入日志 TDD 计划

## 背景和目标

用户希望按 TDD 方式调整 `src/beartools/memory/`：

1. 确认并补齐 memory 摘要是否支持 Anthropic 节点。
2. 写完 memory 后，在日志中加入一条记录，说明本次用哪个模型写入 memory，以及写入的 memory 长度。

本轮遵循 `docs/workflows/codex-tdd-flow.md`。Planner 阶段只允许新增或更新本计划文档；用户确认 Planner Exit 后，再进入 Test Writer 和 Executor。

## 历史上下文

- `docs/codemap.md` 记录当前 memory 普通命令使用 small OpenAI，`diary summary` / `diary append` 使用 large OpenAI。
- `docs/plans/2026-05-13-memory-system-plan.md` 记录原始 memory 系统设计：单次命令记忆用 small，日总结用 large；记忆失败不影响原命令退出码。
- `docs/plans/2026-05-16-llmfactory-client-refactor-plan.md` 记录历史决策：当时 `memory/service.py` 只做 OpenAI 兼容 client + PydanticAI 封装，Anthropic 未纳入 memory 调用方。
- `docs/plans/2026-05-17-llfactory-runtime-merge-plan.md` 记录当前稳定方向：业务调用方只通过 `LLFactory` 获取候选和 SDK client；`LLFactory.list_candidates(type="any", model_size=...)` 返回 OpenAI / Anthropic 候选，`create_async_client(type="any")` 会按配置顺序探活并返回可用 client。
- 当前代码中 `memory/service.py` 的 `_summarize_command_async()` 和 `_summarize_day_async()` 显式 `list_candidates(type="openai", ...)`，且校验 `AsyncOpenAI`，因此 memory 当前不支持 Anthropic。
- 本地依赖检查确认 `pydantic_ai.models.anthropic.AnthropicModel` 和 `pydantic_ai.providers.anthropic.AnthropicProvider(anthropic_client=...)` 可用，可以复用 PydanticAI 而不是手写 Anthropic Messages 调用。

## 非目标

- 不新增 CLI 命令或命令参数。
- 不新增配置项；provider 选择继续走现有 `agent.small` / `agent.large` 配置顺序和 `LLFactory`。
- 不改变 memory 文件格式中的已有字段语义。
- 不让 memory 写入日志打印到 console。
- 不做 Anthropic 在 bill、gmail、prompt eval 等其他模块的迁移。
- 不新增依赖。

## Brainstorm 选项和推荐方案

### 方案 A：memory 使用 `LLFactory(type="any")`，按 provider 创建 PydanticAI model

做法：

- 单次命令摘要仍用 small tier，日总结仍用 large tier。
- 将候选选择从 `type="openai"` 改为 `type="any"`。
- `LLFactory.create_async_client(name=..., type="any", model_size=...)` 返回 OpenAI 或 Anthropic async client。
- 对 OpenAI client 继续使用 `create_openai_responses_model()`。
- 对 Anthropic client 使用 `AnthropicModel(model_name=node.model, provider=AnthropicProvider(anthropic_client=client))`。
- 返回摘要文本时同时保留模型元信息，供写入完成后日志记录。

优点：复用现有 factory 与 provider 配置；不新增业务配置；符合用户“它应该支持”的预期。

风险：PydanticAI Anthropic provider 的类型声明可能与当前 SDK 具体类型有细微差异，需要最小范围适配并用测试约束。

### 方案 B：memory 手写 Anthropic Messages API 调用

优点：依赖更少的 PydanticAI provider 抽象。

缺点：会让 memory 模块维护两套模型调用和输出抽取逻辑；和当前 OpenAI PydanticAI 方式不一致。

### 方案 C：只修日志，不做 Anthropic 支持

优点：改动最小。

缺点：不满足“memory 应该支持 Anthropic”的核心诉求。

推荐采用方案 A。

## Grill Gate

已按 `grill-me` skill 做遗漏检查；能通过读代码回答的问题已自行探索。

问题：memory 应该新增自己的 provider 配置，还是复用 `LLFactory` 的 provider 选择？

推荐答案：复用 `LLFactory`。memory 只关心 small / large，不应该重新定义 provider 优先级；现有配置顺序和探活 fallback 已在 factory 中维护。

结论：采用 `LLFactory(type="any")`，不新增 memory 专属配置。

问题：Anthropic 支持应该手写 SDK 调用，还是接入 PydanticAI AnthropicModel？

推荐答案：接入 PydanticAI AnthropicModel。memory 当前已经用 PydanticAI Agent 运行 prompt，AnthropicModel 可以保持同一抽象层。

结论：使用 `AnthropicModel + AnthropicProvider(anthropic_client=client)`。

问题：日志记录应该放在摘要生成成功时，还是 memory 文件写入成功后？

推荐答案：写入成功后。用户要求“在写完 memory 之后，在 log 加入一条”，日志必须反映落盘已经完成，而不只是模型调用完成。

结论：`append_command_memory()` 写入 day 文件后记录日志；`generate_daily_summary()` 写入 summary 文件后记录日志。

问题：memory 长度应该记录模型输出摘要长度，还是最终写入文件的 entry 长度？

推荐答案：记录最终写入内容长度。这样符合“写入的 memory 长度”，也能覆盖 summary、退出码、help、console stdout/stderr 等最终落盘内容。

结论：命令 day memory 记录本次追加 entry 的字符长度；日 summary 记录最终写入 summary 文件内容的字符长度。

遗漏检查结论：

- help 命令不请求模型；日志中的模型应明确为 `help` 或 `none`，避免误报使用了 small 模型。
- summarizer 失败 fallback 仍会写入 memory；日志中的模型应能表示 fallback，且不能影响原命令结果。
- 日志内容不包含 prompt、stdout/stderr 原文或 API key，只包含 memory 类型、路径、tier、provider、模型名和长度。
- `LLFactory.create_async_client()` 已负责探活；指定候选失败时可能抛异常，memory 现有 fallback 机制继续兜底命令记忆。

## 影响范围

预计修改：

- `src/beartools/memory/service.py`
  - 增加 memory 摘要结果元信息。
  - 单次命令摘要使用 small `type="any"`。
  - 日总结使用 large `type="any"`。
  - 支持 OpenAI 与 Anthropic PydanticAI model 构建。
  - memory 写入完成后记录 info 日志。
- `tests/test_memory_service.py`
  - 增加 Anthropic command summarizer 测试。
  - 增加 Anthropic daily summarizer 测试。
  - 增加写入日志包含模型和 memory 长度的测试。
  - 保留 OpenAI 关闭 client、fallback、help 命令和 ANSI 清洗回归测试。
- `docs/codemap.md`
  - Documentation Sync 阶段同步 memory provider 支持和写入日志行为。
- 本计划文档
  - Documentation Sync 阶段补充最终实现、验证结果、偏离项和剩余风险。

## 重要接口变更清单

- 新增 CLI 命令/参数：无。
- 删除 CLI 命令/参数：无。
- 修改 CLI 行为：无用户可见输出变化；memory 后台摘要可使用 Anthropic 节点。
- 公开函数/类：不新增公开 API；如需内部 dataclass 记录模型元信息，仅作为 `memory/service.py` 私有实现。
- 配置项：无新增、无删除、无修改。
- 文件输入输出契约：
  - `memory/day/YYYY-MM-DD.md` 仍追加命令 memory，格式不变。
  - `memory/summary/YYYY-MM-DD.md` 仍覆盖生成日总结，格式不变。
- 日志契约：
  - 命令 memory 写入后新增 info 日志，包含 memory 类型、路径、tier、provider、模型名和写入字符数。
  - 日 summary 写入后新增 info 日志，包含 memory 类型、路径、tier、provider、模型名和写入字符数。
- REST API 或外部服务调用面：无新增；现有 LLM 调用允许由 OpenAI 扩展为 OpenAI 或 Anthropic。

## TDD/测试策略

Test Writer 阶段先写红灯：

- `_LLMCommandSummarizer` 在 small tier 使用 `LLFactory.list_candidates(type="any")`，当候选 provider 为 `anthropic` 时，使用 `AnthropicModel` 创建 PydanticAI Agent，并关闭 Anthropic async client。
- `_LLMDailySummarizer` 在 large tier 使用 Anthropic 候选时同样可生成总结并关闭 client。
- OpenAI 路径保持原行为，仍使用 `create_openai_responses_model()`。
- `append_command_memory()` 写入 day 文件后记录 info 日志，日志包含模型名和 entry 字符长度。
- `generate_daily_summary()` 写入 summary 文件后记录 info 日志，日志包含模型名和 summary 文件内容字符长度。
- help 命令不调用 summarizer，但仍写入日志，模型字段明确为 `help` 或 `none`。
- summarizer 失败 fallback 仍写入文件并记录 fallback 日志，不影响原命令。

红灯预期：

- Anthropic 测试会失败，因为当前代码强制 `type="openai"` 并要求 `AsyncOpenAI`。
- 写入日志测试会失败，因为当前 `append_command_memory()` / `generate_daily_summary()` 写完文件后没有记录模型与长度日志。

## Verify 标准

### 自动化验证

最小验证命令：

```bash
uv run pytest tests/test_memory_service.py -xvs
uv run ruff check src/beartools/memory/service.py tests/test_memory_service.py
uv run mypy src/beartools/memory/service.py tests/test_memory_service.py
```

预期结果：全部通过。

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期结果：全部通过；若遇到既有无关失败，记录失败命令、原因和与本次改动关系。

### 冒烟端到端验证

建议关键路径：

```bash
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-provider-smoke uv run beartools doctor --help
BEARTOOLS_MEMORY_FAKE_SUMMARY='memory smoke summary' BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-provider-smoke uv run beartools doctor
tail -n 30 log/beartools.log
```

预期结果：

- `doctor --help` 不请求模型，仍写入 day memory，并在日志中记录 help/none 模型与 memory 长度。
- fake summary 路径写入 day memory，并在日志中记录 fallback/static 模型与 memory 长度。
- 日志不包含 API key、完整 prompt 或完整 console 原文。

如果用户愿意消耗真实模型调用，可增加：

```bash
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-provider-real uv run beartools doctor
tail -n 30 log/beartools.log
```

预期结果：真实 small 候选可用时写入 day memory，日志显示实际 provider/model 和 memory 长度；若本地配置第一个可用节点为 Anthropic，应走 Anthropic 摘要路径。

### 全面端到端验证

建议本轮省略全面真实 E2E，只用单元测试覆盖 Anthropic 分支，原因：

- 是否能真实调用 Anthropic 取决于本机配置、密钥、网络和网关状态。
- 本轮改动的核心风险是 provider 分支选择和写入日志，单元测试可稳定覆盖。
- 冒烟 E2E 已覆盖真实 CLI 写入和日志契约。

省略风险：无法在本轮证明当前机器上的某个真实 Anthropic 节点一定可用；如需要证明，应由用户提供或确认一个 Anthropic 节点 name 后追加真实 E2E。

## 分步实施计划

1. Planner：完成本计划文档，等待用户确认 Planner Exit。
2. Test Writer：补 `tests/test_memory_service.py` 红灯测试，运行最小 pytest 证明当前缺口。
3. Executor：实现 provider 分支、摘要元信息和写入后日志。
4. Verify：执行自动化最小验证、完整验证和确认后的冒烟 E2E。
5. Reviewer：按 `docs/checklists/review.md` 做只读 diff review，必要时参考 `docs/checklists/audit.md` 的外部请求与敏感日志风险。
6. Fix Loop：修复 Verify/Review 问题并复测，最多 3 轮自动继续。
7. Documentation Sync：更新本计划最终结果，必要时更新 `docs/codemap.md`。

## 风险、回滚和需确认问题

风险：

- PydanticAI Anthropic provider 与当前 `anthropic==0.97.0` 的类型声明若不完全匹配，可能需要最小范围类型适配。
- `type="any"` 会让 memory 按配置顺序选择 Anthropic 或 OpenAI；如果 Anthropic 节点 prompt 行为不同，摘要风格可能有轻微差异。
- 日志如果记录过多字段可能泄露信息，因此只记录 provider/model/tier/path/length。

回滚：

- 将 memory summarizer 选择恢复为 `type="openai"`。
- 移除 Anthropic model 构建分支。
- 移除写入后 info 日志。
- 保留测试变更时需同步回滚对应测试。

需确认问题：

- 是否确认“全面端到端验证”本轮省略，只保留自动化测试 + 冒烟 E2E？如需要真实 Anthropic E2E，请提供或确认一个 Anthropic 节点 name。

## Planner Exit Confirmation

请确认以下内容后，我再进入 Test Writer：

- 计划文档路径：`docs/plans/2026-05-20-memory-anthropic-log-plan.md`
- 计划正确性：采用 `LLFactory(type="any")`，memory 支持 OpenAI / Anthropic，写完 memory 后记录模型和写入长度日志。
- 重要接口变更清单：无 CLI/配置/文件格式变更；新增后台日志契约；外部 LLM 调用面从 OpenAI-only 扩展为 OpenAI 或 Anthropic。
- 自动化验证：确认执行 `tests/test_memory_service.py`、相关 ruff、相关 mypy，并视情况执行完整 pytest/ruff/mypy。
- 冒烟端到端验证：确认执行 help/fake summary CLI 写入和日志检查。
- 全面端到端验证：建议省略真实 Anthropic E2E；风险是不能证明当前机器真实 Anthropic 节点一定可用。

只有你明确回复类似“确认 Planner Exit：计划正确，重要接口变更确认，三类 Verify 标准确认，可以进入 Test Writer”，我才会继续写测试和实现。

## 最终实现记录

- `memory/service.py` 新增私有 `_MemoryModelInfo`，在 command memory 和 daily summary 写入后记录本次使用的 tier、provider、model 和写入字符数。
- `append_command_memory()` 在 day entry 追加落盘后写 info 日志；help 命令记录 `tier=none provider=none model=help`；summarizer 失败 fallback 记录 `provider=fallback model=summarizer-error`。
- `generate_daily_summary()` 在 summary 文件写入后写 info 日志。
- `_LLMCommandSummarizer` 改为 small `type="any"` 候选，支持 OpenAI 与 Anthropic async client。
- `_LLMDailySummarizer` 改为 large `type="any"` 候选，支持 OpenAI 与 Anthropic async client。
- OpenAI 路径继续使用 `create_openai_responses_model()`；Anthropic 路径使用 `AnthropicModel + AnthropicProvider(anthropic_client=client)`。
- `tests/test_memory_service.py` 增加 Anthropic command/daily 分支、模型元信息、写入日志、help 和 fallback 日志覆盖。
- `docs/codemap.md` 已同步 memory provider 支持和写入日志行为。

## 最终 Verify 结果

Test Writer 红灯：

```bash
uv run pytest tests/test_memory_service.py -xvs
```

结果：失败在 `AttributeError: module 'beartools.memory.service' has no attribute '_MemoryModelInfo'`，证明测试先暴露了模型元信息和日志契约缺口。

最小自动化验证：

```bash
uv run pytest tests/test_memory_service.py -xvs
uv run ruff check src/beartools/memory/service.py tests/test_memory_service.py
uv run mypy src/beartools/memory/service.py tests/test_memory_service.py
```

结果：`16 passed`，ruff 通过，mypy 通过。

完整自动化验证：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

结果：`370 passed`，ruff 通过，mypy 通过，72 source files。

冒烟端到端验证：

```bash
env BEARTOOLS_MEMORY_ROOT=/private/tmp/beartools-memory-provider-smoke-20260520 uv run beartools doctor --help
env BEARTOOLS_MEMORY_FAKE_SUMMARY=memory-smoke-summary BEARTOOLS_MEMORY_ROOT=/private/tmp/beartools-memory-provider-smoke-20260520 uv run beartools doctor
tail -n 80 log/beartools.log
sed -n '1,220p' /private/tmp/beartools-memory-provider-smoke-20260520/day/2026-05-20.md
```

结果：

- `doctor --help` 成功写入 `/private/tmp/beartools-memory-provider-smoke-20260520/day/2026-05-20.md`，日志包含 `tier=none provider=none model=help length=806`。
- fake summary 路径成功写入同一 day 文件，日志包含 `tier=small provider=static model=fake-summary length=782`。
- `beartools doctor` 本身退出码为 0；其中 `google_ping` 检查失败属于当前网络环境结果，不影响命令与 memory 写入验证。

Reviewer / Audit 结论：

- 未发现阻塞性问题。
- 轻量修复了测试中直接覆盖 `_get_logger` 的污染风险，改用 `monkeypatch` 自动恢复。
- 日志只记录 type/path/tier/provider/model/length，不记录 prompt、console 原文或密钥。

## 最终偏离和剩余风险

- 已按用户确认省略真实 Anthropic 全面 E2E；Anthropic 分支由单元测试覆盖。
- 本轮仍沿用 memory 先取候选再按候选 name 创建 client 的现有模式；如果配置中的第一个候选探活失败，memory 会走既有 fallback，而不是在 memory 模块内继续尝试下一个候选。后续如要完整复用 `LLFactory.create_async_client(type="any")` 的无 name fallback，并同时准确记录实际选中模型，需要 factory 返回 client 之外的候选元信息。
