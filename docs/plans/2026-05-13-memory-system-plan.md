# CLI 记忆系统 TDD 计划

## 背景和目标

用户希望按 TDD 方式为 `beartools` 设计一套轻量记忆系统：

1. 每次执行命令时，用 small 模型根据本次命令输入、命令输出和当前命令 help 信息，总结用户目的与执行结果。
2. 将单次命令记忆追加写入 `./memory/day/年月日.md`。
3. 新增 `diary` 命令组：
   - `diary summary`：使用 large 模型总结每天都在干嘛，每天一条，写入 `./memory/summary/年月日.md`。
   - `diary append`：默认处理本月，确保从本月 1 号到昨天，只要存在 `./memory/day/年月日.md`，就用 large 模型生成对应的 `./memory/summary/年月日.md`。

本轮遵循 `docs/workflows/codex-tdd-flow.md`。Planner 阶段只新增本计划文档；用户确认计划和三类 Verify 标准后，再进入 Test Writer 和 Executor。

## 历史上下文

- `docs/codemap.md` 记录 `src/beartools/cli.py` 是 Typer 顶层入口，所有现有命令都从这里注册。
- `pyproject.toml` 当前脚本入口是 `beartools = "beartools.cli:app"`，这会直接调用 Typer app，绕过 `src/beartools/cli.py::_main_wrapper()`。
- `src/beartools/cli.py::_main_wrapper()` 已有 `bill` 默认子命令改写逻辑，但因为脚本入口没有指向它，`uv run beartools ...` 不一定能触发该包装逻辑。
- `src/beartools/llm/factory.py::LLFactory.create()` 已支持 `tier="small"` 和 `tier="large"`，适合本轮按场景选择模型：单次命令记忆用 small，日总结用 large。
- `docs/plans/2026-05-13-prompt-reliability-check-plan.md` 已沉淀：真实 LLM 调用依赖本地配置、网络和网关，不适合作为默认单元测试门禁；单元测试应 mock LLM 调用链。
- `docs/plans/2026-05-09-model-check-tdd-plan.md` 已沉淀：模型相关能力应严格控制输出契约，进度和失败原因要清楚展示。

## 非目标

- 不记录任意 shell 命令，只记录通过 `beartools` 入口执行的 CLI 命令。
- 不新增数据库、不引入向量库、不做跨项目全局记忆。
- 不在本轮实现长期检索、RAG、自动注入上下文或多 Agent 共享记忆。
- 不默认记录敏感配置文件内容、环境变量、API key 或完整 trace。
- 不让记忆失败影响原命令的原始退出码；记忆写入和 LLM 总结失败只做短提示或日志记录。
- 不新增依赖；优先使用标准库、Typer、Rich 和现有 LLM 工厂。

## Brainstorm 选项和推荐方案

### 方案 A：在 CLI 入口包装所有 beartools 命令

做法：

- 将脚本入口改为 `beartools.cli:_main_wrapper`。
- `_main_wrapper()` 继续处理 `bill` 默认子命令，同时捕获本次 `argv`、stdout、stderr、exit code、开始/结束时间。
- 根据命令路径获取当前命令 help 文本。
- 原命令执行结束后，用 small 模型生成目的与结果摘要，并追加到 `memory/day/YYYY-MM-DD.md`。
- `diary` 命令自身也进入单次命令记忆，记忆内容同样来自 beartools 命令、CLI/console 显示信息和当前命令 help。

优点：最接近“每次执行命令”的语义；能统一采集输出和退出码；不需要改每个命令模块。

缺点：需要小心保持 stdout/stderr、Rich 输出、Typer Exit 和原退出码行为。

### 方案 B：在每个命令函数手动调用记忆服务

优点：单个命令上下文更明确。

缺点：需要修改大量命令；容易漏记；新增命令要重复接入；不适合作为统一记忆系统。

### 方案 C：只做 `diary` 命令，手动读取已有 day 文件

优点：风险最低。

缺点：没有解决“每次执行命令自动记忆”的核心需求。

推荐采用方案 A，并把业务逻辑拆成可测试模块：

