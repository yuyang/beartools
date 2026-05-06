## 背景

原方案只打算为 `beartools` 增加一组基于 `--help` 的基础命令冒烟测试。但当前需求已经升级为“真实集成测试 skill”：使用真实配置文件，不做 mock，允许本地文件系统、本地服务端口、外部网络和真实账号凭据参与执行。

同时，用户明确要求：

- `clear` 不纳入覆盖范围；
- `fetch` 集成测试中禁止上传到思源；
- 需要的真实输入文件可以由用户提供，并放到 skill 的 assets 中管理或索引；
- 不要求覆盖所有子命令，但要覆盖所有顶层命令对应的一条真实集成路径。

## 目标

- 为项目增加一个新的 skill，名称暂定为 `testing-cli-integrations`。
- 新增一组基于 `pytest` 的 CLI 真实集成测试，而不是仅验证 help 输出。
- 采用 `core/live` 双层分组：
  - `core`：本地、稳定、低副作用命令；
  - `live`：依赖本地服务、外网或真实凭据的命令。
- 支持 full 与 smoke 两种执行方式；smoke 不是 help 抽样，而是真实集成 case 抽样。
- 把用户提供的固定输入资产纳入 skill 的 assets 设计中，确保后续可复用。

## 非目标

- 本次不覆盖 `clear` 命令。
- 本次不要求覆盖每个命令的所有子命令。
- 本次不引入 mock、fake service 或假凭据。
- 本次不把这组集成测试扩展成完整端到端回归平台。

## 用户已提供的固定资产

### bill 样例

- 源文件：`/Users/liuyy/Documents/个人/结算/2601/京东交易流水(申请时间2026年01月09日22时53分47秒)_220.csv`
- 仓库内副本目标：`tests/assets/bill/jd-220.csv`
- `from` 参数：`yy`
- 来源：`京东`

### codex prompt 样例

- 源文件：`./input/m1.md`
- 仓库内副本目标：`tests/assets/codex/m1.md`

### fetch 固定 URL

1. `https://mp.weixin.qq.com/s/Jac9uhA6zE1OsIYDGjr9-g`
2. `https://mp.weixin.qq.com/s/Iu9g7Ol8jLgtXu18QxMwOg`

## 方案选择

本次采用方案 B：`core/live` 双层真实集成测试。

选择原因：

- 在“真实配置 + 真实依赖”的前提下，把所有命令放进一个默认全量集会导致执行成本和波动性过高。
- `core` 组可以作为日常频繁验证入口，`live` 组保留给需要联网、账号或本地服务的场景。
- smoke 抽样可以按组独立进行，既保留真实性，也能控制成本。

未采用的方案：

- 所有命令默认全量真实跑：覆盖最完整，但日常使用成本太高。
- 所有命令都尝试执行、不满足环境时自动 skip：会稀释“真实通过”的含义，不利于 skill 约束。

## 命令分组设计

### core 组

默认作为低副作用真实集成测试入口，包含：

- `doctor`
- `record`
- `markdown`

### live 组

依赖本地服务、外部网络或真实凭据，包含：

- `bill`
- `siyuan`
- `fetch`
- `gmail`
- `codex`

执行约束：

- `live` 仍然是真实集成测试；
- 但当本地服务未启动、真实凭据不可用、或上游接口兼容性异常时，测试应以 `skip` 结束，并给出明确原因；
- `skip` 只适用于 `live`，不适用于 `core`。

## 参数选择原则

总体原则：**选择每个顶层命令的一条“真实且尽量最小副作用”的可执行路径**。

### doctor

- 执行路径：`beartools doctor`
- 默认不带 `--run-llm`
- 原因：这是 `doctor` 的主链路，且不强依赖模型调用

### record

- 执行路径：`beartools record getall`
- 原因：真实读取本地 sqlite 数据，但通常不会产生写副作用

### markdown

- 执行路径：`beartools markdown embed-images <temp.md>`
- 输入资产：测试运行时动态创建临时 markdown 文件与本地图片
- 原因：最适合真实验证本地文件处理链路

### bill

- 分组：`live`
- 执行路径：
  - `beartools bill normalize <bill_path> yy`
  - `beartools bill run <bill_path> yy`
- 输入资产：复制到 `tests/assets/bill/jd-220.csv` 的京东账单副本
- 原因：当前真实链路依赖外部 LLM/账号环境，波动性高于 `core` 组，因此归入 `live`

