# Model Check TDD Plan

## 背景和目标

用户希望新增 `model check` 功能：

1. 用户准备一系列简单选择题。
2. 工具读取 LLM 配置里的所有模型，对每个模型测试全部题目。
3. 汇总每个模型的答案、正确率和失败情况。

本轮必须按 `docs/workflows/codex-tdd-flow.md` 执行：先计划、再测试、再实现、再验证、review、fix、docs-sync。

## 历史上下文

- `docs/codemap.md` 说明 LLM 配置集中在 `src/beartools/config.py` 的 `agent.large` / `agent.small`，运行时节点转换与探测集中在 `src/beartools/llm/runtime.py`。
- `docs/codemap.md` 说明 CLI 入口集中在 `src/beartools/cli.py`，业务命令适配层放在 `src/beartools/commands/`。
- `docs/plans/2026-05-09-superpowers-docs-compression-plan.md` 记录：配置解析集中在 `config.py`，`llm/runtime.py` 和 `llm/factory.py` 只消费解析后的配置对象；`doctor --run-llm` 只做可选 LLM 健康检查，不应默认触发模型探测。
- 本轮曾出现流程偏离：在计划文档确认前已经产生了初版实现和测试。后续阶段以本计划为基准，继续执行 TDD 的测试、验证、review 和文档同步，并避免扩大改动范围。

## 当前工作区状态

- 已存在未跟踪草稿文件：`src/beartools/model_check.py`、`src/beartools/commands/model_check/`、`tests/test_model_check.py` 和本计划文档。
- 当前草稿已经覆盖题库解析、模型节点收集、单节点串行评测、Markdown 报告和命令适配。
- 当前 `src/beartools/cli.py` 尚未注册 `model-check` 命令，因此 `tests/test_model_check.py::test_cli_registers_model_check_command` 预期会暴露红灯。
- 在用户确认本计划前，除维护计划文档外，不继续修改生产代码或测试代码。
- 最终实现已调整为 `src/beartools/commands/model/` 命令组，并移除草稿中的 `model_check` 命令目录。

## 非目标

- 不新增数据库、持久化表结构或后台服务。
- 不改动现有 `agent.large` / `agent.small` 配置格式。
- 不把该能力塞进 `doctor --run-llm`，因为 doctor 语义是健康检查，不是模型质量评测。
- 不支持主观题、开放题、多选题、复杂评分器或 LLM-as-judge。
- 不新增依赖；题库优先使用已有 `pyyaml` 和标准库 `json`。

## Brainstorm 选项和推荐方案

### 方案 A：新增独立 CLI 组 `beartools model check`

- 题库使用 YAML/JSON：`questions[].id/question/options/answer`。
- `model` 是顶层命令组，当前只提供 `check` 子命令，后续可以继续扩展其他模型工具。
- `check` 子命令默认读取 `check/questions.yaml`，默认写入 `output/report-YYYYMMDD-HHMMSS.md`。
- 遍历 `agent.large` 和 `agent.small` 的所有去重节点。
- 直接使用 OpenAI Chat Completions 兼容接口请求每个模型。
- Prompt 明确要求模型只输出 `A-Z` 中的单个选项字母。
- 只接受严格单字母答案；任何解释、包装文本或额外字符都判错。
- CLI 输出 Rich 表格，可选写 Markdown 报告。

优点：边界清晰，不污染 doctor；适合后续扩展报告格式。

### 方案 B：扩展 `beartools doctor --run-llm`

- 在 LLM 健康检查后顺便跑题库。

问题：健康检查和准确率评测目标不同，会让 doctor 变慢且语义混乱。

### 方案 C：新增 `beartools llm check`

- 新增一个 LLM 命令组，后续可扩展更多 LLM 工具。

问题：当前项目还没有 LLM 命令组，单功能先建命令组略重。

### 推荐方案

采用方案 A：新增 `beartools model check [questions_path] [--output report.md]`，业务逻辑放在 `src/beartools/model_check.py`，命令适配放在 `src/beartools/commands/model/command.py`。

## Grill Gate

问题：题库格式是否应该现在做成可配置、兼容多种字段命名，还是先固定一个最小 schema？

推荐答案：先固定最小 schema，避免解析逻辑过度复杂。字段为：

```yaml
questions:
  - id: math-1
    question: 1+1 等于几？
    options:
      A: "1"
      B: "2"
    answer: B
```

用户确认结论：已确认使用最小 schema；第一题可以使用上面的示例题。

问题：命令是做成单个 `model-check`，还是做成后续可扩展的 `model check` 命令组？

推荐答案：使用 `beartools model check`。当前只有 `check` 子命令，但保留后续添加模型相关子命令的空间。

用户确认结论：已确认使用 `model check`。

问题：模型输出里出现 `答案：B`、`B。`、解释文本时是否尝试宽松解析？

推荐答案：不宽松解析。Prompt 引导只输出单个选项字母，解析端也只接受严格的 `A-Z` 单字母，其他全部判错，这样评测更稳定、更可解释。

用户确认结论：已确认其他答案都认为错误。

## 影响范围

- 新增 `src/beartools/model_check.py`：题库解析、节点收集、模型调用、答案解析、报告渲染。
- 新增或调整 `src/beartools/commands/model/`：Typer 命令组、`check` 子命令适配和 CLI 输出。
- 修改 `src/beartools/cli.py`：注册 `model` 命令组。
- 新增 `check/questions.yaml`：默认选择题题库，第一题使用计划中的示例题。
- 新增 `tests/test_model_check.py`：题库解析、答案解析、节点评测汇总、Markdown 报告、CLI 注册。
- 可选更新 `docs/codemap.md`：如果功能完成后成为稳定入口，需要同步 CLI 和测试地图。