- `src/beartools/memory/models.py`：命令记忆、日总结结果等数据结构。
- `src/beartools/memory/service.py`：路径计算、追加日记忆、用 small 生成单次摘要、用 large 生成每日 summary、补齐本月 summary。
- `prompts/cli_command_memory.md`：单次命令记忆 prompt，由 `PromptManager` 统一管理。
- `prompts/cli_daily_summary.md`：每日 summary prompt，由 `PromptManager` 统一管理。
- `src/beartools/memory/prompts.py`：只负责调用 `PromptManager` 渲染记忆 prompt，不硬编码完整 prompt 正文。
- `src/beartools/commands/diary/command.py`：`summary` / `append` 命令适配。
- `src/beartools/cli.py`：入口包装、命令执行采集和 `diary` 注册。

## Grill Gate

问题：这里的“每次执行命令”是否要覆盖任意 shell 命令，还是只覆盖 `beartools` CLI 自己的命令？

推荐答案：第一版只覆盖 `beartools` CLI 自己的命令。这样不需要改 shell profile，也不会误采集用户在项目目录里执行的其他敏感命令；实现上也能稳定拿到 Typer help、stdout/stderr 和退出码。

用户确认结论：第一版只覆盖 `beartools` CLI 自己的命令，且总结依据是 beartools 命令、CLI/console 上显示的信息和当前命令 help。

问题：`diary` 命令自身是否也要被单次命令记忆记录？

推荐答案：默认跳过 `diary` 命令自身，避免 `diary summary` / `diary append` 生成的总结再被写入 day 记忆，造成循环噪音。后续如果需要审计 diary 命令，可加显式选项。

用户确认结论：不采用推荐答案。`diary` 命令自身也进入 day 记忆。

问题：如果 small 模型不可用、网络失败或总结失败，原命令是否失败？

推荐答案：不失败。原命令的退出码必须保持不变；记忆失败写入一条本地 fallback 记录，包含命令、退出码和“LLM 总结失败：原因”，并尽量在 stderr 给出短提示。

用户确认结论：确认。LLM 记忆失败不改变原命令退出码，并写入 fallback 记录。

问题：`diary append` 遇到已经存在的 `memory/summary/YYYY-MM-DD.md` 时，要不要覆盖重写？

推荐答案：默认不覆盖。`append` 语义更像补齐缺失 summary，避免覆盖用户手工调整过或之前生成过的总结；后续如果需要可另加 `--force`。

用户确认结论：确认默认不覆盖。

遗漏检查结论：

- 需要防止记录敏感信息：默认截断 stdout/stderr，并在 prompt 和落盘内容中避免记录环境变量、API key、配置密钥。
- 需要防止无限递归：记忆总结过程不能再次触发命令记忆；但 `diary` CLI 本身执行完成后仍会进入 day 记忆。
- 需要保留原命令用户体验：捕获输出后仍原样回放 stdout/stderr，并保持退出码。
- 需要可测试：单元测试 mock LLM summarizer，不触发真实模型请求。

## 影响范围

预计新增：

- `src/beartools/memory/__init__.py`
- `src/beartools/memory/models.py`
- `src/beartools/memory/service.py`
- `src/beartools/memory/prompts.py`
- `prompts/cli_command_memory.md`
- `prompts/cli_daily_summary.md`
- `src/beartools/commands/diary/__init__.py`
- `src/beartools/commands/diary/command.py`
- `tests/test_memory_service.py`
- `tests/test_diary_command.py`
- `tests/test_cli_memory_capture.py`

预计修改：

- `src/beartools/cli.py`：注册 `diary` 命令组；将 `_main_wrapper()` 扩展为统一入口包装；保留并测试现有 `bill` 默认子命令行为。
- `pyproject.toml`：将脚本入口从 `beartools.cli:app` 改为 `beartools.cli:_main_wrapper`。
- `docs/codemap.md`：Documentation Sync 阶段补充 `diary` 入口和 `memory` 模块职责。
- 本计划文档：最终记录实际改动、验证结果、偏离项和后续建议。

## 数据与文件格式

日期使用本地时区的当前日期，文件名采用 ASCII 友好的 ISO 格式：

