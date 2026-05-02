## 背景

当前 `src/beartools/codex.py` 会创建一个未挂载任何工具的 `agents.Agent`，因此 Codex 运行时只能输出文本，不能执行联网搜索或本地命令。当前目标是以最小改动方式，为 Codex 接入两个官方工具：`WebSearchTool` 与 `ShellTool`。

## 目标

- 为 `src/beartools/codex.py` 中创建的 Agent 显式挂载 `WebSearchTool()`。
- 为同一个 Agent 显式挂载 `ShellTool(executor=...)`。
- `ShellTool` 固定在仓库根目录下的 `output/codex` 作为工作目录执行。
- 保持现有 trace/final output 行为兼容，不引入额外的大范围重构。

## 非目标

- 本次不接入 `FileSearchTool`。
- 本次不接入 `ApplyPatchTool`。
- 本次不实现 shell 审批流、命令白名单/黑名单、沙箱隔离。
- 本次不引入新的 codex runtime 抽象层。

## 方案选择

本次采用方案 A：直接在 `src/beartools/codex.py` 中完成工具装配，并补一个项目内的本地 shell executor。

选择原因：

- 改动集中，便于快速验证。
- 与当前 `codex.py` 已承担 Agent 组装职责的结构保持一致。
- 满足“先接入 `WebSearchTool + ShellTool` 即可”的范围要求。

未采用的方案：

- 抽离 `codex_tools.py` 或 `codex_runtime.py`：结构更清晰，但超出本次最小接入目标。
- 仅接入 `WebSearchTool`：不满足当前需求。

## 设计细节

### Agent 工具挂载

在 `src/beartools/codex.py` 的 `_stream_codex_events()` 中，创建 Agent 时显式传入：

- `WebSearchTool()`
- `ShellTool(executor=...)`

这样工具能力只对 codex 运行链路生效，不影响其他模块。

### ShellTool 执行器

新增一个项目内的本地 shell executor，用于适配 `ShellTool` 需要的执行协议。

执行器职责：

- 接收 SDK 传入的 shell command request。
- 确保工作目录 `output/codex` 存在。
- 在 `output/codex` 下执行命令。
- 使用 `codex.timeout_seconds` 作为命令超时。
- 收集并返回 `stdout`、`stderr`、`exit_code` 等信息。

执行器约束：

- 工作目录固定为仓库根目录下的 `output/codex`。
- 不读取 markdown 文件所在目录作为工作目录。
- 不增加单独的 shell 工作目录配置项。

### 配置策略

继续复用现有配置：

- `codex.base_url`
- `codex.api_key`
- `codex.model`
- `codex.instructions`
- `codex.output_dir`
- `codex.timeout_seconds`

本次不新增 `enable_shell`、`enable_web_search`、`shell_working_dir` 等配置项。

### 事件与输出

现有 `tool_called` / `tool_output` 事件处理逻辑保留，目标是让新接入的工具自然进入当前输出链路：

- console 中继续打印 `[tool:start]` 与 `[tool:output]`
- trace 文件继续逐行记录序列化事件

如果 shell 执行失败：

- 优先通过 tool 输出保留错误详情
- 如果最终上抛异常，则继续复用现有失败落盘逻辑：
  - final output 写入 `[未完成]`
  - trace 追加 `error` 事件

## 代码改动范围

预计涉及：

- `src/beartools/codex.py`
  - 新增 tool 构建逻辑
  - 新增 shell executor
  - 在 Agent 创建时挂载 `WebSearchTool` 与 `ShellTool`

- `tests/` 下 codex 相关测试
  - 验证 Agent 包含目标工具
  - 验证 shell executor 使用 `output/codex`
  - 验证结果结构可被现有 trace 链路消费

## 测试策略

最小必要测试包括：

1. Agent 创建时包含 `WebSearchTool`
2. Agent 创建时包含 `ShellTool`
3. shell executor 固定在 `output/codex` 工作目录执行
4. 现有 `codex run` 命令测试不被破坏

如需避免真实网络和真实 shell 副作用，测试中优先使用 monkeypatch 或伪造 executor 输入输出。

## 风险与后续

当前方案的已知风险：

- `ShellTool` 引入了本地命令执行能力，后续如果对安全性要求提高，需要补审批或限制策略。
- `WebSearchTool` 依赖服务端能力与模型/tool 支持，实际可用性需通过联调验证。
- 如果后续继续接入 `ApplyPatchTool`，`codex.py` 可能需要再抽象一层工具构建逻辑。

后续可选增强：

- 为 shell 增加审批开关
- 将 tool 构建抽离到独立模块
- 增加更细粒度的 trace 结构化展示
