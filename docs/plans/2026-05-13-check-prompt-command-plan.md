# check prompt 命令迁移 TDD 计划

## 背景和目标

用户希望按 TDD 方式开发，把现有 `beartools prompt check` 命令迁移为 `beartools check prompt` 子命令；随后进一步明确 `prompt eval` 也要迁移，并去掉顶层 `prompt` 命令。剩余所有业务逻辑不变。

本轮目标：

- 新增顶层 `check` 命令组，并提供 `prompt` 子命令。
- `beartools check prompt` 复用现有 Prompt 静态检查逻辑、参数、输出和退出码语义。
- `beartools check eval` 复用现有 Prompt golden eval 逻辑、参数、输出和退出码语义。
- 移除顶层 `prompt` 命令组，避免同一类检查能力分散在 `prompt` 和 `check` 两个入口。
- 不修改 Prompt 检查业务规则、不改 eval 逻辑、不引入新依赖。

## 历史上下文

- `docs/codemap.md` 记录当前 CLI 入口由 `src/beartools/cli.py` 注册，`beartools prompt check` 由 `src/beartools/commands/prompt/command.py` 适配，业务逻辑在 `src/beartools/prompt/checker.py`。
- `docs/plans/2026-05-13-prompt-reliability-check-plan.md` 已落地 Prompt 可靠性检查，原约定：
  - `prompt check` 是静态检查，不调用真实 LLM。
  - `prompt eval` 必须用户显式指定 YAML 和 tier，保留在 Prompt 工具组下。
  - `--name` 和 `--strict` 是 `prompt check` 的现有行为。
- 本轮用户已更新命令归属要求：`prompt eval` 也迁移到 `check eval`，并移除顶层 `prompt` 命令，因此上一条历史约定中的命令路径需要被本轮新计划取代；业务语义保持不变。
- `docs/plans/2026-05-09-model-check-tdd-plan.md` 对命令可扩展性已有类似结论：当命令未来可能扩展时，优先使用命令组加子命令。

## 非目标

- 不改 `check_all_prompts()`、`PromptCheckResult`、静态规则或报告内容。
- 不调整 eval 的参数、输出、错误处理或执行逻辑，只迁移命令路径。
- 不新增真实模型调用，也不调整外部配置。
- 不做 CLI 大范围重构。
- 不引入向后兼容别名，除非用户明确要求保留旧的 `prompt` 顶层命令。

## Brainstorm 选项和推荐方案

### 方案 A：新增 `check` 顶层组，迁移 prompt check 和 prompt eval

做法：新增 `src/beartools/commands/check/`，把现有 prompt check 的 CLI 适配函数注册为 `check prompt`，把现有 prompt eval 的 CLI 适配函数注册为 `check eval`；从主 CLI 移除顶层 `prompt` 命令。

优点：符合用户“prompt eval 也迁移，去掉 prompt 这个命令”的最新表述，命令结构清晰，后续可扩展 `check model`、`check config` 等能力。

缺点：旧命令会失效，需要用户切换调用方式；已有文档中的 `prompt eval` 示例需要同步更新。

### 方案 B：同时保留 `prompt` 和 `check`

做法：新增 `check prompt` 和 `check eval`，同时旧的 `prompt check` 和 `prompt eval` 继续可用。

优点：兼容已有脚本。

缺点：用户明确要求去掉 `prompt` 命令，双入口不符合最新需求。

### 方案 C：只改显示文案，不改命令结构

做法：保留 `prompt check`，只在 help 或文档中说明。

优点：改动最小。

缺点：没有满足命令路径迁移需求。

推荐采用方案 A：新增 `beartools check prompt` 和 `beartools check eval`，移除顶层 `prompt` 命令，业务逻辑复用现有函数。

## Grill Gate

问题：是否需要保留旧入口 `beartools prompt check` / `beartools prompt eval` 作为兼容别名？

推荐答案：不保留。用户已明确说“prompt eval 也迁移，去掉 prompt 这个命令”；命令路径变化应明确，测试也应约束顶层 `prompt` 不再注册。

用户确认结论：用户已确认 `prompt eval` 也迁移，并去掉 `prompt` 命令。

