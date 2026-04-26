# bill run 默认入口实施计划
> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development (recommended) 或 superpowers:executing-plans 逐条实施本计划任务。步骤使用 checkbox (- [ ]) 语法跟踪进度。

**目标:** 
- 新增 `bill run` 子命令，`bill` 默认入口等价于 `bill run`。
- 统一输出文件命名：标准化结果为 `*.normalized.xlsx`，分析结果为 `*.analysis.xlsx`。
- 保留 `bill normalize` 与 `bill analysis` 仍可独立使用。
- 新增轻量 orchestration layer 串联 normalize → analysis。
- 修复现有残留的 CSV 命名与 README.md 文案统一为 Excel。

**架构:**
- 在 `src/beartools/bill/service.py` 新增 `run_bill_pipeline` orchestration 函数
- 在 `src/beartools/bill/models.py` 更新 NormalizeBillFileResult.output_csv_path → output_path，新增 `RunBillPipelineResult`
- 在 `src/beartools/commands/bill/command.py` 新增 run 子命令与默认 callback
- 复用 `.worktrees/bill-analysis` 里的完整代码（模型、服务、命令、测试、prompt）

---

## Task 1: 把 bill-analysis 分支的完整代码合并到当前工作树 ✅
完成！复制：
- src/beartools/bill/
- src/beartools/commands/bill/
- tests/test_bill*.py
- prompts/bill_transaction_analysis.md

## Task2: 新增 run_bill_pipeline、bill run、默认入口、测试 ✅
完成！

## Task3: 更新 README.md ✅
完成！

## Task4: 整体验证 ✅
完成！所有 bill 相关测试 26/26 全过，ruff/mypy 全过！
