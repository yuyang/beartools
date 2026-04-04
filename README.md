# beartools
自用的tool，skill等等

## 账单归一化示例

可以使用 `beartools.bill.normalize_bill_file` 将单个账单文件归一化为统一 CSV。

```python
from beartools.bill import normalize_bill_file

result = normalize_bill_file(
    "/path/to/wechat.xlsx",
    "2601-",
)

print(result.output_csv_path)
print(result.source)
print(result.row_count)
```

输出文件会自动写入：

```text
./data/bill/{from}{source}.csv
```

例如：

```text
./data/bill/2601-微信.csv
./data/bill/2601-支付宝.csv
```

输出 CSV 固定列为：

```text
from,source,transaction_time,counterparty,amount,status,remark
```

## 命令行示例

也可以通过 CLI 调用：

```bash
beartools bill normalize "/path/to/wechat.xlsx" "2601-"
```

命令成功后会输出：

- 输出文件路径
- 来源（如微信、支付宝、京东）
- 行数

例如输出文件：

```text
data/bill/2601-微信.csv
```
