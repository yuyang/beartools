# bill 状态映射与部分退款处理设计

## 背景

当前 `bill` 归一化逻辑在 `src/beartools/bill/service.py` 中直接写死了少量状态判断：

- `交易成功` 视为成功交易，金额强制转正
- `退款成功` 视为退款，金额强制转负

但真实账单文件中的 `交易状态` 明显更多，且存在动态格式，例如：

- `支付成功`
- `已转账`
- `对方已收钱`
- `已存入零钱`
- `已到账`
- `已全额退款`
- `已退款￥1.00`
- `已退款(￥1.00)`

现状问题：

1. 状态规则散落在代码中，不便维护与扩展
2. 对未知状态没有显式确认机制
3. 动态退款状态无法通过精确字符串枚举完整覆盖
4. 部分退款无法进入专门金额修正逻辑

## 目标

- 将原始账单状态映射规则迁移到单独配置文件维护：`config/bill_status_mapping.yaml`
- 系统内部只保留 3 种标准状态：
  - `NORMAL_SUCCESS`
  - `REFUND`
  - `PART_REFUND`
- 支持两类映射规则：精确匹配与模式匹配
- 运行中遇到未知状态时，要求用户人工确认分类，并把结果写回配置文件
- 用户确认后继续当前分析流程，避免下次重复询问
- `PART_REFUND` 进入带 Tool Calling 的 LLM 金额修正逻辑，用于修正实际退款金额

## 非目标

- 不按平台、来源分别维护状态映射，所有来源统一处理
- 不改变账单结构识别逻辑
- 不新增更多标准状态枚举
- 不引入自动猜测未知状态的分类逻辑
- 不重构现有 LLM 运行时框架，只在 bill 场景接入已有 LLM 能力

## 用户可见行为

### 1. 已知状态

当账单中的原始状态能通过配置命中时，归一化流程直接继续，不新增额外交互。

### 2. 未知状态

当账单中出现配置无法识别的状态时：

1. 系统收集本次文件中的未知状态去重值
2. 逐个要求用户确认该状态属于：
   - `NORMAL_SUCCESS`
   - `REFUND`
   - `PART_REFUND`
3. 系统将确认结果立即写回 `config/bill_status_mapping.yaml`
4. 写回成功后继续当前分析流程

这保证：

- 同一次运行中得到确认后即可继续执行
- 后续再次遇到相同状态时无需再问

### 3. 部分退款

当状态映射到 `PART_REFUND` 时：

1. 该记录进入部分退款金额修正分支
2. 调用 LLM 结合行内上下文判断退款语义
3. 当需要数值计算时，LLM 通过 Tool Calling 调用 `CalculateTool`
4. 修正后的金额以负数形式写入归一化结果
5. 该记录不参与全额退款抵消逻辑

## 配置设计

配置文件路径固定为：

- `config/bill_status_mapping.yaml`

配置结构采用两层匹配：

```yaml
exact:
  交易成功: NORMAL_SUCCESS
  支付成功: NORMAL_SUCCESS
  已转账: NORMAL_SUCCESS
  对方已收钱: NORMAL_SUCCESS
  已存入零钱: NORMAL_SUCCESS
  已到账: NORMAL_SUCCESS
  退款成功: REFUND
  已全额退款: REFUND

patterns:
  - pattern: "^已退款"
    normalized_status: PART_REFUND
```

### 匹配规则

按以下优先级处理：

1. 先查 `exact`
2. 再按顺序遍历 `patterns`，命中第一条即返回
3. 两者都未命中时，认定为未知状态

### 配置写回规则

- 用户确认未知状态后，默认写回 `exact`
- 本次不支持运行时自动生成新的 `patterns` 规则
- `patterns` 由开发者手工维护，用于处理类似 `^已退款` 这类动态文本状态

这样可以避免系统把一次性的原始值误写成过度泛化的正则。

## 标准状态语义

### `NORMAL_SUCCESS`

- 表示成功完成的正常交易
- 金额在归一化后强制为正数
- 可参与“成功交易 vs 全额退款”抵消逻辑中的成功侧

### `REFUND`

- 表示全额退款或明确退款完成
- 金额在归一化后强制为负数
- 可参与“成功交易 vs 全额退款”抵消逻辑中的退款侧

### `PART_REFUND`

