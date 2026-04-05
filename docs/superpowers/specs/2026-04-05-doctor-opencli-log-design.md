# doctor opencli 输出截断与日志输出调整设计

## 背景

当前 `doctor` 命令中的 `opencli` 检查会将 `opencli doctor` 的完整输出放入 `detail`，并由 `doctor` 命令逐行打印到终端。输出过长时会污染 console，可读性较差。

同时，默认日志初始化会同时写入文件和 console，这与当前项目希望“终端展示只保留必要信息、详细调试信息查看日志文件”的使用方式不一致。

## 目标

1. `doctor` 命令在终端展示 `opencli` 检查结果时，只显示前 10 行和后 20 行。
2. 当中间内容被省略时，使用 `...(省略 X 行)` 明确标记。
3. 完整输出仍保留到日志文件，方便调试排查。
4. 默认日志配置不再向 console 输出，仅写入日志文件。
5. 将“不要把日志打印到 console，debug 时查看日志文件”写入 `AGENTS.md`。

## 方案对比

### 方案一：在 opencli 检查内部生成 console 摘要（采用）

- `opencli` 检查内部保留完整 stdout/stderr，用于写日志。
- 对外返回给 `doctor` 的 `detail` 改为摘要文本。
- `doctor` 现有展示逻辑保持不变。

优点：
- 改动集中，影响范围最小。
- 不需要改 `CheckResult` 结构。
- 能精准只影响 `opencli` 检查，不改变其他检查项行为。

缺点：
- `detail` 字段不再等于完整原始输出，而是终端展示摘要。

### 方案二：在 doctor 展示层统一截断

- `opencli` 检查继续返回完整 `detail`。
- `doctor` 在打印时识别并截断内容。

优点：
- 检查层保留原始语义。

缺点：
- 展示层需要理解具体检查项特例。
- 逻辑职责更混杂。

### 方案三：扩展结果模型，拆分 summary/full_detail

- `CheckResult` 同时提供摘要和完整输出。

优点：
- 语义最清晰。

缺点：
- 改动面偏大，不符合本次需求规模。

## 最终设计

### 1. opencli 检查输出处理

修改文件：`src/beartools/commands/doctor/checks/opencli.py`

- 新增一个内部辅助函数，用于将完整文本按“前 10 行 + 省略标记 + 后 20 行”生成摘要。
- 行数不超过 30 行时，直接原样返回。
- 省略标记格式固定为：`...(省略 X 行)`。
- `run()` 中仍然先拼出完整 `stdout/stderr` 文本。
- 返回给 `CheckResult.detail` 的内容使用摘要文本，而不是完整文本。
- 同时将完整文本写入日志，避免调试信息丢失。

### 2. doctor 命令展示逻辑

修改文件：`src/beartools/commands/doctor/command.py`

- 不改当前 console 输出流程。
- `print_result()` 继续逐行打印 `result.detail`。
- `logger.info(...)` 改为实际记录完整输出，而不是摘要输出。

为此需要在检查结果与日志记录之间建立“摘要/完整内容”的分工：
- console 只依赖 `CheckResult.detail`
- 日志记录显式使用 opencli 检查内部产出的完整输出

考虑到当前 `CheckResult` 没有独立字段保存完整输出，本次会采用最小改动方式：在 `opencli` 检查内直接额外记录完整日志，而不是扩展通用结果模型。

### 3. 默认日志配置调整

修改文件：`src/beartools/logger.py`

- 移除默认简单配置中的 `console_handler`。
- `QueueListener` 仅绑定 `file_handler`。
- 这样默认情况下日志只进入文件，不再打印到 console。
- 若未来使用外部 `logging` 配置文件，是否输出到 console 仍由该高级配置自行决定；本次不额外改高级配置机制。

### 4. 团队规范补充

修改文件：`AGENTS.md`

- 在项目规范中补充说明：
  - 不要把日志打印到 console。
  - 调试时优先查看日志文件。

## 数据流变化

### 调整前

1. `opencli doctor` 执行完成。
2. 完整 stdout/stderr 合并进 `CheckResult.detail`。
3. `doctor` 将完整 `detail` 逐行打印到终端。
4. logger 默认同时输出到 console 和文件。

### 调整后

1. `opencli doctor` 执行完成。
2. 完整 stdout/stderr 先在检查内部保留。
3. 生成摘要文本，放入 `CheckResult.detail` 供终端展示。
4. 完整输出直接写入日志文件。
5. 默认 logger 仅写文件，不再额外污染 console。

## 错误处理

- `opencli` 未安装：保持现有失败提示，不需要做截断。
- `opencli doctor` 超时：保持现有超时信息，日志中记录超时上下文。
- `opencli doctor` 非零退出：终端仍展示摘要，日志保留完整输出。
- 如果 stdout/stderr 为空：`detail` 允许为 `None`，保持现有行为。

## 测试策略

本次按 TDD 执行，至少补充以下测试：

1. 摘要函数在总行数不超过 30 行时返回原文。
2. 摘要函数在总行数超过 30 行时返回前 10 行、后 20 行与正确的省略行数。
3. `opencli` 成功执行且输出过长时，`CheckResult.detail` 为摘要而非完整文本。
4. 默认日志初始化后，根日志仅通过文件 handler 落盘，不向 console 输出。

## 涉及文件

- 修改：`src/beartools/commands/doctor/checks/opencli.py`
- 修改：`src/beartools/logger.py`
- 修改：`AGENTS.md`
- 可能修改：`tests/` 下对应测试文件（新增或扩展）

## 非目标

- 不统一改造所有 doctor 检查项的 detail 展示策略。
- 不扩展 `CheckResult` 通用数据结构。
- 不改高级 logging 配置文件的行为。
