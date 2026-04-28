# bill run 进度输出设计

## 背景

`bill run` 在执行 `normalize -> analysis` 完整链路时，`analysis` 阶段会逐行调用大模型分析账单用途与归属人。由于大模型调用耗时不稳定，用户在命令执行期间容易误以为命令卡住，缺少对当前阶段与处理进度的感知。

当前 `bill` 命令只会在流程结束后一次性打印最终结果，不会在运行中输出状态；仓库中虽有 `doctor` 命令的阶段性输出模式，但没有适用于长耗时 LLM 分析场景的定时进度播报机制。

## 目标

- 为 `bill run` 增加运行中进度输出，降低长耗时阶段的不确定感。
- 每隔 3 秒输出当前步骤。
- 当当前步骤为 `Analysis` 时，额外输出“已完成分析的总行数”。
- `Analysis` 期间使用单行覆盖刷新；步骤切换时使用换行输出，保证终端阅读体验清晰。
- 保持 `bill run` 现有业务流程、输出文件规则与错误处理语义不变。

## 非目标

- 不修改 `normalize` 与 `analysis` 的业务处理规则。
- 不引入 Rich `Live`、`Progress` 等复杂终端渲染组件。
- 不实现 token 级别的大模型流式输出。
- 不调整 `bill analysis` 单独命令的最终输出结构，除非后续确认要复用同一套进度机制。
- 不改变现有日志系统，仅增强命令行 stdout 可见进度。

## 用户可见行为

### 输出规则

- `bill run` 启动后，当步骤发生变化时，输出一行新的步骤提示。
- 如果当前步骤为 `Analysis`，则每隔 3 秒刷新同一行，显示当前已完成分析的总行数。
- 当 `Analysis` 结束并进入下一步骤时，先结束当前覆盖行，再输出新的步骤行。
- 命令完成或失败时，停止进度输出，随后打印原有最终结果或错误信息。

### 文案格式

- 普通步骤：`当前步骤: Normalize`
- Analysis 首次进入：`当前步骤: Analysis`
- Analysis 定时刷新：`当前步骤: Analysis，已分析: 12`

### 计数口径

- `已分析` 采用“**已完成分析的总行数**”口径。
- 仅当单行 analysis 调用返回后，计数才加一。
- 单行失败但已完成返回并被兜底写入 `unknow` 时，也计入“已分析”。
- 因整体失败提前中断时，最后一次显示的计数应反映中断前已经完成返回的总行数。

## 技术方案

### 总体选择

采用“**command 层定时播报 + service 层暴露轻量进度状态**”方案。

- `command` 层负责启动、停止进度播报线程，以及终端输出策略。
- `service` 层负责在真实处理流程中维护当前步骤与 analysis 完成计数。
- 普通换行输出继续使用现有 `rich.console.Console.print()`。
- Analysis 单行覆盖刷新采用 `sys.stdout.write("\r...") + flush()`。

该方案优于在 service 层直接打印，因为它能保持业务层与输出层解耦，也比引入 Rich Live 更轻量、更容易测试。

## 模块设计

### 1. 进度状态对象

新增一个轻量进度状态对象，职责仅为承载当前运行状态，不承担业务逻辑。

建议字段：

- `current_step: str`
- `analysis_completed_count: int`

状态对象需要满足：

- 默认初始值清晰，可表示“尚未进入任何步骤”。
- 可被 `service` 更新、被 `command` 轮询读取。
- 字段语义稳定，避免把终端展示文案直接写死在业务层。

如有并发可见性顾虑，可在对象内部补充轻量锁，但本次场景只有单写线程 + 单读线程，优先保持实现简单。

### 2. service 层状态推进

在 `run_bill_pipeline()` 中按阶段推进状态：

1. 进入 normalize 前，设置 `current_step = "Normalize"`
2. normalize 完成后，进入 analysis 前，设置 `current_step = "Analysis"`
3. analysis 逐行处理期间，每当单行分析返回，递增 `analysis_completed_count`
4. analysis 结果写盘或收尾时，可设置后续步骤名（如 `SaveResult`），或在流程结束前保持 `Analysis`

其中最关键的挂点是现有 `_process_data_rows()` 中逐行调用分析器的循环；该位置已经天然具备“单行分析完成”的时机，是更新 `analysis_completed_count` 的最准入口。

### 3. command 层进度播报器

在 `bill run` 命令中引入轻量进度播报器：

- 在执行 `run_bill_pipeline()` 前启动后台线程
- 后台线程每 3 秒读取一次进度状态
- 若发现步骤发生变化：
  - 若上一状态为 Analysis 单行刷新，先补换行
  - 使用 `Console.print()` 输出新的步骤行
