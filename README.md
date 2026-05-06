# beartools
自用的tool，skill等等

## 账单处理示例

### 完整流程（推荐）
可以使用 `beartools bill` 默认入口，或 `beartools bill run` 子命令，从原始账单直接得到分析结果：

```bash
beartools bill "/path/to/wechat.xlsx" "2601-"
beartools bill run "/path/to/wechat.xlsx" "2601-"
```

```python
from beartools.bill import run_bill_pipeline

result = run_bill_pipeline(
    "/path/to/wechat.xlsx",
    "2601-",
)

print(result.normalized_output_path)  # 归一化输出：/data/bill/2601-微信.normalized.xlsx
print(result.analysis_output_path)    # 分析输出：/data/bill/2601-微信.analysis.xlsx
print(result.source)
print(result.normalized_row_count)
print(result.analysis_total_rows)
```

### 归一化单独使用
可以使用 `beartools.bill.normalize_bill_file` 将单个账单文件归一化为统一 Excel。

```python
from beartools.bill import normalize_bill_file

result = normalize_bill_file(
    "/path/to/wechat.xlsx",
    "2601-",
)

print(result.output_path)
print(result.source)
print(result.row_count)
```

输出文件会自动写入：
```text
./data/bill/{from}{source}.normalized.xlsx
```
例如：
```text
./data/bill/2601-微信.normalized.xlsx
./data/bill/2601-支付宝.normalized.xlsx
```

归一化输出 Excel 固定工作表名为"账单明细"，列：
```text
原始来源,交易时间,交易对方,金额,交易状态,注意,备注
```

### 分析单独使用
可以使用 `beartools.bill.analyze_bill_file` 分析归一化后的 Excel：

```python
from beartools.bill import analyze_bill_file

result = analyze_bill_file(
    "/path/to/normalized.xlsx"
)

print(result.output_path)
print(result.total_rows)
print(result.failed_rows)
```

分析输出在原文件同目录，后缀 `*.analysis.xlsx`，新增用途、归属人两列。

## 命令行示例

### 完整流程（推荐）
```bash
beartools bill "/path/to/wechat.xlsx" "2601-"
beartools bill run "/path/to/wechat.xlsx" "2601-"
```
命令成功后会输出归一化输出路径、分析输出路径、来源、归一化行数、分析总行数、分析失败行数。

### 单独归一化
```bash
beartools bill normalize "/path/to/wechat.xlsx" "2601-"
```
命令成功后会输出：
- 输出文件路径
- 来源（如微信、支付宝、京东）
- 行数

例如输出文件：
```text
data/bill/2601-微信.normalized.xlsx
```

### 单独分析
```bash
beartools bill analysis "/path/to/normalized.xlsx"
```
命令成功后会输出：
- 输出文件路径
- 总行数
- 分析失败行数

## CLI 集成测试

项目内提供了一组真实 CLI 集成测试与配套 skill，用于验证顶层命令在真实配置、真实文件、本地服务、外网和真实凭据条件下是否仍然可用。

### 相关文件

- 测试入口：`tests/test_cli_integration_commands.py`
- 测试资产索引：`tests/assets/cli_integration_assets.yaml`
- 项目内 skill：`skills/testing-cli-integrations/SKILL.md`

### 分组说明

- `core`：本地、低副作用、适合频繁运行
  - `doctor`
  - `record`
  - `markdown`
- `live`：依赖真实服务、外网或凭据
  - `bill`
  - `siyuan`
  - `fetch`
  - `gmail`
  - `codex`

说明：

- `clear` 不在这组集成测试覆盖范围内
- `fetch` 集成测试固定使用 `--no-upload`，避免写入思源
- `live` 命令会真实执行；如果本地服务未启动、凭据不可用或上游环境异常，测试会 `skip` 并给出原因

### 运行方式

`core` 全量：

```bash
BEARTOOLS_INTEGRATION_GROUP=core uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v
```

`live` 全量：

```bash
BEARTOOLS_INTEGRATION_GROUP=live uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v
```

`all` 全量：

```bash
BEARTOOLS_INTEGRATION_GROUP=all uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v
```

`smoke` 模式：

```bash
BEARTOOLS_INTEGRATION_GROUP=all BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=3 BEARTOOLS_SMOKE_SEED=20260506 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v
```

### 测试资产

当前仓库内已固定的测试输入包括：

- `tests/assets/bill/jd-220.csv`
- `tests/assets/codex/m1.md`

对应路径与参数以 `tests/assets/cli_integration_assets.yaml` 为准。
