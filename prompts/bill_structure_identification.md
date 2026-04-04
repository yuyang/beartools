# 账单结构识别 Prompt

请识别以下账单文件的结构信息：

**文件名**: {{file_name}}
**文件类型**: {{file_type:unknown}}
**候选来源**: {{candidate_sources:支付宝,微信,京东,未知}}

## 文件内容

{{file_content}}

## 识别任务

请完成以下识别：

1. 判断文件来源平台：支付宝 / 微信 / 京东 / 未知
2. 判断真正表头所在行号
3. 判断真正数据开始所在行号
4. 识别以下标准字段对应的原始列名：
   - `transaction_time`：交易时间
   - `counterparty`：交易对象
   - `amount`：金额
   - `status`：交易状态
   - `remark_columns`：除以上四类核心字段之外的其他列
5. 输出识别出的前 5 行样例数据
6. 如果字段无法唯一判断，保留空值并说明原因

## 识别规则

- 文件中的导出信息、统计信息、特别提示、空行、装饰分隔线都不算正式表头和数据
- 优先根据表头语义识别，不要仅根据列位置猜测
- 如果金额带货币符号，仍视为金额列
- 行号从 1 开始
- 只能基于提供的文件内容判断，不要虚构不存在的列
- `remark_columns` 不是单独找“备注”列，而是除核心字段外剩余的全部列

## 输出要求

请严格输出 JSON，不要输出任何额外说明文字。

输出结构如下：

```json
{
  "files": [
    {
      "file_name": "",
      "source": "支付宝/微信/京东/未知",
      "header_row": 0,
      "data_start_row": 0,
      "field_mapping": {
        "transaction_time": {
          "column_name": "",
          "confidence": "high/medium/low",
          "reason": ""
        },
        "counterparty": {
          "column_name": "",
          "confidence": "high/medium/low",
          "reason": ""
        },
        "amount": {
          "column_name": "",
          "confidence": "high/medium/low",
          "reason": ""
        },
        "status": {
          "column_name": "",
          "confidence": "high/medium/low",
          "reason": ""
        },
        "remark_columns": {
          "column_names": [],
          "confidence": "high/medium/low",
          "reason": ""
        }
      },
      "sample_rows": [
        {},
        {},
        {},
        {},
        {}
      ],
      "notes": []
    }
  ]
}
```