- 若当前步骤仍为 `Analysis`：
  - 使用 `sys.stdout.write("\r...")` 覆盖同一行
  - 使用 `sys.stdout.flush()` 立即刷新终端
- 命令结束或异常退出时，通过 `threading.Event` 通知线程停止，并完成最后一行清理

### 4. 输出通道选择

采用混合输出：

- **换行消息**：`Console.print()`
- **覆盖刷新消息**：`sys.stdout.write()` + `flush()`

原因：

- `Console.print()` 默认追加换行，适合步骤切换与最终结果。
- `sys.stdout.write("\r...")` 更适合实现 Analysis 期间同一行覆盖刷新。
- 不引入 Rich `Live` / `Progress`，避免终端渲染复杂度和测试负担。

## 执行流程

### 正常链路

1. `bill run` 创建进度状态对象。
2. `bill run` 启动进度播报线程。
3. `run_bill_pipeline()` 进入 `Normalize`，播报器输出：`当前步骤: Normalize`
4. 进入 `Analysis`，播报器换行输出：`当前步骤: Analysis`
5. Analysis 期间每 3 秒覆盖刷新：`当前步骤: Analysis，已分析: N`
6. 流程完成，播报器停止。
7. CLI 输出原有最终结果与成功提示。

### 异常链路

1. 任一阶段抛错后，`bill run` 仍必须停止播报线程。
2. 如果异常发生在 Analysis 覆盖刷新期间，需要先结束当前覆盖行，避免错误信息顶在同一行后面。
3. 随后按现有规则输出 `❌` 错误信息并返回非零退出码。

## 错误处理

- 进度播报失败不能影响主流程业务结果；如播报线程内部出现可恢复问题，应尽量静默退出，不反向中断账单处理主流程。
- 主流程异常优先级高于进度输出，不能因为 UI 层状态问题吞掉真实业务异常。
- 若进度状态对象未传入，`run_bill_pipeline()` 与 `analyze_bill_file()` 应继续保持当前行为，避免影响既有调用方。

## 代码边界

### command 层职责

- 创建与持有进度状态对象
- 启动/停止定时播报线程
- 决定 stdout 展示方式
- 在结束时确保终端输出落在干净的新行上

### service 层职责

- 在真实处理阶段推进步骤状态
- 在单行 analysis 完成后更新计数
- 不直接进行 console/stdout 输出

### agent / LLM 层职责

- 不改动大模型调用协议
- 不新增 token 流式回调

## 测试策略

### service 测试

- 新增进度状态推进测试：验证 `run_bill_pipeline()` 会正确设置步骤。
- 新增 analysis 计数测试：验证 `analysis_completed_count` 仅在单行分析完成返回后增加。
- 验证单行失败但被兜底写入时，计数仍然累计。

### command 测试

- 新增 `bill run` 进度输出测试：验证步骤切换时会输出新行文案。
- 新增 Analysis 刷新测试：验证会输出带有 `当前步骤: Analysis，已分析:` 的进度内容。
- 新增异常链路测试：验证异常时不会把错误信息粘连在覆盖刷新行后面。

### 回归测试

- 保持现有 `bill run` 最终结果输出测试通过。
- 保持 `bill normalize` / `bill analysis` 独立命令行为不变。

## 兼容性说明

- 本次改动只增强 `bill run` 运行中的用户可见进度，不改变最终输出结果结构。
- 对脚本调用方而言，stdout 中会新增中间进度信息；如果外部脚本严格按固定行号解析输出，需要调整为按关键字段匹配。
- 输出文件、异常码、analysis 失败阈值与 `unknow` 兜底逻辑保持不变。

## 待实现文件清单

### 需要修改

- `src/beartools/commands/bill/command.py`
  - 为 `bill run` 增加进度播报器与终端输出协调逻辑。
- `src/beartools/bill/service.py`
  - 为 pipeline 和 analysis 增加可选进度状态推进。
- `src/beartools/bill/models.py`
  - 如现有模型中没有合适位置，新增轻量进度状态模型。
- `tests/test_bill_command.py`
  - 增加运行中进度输出相关测试。
- `tests/test_bill_service.py`
  - 增加进度状态推进与 analysis 计数测试。

### 预计无需修改

- `src/beartools/bill/agent.py`
  - 不涉及大模型调用协议改动。
- `src/beartools/llm/runtime.py`
  - 不涉及节点选择、故障切换与底层 LLM 运行时逻辑变更。
