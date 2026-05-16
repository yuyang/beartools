# Model Check Responses API TDD Plan

## 背景和目标

用户希望把现有 `beartools model check` 从 Chat Completions 接口改为 Responses API，并要求按 TDD 方式执行。

当前 `src/beartools/model_check.py` 中 `_ask_question()` 调用 `client.chat.completions.create(...)`。本轮目标是让 `model check` 的单题请求改为 `client.responses.create(...)`，并保持既有题库、严格判分、进度输出、报告格式、`--id`、`--model-name` 行为不变。

## 历史上下文

- `docs/codemap.md` 记录：`model check` 的业务逻辑位于 `src/beartools/model_check.py`，命令适配位于 `src/beartools/commands/model/command.py`。
- `docs/plans/2026-05-09-model-check-tdd-plan.md` 记录：初版 `model check` 使用选择题 YAML/JSON、严格单字母判分、默认题库 `check/questions.yaml`、默认报告 `output/report-YYYYMMDD-HHMMSS.md`。
- 当前 `LLFactory` 和 LLM 运行时探测已经默认使用 Responses API；`model check` 是少数仍直接走 Chat Completions 的模型调用路径。
- 本轮已实测本地 Code Plan 的 `/chat/completions` 可用，`/responses` 返回 404；但用户判断文档应支持，要求先把 `model check` 统一改为 Responses API。

## 非目标

- 不新增 `api_mode`、provider 分支或 Chat/Responses 自动回退。
- 不改变 `agent.large` / `agent.small` 配置格式。
- 不修改 `LLFactory`、运行时探测、doctor、prompt eval、diary、gmail 等其他调用链。
- 不改变答案解析策略；仍只接受合法选项中的单个字母。
- 不新增依赖，不改数据库或持久化格式。

## Brainstorm 选项和推荐方案

### 方案 A：仅改 `model check` 为 Responses API

- `_OpenAIClientProtocol` 从 `chat.completions` 改为 `responses`。
- `_ask_question()` 使用 `client.responses.create(model=node.model, input=[...], temperature=0)`。
- 新增/调整响应文本提取逻辑，优先兼容 OpenAI SDK 的 `output_text`，再兼容 `output[].content[].text`。
- 测试使用 fake responses client 约束请求路径和 payload。

优点：改动最小，符合用户当前要求。

风险：若某些 OpenAI 兼容网关只支持 Chat Completions，`model check` 会从可用变为失败。

### 方案 B：新增配置开关，支持 Chat/Responses 双模式

- 给 agent node 增加 `api_mode`。
- `model check` 根据节点选择接口。

优点：兼容性最好。

问题：涉及配置格式、运行时、样例配置和更多测试，不符合本轮“把 model check 改成 response 接口”的最小范围。

### 方案 C：Responses 优先，失败时自动回退 Chat

优点：用户体验平滑。

问题：评测结果会隐藏接口兼容性问题，也会让同一模型的调用协议不透明，不适合作为 model check 的准确评测工具。

### 推荐方案

采用方案 A。`model check` 统一改为 Responses API，错误继续按单题失败记录，不做回退。

用户确认结论：已通过 diff comment 确认使用方案 A。

## Grill Gate

使用 `grill-me` skill 做遗漏检查。能通过代码回答的问题已自行探索。

问题：这次是否需要保留 Chat Completions 回退，以免 Code Plan 或其他网关不支持 Responses 时评测不中断？

推荐答案：不保留。本轮用户明确要求“改成 response 接口”，且 `model check` 应暴露模型/网关真实兼容性；失败应记录为该节点的调用失败，而不是静默换协议。

用户确认结论：已通过 diff comment 确认不保留 Chat Completions 回退。

问题：Responses 输入应使用简单字符串，还是模拟原 Chat messages 的 system/user 结构？

推荐答案：使用 Responses API 支持的 message input 列表，保留 system 约束和 user 题面，避免改变 prompt 语义。

结论：按推荐方案执行。

问题：是否需要跑真实 Code Plan `/responses` 作为冒烟门禁？

推荐答案：不作为通过门禁。它依赖外部服务、套餐状态和用户密钥；本轮可选执行 `--model-name doubaolite --id ...` 作为冒烟证据，但若返回 404，应记录为外部接口兼容性结果，而不是自动化失败。

结论：冒烟端到端可运行，但不把真实服务成功作为代码合并门槛。

## 影响范围

- `src/beartools/model_check.py`
  - 协议类型从 Chat Completions 调整为 Responses。
  - `_ask_question()` 改用 `responses.create()`。
  - `_extract_response_text()` 改为解析 Responses 响应。
- `tests/test_model_check.py`
  - fake client 从 chat completions 改为 responses。
  - 增加测试确认 `responses.create()` 被调用，且请求体包含 `model`、`input` 和严格答题提示。
  - 增加响应解析覆盖 `output_text` 与 `output[].content[].text`。
- 可选 `docs/codemap.md`
  - 如果最终实现成为稳定事实，将 `model_check.py` 描述从 Chat Completions 更新为 Responses API。
- 本计划文档
  - 结束时同步最终实现、验证结果和偏离项。

## TDD/测试策略

