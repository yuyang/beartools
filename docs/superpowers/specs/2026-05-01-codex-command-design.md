# Codex 子命令设计

## 背景

beartools 目前已经有多个 CLI 子命令，但还没有一个面向 Codex 的独立入口。现有 `agent`/`llm` 配置主要服务于通用 LLM 运行时，不适合直接承载 Codex 的专用能力，尤其是以下要求：

- 使用独立的 `api_key`、`base_url`、`model` 配置
- 输入来自本地 Markdown 文件，而不是命令行直接输入文本
- 通过 Codex SDK 的 stream 模式实时输出过程
- 除最终回答外，还需要保留 thinking/tool 过程日志

因此需要新增独立 `codex` 子命令与专用配置、执行模块。

## 目标

新增 `beartools codex run <md_path>` 命令，读取本地 Markdown 文件全文作为 prompt，使用 Codex 官方流式 SDK 执行，并满足以下行为：

- 实时将 stream 事件输出到 console
- 实时将 stream 事件写入日志
- 记录每次工具调用信息
- 记录 thinking/reasoning 过程
- 生成两份结果文件：最终回答文件和 trace 文件

## 范围

本次只支持本地 Markdown 文件路径，不支持 HTTP/HTTPS URL。

本次只实现单次执行命令，不实现交互式 REPL。

本次不复用现有 `beartools.llm.factory`，避免将通用 LLM 运行时与 Codex 专用流式事件模型耦合。

## 采用方案

本次只保留一个实现方案：独立 `codex` 命令组 + 独立 Codex 执行模块。

实现方式：

- 在 CLI 中新增 `codex` 命令组
- 增加 `run` 子命令
- 新增 `CodexConfig`
- 新增专用执行模块消费 Codex SDK 事件流

选择这个方案的原因：

- 与现有 `gmail`、`record` 等命令组风格一致
- 配置边界清晰，不污染通用 `agent` 配置
- 更容易扩展后续的 `codex doctor`、`codex config` 等子命令
- 更容易围绕 stream 事件实现 console、log、trace 三路输出

## 命令设计

### CLI 入口

新增命令组：

- `beartools codex`

新增子命令：

- `beartools codex run <md_path>`

建议参数：

- 位置参数 `md_path`：本地 Markdown 文件路径
- 可选参数 `--output-file`：指定最终回答输出文件路径
- 可选参数 `--trace-file`：指定 trace 输出文件路径

如果未显式指定输出路径，则自动写入 `codex.output_dir`。

### 默认输出文件命名

假设输入文件为 `docs/prompt/foo.md`，默认输出：

- 最终回答：`<codex.output_dir>/foo.codex.md`
- trace 文件：`<codex.output_dir>/foo.codex.trace.log`

## 配置设计

新增 `codex` 配置块，与 `agent` 完全隔离。

建议字段：

- `base_url`：Codex 服务地址
- `api_key`：Codex 独立密钥
- `model`：Codex 使用的模型名
- `output_dir`：输出目录
- `timeout_seconds`：单次执行超时
- `bin_path`：可选，本地 Codex runtime/CLI 路径（若 SDK 需要）

配置来源优先级继续沿用项目现有规则：

- 环境变量
- `config/beartools.secrets.yaml`
- `config/beartools.yaml`

示例上需要同时更新：

- `config/beartools.yaml.sample`
- `config/beartools.secrets.yaml.sample`

## 模块拆分

建议新增以下文件：

- `src/beartools/commands/codex/__init__.py`
- `src/beartools/commands/codex/command.py`
- `src/beartools/codex.py` 或 `src/beartools/codex/client.py`

职责划分如下。

### `commands/codex/command.py`

负责：

- 解析 CLI 参数
- 校验输入文件存在且可读
- 调用业务层执行
- 统一处理 CLI 层错误并转换为退出码

### `codex` 业务模块

负责：

- 读取 Markdown 文件内容
- 创建 Codex SDK client/runtime
- 消费 stream 事件
- 将事件分发到 console、logger、trace 文件
- 聚合最终回答文本
- 写出最终回答文件

## 数据流

执行流程如下：

1. 用户执行 `beartools codex run <md_path>`
2. CLI 校验 `md_path` 是存在且可读的本地文件
3. 读取 Markdown 全文作为 prompt
4. 加载独立 `codex` 配置
5. 初始化 Codex SDK / runtime
6. 以 stream 模式发起请求
7. 对每个 stream 事件执行分发：
   - 输出到 console
   - 写入应用日志
   - 写入 trace 文件
   - 如属于最终回答文本，则累计到结果缓冲区