- 表示部分退款，或状态文本仅说明“发生退款”但不应直接等价为全额退款
- 金额不直接使用原始行金额定论
- 需要调用 LLM 修正实际退款金额
- 当修正涉及数值运算时，LLM 通过 Tool Calling 使用 `CalculateTool`
- 不参与现有全额退款抵消逻辑

用户已确认：所有匹配 `^已退款` 的动态状态默认归为 `PART_REFUND`。

## 数据模型调整

### `NormalizedBillRow`

保留：

- `status`：原始账单状态

新增：

- `normalized_status`：标准状态，取值为 `NORMAL_SUCCESS` / `REFUND` / `PART_REFUND`

这样做的原因：

- 原始状态便于排查与审计
- 业务判断统一依赖标准状态，避免继续在代码中散落平台文案判断

## 归一化流程设计

### 1. 行级状态标准化

在 `_normalize_rows()` 中，读取原始 `status` 后：

1. 通过状态映射配置解析为 `normalized_status`
2. 再根据 `normalized_status` 决定金额处理策略

金额规则：

- `NORMAL_SUCCESS`：金额强制转正
- `REFUND`：金额强制转负
- `PART_REFUND`：调用带 Tool Calling 的部分退款金额修正逻辑，得到负数退款金额

### 2. notice 规则

归一化输出中的 `注意` 列不再基于原始 `status` 判断，而基于 `normalized_status` 判断。

建议规则：

- `NORMAL_SUCCESS`：不标记 `focus`
- `REFUND`：不标记 `focus`
- `PART_REFUND`：不标记 `focus`，因为属于系统已识别并处理的合法状态
- 无法完成修正的异常分支：标记 `focus` 或直接失败，由具体错误处理策略决定

## 未知状态确认流程

### 总体行为

归一化前或归一化过程中，只要发现未知状态，就不能静默跳过或自行猜测。

建议流程：

1. 扫描当前文件所有数据行，收集未知状态去重列表
2. 若列表为空，正常继续
3. 若列表非空，按顺序逐个请求用户确认分类
4. 每确认一个状态，立即更新 YAML 文件
5. 所有未知状态确认完毕后，再进入正式归一化与分析

这样优于“处理到一半遇到未知再停下”，因为用户只需集中确认一次。

### 交互边界

- 用户确认入口属于 `command` 层职责
- 配置读写、状态解析属于 `bill` 领域服务职责
- `service` 层不直接与终端交互，保持可测试性

## 部分退款金额修正设计

### 输入信息

LLM 修正 `PART_REFUND` 金额时，至少需要以下输入：

- 原始状态
- 备注
- 交易对方
- 原始金额
- 原始来源
- 交易时间

### Tool Calling 方案

`PART_REFUND` 的金额修正采用“LLM 语义理解 + `CalculateTool` 数值计算”模式。

职责拆分：

- LLM：理解账单状态、备注、交易语义，决定是否需要计算，以及应该计算什么
- `CalculateTool`：只负责执行算术表达式并返回结果，不负责任何业务语义判断

`CalculateTool` 建议职责尽量单一：

- 输入：一个算术表达式字符串
- 输出：计算结果字符串或数值

例如可支持：

- `1.00`
- `10.50 - 2.30`
- `(299 - 20) - 200`

### 输出要求

LLM 最终需要输出结构化结果，至少包括：

- `refund_amount`
- `reason`

其中：

- `refund_amount` 必须可解析为单个数字
- 语义上表示退款金额，而不是原始整笔交易金额
- 系统最终统一转为负数写入归一化结果

### 失败策略

如果 LLM 无法得出可解析金额，或者 Tool Calling 后仍无法得到合法结果，本次设计建议视为失败，不做静默兜底猜测。

原因：

- 金额错误的风险高于中断处理的成本
- 部分退款属于金额敏感场景，错误推断会直接污染账单结果

## 退款抵消逻辑调整

当前 `_apply_refund_offset()` 只处理原始状态 `交易成功` 与 `退款成功` 的配对。

改造后应改为：

- 基于 `normalized_status` 进行匹配
- 仅匹配：
  - `NORMAL_SUCCESS`
  - `REFUND`
- `PART_REFUND` 不参与抵消

匹配策略本身保持不变：

- 按金额绝对值分组
- 成功与退款一一配对
- 成功与全额退款配对成功后，两行都忽略

