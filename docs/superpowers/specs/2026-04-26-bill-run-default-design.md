# bill run 默认入口设计

## 背景

当前账单处理链路已经拆分为 `bill normalize` 与 `bill analysis` 两个职责明确的阶段，但实际使用场景中，用户更常见的需求是“给一个原始账单文件，直接得到最终分析结果”。

为减少命令记忆成本与重复手工操作，需要在保留现有分层职责的前提下，补充一个面向最终用户的默认执行入口，将原始账单处理为标准化结果并继续完成分析。

## 目标

- 新增 `bill run` 子命令，作为账单处理主入口。
- `bill` 作为默认入口时，行为等价于 `bill run`。
- `bill run` 只接受原始账单文件输入，固定执行流程为：`原始文件 -> normalize -> analysis`。
- 成功时同时保留 `*.normalized.xlsx` 与 `*.analysis.xlsx` 两个输出文件。
- 新增轻量 orchestration 层，负责串联流程与结果清理；`normalize` 与 `analysis` 继续各自负责本阶段业务逻辑。

## 非目标

- 不调整 `bill normalize` 与 `bill analysis` 的核心处理规则。
- 不支持 `bill run` 直接接收已标准化文件或跳过某一阶段执行。
- 不在本次设计中修改分析分类规则、LLM prompt 内容或失败阈值策略。
- 不引入新的输出格式、批量目录扫描模式或交互式确认流程。

## CLI 设计

### 命令结构

- 新增 `bill run <raw_file>`。
- `bill <raw_file>` 作为默认入口，等价于 `bill run <raw_file>`。
- 保留现有 `bill normalize <raw_file>`。
- 保留现有 `bill analysis <normalized_file>`。

### 参数约束

- `bill run` 仅接受原始账单文件路径。
- `bill analysis` 继续仅接受 `normalize` 产出的标准化文件。
- 默认入口改造仅影响 `bill` 根命令的直达行为，不改变已有显式子命令的参数语义。

### 示例

```bash
beartools bill run ./input/wechat.csv
beartools bill ./input/wechat.csv
beartools bill normalize ./input/wechat.csv
beartools bill analysis ./input/wechat.normalized.xlsx
```

## 执行流程

### bill run 主流程

1. 校验输入路径存在且为原始账单文件。
2. 调用 `normalize` service 生成 `*.normalized.xlsx`。
3. 若 `normalize` 成功，继续调用 `analysis` service，输入为上一步产出的标准化文件。
4. 若 `analysis` 成功，返回成功结果，并保留两个输出文件。

### 失败分支

1. `normalize` 失败：
   - 立即终止流程。
   - 不进入 `analysis`。
   - 不生成 `analysis` 输出。
2. `analysis` 失败：
   - 保留已经成功生成的 `*.normalized.xlsx`。
   - 不保留 `*.analysis.xlsx`。
   - 将错误向 CLI 抛出，由 CLI 统一输出失败信息并返回非零退出码。

## 输出文件规则

- 本次实现需要将 `run` 流程中的标准化产物命名明确为 `*.normalized.xlsx`。
- `analysis` 输出文件命名明确为 `*.analysis.xlsx`。
- 如当前 `normalize` 单独命令的输出命名与上述规则不一致，实现时需要一并对齐，避免 `bill run` 与 `bill normalize` 产物命名风格不同。
- `bill run` 成功时，最终目录中应同时存在：
  - `xxx.normalized.xlsx`
  - `xxx.analysis.xlsx`
- `bill run` 在 `analysis` 失败时，只允许留下 `xxx.normalized.xlsx`。
- 不新增第三种中间文件或临时持久化文件命名规则。

## 错误处理

### 编排层规则

- orchestration 层只负责流程编排、阶段衔接与输出保留策略。
- orchestration 层不吞掉底层异常，应保留原始错误语义并补充必要的阶段上下文。
- 当 `analysis` 失败时，如已生成目标 `*.analysis.xlsx`，需要确保该文件不会留在磁盘上。

### analysis 既有规则保持不变

- 单行 LLM 分析失败时，该行写入 `unknow`。
- 当失败行数超过 5 行时，整个 `analysis` 任务报错。
- 超过 5 行失败时报错时，不留下 `*.analysis.xlsx`。
- 这些规则在 `bill run` 场景下继续完全适用，不额外放宽或收紧。

## 代码边界

### 新增 orchestration 层职责

- 接收原始文件路径。
- 顺序调用 `normalize` 与 `analysis`。
- 根据阶段结果决定是否继续下一步。
- 负责 `bill run` 级别的输出保留与清理策略。
- 为 CLI 提供统一的高层调用入口。

### 现有 normalize / analysis 边界保持

- `normalize` 仍只负责原始账单到标准化 Excel 的转换。
- `analysis` 仍只负责读取标准化 Excel、逐行分析并生成分析结果文件。
- 不将 LLM 规则、Excel 读写细节或字段校验逻辑上提到 orchestration 层。
- CLI 层只做参数接收、命令分发、用户可见输出，不承载跨阶段业务逻辑。

## 测试策略

### 单元测试

- 为 orchestration 层新增成功链路测试，覆盖 `normalize -> analysis` 顺序调用。
- 为 orchestration 层新增 `normalize` 失败测试，验证不会继续调用 `analysis`。
- 为 orchestration 层新增 `analysis` 失败测试，验证保留 `normalized` 且不保留 `analysis` 输出。
- 为 CLI 新增默认入口测试，验证 `bill <raw_file>` 等价于 `bill run <raw_file>`。

### 回归测试

- 保留并通过现有 `bill normalize` 测试，确认单阶段命令行为不变。
- 保留并通过现有 `bill analysis` 测试，确认失败阈值与 `unknow` 回填规则不变。
- 增加显式子命令回归测试，确认 `bill normalize` / `bill analysis` 仍可独立使用。

## 兼容性说明

- 对已有用户兼容：`bill normalize` 与 `bill analysis` 命令继续保留，原有脚本仍可继续使用，但如果脚本依赖旧的标准化文件命名，需要同步调整为新的后缀规则。
- 对新用户更友好：`bill` 默认直接执行完整链路，降低使用门槛。
- 输出文件命名将统一收敛为 `.normalized.xlsx` 与 `.analysis.xlsx` 两种明确后缀，避免不同入口产物风格不一致。
- `analysis` 失败阈值、单行兜底值与最终产物保留策略保持一致，不改变既有质量预期。

## 待实现文件清单

### 需要修改

- `src/beartools/commands/bill/command.py`
  - 新增 `bill run` 子命令。
  - 调整 `bill` 根入口默认行为，使其等价于 `bill run`。
- `src/beartools/bill/service.py`
  - 新增轻量 orchestration 层入口，串联 `normalize` 与 `analysis`。
  - 处理 `analysis` 失败时的结果文件清理。
- `src/beartools/bill/models.py`
  - 如有必要，补充编排层结果模型或统一输出路径字段命名。
- `tests/test_bill_command.py`
  - 增加 `bill` 默认入口与 `bill run` 的 CLI 测试。
- `tests/test_bill_service.py`
  - 增加 orchestration 层成功与失败分支测试。

- `README.md`
  - 如已有账单命令示例，补充 `bill run` / 默认入口说明，并同步更新文件命名示例。

### 预计无需修改

- `src/beartools/bill/agent.py`
  - 本次设计不改变 LLM 调用协议。
- 与 prompt、分类规则、标准化字段映射直接相关的文件
  - 本次设计不涉及规则层变更。