Test Writer 阶段先改测试，不改生产代码：

- 将 `_FakeClient` 改成 `responses.create()` fake。
- 期望 `run_model_check_for_node()` 调用 `fake_client.responses.calls[0]`。
- 断言不会再依赖 `chat.completions`。
- 增加 Responses 文本提取的回归测试。

红灯预期：

- 当前生产代码仍访问 `client.chat.completions.create()`，新 fake client 不提供 `chat`，最小测试应失败。

Executor 阶段再改实现，使测试转绿。

## Verify 标准

### 自动化验证

最小验证：

```bash
uv run pytest tests/test_model_check.py -xvs
uv run ruff check src/beartools/model_check.py tests/test_model_check.py
uv run mypy .
```

完整验证：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期：最小验证通过；完整验证如遇既有无关失败，需要记录具体失败并说明是否与本次改动有关。

### 冒烟端到端验证

默认执行一个不发送真实密钥的 CLI 帮助冒烟：

```bash
uv run beartools model check --help
```

可选真实接口冒烟，若用户同意使用本地配置调用外部模型：

```bash
uv run beartools model check --id math-1 --model-name doubaolite --output output/model-check-responses-smoke.md
```

预期：命令走 Responses API；若 Code Plan 返回 404，记录为外部服务/套餐/网关兼容性结果，不视为代码自动化失败。

### 全面端到端验证

建议省略全面真实模型矩阵 E2E。原因：

- 会遍历多个外部网关并消耗 token。
- 本轮只改变接口协议，自动化 fake client 能覆盖代码行为。
- 外部服务成功与否受套餐、密钥、网关兼容性影响，不稳定。

剩余风险：未能证明每个真实节点都支持 Responses API；需要后续按需逐个网关验收。

## 分步实施计划

1. Planner：写入本计划文档，等待用户确认 Planner Exit。
2. Test Writer：修改 `tests/test_model_check.py`，运行最小测试，确认红灯。
3. Executor：修改 `src/beartools/model_check.py`，让 `model check` 走 Responses API。
4. Verify：运行自动化最小验证、CLI help 冒烟；按情况运行完整验证。
5. Reviewer：只读 diff，按 `docs/checklists/review.md` 检查；本轮涉及外部请求和密钥配置，轻量参考 `docs/checklists/audit.md`。
6. Fix Loop：修复 Verify/Review 问题并复测。
7. Documentation Sync：更新本计划最终状态；如稳定事实变化明显，更新 `docs/codemap.md`。

## 风险、回滚和需确认问题

风险：

- 某些 OpenAI 兼容网关可能不支持 `/responses`，`model check` 会从原本可用变为单题失败。
- Responses 响应对象在不同 SDK/网关中字段可能有差异，本轮覆盖常见 `output_text` 和 `output[].content[].text`。
- 真实 Code Plan 的 Responses 支持仍需外部服务确认。

回滚：

- 将 `_ask_question()` 恢复为 `chat.completions.create()`。
- 将测试 fake client 恢复为 Chat Completions fake。

需用户确认：

- 确认本轮只改 `model check`，不做 Chat 回退和配置模式扩展。
- 确认三类 Verify 标准，尤其确认省略全面真实模型矩阵 E2E 及其风险。

用户确认结论：已确认 Planner Exit，计划正确，三类 Verify 标准确认，可以进入 Test Writer。

## 最终实现记录

- `src/beartools/model_check.py` 的 `_ask_question()` 已改为调用 `client.responses.create(...)`。
- Responses 请求使用 message input 列表，保留 system 约束和 user 题面，继续传入 `temperature=0`。
- `_extract_response_text()` 已改为解析 Responses 响应，支持 `output_text` 和 `output[].content[].text` 两种常见形态。
- `tests/test_model_check.py` 的 fake client 已改为只暴露 `responses.create()`，并断言请求体包含 `model`、`temperature`、`input` 和严格答题提示。
- 未实现 Chat Completions 回退，符合用户确认的方案 A。
- `docs/codemap.md` 已同步 `model_check.py` 调用 Responses API 的稳定事实。

## 最终 Verify 结果

Test Writer 红灯：

```bash
uv run pytest tests/test_model_check.py -xvs
```

结果：失败在 `AttributeError: '_FakeClient' object has no attribute 'chat'`，证明当前实现仍走 Chat Completions。

最小验证：

```bash
uv run pytest tests/test_model_check.py -xvs
uv run ruff check src/beartools/model_check.py tests/test_model_check.py
uv run mypy .
```

结果：

- `tests/test_model_check.py`：17 passed。
- `ruff check src/beartools/model_check.py tests/test_model_check.py`：通过。
- `mypy .`：通过，70 source files。

完整验证：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
```

结果：

- `tests/`：377 passed。
- `ruff check .`：通过。

冒烟端到端验证：

```bash
uv run beartools model check --help
```

结果：通过，显示 `questions_path`、`--id`、`--model-name`、`--output`。

全面端到端验证：

- 已按 Planner 确认省略真实模型矩阵 E2E。
- 剩余风险：未逐个证明本地所有真实节点都支持 Responses API；不支持的节点会在 `model check` 中按单题调用失败记录。