## 模块职责划分

### 配置加载/写回模块

建议新增一个专门的状态映射模块，职责：

- 读取 `config/bill_status_mapping.yaml`
- 解析 `exact` 与 `patterns`
- 根据原始状态返回标准状态
- 将用户确认结果写回配置

### CalculateTool 模块

建议新增一个专门的 `CalculateTool`，职责：

- 接收算术表达式
- 返回精确计算结果
- 不承担状态分类、金额提取、语义推断等业务逻辑

该 tool 仅服务于 `PART_REFUND` 的金额修正场景。

### `service` 层

职责：

- 调用状态映射模块完成标准状态解析
- 按标准状态调整金额
- 对 `PART_REFUND` 调用带 `CalculateTool` 的部分退款修正逻辑
- 在退款抵消阶段只处理 `NORMAL_SUCCESS` / `REFUND`

不负责：

- 终端交互
- 让用户选择未知状态分类

### `command` 层

职责：

- 发现未知状态后向用户发起确认
- 将确认结果交给配置模块写回 YAML
- 写回完成后继续执行当前流程

## 测试策略

采用 TDD，先写失败测试，再改实现。

### 1. 配置映射测试

- `exact` 能正确映射固定状态
- `patterns` 能命中 `^已退款` 这类动态状态
- `exact` 与 `patterns` 同时可能命中时，`exact` 优先
- 未命中任何规则时，明确返回“未知状态”结果

### 2. 配置写回测试

- 用户确认后能正确写回 `config/bill_status_mapping.yaml`
- 已存在的 `exact` 不被错误覆盖
- 写回后重新加载即可命中新状态

### 3. 归一化测试

- `NORMAL_SUCCESS` 交易金额转正
- `REFUND` 交易金额转负
- `PART_REFUND` 进入带 Tool Calling 的金额修正分支

### 4. Tool Calling / CalculateTool 测试

- `CalculateTool` 能正确计算简单表达式
- `PART_REFUND` 场景下，LLM 修正入口能够使用 `CalculateTool`
- Tool 返回非法结果时，流程明确失败

### 5. 未知状态流程测试

- 当文件中出现未知状态时，能够返回待确认状态列表
- 所有状态确认并写回后，当前流程能继续执行

### 6. 退款抵消测试

- `NORMAL_SUCCESS + REFUND` 同额时会配对抵消
- `PART_REFUND` 不参与抵消

## 风险与兼容性

### 风险

1. **YAML 写回失败**
   - 会阻断当前流程
   - 需要向用户清晰暴露错误

2. **LLM 无法稳定提取部分退款金额**
   - 需要明确失败而不是静默输出错误金额

3. **Tool Calling 结果不合法**
   - 表达式错误、返回值不可解析时必须显式失败

4. **历史测试依赖原始状态文案**
   - 改为标准状态驱动后，需要同步更新测试断言

### 兼容性结论

- 对已有归一化输出表头影响可控
- 原始状态仍保留，可保持可读性
- 新增标准状态字段后，内部逻辑更稳定，外部结果更可维护

## 待实现文件清单

### 需要新增

- `config/bill_status_mapping.yaml`
  - 维护状态映射配置
- `src/beartools/bill/status_mapping.py`
  - 提供配置加载、状态解析、配置写回能力
- `src/beartools/bill/calculate_tool.py`
  - 提供 `PART_REFUND` 场景使用的算术计算 tool

### 需要修改

- `src/beartools/bill/models.py`
  - 为统一账单行增加 `normalized_status` 字段，并补充标准状态类型
- `src/beartools/bill/service.py`
  - 接入状态映射、未知状态处理入口、部分退款金额修正、退款抵消调整
- `src/beartools/commands/bill/command.py`
  - 增加未知状态确认交互与继续执行流程
- `src/beartools/bill/agent.py`
  - 增加带 Tool Calling 的部分退款金额修正入口
- `prompts/`
  - 增加或调整部分退款金额修正 prompt
- `tests/test_bill_service.py`
  - 增加状态映射、未知状态、部分退款、退款抵消测试
- `tests/test_bill_command.py`
  - 增加未知状态确认交互测试
- `tests/test_bill_agent.py`
  - 增加部分退款金额修正与 Tool Calling 相关测试
