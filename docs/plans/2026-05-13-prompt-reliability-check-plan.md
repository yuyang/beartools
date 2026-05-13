# Prompt 可靠性检查 TDD 计划

## 背景和目标

用户希望查看当前项目内所有 prompt，并用 TDD 方式实现一种校验 prompt 可靠性的能力。

本轮目标是新增一个轻量、可扩展的 prompt 可靠性检查 CLI：

- 列出并检查 `prompts/*.md` 模板。
- 覆盖已知代码内动态 prompt，例如模型选择题 prompt 和 Gmail 摘要 prompt。
- 校验模板变量、渲染可用性、输出格式约束、JSON/schema/枚举约束和关键任务约束。
- 支持用户显式指定 YAML 文件执行真实模型 golden eval；未指定 YAML 时不调用真实 LLM。
- 用户指定的 YAML 文件不存在时直接报错，不自动创建、不回退默认文件。
- 输出清晰的 CLI 结果，失败时返回非 0，便于后续接入 pre-commit 或 CI。

## 历史上下文

- `docs/codemap.md` 记录 `src/beartools/prompt/template.py` 负责模板变量提取和渲染，`src/beartools/prompt/manager.py` 负责管理 `prompts/` 目录。
- `docs/codemap.md` 的变更落点指出调整 Prompt 模板系统应优先修改 `prompt/template.py`、`prompt/manager.py` 和 `prompts/`。
- `docs/plans/2026-05-09-model-check-tdd-plan.md` 已落地 `beartools model check`，结论包括：
  - 对模型评测类命令，优先使用可扩展命令组。
  - Prompt 侧要求严格输出，解析端也严格判定，不自动宽松恢复。
  - 真实模型调用依赖本地配置和网关，不适合作为默认自动化测试门禁。
- `docs/plans/2026-05-09-codex-novel-plan.md` 已沉淀小说分镜 prompt 的角色一致性、视觉风格锚点和 prompt 文件落盘约束，本轮检查应把这些稳定约束纳入静态规则。

## 非目标

- 本轮不直接改写现有 prompt 内容，除非测试暴露明显拼写或约束缺失且用户确认计划后进入实现阶段。
- 本轮不默认调用真实 LLM 做 golden eval；只有用户显式指定 YAML 文件时才运行真实评测。
- 本轮不新增数据库、不修改持久化格式、不引入新依赖。
- 本轮不把 `model check` 和 `prompt check` 合并；前者评测模型能力，后者评测 prompt 资产和契约。

## Brainstorm 选项和推荐方案

### 方案 A：静态 `prompt check` 起步

做法：新增 `beartools prompt check`，扫描模板和少量注册的代码内 prompt，用内置规则检查变量、渲染、输出格式和关键约束。

优点：速度快、稳定、可测试，不依赖外部模型，适合 TDD 和日常门禁。

缺点：只能发现“契约不清楚、结构不稳”的问题，不能证明真实模型一定答对。

### 方案 B：直接做真实模型 golden eval

做法：为每个 prompt 建 YAML 样例并调用真实 LLM，按 schema 和预期输出评分。

优点：更接近最终效果，能发现模型实际跑偏。

缺点：依赖配置、网络、费用和模型波动，TDD 红绿灯不够稳定；样例集设计也需要更多业务确认。

### 方案 C：只写文档规范和人工 checklist

做法：把 prompt 可靠性标准写成文档，由人 review。

优点：成本最低。

缺点：不能自动回归，也不能在 CLI 中一键检查。

推荐采用方案 A + 受控方案 B：

- `beartools prompt check` 默认只做静态检查。
- `beartools prompt eval <yaml_path>` 只有在用户显式传入 YAML 文件时才调用真实 LLM。
- `<yaml_path>` 不存在时直接报错并返回非 0。
- 新增一个示例 golden eval YAML，供 Verify 显式指定使用；命令仍不提供默认 YAML，避免误触发外部调用。

## Grill Gate

问题：第一版是否要把真实 LLM golden eval 纳入必做范围？

推荐答案：纳入，但必须由用户显式指定 YAML 文件。这样既保留真实模型评测能力，又不会让日常 `prompt check` 自动触发外部调用、费用和模型波动。

用户确认结论：采用方案 A；方案 B 也做，但是需要用户指定 YAML 文件；不存在的 YAML 直接报错。

后续 Grill Gate 结论：