- 日记忆：`memory/day/YYYY-MM-DD.md`
- 日总结：`memory/summary/YYYY-MM-DD.md`

原因：用户写的“年月日.md”表达的是按天文件；ISO 日期排序稳定、跨平台安全、便于本月补齐和测试。

`memory/day/YYYY-MM-DD.md` 追加格式建议：

```md
## HH:MM:SS beartools <command...>

- 目的：...
- 结果：...
- 退出码：0
- help：<当前命令 help 的一句话摘要>
```

`memory/summary/YYYY-MM-DD.md` 格式建议：

```md
# YYYY-MM-DD

- 今天主要在做：...
- 关键结果：...
- 未完成/后续：...
```

若同一天重复执行 `diary summary`，默认覆盖当天 summary 文件，保证“一天一条”是最新总结；`memory/day` 只追加不覆盖。

## LLM 调用策略

- 单次命令记忆使用 `LLFactory().create(tier="small")`。
- `diary summary` 和 `diary append` 生成日总结时使用 `LLFactory().create(tier="large")`。
- 所有记忆相关 prompt 正文放在 `prompts/` 目录，通过现有 `PromptManager` 渲染，便于统一检查和后续维护。
- Prompt 输入包含：
  - 用户命令：`sys.argv` 经 shell 安全展示后的文本。
  - 当前命令 help：通过 Typer command context 或回退 help 生成函数获取。
  - stdout/stderr：默认各自截断到固定字符数，避免 prompt 过长和敏感信息扩散。
  - exit code 和耗时。
- Prompt 输出要求简短 Markdown，不允许输出 JSON 以外的额外结构要求；解析端不做复杂解析，只将模型文本作为摘要正文或从中抽取固定小节。
- 测试中通过 fake summarizer 覆盖成功、失败和 fallback，不调用真实 LLM。

## TDD/测试策略

Test Writer 阶段先写测试，预期实现前红灯：

- `memory/day/YYYY-MM-DD.md` 不存在时自动创建父目录并追加单次命令记忆。
- 追加多次命令不会覆盖已有 day 内容。
- 单次命令摘要调用 small tier summarizer，并包含 argv、stdout、stderr、exit code 和 help 信息。
- `diary summary` 调用 large tier summarizer，输入为当天 `memory/day/YYYY-MM-DD.md` 的内容。
- `diary append` 为缺失 summary 的日期调用 large tier summarizer。
- summarizer 失败时写入 fallback 记录，原命令退出码不被改写。
- `diary summary --date YYYY-MM-DD` 读取对应 day 文件并写入 `memory/summary/YYYY-MM-DD.md`。
- `diary summary` 默认总结今天；如果 day 文件不存在，给出清晰提示并返回非 0。
- `diary append` 默认从本月 1 号处理到昨天，只为存在 day 文件但不存在 summary 文件的日期生成 summary。
- `diary append --month YYYY-MM` 可处理指定月份；未来月份或格式错误返回清晰错误。
- `diary append` 不重复覆盖已存在 summary，除非后续显式加 `--force`；本轮不默认加 force。
- CLI 注册 `diary summary` 和 `diary append`。
- 脚本入口指向 `_main_wrapper`，并保留 `bill` 默认子命令改写行为。
- `diary` 命令自身写入 `memory/day`。

红灯策略：

- 在生产实现不存在时，`tests/test_memory_service.py` 和 `tests/test_diary_command.py` 应导入失败或行为失败。
- CLI 捕获类测试通过 fake command / monkeypatch summarizer 验证包装逻辑，不运行真实外部命令。

## Verify 标准

### 自动化验证

最小验证命令：

```bash
uv run pytest tests/test_memory_service.py tests/test_diary_command.py tests/test_cli_memory_capture.py tests/test_cli_entrypoint.py -xvs
uv run ruff check src/beartools/memory src/beartools/commands/diary src/beartools/cli.py tests/test_memory_service.py tests/test_diary_command.py tests/test_cli_memory_capture.py tests/test_cli_entrypoint.py
uv run mypy src/beartools/memory src/beartools/commands/diary src/beartools/cli.py
```