## 影响范围

预计新增：

- `src/beartools/commands/check/__init__.py`
- `src/beartools/commands/check/command.py`

预计修改：

- `src/beartools/cli.py`：注册 `check` 顶层命令组。
- `src/beartools/commands/prompt/command.py`：拆出或保留可复用函数，但不再作为顶层 `prompt` 命令注册来源。
- `src/beartools/commands/prompt/__init__.py`：如不再需要，停止被 `cli.py` 引用；是否删除取决于最小改动原则和测试覆盖。
- `tests/test_prompt_command.py`：更新 CLI 注册和行为测试。
- `docs/codemap.md`：Documentation Sync 阶段更新 CLI 入口地图。
- 本计划文档：最终同步实际实现、验证结果和偏离项。

## TDD/测试策略

Test Writer 阶段先改测试，预期红灯：

- `beartools check --help` 显示 `prompt` 子命令。
- `beartools check --help` 显示 `eval` 子命令。
- `beartools check prompt --name bill_transaction_analysis` 成功运行，并沿用现有输出内容。
- `beartools check prompt --strict` 沿用 warning 失败语义。
- `beartools check eval <yaml_path> --tier small` 沿用现有 eval 行为。
- `beartools prompt --help` 不再成功或不再显示顶层命令，证明顶层 `prompt` 已移除。
- 旧入口 `beartools prompt check` 和 `beartools prompt eval` 不再作为有效路径。

如 Typer 帮助输出包含全局字符串导致“旧入口不显示”的断言不稳定，测试应优先断言 `prompt --help`、`prompt check --help`、`prompt eval --help` 不再成功。

## Verify 标准

### 自动化验证

最小验证命令：

```bash
uv run pytest tests/test_prompt_command.py tests/test_prompt_checker.py tests/test_prompt_evaluator.py tests/test_cli_entrypoint.py -xvs
uv run ruff check src/beartools/cli.py src/beartools/commands/prompt src/beartools/commands/check tests/test_prompt_command.py
uv run mypy src/beartools/cli.py src/beartools/commands/prompt src/beartools/commands/check
```

预期结果：全部通过。

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期结果：全部通过；若遇到既有无关失败，记录失败测试、原因和与本次迁移的关系。

### 冒烟端到端验证

建议关键路径：

```bash
uv run beartools check prompt --name bill_transaction_analysis
uv run beartools check prompt
uv run beartools check eval /tmp/not-exists-prompt-eval.yaml --tier small
uv run beartools check eval check/prompts/bill-transaction-analysis-eval.yaml --tier small
```

预期结果：

- `check prompt` 能执行原 `prompt check` 的静态检查。
- `--name` 过滤和默认全量检查行为不变。
- `check eval` 能执行原 `prompt eval` 的 YAML 解析、tier 校验、结果输出和失败退出码。
- 不存在的 eval YAML 仍返回清晰错误。

### 全面端到端验证

建议本轮省略全面 E2E，原因是本次只迁移本地 CLI 路由，不改变 Prompt 检查业务逻辑，也不需要真实 LLM 验证。

若用户要求执行全面 E2E，建议命令：

```bash
uv run beartools check prompt --name bill_transaction_analysis
uv run beartools check prompt --strict
uv run beartools check eval check/prompts/bill-transaction-analysis-eval.yaml --tier small
uv run beartools check eval check/prompts/bill-transaction-analysis-eval.yaml --tier large
```

风险：`prompt eval` 会真实调用 LLM，依赖本地配置、网络和模型稳定性。

用户确认结论：不省略全面 E2E，需要实际运行 `check prompt` 和 `check eval`。

## 分步实施计划

1. Test Writer：更新 CLI 测试，先运行最小 pytest，确认 `check prompt` / `check eval` 未实现或旧 `prompt` 仍存在导致红灯。
2. Executor：新增 `check` 命令组，复用现有 prompt check 和 prompt eval 函数，移除顶层 `prompt` 命令组注册。
3. Verify：执行已确认的自动化验证和冒烟 E2E；如用户要求，执行全面 E2E。
4. Reviewer：按 `docs/checklists/review.md` 审查 diff；本次不涉及安全、持久化数据或外部发布，默认不单独 audit。
5. Fix Loop：修复 verify/review 发现的问题，3 轮以内自行推进。
6. Documentation Sync：更新 `docs/codemap.md` 和本计划文档最终结果。

