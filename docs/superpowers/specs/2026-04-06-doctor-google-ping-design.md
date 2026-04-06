# doctor google_ping 科学上网检测改造设计

## 背景

当前 `doctor` 命令中的 `google_ping` 检查，本质上是对 `www.google.com:443` 做单点 TCP 连通性探测。

这种方式存在几个问题：

1. 检查名叫 `google_ping`，但实际既不是系统 `ping`，也不是 HTTPS 可用性检查。
2. 单点依赖 `www.google.com`，在 GFW 场景下非常容易误报失败。
3. 只能证明 TCP 建连是否成功，不能证明目标站点是否真的可通过 HTTPS 访问。

本次目标不是新增独立检查项，而是在保持 `doctor` 现有使用方式不变的前提下，直接增强原有 `google_ping` 检查，让它更贴近“科学上网是否可用”的真实语义。

## 目标

1. 保留 `google_ping` 这个检查名，不新增新的 doctor 检查项。
2. 将检查逻辑从“单点 TCP 探测”改为“多目标 HTTPS 可访问性检测”。
3. 默认检测 5 个目标站点。
4. 单个目标只要成功拿到 HTTPS 响应，即视为该目标通过。
5. 当 5 个目标中至少 3 个通过时，整体判定为成功。
6. 保留 `doctor.checks.google_ping` 配置入口，并允许后续通过配置覆盖目标列表与通过阈值。
7. 不自动读取或复用 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 等代理环境变量，仅判断当前直连网络能力。

## 方案对比

### 方案一：直接改造现有 `google_ping`（采用）

- 保留 `google_ping` 名称。
- 将内部逻辑替换为 5 个 HTTPS 目标的并发请求。
- 使用 `success_threshold` 判定整体结果。

优点：
- 不影响 `doctor.enabled_checks` 现有配置。
- 用户使用方式不变。
- 改动集中，兼容性最好。

缺点：
- `google_ping` 名称与新语义不完全一致。

### 方案二：新增 `gfw_bypass` 等新检查项

- 保留原 `google_ping` 逻辑。
- 新增一个真正表达“科学上网检测”的检查项。

优点：
- 命名更清晰。

缺点：
- 会改变 `doctor` 输出结构。
- 用户明确要求不要新增新的检查项。

### 方案三：在单个检查中同时输出 TCP / HTTPS / DNS 多层结果

- 保留现有探测并叠加 HTTPS 语义。
- 输出更多诊断维度。

优点：
- 排障信息更全面。

缺点：
- 超出本次需求规模。
- 实现和输出复杂度偏高。

## 最终设计

### 1. 检查语义

修改文件：`src/beartools/commands/doctor/checks/google_ping.py`

- 保留检查名 `google_ping`。
- 将原先的单点 TCP 建连逻辑替换为 5 个 HTTPS 目标的访问检查。
- 每个目标只要成功返回响应，即视为可访问。
- 最终按成功站点数与阈值比较，产出 `SUCCESS` 或 `FAILURE`。

### 2. 默认目标列表

默认使用以下 5 个 HTTPS 目标：

1. `https://www.google.com/generate_204`
2. `https://www.youtube.com/`
3. `https://www.facebook.com/`
4. `https://x.com/`
5. `https://www.instagram.com/`

选择原则：

- 都是典型的境外 HTTPS 目标。
- 分布在不同产品与厂商上，避免单一站点波动导致整体误判。
- `google.com` 选用 `generate_204`，减少响应体开销。

### 3. 配置结构

保留 `doctor.checks.google_ping` 配置入口，并在现有 `timeout` 基础上扩展以下字段：

- `timeout`：单个目标请求超时时间，单位秒。
- `targets`：目标 URL 列表。
- `success_threshold`：整体成功阈值。

默认值建议：

- `timeout = 2`
- `targets =` 上述 5 个目标
- `success_threshold = 3`

这样可以满足两个目标：

1. 默认即可使用，不需要额外配置。
2. 用户后续可以自行替换目标列表或调整阈值。

### 4. 执行方式

- 单次 `google_ping` 检查内部并发访问全部目标。
- 每个目标共享同一套超时配置。
- 最终展示结果时，按配置中的目标顺序输出，而不是按异步完成顺序输出。

这样可以兼顾：

- 检查速度
- 输出稳定性
- 结果可读性

### 5. 成功与失败判定

单个目标：

- 成功拿到 HTTPS 响应：记为成功。
- 请求超时、DNS 解析失败、连接失败、TLS 失败、其他请求异常：记为失败。

整体检查：

- `成功数 >= success_threshold`：`SUCCESS`
- `成功数 < success_threshold`：`FAILURE`

### 6. 输出设计

整体 `message`：

- 成功：`科学上网检查通过（4/5）`
- 失败：`科学上网检查失败（2/5）`

`detail` 中逐项输出每个目标的结果摘要，格式保持可读，例如：

- `google: 成功 204`
- `youtube: 超时`
- `facebook: DNS 解析失败`
- `x: TLS 请求失败`
- `instagram: 连接失败`

其中目标名称可以根据 URL 归一化为简短标签，避免 detail 过长。

## 数据流变化

### 调整前

1. `google_ping` 读取 `timeout`。
2. 对 `www.google.com:443` 执行单次 TCP 建连。
3. 建连成功则返回成功，否则返回失败。

### 调整后

1. `google_ping` 读取 `timeout`、`targets`、`success_threshold`。
2. 并发访问全部 HTTPS 目标。
3. 汇总每个目标的成功/失败结果。
4. 计算成功数。
5. 根据阈值返回整体成功或失败。
6. 将每个目标的摘要结果放入 `detail`。

## 错误处理

本次需要把单目标错误显式分类，便于用户定位失败原因：

- 超时：`超时`
- DNS 解析失败：`DNS 解析失败`
- 连接失败：`连接失败`
- TLS / HTTPS 请求失败：`HTTPS 请求失败`
- 收到响应：`成功 <状态码>`

单个目标失败不应中断整个检查流程，必须等待全部目标完成后再汇总结果。

## 测试策略

本次按 TDD 执行，先补 `google_ping` 检查测试，再改实现。

至少覆盖以下场景：

1. 5 个目标中 3 个成功时，整体返回成功。
2. 5 个目标中只有 2 个成功时，整体返回失败。
3. 多个目标分别出现超时、DNS 失败、连接失败时，detail 能输出正确摘要。
4. 自定义配置中的 `targets` 与 `success_threshold` 能覆盖默认值。
5. 输出 detail 按配置顺序稳定展示。
6. 请求为并发执行而不是串行执行。

## 涉及文件

- 修改：`src/beartools/commands/doctor/checks/google_ping.py`
- 修改：`src/beartools/config.py`
- 修改：`config/beartools.yaml.sample`
- 可能修改：`config/beartools.yaml`
- 新增或修改：`tests/` 下 `google_ping` 相关测试文件

## 非目标

- 不新增新的 doctor 检查项。
- 不自动复用系统代理环境变量。
- 不把检查扩展为完整的代理链路诊断工具。
- 不改造其他 doctor 检查项的语义与输出方式。

## 实施注意事项

1. `google_ping` 名称虽然保留，但文案要尽量转向“科学上网检查”，减少误导。
2. 如果当前项目尚未引入合适的异步 HTTP 客户端，需要优先评估是否复用现有依赖，避免为单一检查引入过重依赖。
3. 所有新增配置默认值必须在代码和示例配置文件中保持一致。
4. 文档与测试中的描述统一使用“HTTPS 响应成功即算通过”，避免出现“必须 2xx/3xx 才通过”的歧义。