预期结果：全部通过。

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期结果：全部通过；如果遇到既有无关失败，记录失败命令、原因和与本次改动的关系。

### 冒烟端到端验证

建议关键路径：

```bash
rm -rf /tmp/beartools-memory-smoke
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-smoke uv run beartools doctor
mkdir -p /tmp/beartools-memory-smoke/day
printf '## 09:00:00 beartools doctor\n\n- 目的：验证环境\n- 结果：doctor 已运行\n' > /tmp/beartools-memory-smoke/day/2026-05-10.md
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-smoke uv run beartools diary summary --date 2026-05-10
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-smoke uv run beartools diary append --month 2026-05
find /tmp/beartools-memory-smoke -type f | sort
```

预期结果：

- `beartools doctor` 正常输出健康检查结果，退出码保持原样，并在 smoke memory root 下写入当天 day 文件。
- 手工创建的 `day/2026-05-10.md` 可用于验证 `diary summary --date 2026-05-10` 写入 `summary/2026-05-10.md`。
- `diary append --month 2026-05` 不重复覆盖已有 summary，并对本月 1 号到昨天的已有 day 文件补齐 summary。
- `diary summary` / `diary append` 自身执行后也会进入当天 day 记忆。
- 如果本地 small LLM 不可用，原命令仍成功；记忆文件中出现 fallback 记录，最终结果说明真实 LLM 摘要未完成。

### 全面端到端验证

建议本轮全面 E2E 包含真实 small 模型路径和失败 fallback 路径：

```bash
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-e2e uv run beartools check prompt
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-e2e uv run beartools diary summary
BEARTOOLS_MEMORY_ROOT=/tmp/beartools-memory-e2e uv run beartools diary append
```

预期结果：

- `check prompt` 的原有输出和退出码不因记忆系统改变。
- day 文件包含本次命令目的、结果、help 摘要和退出码。
- summary 文件是一日一条的 Markdown 总结。
- `diary` 命令自身也追加新的 day 记录。

如果用户希望本轮不消耗真实模型调用，可明确确认省略全面 E2E 的真实 small 模型部分；届时只执行 fake/fallback 路径，并记录剩余风险：真实模型 prompt 质量和网关兼容性未被当前回合验证。

## 分步实施计划

1. Planner：写入本计划文档，等待用户确认计划和三类 Verify 标准。
2. Test Writer：新增 `memory` service、`diary` command、CLI capture 的红灯测试。
3. Executor：实现记忆数据模型、服务、small summarizer、`diary` 命令和 CLI 包装入口。
4. Verify：按确认的自动化、冒烟 E2E、全面 E2E 标准执行验证。
5. Reviewer：按 `docs/checklists/review.md` 检查 diff；由于涉及持久化本地记忆和命令输出采集，轻量参考 `docs/checklists/audit.md`。
6. Fix Loop：修复 Verify/Review 发现的问题，最多 3 轮内部修复后再请求用户决定。
7. Documentation Sync：更新 `docs/codemap.md` 和本计划最终结果；如发现稳定操作规则变化，再建议是否更新 `AGENTS.md`。

## 风险、回滚和需要用户确认的问题

风险：

- 捕获 stdout/stderr 可能影响 Rich 控制台效果；实现需尽量原样回放并在测试中覆盖普通输出路径。
- Typer/Click 对退出码和异常处理较敏感；入口包装必须保留原始退出码。
- LLM 摘要可能泄露命令输出里的敏感信息；需要截断、脱敏和失败 fallback。
- 将脚本入口改为 `_main_wrapper` 是全局行为变更；虽然范围合理，但必须用 CLI entrypoint 测试保护。

回滚：

- 将 `pyproject.toml` 脚本入口恢复为 `beartools.cli:app`。
- 删除 `src/beartools/memory/`、`src/beartools/commands/diary/` 和相关测试。
- 从 `src/beartools/cli.py` 移除 `diary` 注册和记忆捕获包装。
- 删除本轮生成的 `memory/` 测试产物；正式实现中测试应使用临时目录或 `BEARTOOLS_MEMORY_ROOT`，不污染项目真实记忆。

需要用户确认：

已确认：

