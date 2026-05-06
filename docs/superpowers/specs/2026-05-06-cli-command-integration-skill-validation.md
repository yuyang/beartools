## 基线验证（无 skill）

在本轮实现前，集成测试方案天然容易出现以下偏差：

- 把所有命令都放进同一组，无法区分本地稳定链路与真实外部依赖链路
- 把 `fetch` 默认上传行为直接带入测试，污染思源数据
- 使用外部绝对路径资产，导致测试无法迁移
- 在 `live` 组环境不满足时直接 FAIL，导致整组不可用

## 带 skill 的目标行为

引入 `skills/testing-cli-integrations/SKILL.md` 后，应稳定遵循这些约束：

- 使用 `tests/test_cli_integration_commands.py` 作为统一入口
- 明确区分 `core` 与 `live`
- `fetch` 固定 `--no-upload`
- 测试资产优先放在 `tests/assets/`
- `live` 组环境不满足时使用 `skip`，并暴露原因

## 当前验证结论

- `core` 组当前可全绿：`doctor`、`record`、`markdown`
- `live` 组中：
  - `fetch` 通过
  - `codex` 通过
  - `siyuan` 因本地 6806 未启动而应 skip
  - `gmail` 因真实抓取失败而应 skip
  - `bill` 因上游 LLM 响应兼容问题而应 skip

这说明当前 skill 设计已经把“真实集成”与“环境不满足”两个维度分开，不会再退化回 help-only smoke。