1. `prompt eval` 的 YAML 第一版采用通用但简单的格式：`cases[].id`、`cases[].prompt`、`cases[].params`、`cases[].expect.json`。
2. `prompt eval` 第一版只支持 `prompts/*.md` 模板，不支持代码内动态 prompt；代码内动态 prompt 只纳入 `prompt check` 静态资产。
3. `prompt eval` 必须显式传 `--tier small|large`，没有传就报错；用 `LLFactory().create(tier=...)` 创建对应模型。
4. `LLFactory.create()` 需要新增可选 `tier` 参数，不传仍默认 `small`，避免破坏现有调用。
5. `prompt eval` 遇到 case 失败不立即停止，继续跑完全部 case 后汇总；只要有失败，最终返回非 0。
6. `prompt eval` 只支持 `expect.json` 的 JSON 精确子集匹配；模型可以多输出字段，但期望字段和值必须相等。
7. 模型输出必须是纯 JSON；不允许 Markdown 代码块、前后解释或自动剥离包装。
8. YAML `params` 沿用 `PromptTemplate.render()` 行为：模板默认变量可省略，也可被 YAML 显式覆盖。
9. `prompt eval` 第一版不写报告文件，只在 console 显示每个 case 的 PASS/FAIL、错误摘要和截断 raw output。
10. `prompt check --strict` 把 warning 当失败；默认 `prompt check` 只在 error 时失败。
11. 用户已确认三类 Verify 标准，并要求本轮准备一个可显式传入的 eval YAML 文件。

## 影响范围

预计新增：

- `src/beartools/prompt/checker.py`：Prompt 资产收集、静态规则、结果模型和报告渲染。
- `src/beartools/prompt/evaluator.py`：读取用户指定 YAML、渲染 prompt、调用真实 LLM、校验输出。
- `src/beartools/commands/prompt/__init__.py`：导出 prompt 命令组。
- `src/beartools/commands/prompt/command.py`：`prompt check` 与 `prompt eval` CLI。
- `tests/test_prompt_checker.py`：静态检查业务测试。
- `tests/test_prompt_evaluator.py`：YAML 解析、文件不存在报错、模型调用 mock 和结果判定测试。
- `tests/test_prompt_command.py` 或扩展 `tests/test_cli_entrypoint.py`：CLI 注册和输出测试。
- `check/prompts/bill-transaction-analysis-eval.yaml`：账单分类 prompt 的示例 golden eval YAML，用于真实 `prompt eval` 验收。

预计修改：

- `src/beartools/cli.py`：注册 `prompt` 命令组。
- `docs/codemap.md`：Documentation Sync 阶段补充 prompt check 入口和测试地图。
- 本计划文档：最终同步实际实现、验证结果和偏离项。

本轮新增 `check/prompts/bill-transaction-analysis-eval.yaml` 作为示例 golden eval 文件，但 `prompt eval` 不会默认读取它；用户必须显式传入该路径。

## TDD/测试策略

Test Writer 阶段先写测试，预期在实现前红灯：

- `PromptManager` 可枚举的模板都能被 `collect_prompt_assets()` 收集。
- 代码内 prompt 资产至少包含 `model_check_question` 和 `gmail_summary`。
- `check_prompt_asset()` 对缺少必填输出约束的测试 prompt 返回 warning 或 error。
- `check_all_prompts()` 支持按 `--name` 过滤。
- JSON 类 prompt 必须检查“只输出 JSON / 不要解释 / 字段名或 schema 约束”一类契约。
- `codex_novel_scene_select` 必须检查数量、JSON 数组、`pic_prompt` 字段、角色一致性和视觉风格锚点关键约束。
- CLI 成功时输出检查数量和通过状态；有 error 时返回非 0。
- `load_prompt_eval_cases()` 读取用户指定 YAML；路径不存在时抛出清晰错误。
- `run_prompt_eval()` 使用 mock client/agent 测试成功、输出不匹配和解析失败，不在单元测试中调用真实 LLM。
- `beartools prompt eval missing.yaml` 返回非 0，并提示 YAML 文件不存在。
- `beartools prompt eval cases.yaml` 没传 `--tier` 时返回非 0，并提示必须指定 `small` 或 `large`。
- `beartools prompt eval cases.yaml --tier small|large` 使用对应 tier 创建模型。
- Markdown 代码块包装 JSON、解释文字包装 JSON、字段值不匹配都判失败；纯 JSON 子集匹配判通过。

如果发现很难让新测试红灯，允许使用 characterization test 先锁定当前 `PromptManager` 行为，再新增 checker 测试暴露缺口。

## Verify 标准

### 自动化验证

最小验证命令：

```bash
uv run pytest tests/test_prompt.py tests/test_prompt_checker.py tests/test_prompt_evaluator.py tests/test_prompt_command.py tests/test_cli_entrypoint.py -xvs
uv run ruff check src/beartools/prompt src/beartools/commands/prompt tests/test_prompt_checker.py tests/test_prompt_evaluator.py tests/test_prompt_command.py src/beartools/cli.py
uv run mypy src/beartools/prompt src/beartools/commands/prompt src/beartools/cli.py
```