## TDD/测试策略

先写测试，覆盖：

- YAML 题库解析成功路径。
- Prompt 包含严格输出单个选项字母的约束。
- 模型输出包含解释性文字时判错，而不是提取合法选项。
- 单模型两题评测能统计正确数、总数和正确率。
- Markdown 报告包含汇总和明细。
- CLI 注册了 `model check` 命令组和子命令。
- `model check` 在未传参时使用默认 `check/questions.yaml` 和 `output/report-YYYYMMDD-HHMMSS.md`。

红灯策略：

- 在生产实现不存在或未注册 CLI 时，`tests/test_model_check.py` 和 CLI 注册测试应失败。
- 如果由于本轮早前偏离导致测试已经绿灯，则将这些测试作为回归测试/characterization test，继续按 Verify 标准证明当前行为。

## Verify 标准

最小验证命令：

```bash
uv run pytest tests/test_model_check.py tests/test_cli_entrypoint.py -xvs
uv run ruff check src/beartools/model_check.py src/beartools/commands/model tests/test_model_check.py src/beartools/cli.py
uv run mypy .
```

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

人工验收：

- `beartools model check --help` 显示题库参数。
- 默认题库位于 `check/questions.yaml`，默认报告输出到 `output/report-YYYYMMDD-HHMMSS.md`。
- 提供一份 report Markdown 示例给用户查看字段和格式。
- 使用本地 mock 测试不触发真实 LLM 请求。
- 真实模型评测依赖用户本地 `config/beartools.yaml` / secrets 中的 API key 和网关可用性，不作为自动化测试门禁。

## 分步实施计划

1. Planner：写入本计划文档，并等待用户确认。
2. Test Writer：新增或校正 `tests/test_model_check.py`，先运行最小测试观察红灯或记录无法红灯原因。
3. Executor：按推荐方案实现业务模块、命令适配和 CLI 注册。
4. Verify：运行最小验证命令；必要时运行完整验证命令。
5. Reviewer：按 `docs/checklists/review.md` 检查 diff；因本功能涉及外部 LLM 请求和配置密钥，轻量参考 `docs/checklists/audit.md`。
6. Fix Loop：修复 review/verify 中发现的问题并复测。
7. Documentation Sync：按最终实现更新本计划状态；必要时更新 `docs/codemap.md`。

## 风险、回滚和需要用户确认的问题

风险：

- 不同网关对 `temperature=0` 或 OpenAI Chat Completions 参数兼容性不同，可能出现部分模型调用失败。
- 模型可能不按要求只输出选项字母；当前计划采用保守解析策略，从输出中提取第一个合法选项。
- 遍历所有模型和所有题目可能耗时、耗费 token；初版串行执行，优先简单可靠。
- 题库包含敏感内容时，内容会发送给配置中的所有模型网关。

回滚：

- 删除 `src/beartools/model_check.py`、`src/beartools/commands/model/`、`tests/test_model_check.py` 和 `check/questions.yaml`。
- 从 `src/beartools/cli.py` 移除 `model` 注册。
- 如更新 `docs/codemap.md`，回滚对应文档条目。

需要用户确认：

- 已确认题库最小 schema：`questions[].id/question/options/answer`。
- 已确认初版串行调用所有 `agent.large` 和 `agent.small` 去重节点。
- 已确认严格答案解析规则：只接受单个选项字母，其他输出都判错。

## 最终实现记录

- 新增 `beartools model check [questions_path] --output report.md`。
- 默认题库为 `check/questions.yaml`，默认报告为 `output/report-YYYYMMDD-HHMMSS.md`。
- `model` 顶层命令组当前只有 `check` 子命令，后续可以继续扩展。
- 题库选项只允许 `A-Z`；模型输出必须严格等于其中一个合法选项，否则判错。
- Prompt 已明确要求只输出单个选项字母，不输出解释、标点、空格或前后缀。
- 报告包含模型维度汇总表和逐题明细表。
- CLI 在控制台逐题输出评测进度，包含总进度、当前模型和当前题目；每题完成后输出正确或错误，错误时包含题目 id、模型结果和正确答案。
- `--id` 可以只测试指定题目 ID；`--model-name` / `-m` 可以只测试匹配的配置节点 name 或 model。

## 最终 Verify 结果

- `uv run pytest tests/test_model_check.py tests/test_cli_entrypoint.py -xvs`：通过，11 passed；增加 console 进度后相关测试为 12 passed；增加 `--id` / `--model-name` 后相关测试为 18 passed。
- `uv run ruff check src/beartools/model_check.py src/beartools/commands/model tests/test_model_check.py src/beartools/cli.py`：通过。
- `uv run mypy .`：通过。
- `uv run ruff check .`：通过。
- `uv run beartools model check --help`：通过，显示默认题库 `check/questions.yaml` 和时间戳报告说明。
- `uv run pytest tests/ -xvs`：未完全通过，停在既有 `tests/test_doctor.py::TestDoctorCommand::test_run_single_check_logs_begin_message`，当前代码输出 `开始检查 llm`，测试期待 `begin to check llm`。该失败与本次 model check 改动无关。

## Report 示例

```md
# Model Check Report

- 题目数：1
- 模型数：1

| Tier | Name | Model | Correct | Accuracy | Errors | Duration |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| small | small-1 | gpt-test | 1/1 | 100.00% | 0 | 0.42s |

## Details

### small/small-1 (gpt-test)

| Question | Expected | Predicted | Correct | Raw Output | Error |
| --- | --- | --- | --- | --- | --- |
| math-1 | B | B | yes | B | |
```
