# docs/superpowers 压缩归档计划

日期：2026-05-09
状态：历史计划归档
范围：将 `docs/superpowers` 下的一次性 spec/plan 压缩为可长期维护的历史上下文，并建立 `docs/plans/` 作为后续计划文档目录。

## 目标

- 删除 `docs/superpowers` 下过时的一次性施工稿。
- 保留已经落地或仍有维护价值的设计结论。
- 将这些结论作为一份历史 plan 归档到 `docs/plans/`。
- 后续所有新计划统一写入 `docs/plans/<YYYY-MM-DD>-<short-slug>.md`。

## 非目标

- 不恢复旧 plan 中的逐步 TDD 指令、commit 步骤、失败测试片段和 superpowers 执行要求。
- 不把历史设计结论塞回 `AGENTS.md`。
- 不替代 `docs/codemap.md` 的当前代码导航职责。

## 历史上下文压缩结果

以下内容从原 `docs/superpowers` 下的一次性 spec/plan 压缩而来。

## 账单处理

### `bill run` 默认入口

- `beartools bill <input> <from>` 由 CLI wrapper 自动改写为 `beartools bill run <input> <from>`。
- `bill run` 固定执行 `原始账单 -> normalize -> analysis`，不支持跳过阶段。
- 成功后保留两个产物：`*.normalized.xlsx` 与 `*.analysis.xlsx`。
- `normalize` 和 `analysis` 仍保持独立命令与独立 service 职责；编排逻辑只放在 `run_bill_pipeline()`。
- 如果 `analysis` 失败，已经生成的 normalized 文件可保留，analysis 输出不应作为成功产物保留。

### 运行进度

- `service` 层通过 `BillRunProgressState` / `NormalizeProgressSnapshot` 表达进度，不直接负责终端展示。
- `command` 层负责用户可见进度播报。
- `Analysis` 阶段使用同一行刷新已处理行数，普通步骤使用独立行输出。
- LLM agent 层不感知进度展示细节。

### 交易状态映射

- 原始交易状态必须先归一到标准状态：`NORMAL_SUCCESS`、`REFUND`、`PART_REFUND`、`IGNORE`。
- 状态映射配置位于 `config/bill_status_mapping.yaml`。
- 已知状态由配置匹配；未知状态抛出 `UnknownBillStatusesError`，由 CLI 交互确认后追加 exact mapping。
- 退款抵消、忽略行和部分退款金额修正都基于标准状态，而不是直接依赖原始文本。
- 部分退款金额解析通过专用 prompt 和 `calculate_expression()` 工具完成，避免把算术逻辑交给自由文本输出。

## LLM 配置与运行时

### large/small 节点池

- LLM 节点配置按 `large` 与 `small` 两组维护。
- 每组按配置顺序选择第一个健康节点；节点失败后按顺序切换到下一个可用节点。
- `small` 是兼容旧接口时的默认 tier。
- 运行时只做节点选择、健康探测、失败标记和回退，不做请求级透明重放。

### 敏感配置

- 主配置文件：`config/beartools.yaml`，用于普通配置。
- 敏感配置样例：`config/beartools.secrets.yaml.sample`。
- 本地敏感配置文件 `config/beartools.secrets.yaml` 不应进入版本库。
- LLM key、思源 token 等敏感值应从 secrets 文件或环境变量读取，避免写入公开样例和文档。
- 配置解析集中在 `config.py`；`llm/runtime.py` 和 `llm/factory.py` 只消费解析后的配置对象。

## Codex 命令

### Markdown 执行

- `beartools codex run <md_path>` 读取本地 Markdown 作为任务输入。
- 输出包括 final output 文件与 trace 文件，默认位于 `output/codex/`。
- 运行链路使用 OpenAI Agents SDK 的 `Runner.run_streamed(...).stream_events()`。
- 模型显式使用 `OpenAIResponsesModel`，以支持官方 hosted tools。
- `WebSearchTool` 与本地 `ShellTool` 一起挂载；shell 执行有超时、输出收敛和工作目录约束。
- trace 记录应偏向可诊断性，不要求保持旧 plan 中的中间事件结构。

### 图片生成与编辑

- `beartools codex pic <md_path>` 是 Markdown 图片任务入口，输出目录固定在 `out/pic/<stem>/`。
- `picbatch` 负责多个 Markdown 文件批量生成，单项失败不应吞掉错误信息。
- `picedit` 负责基于本地图片和提示词执行图片编辑。
- 图片任务支持 prompt refine、尺寸/质量/格式归一化、trace 脱敏和 token usage 提取。
- Codex 图片相关实现集中在 `codex_pic.py`，CLI 只做参数接收、错误展示和完成提示。

## Fetch 与 Markdown 抓取

- 专用处理器保留给微信和 X/Twitter，避免破坏已有图片内嵌和落盘行为。
- 未知域名走通用 Markdown fallback：`GenericMarkdownFetchHandler`。
- 通用处理器只封装 `opencli` 的 Markdown 抽取能力，不在项目内自研 HTML-to-Markdown。
- 通用抓取结果需要稳定写入 `.md` 文件，便于后续上传思源或测试断言。
- 抓取失败时尽量保留原始 URL、错误信息和命令输出，方便 CLI 展示和日志排查。

## Gmail

- `beartools gmail fetch` 负责拉取最近若干天的 INBOX 邮件。
- 默认最多处理 100 封，避免一次性请求和 LLM 摘要过大。
- Gmail OAuth、邮件列表、正文提取和 Markdown 输出集中在 `gmail.py`。
- CLI 层只处理参数、展示和错误退出。
- 摘要逻辑复用现有 LLM factory，不为 Gmail 单独维护另一套模型配置。

## Doctor

- `google_ping` 默认目标用于检查科学上网相关 HTTPS 连通性。
- 默认目标中使用 `wikipedia.org`，不再使用容易误报的 `x.com`。
- 默认成功阈值为 3 个目标成功。
- `doctor --run-llm` 才执行 LLM 检查，避免普通健康检查默认触发模型探测。
- 新增检查项应放在 `src/beartools/commands/doctor/checks/`，并通过 `register_check` 注册。

## CLI 集成验证

- 集成验证按 `core` 和 `live` 分组是合理边界：
  - `core`：本地、低副作用、适合频繁运行。
  - `live`：依赖真实服务、网络、凭据或本地外部程序。
- README 当前仍提到 `tests/test_cli_integration_commands.py`，但当前文件树未包含该文件；恢复集成测试前需要先确认其是否被移除、未提交或尚未创建。
- 项目内 `skills/testing-cli-integrations/` 和 `tests/assets/cli_integration_assets.yaml` 仍可作为恢复集成测试时的参考。

## 文档维护规则

- `docs/codemap.md` 维护当前代码结构、模块职责、调用链和测试地图。
- `docs/plans/` 维护未来所有计划文档，也承载这份历史压缩归档。
- 一次性 spec 不再单独常驻仓库；如果未来需要商业开发流程或 TDD flow，使用 `docs/workflows/codex-tdd-flow.md` 和 `docs/checklists/` 生成新的 plan。
- 当代码行为与本文不一致时，以代码为准，并同步更新 `docs/codemap.md` 或新增后续 plan 记录变化。