预期结果：全部通过。

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期结果：全部通过；如果遇到既有无关失败，记录失败测试、原因和与本次改动的关系。

### 冒烟端到端验证

建议关键路径：

```bash
uv run beartools prompt check --name bill_transaction_analysis
uv run beartools prompt check
uv run beartools prompt check --name codex_novel_scene_select
uv run beartools prompt eval /tmp/not-exists-prompt-eval.yaml
uv run beartools prompt eval check/prompts/bill-transaction-analysis-eval.yaml --tier small
```

预期结果：

- 单个 prompt 检查能显示该 prompt 的通过/告警/错误详情。
- 全量检查能覆盖 `prompts/*.md` 和注册的代码内 prompt。
- 若当前 prompt 存在 warning，CLI 可以返回 0；若存在 error，CLI 返回非 0，并列出具体 prompt 和规则。
- 指定不存在的 eval YAML 时直接报错并返回非 0。
- 没传 `--tier` 时直接报错并返回非 0。
- 指定存在的 YAML 且传入 `--tier small|large` 时，逐个 case 输出 PASS/FAIL，并在全部 case 跑完后汇总。

### 全面端到端验证

建议本轮全面 E2E 包含本地静态检查和“显式 YAML 才触发 eval”的本地行为验证：

```bash
uv run beartools prompt check
uv run beartools prompt check --strict
uv run beartools prompt eval check/prompts/bill-transaction-analysis-eval.yaml --tier small
uv run beartools prompt eval check/prompts/bill-transaction-analysis-eval.yaml --tier large
```

预期结果：

- 默认模式适合日常使用，warning 不阻断。
- `--strict` 将 warning 视为失败，便于用户主动提高 prompt 质量门槛。
- `prompt eval check/prompts/bill-transaction-analysis-eval.yaml --tier small|large` 真实调用 LLM 并输出每个 case 的通过/失败结果。

如果用户在 Verify 阶段没有提供可运行的 YAML，则全面 E2E 的真实 LLM 部分记录为未执行；这不阻断静态 `prompt check` 交付，但需要在最终结果中说明真实模型可靠性没有被当前回合验证。

## 分步实施计划

1. Test Writer：新增 prompt checker 和 CLI 测试，先运行最小 pytest，确认红灯或记录无法红灯原因。
2. Executor 第一层：实现 `prompt/checker.py` 的资产收集、规则模型、检查函数和文本报告。
3. Executor 第二层：实现 `prompt/evaluator.py` 的 YAML 加载、文件存在校验、case 运行和结果判定；真实调用路径必须可被测试 mock。
4. Executor 第三层：实现 `commands/prompt/command.py`，注册 `beartools prompt check` 和 `beartools prompt eval <yaml_path>`，`check` 支持 `--name` 和 `--strict`。
5. Executor 第四层：把代码内动态 prompt 注册到 checker，至少覆盖 `model_check_question` 和 `gmail_summary`。
6. Verify：执行 Planner 确认的自动化、冒烟 E2E 和全面 E2E。
7. Reviewer：按 `docs/checklists/review.md` 审查 diff；由于 `prompt eval` 涉及外部 LLM 调用和用户提供内容，轻量参考 `docs/checklists/audit.md`。
8. Fix Loop：修复 verify/review 发现的问题，最多 3 轮内自行推进。
9. Documentation Sync：更新 `docs/codemap.md` 和本计划文档的最终实现与验证结果。

## 风险、回滚和需要用户确认的问题

风险：

- 静态规则过严会让已有 prompt 产生大量 warning；初版应区分 error 和 warning。
- “所有 prompt”无法完全自动发现任意代码内字符串；初版通过显式 registry 覆盖已知动态 prompt，后续再扩展。
- JSON prompt 中包含 fenced code block 作为 schema 示例是正常现象，不应误判为模型输出允许 Markdown。
- `prompt eval` 会发送用户 YAML 中的输入内容给真实 LLM；命令必须是显式调用，不在 `prompt check` 中自动触发。
- 真实 LLM 输出会受模型波动影响；单元测试只 mock 调用链，真实效果需要用户提供 YAML 后在 Verify 中执行。

回滚：

- 删除新增 `src/beartools/prompt/checker.py`、`src/beartools/prompt/evaluator.py`、`src/beartools/commands/prompt/`、相关测试。
- 从 `src/beartools/cli.py` 移除 `prompt` 命令组注册。
- 回滚 `docs/codemap.md` 和本计划文档中的 Documentation Sync 内容。