1. 第一版只记录 `beartools` CLI 自己的命令，不记录任意 shell 命令；总结依据是命令、CLI/console 显示信息和当前命令 help。
2. `diary` 命令自身写入 day 记忆。
3. LLM 记忆失败不改变原命令退出码，并写入 fallback 记录。
4. 日期文件名采用 `YYYY-MM-DD.md`，作为“年月日.md”的具体落盘格式。
5. 三类 Verify 标准已确认；冒烟 E2E 使用 `doctor` 验证 day 记录，并创建 `2026-05-10` day 数据验证 `diary summary` 和 `diary append`。
6. `diary summary` / `diary append` 使用 large 模型生成 daily summary。
7. `diary append` 默认不覆盖已经存在的 summary。

## 最终实现结果

- 新增 `src/beartools/memory/`，包含记忆数据模型、Prompt 渲染和业务服务。
- 新增 `prompts/cli_command_memory.md` 和 `prompts/cli_daily_summary.md`，记忆相关 prompt 已统一放在 `prompts/` 目录，通过 `PromptManager` 渲染。
- 新增 `beartools diary summary` 和 `beartools diary append`。
- `pyproject.toml` 的脚本入口改为 `beartools.cli:_main_wrapper`，使 CLI 入口包装和既有 `bill` 默认子命令逻辑真实生效。
- `_main_wrapper()` 捕获 beartools 命令、CLI/console 输出、退出码和 help 摘要，命令完成后追加写入 `memory/day/YYYY-MM-DD.md`。
- 单次命令记忆用 small 模型；daily summary 用 large 模型。
- `diary` 命令自身也进入 day 记忆。
- `diary append` 默认只补齐缺失 summary，不覆盖已有 summary。

## 最终 Verify 结果

自动化验证：

- `uv run pytest tests/test_memory_service.py tests/test_diary_command.py tests/test_cli_memory_capture.py tests/test_cli_entrypoint.py -xvs`：通过，17 passed。
- `uv run pytest tests/test_memory_service.py tests/test_diary_command.py tests/test_cli_memory_capture.py tests/test_prompt_checker.py -xvs`：迁移 prompt 到 `prompts/` 后通过，23 passed。
- `uv run beartools check prompt --name cli_command_memory`：通过，1 checked，status pass。
- `uv run beartools check prompt --name cli_daily_summary`：通过，1 checked，status pass。
- `uv run pytest tests/ -xvs`：最终通过，367 passed。
- `uv run ruff check .`：通过。
- `uv run mypy .`：通过，70 source files。

冒烟 E2E：

- 使用 `BEARTOOLS_MEMORY_ROOT=/private/tmp/beartools-memory-smoke-codex-2` 运行 `uv run beartools doctor`，退出码为 0，输出正常，且当天 day 记忆写入成功。
- 手工创建 `/private/tmp/beartools-memory-smoke-codex-2/day/2026-05-10.md` 后运行 `uv run beartools diary summary --date 2026-05-10`，生成 `/private/tmp/beartools-memory-smoke-codex-2/summary/2026-05-10.md`。
- 运行 `uv run beartools diary append --month 2026-05`，已有 summary 未被覆盖，输出 `补齐 0 天 summary`。
- 冒烟中通过 fake summary 环境变量避免消耗真实 LLM；真实网关调用路径由单元测试和 `LLFactory` 既有测试覆盖，真实模型质量仍属于运行时风险。

## Review 结论

未发现阻塞性问题。

剩余风险：

- CLI 包装会捕获并回放 stdout/stderr，已用 `doctor`、`diary` 和完整测试套件覆盖，但极少数依赖原始 TTY 行为的命令未来可能需要专项适配。
- day 记忆会包含截断后的 console stdout/stderr；prompt 已要求不要输出密钥，仍建议用户避免在 CLI 输出中直接打印敏感配置。
- 冒烟 E2E 使用 fake summary，没有消耗真实 small/large 模型；真实模型输出质量需要在实际使用中继续观察。

文档同步：

- 已更新 `docs/codemap.md`，补充 CLI 入口、`diary` 命令、`memory` 模块职责和 prompt 管理约定。
