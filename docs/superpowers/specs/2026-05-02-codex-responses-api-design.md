## 背景

当前 `src/beartools/codex.py` 使用 `OpenAIChatCompletionsModel` 创建 Agent，同时挂载了 `WebSearchTool` 与 `ShellTool`。运行 `uv run beartools codex run ./input/m1.md` 时，OpenAI Agents SDK 明确报错：hosted tools 不支持 ChatCompletions API，`WebSearchTool` 必须运行在 Responses API 路线上。

用户要求保留现有功能，包括：

- 继续支持 `WebSearchTool`
- 继续支持 `ShellTool`
- 保留当前 CLI、trace 文件、final output 文件行为
- 尽量使用官方事件与 tool item 定义，不额外引入自定义 class 或自定义 tool 事件结构

## 目标

- 将 codex 运行链路从 `OpenAIChatCompletionsModel` 切换到 `OpenAIResponsesModel`
- 保留 `WebSearchTool + ShellTool` 混用能力
- 保留 `Runner.run_streamed(...).stream_events()` 流式处理模式
- 改为直接消费官方事件 / item 类型，减少中间自定义事件结构

## 非目标

- 本次不移除 `WebSearchTool`
- 本次不移除 `ShellTool`
- 本次不改 CLI 入口参数
- 本次不修改 `CodexConfig` 配置结构
- 本次不引入新的运行时抽象层

## 方案选择

采用方案 A：显式将 model 从 `OpenAIChatCompletionsModel` 切换为 `OpenAIResponsesModel`，并保留现有 `Runner.run_streamed` 结构。

选择原因：

- 官方 hosted tools 与 Responses API 路线天然兼容
- 与当前代码结构最接近，改动边界清晰
- 相比隐式依赖 SDK 默认 API，显式 model 更利于阅读、调试和后续维护
- 能在保留现有 shell/trace/final output 行为的前提下完成兼容修复

未采用方案：

- 方案 B：依赖 SDK 默认 Responses API。问题是行为更隐式，不利于结合当前自定义 `base_url` 做排查。
- 保留 ChatCompletionsModel 并改写 WebSearch 为函数工具。问题是不符合“保留官方 `WebSearchTool`”的要求。

## 设计细节

### 1. 模型初始化切换

在 `src/beartools/codex.py` 中：

- `OpenAIChatCompletionsModel` 替换为 `OpenAIResponsesModel`
- `AsyncOpenAI(api_key=..., base_url=...)` 保持不变
- `Agent(..., tools=_build_codex_tools())` 保持不变

预期效果：

- `WebSearchTool` 将运行在官方支持的 Responses API 路径
- `ShellTool` 继续作为本地 runtime tool 一起工作

### 2. 流式事件消费改造

当前代码会把官方事件再手工转换成自定义 dict，例如：

- `{type: "tool_called", ...}`
- `{type: "tool_output", ...}`

本次要尽量改成直接使用官方事件与 item 类型，不额外定义自定义 class，也尽量少做中间结构重组。

消费原则：

- 顶层事件优先基于官方 `event.type` 分发
- 文本增量使用 `ResponseTextDeltaEvent`
- 工具调用使用官方 `ToolCallItem`
- 工具输出使用官方 `ToolCallOutputItem`
- reasoning 使用官方 `ReasoningItem`

允许的最小转换范围：

- 为了兼容现有 trace 写入与 console 输出，可以在“写日志/打印”这一层提取字段值
- 但不再额外发明新的事件 class，也不再把整条语义事件重新拼装成内部自定义协议

### 3. 保留现有外部行为

需要保持这些行为不变：

- `codex run` 命令入口不变
- 输出文件路径规则不变
- trace 文件继续逐行写事件信息
- final output 继续通过文本 delta 拼接
- `ShellTool` 继续固定在 `output/codex` 目录执行

如果 Responses API 下工具事件的对象结构与原先测试假设不完全一致，则：

- 调整测试和事件解析实现
- 不改 CLI 对用户暴露的行为

### 4. 测试策略

需要补足或调整这些测试：

1. 验证 codex 使用 `OpenAIResponsesModel` 而不是 `OpenAIChatCompletionsModel`
2. 验证 `WebSearchTool + ShellTool` 仍一起挂载
3. 验证流式输出测试在 Responses 路线下仍能写入 trace / final output
4. 保留现有 shell executor 工作目录测试

测试实现上优先：

- monkeypatch 官方 model 类与 Runner
- 使用官方事件 / item 的最小替身或兼容对象模拟 SDK 返回
- 避免继续扩大自定义协议范围

## 代码改动范围

预计涉及：

- `src/beartools/codex.py`
  - 切换 model 类型
  - 调整事件消费方式，尽量改成官方事件/官方 item 驱动

- `tests/test_codex_command.py`
  - 更新 model 路径断言
  - 更新事件模拟方式与断言

## 风险与注意事项

- Responses API 下事件对象与当前手工 dict 方案不同，改造时需要以官方文档和 SDK 源码字段为准
- 如果 trace 文件当前强依赖自定义 dict 结构，迁移后 trace 内容可能会在字段层面略有变化，但要保持可读性和问题定位能力
- 若 SDK 对 Responses 模式下某些事件名称或 item 类型有版本差异，需要在测试中保持足够稳健，避免只对某一个字符串写死断言

## 验收标准

- `uv run beartools codex run ./input/m1.md` 不再报 hosted tools 与 ChatCompletions API 不兼容错误
- `WebSearchTool` 保留可用
- `ShellTool` 保留可用
- codex 相关测试、ruff、mypy 通过