8. turn 完成后，将最终回答缓冲区写入最终输出文件
9. console 打印输出文件路径与 trace 文件路径

## 事件处理设计

本需求的关键不只是拿到最终文本，而是完整消费 Codex 事件流。

事件处理分三类。

### 一、thinking/reasoning 事件

目标：

- 用户可以在运行时看到 Codex 的思考过程
- 过程需要写入日志和 trace 文件

处理策略：

- 监听官方 SDK 中的 agent message / reasoning delta 事件
- console 输出时增加前缀，例如 `[thinking]`
- logger 记录原始事件或结构化摘要
- trace 文件保留可追溯原文

这些内容默认不写入最终回答文件，避免污染结果可读性。

### 二、tool 调用事件

目标：

- 用户知道本次执行调用了哪些 tool
- 用户知道 tool 的开始、完成和必要输出

处理策略：

- 监听工具调用开始事件
- 监听工具调用完成事件
- 如果官方事件模型支持工具运行增量输出，也同步打印与记录

console 建议展示格式：

- `[tool:start] bash`
- `[tool:output] ...`
- `[tool:done] bash`

logger 和 trace 文件保存完整信息，供排查问题使用。

### 三、最终回答文本事件

目标：

- 实时看到最终回答内容
- 最终回答需要单独聚合成可阅读文件

处理策略：

- 监听文本 delta 事件
- console 实时增量输出
- logger 和 trace 文件同步记录
- 同时将文本拼接到最终结果缓冲区

## 输出产物设计

为了兼顾“给人看”和“排问题”，本次采用双文件方案。

### 最终回答文件

保存内容：

- 输入 Markdown 路径
- 执行时间
- 模型信息
- 最终回答正文

用途：

- 面向阅读与复用
- 不混入 thinking/tool 噪声

### trace 文件

保存内容：

- 完整 stream 事件轨迹
- thinking/reasoning
- tool 调用开始/结束/输出
- 文本增量事件
- usage、结束状态、异常信息

用途：

- 调试
- 审计
- 回溯完整执行过程

## 日志策略

项目规范要求默认不要把日志系统直接打印到 console，因此本设计采用双通道：

- console 输出：使用 `rich.console.Console`
- 应用日志：使用现有 `get_logger(__name__)`

也就是说，实时输出到终端不是通过 logger 的 console handler 完成，而是业务层显式打印。

日志建议至少包含：

- 执行开始：输入路径、输出路径、模型名
- prompt 摘要或长度
- 每个重要 stream 事件的类型和内容
- 执行结束：总字数、usage、输出文件路径
- 异常详情

## 错误处理

需要覆盖以下失败场景：

- 输入 Markdown 文件不存在
- 输入路径不是文件
- 输入文件不可读
- `codex` 配置缺失或非法
- SDK 初始化失败
- 流式执行过程中网络/认证/超时失败
- 已收到部分事件后中断

处理原则：

- CLI 友好提示错误
- 返回退出码 1
- 若已有部分 trace，则尽量保留 trace 文件
- 若已有部分最终文本，也可以在结果文件中保留已累计内容，并明确标记为未完成

## 测试设计

按照 TDD，至少覆盖以下用例：

### CLI 测试

- `codex` 命令组已注册
- `codex run --help` 可正常显示

### 配置测试

- 可解析独立 `codex` 配置
- 不依赖 `agent` 公共配置
- 缺字段时给出明确错误

### 命令测试

- 成功读取 Markdown 并调用业务层
- 输入文件不存在时退出码为 1
- 默认输出路径生成正确

### 业务测试

- Markdown 读取正确
- 文本 delta 会累计到最终回答
- tool 事件会进入 trace 和日志分发
- reasoning 事件会进入 trace 和日志分发
- 最终回答文件与 trace 文件均成功写出
- 执行中途失败时仍能保留部分 trace

## 与现有代码的兼容性

本设计只新增模块和配置字段，不改变当前 `doctor`、`gmail`、`fetch`、`bill` 等既有命令行为。

不修改现有通用 `llm` 运行时，以降低回归风险。

## 结论

采用以下实现边界：

- 命令采用 `beartools codex run <md_path>`
- 仅支持本地 Markdown 文件
- 使用独立 `codex` 配置
- 使用 Codex 官方流式 SDK / 原生事件流模型
- 每个 stream 事件同时输出到 console 和日志
- 最终落盘两份文件：回答文件 + trace 文件

这个方案满足当前需求，也为后续扩展 Codex 相关子命令保留了清晰边界。