### siyuan

- 执行路径：`beartools siyuan ls-notebooks`
- 原因：最小读取型命令，依赖本地思源服务，但写副作用最低

### fetch

- 执行路径：`beartools fetch <url> --no-upload`
- URL 来源：从两条固定微信文章 URL 中选择一条主用，另一条可用于 smoke 池
- 原因：保留真实抓取链路，同时显式禁止上传，避免污染思源数据

### gmail

- 执行路径：`beartools gmail fetch`
- 原因：这是该顶层命令当前唯一真实业务入口

### codex

- 执行路径：`beartools codex run tests/assets/codex/m1.md`
- 输入资产：复制到 `tests/assets/codex/m1.md` 的 prompt 副本
- 原因：使用真实配置和真实 prompt，覆盖 codex 主链路

## smoke 设计

smoke 不再是所有命令统一 `--help` 抽样，而是**真实集成 case 抽样**。

建议通过环境变量控制：

- `BEARTOOLS_INTEGRATION_GROUP=core|live|all`
- `BEARTOOLS_SMOKE=1`
- `BEARTOOLS_SMOKE_SAMPLE=<n>`
- `BEARTOOLS_SMOKE_SEED=<seed>`

执行规则：

- full 模式：跑所选组全部 case
- smoke 模式：从所选组的 case 池中随机抽样
- 为保证可复现，smoke 必须支持 seed

## 断言设计

由于是集成测试，断言不能过度依赖返回内容的精确文本，而应优先验证稳定信号：

- 命令退出码为 0
- stdout 包含成功完成的关键片段
- 预期输出文件存在
- 输出文件内容具备最小关键结构

按命令的断言策略：

- `doctor`：检查退出码与总览/检查输出关键字
- `record`：检查退出码，stdout 非空或包含列表型输出
- `markdown`：检查 markdown 文件被真实改写，出现 base64 片段
- `bill normalize`：检查归一化输出文件存在
- `bill run`：检查归一化与分析输出存在
- `siyuan`：检查命令成功，stdout 返回 notebook 相关内容
- `fetch`：检查退出码为 0，并产生抓取结果/成功输出
- `gmail`：检查命令成功并返回摘要型输出
- `codex`：检查结果文件与 trace 文件存在

## assets 设计

skill 目录中需要有 `assets` 概念，测试资产则优先复制到仓库内 `tests/assets/`，避免依赖用户本机绝对路径。

建议分两类：

1. **仓库内测试资产**
   - `tests/assets/bill/jd-220.csv`
   - `tests/assets/codex/m1.md`
   - `tests/assets/cli_integration_assets.yaml`

2. **skill 目录辅助资产**
   - `fetch` URL 清单
   - `markdown` 临时输入模板说明

这样测试可以完全基于仓库内相对路径执行，同时 skill 仍可提供额外的说明性 assets。

## 测试组织方式

建议新增一个独立测试文件，例如：

- `tests/test_cli_integration_commands.py`

文件职责：

- 维护所有真实集成 case 定义
- 维护 `core/live/all/smoke` 选择逻辑
- 统一处理环境变量控制
- 对每个命令封装一条最小真实执行路径

skill 文档职责：

- 告诉用户何时使用这套集成测试
- 解释 `core/live` 与 `smoke/full` 的区别
- 指明所需资产与真实依赖
- 告知 `fetch` 一律使用 `--no-upload`

## 风险与约束

当前方案的主要风险：

- `gmail`、`codex`、`fetch` 会受网络与凭据状态影响
- `siyuan` 依赖本地 6806 服务状态
- `bill` 样例复制进仓库后会增加测试资产体积，需要控制只保留必要文件
- `bill` 的真实执行依赖外部 LLM 返回格式，可能受上游兼容性影响
- `record` 的真实数据内容不稳定，因此断言要避免依赖精确条数

约束策略：

- skill 中要明确说明：这是“真实集成测试”，不是稳定纯单测
- 默认推荐优先跑 `core`，按需跑 `live`
- 对仓库内测试资产路径做存在性校验；若资产缺失，应尽早失败并给出明确提示
- `live` 组若遇到环境不满足，应使用显式 `skip` 暴露原因，而不是伪造通过

## 下一步

在该设计确认后，后续 implementation plan 需要改写为集成测试版本，替换原来的 help-only 方案，并补上 skill 目录、assets 索引文件以及 pytest 真实 case 实现。