需要用户确认：

1. 是否确认更新后的范围：`prompt check` 默认静态检查，`prompt eval <yaml_path>` 才做真实 LLM golden eval，YAML 不存在直接报错？
2. 是否确认本计划中的三类 Verify 标准，尤其是如果 Verify 阶段没有用户提供的可运行 YAML，则真实 LLM 部分记录为未执行但不阻断静态检查交付？

## 最终实现记录

已完成：

- 新增 `beartools prompt check`，默认静态检查 `prompts/*.md` 和已知动态 prompt。
- 新增 `beartools prompt eval <yaml_path> --tier small|large`，只在用户显式指定 YAML 时运行真实 LLM eval。
- 新增 `src/beartools/prompt/checker.py`：
  - 收集模板 prompt 和动态 prompt。
  - 当前动态 prompt 覆盖 `model_check_question`、`gmail_summary`。
  - 检查输出契约、JSON 纯输出约束、小说分镜角色/视觉风格锚点等规则。
  - 默认 warning 不阻断，`--strict` 将 warning 视为失败。
- 新增 `src/beartools/prompt/evaluator.py`：
  - YAML 格式为 `cases[].id`、`cases[].prompt`、`cases[].params`、`cases[].expect.json`。
  - 第一版只支持 `prompts/*.md` 模板。
  - YAML 不存在直接报错。
  - 模型输出必须是纯 JSON 对象，不剥离 Markdown 代码块或解释文字。
  - `expect.json` 使用精确子集匹配，模型可多输出字段。
  - 单个 case 失败或模型调用报错时继续执行后续 case，最后统一汇总。
- 扩展 `LLFactory.create(node=None, tier="small")`，不传仍默认 small，`prompt eval` 可显式使用 large tier。
- 新增 `check/prompts/bill-transaction-analysis-eval.yaml`，包含 3 个账单分类 golden case。
- 新增测试：
  - `tests/test_prompt_checker.py`
  - `tests/test_prompt_evaluator.py`
  - `tests/test_prompt_command.py`
  - `tests/test_agent_factory.py` 增加 large tier 创建模型回归测试。
- 更新 `docs/codemap.md`，记录新 CLI、模块职责、调用链、测试地图和数据位置。

## 最终 Verify 结果

自动化验证：

- `uv run pytest tests/test_prompt.py tests/test_prompt_checker.py tests/test_prompt_evaluator.py tests/test_prompt_command.py tests/test_cli_entrypoint.py tests/test_agent_factory.py -xvs`：通过，61 passed。
- `uv run ruff check src/beartools/prompt src/beartools/commands/prompt tests/test_prompt_checker.py tests/test_prompt_evaluator.py tests/test_prompt_command.py src/beartools/cli.py tests/test_agent_factory.py`：通过。
- `uv run mypy src/beartools/prompt src/beartools/commands/prompt src/beartools/cli.py`：通过。

完整验证：

- `uv run pytest tests/ -xvs`：通过，350 passed。
- `uv run ruff check .`：通过。
- `uv run mypy .`：通过，62 source files。

冒烟端到端验证：

- `uv run beartools prompt check --name bill_transaction_analysis`：通过，1 checked，pass。
- `uv run beartools prompt check --name codex_novel_scene_select`：通过，1 checked，pass。
- `uv run beartools prompt check`：通过，12 checked；5 个 warning，默认模式 exit 0。
- `uv run beartools prompt eval /tmp/not-exists-prompt-eval.yaml --tier small`：按预期失败，提示 YAML 文件不存在。
- `uv run beartools prompt eval check/prompts/bill-transaction-analysis-eval.yaml --tier small`：通过，3 passed，0 failed。

全面端到端验证：

- `uv run beartools prompt check --strict`：按预期失败；当前存在 5 个 warning，strict 模式将 warning 视为失败。
- `uv run beartools prompt eval check/prompts/bill-transaction-analysis-eval.yaml --tier large`：未执行成功。该命令被安全审查拦截，因为会把 eval YAML 中的 prompt 输入发送到配置里的外部 LLM 端点。未尝试绕过。

## 偏离和剩余风险

- 原计划中全面 E2E 包含 large tier 真实 eval；实际被安全审查拦截。需要用户在了解数据会发送到外部 LLM 端点后单独显式授权，才能再次运行。
- `prompt check --strict` 当前失败是预期行为，不表示功能失败；它暴露了以下 prompt 缺少更明确输出契约 warning：`bill_part_refund_amount`、`bug_analysis`、`code_review`、`feature_design`、`gmail_summary`。
- 静态检查规则是第一版启发式规则，能发现契约缺失和明显结构风险，但不能替代真实模型表现验证。