## 风险、回滚和需要用户确认的问题

风险：

- 如果外部脚本仍调用 `beartools prompt check` 或 `beartools prompt eval`，移除旧入口会造成脚本失败。
- Typer 命令复用函数时需要避免重复注册或 help 文案漂移。
- eval 逻辑不应在迁移中改变，尤其是 YAML 不存在、tier 必填、失败继续跑完全部 case 的语义。

回滚：

- 删除新增 `src/beartools/commands/check/`。
- 从 `src/beartools/cli.py` 移除 `check` 命令组注册。
- 恢复 `src/beartools/cli.py` 中的 `prompt` 命令组注册。
- 恢复 `src/beartools/commands/prompt/command.py` 中的 `prompt_app.command("check")` 和 `prompt_app.command("eval")` 注册。
- 回滚测试和文档同步改动。

用户已确认：

- 按最新推荐方案移除整个顶层 `prompt` 命令，不保留旧入口兼容别名。
- 本轮不省略全面 E2E，需要实际运行 `check prompt` 和 `check eval`。

## 最终实现与验证结果

最终实现：

- 新增 `src/beartools/commands/check/`，注册 `check prompt` 和 `check eval`。
- `check prompt` 复用原 `commands/prompt/command.py::check()`。
- `check eval` 复用原 `commands/prompt/command.py::eval_command()`。
- `src/beartools/cli.py` 移除顶层 `prompt` 命令注册，改为注册顶层 `check` 命令组。
- 移除未使用的 `prompt_app` Typer 对象和旧 `prompt` 子命令注册语句。
- 更新 `tests/test_prompt_command.py`，覆盖新命令路径、旧顶层 `prompt` 移除、eval tier/YAML 错误和成功路径。
- 更新 `docs/codemap.md`，把 Prompt 检查和 eval 入口改为 `check prompt` / `check eval`。

自动化验证：

- `uv run pytest tests/test_prompt_command.py -xvs`：先红灯，`check` 命令未注册导致失败；实现后 6 passed。
- `uv run pytest tests/test_prompt_command.py tests/test_prompt_checker.py tests/test_prompt_evaluator.py tests/test_cli_entrypoint.py -xvs`：22 passed。
- `uv run ruff check src/beartools/cli.py src/beartools/commands/prompt src/beartools/commands/check tests/test_prompt_command.py`：通过。
- `uv run mypy src/beartools/cli.py src/beartools/commands/prompt src/beartools/commands/check`：通过。
- `uv run pytest tests/ -xvs`：351 passed。
- `uv run ruff check .`：通过。
- `uv run mypy .`：通过。

E2E 验证：

- `uv run beartools check prompt --name bill_transaction_analysis`：通过，检查 1 个 prompt。
- `uv run beartools check prompt`：通过，检查 12 个 prompt；默认 warning 不阻断。
- `uv run beartools check prompt --strict`：按预期失败；当前存在 5 个 warning，strict 模式将 warning 视为失败。
- `uv run beartools check eval /tmp/not-exists-prompt-eval.yaml --tier small`：按预期失败，提示 YAML 文件不存在。
- `uv run beartools check eval check/prompts/bill-transaction-analysis-eval.yaml --tier large`：通过，3 passed, 0 failed。
- `uv run beartools --help`：通过，主命令列表显示 `check`，不显示 `prompt`。
- `uv run beartools prompt --help`：按预期失败，提示没有 `prompt` 命令。

未完成验证：

- `uv run beartools check eval check/prompts/bill-transaction-analysis-eval.yaml --tier small`：执行审批被拒，原因是该真实 eval 会把本地 prompt/YAML 内容发送到配置的外部 LLM endpoint；未绕过执行。

Reviewer 结论：

- 本次改动只迁移 CLI 路由，未改变 Prompt checker/evaluator 业务逻辑。
- 旧顶层 `prompt` 入口被移除，存在外部脚本需改命令路径的兼容性风险。
