---
name: testing-cli-integrations
description: Use when validating whether beartools top-level CLI commands still work through real integrations with local files, local services, network access, or real credentials after changes or before release.
---

# Testing CLI Integrations

## Overview

这是一组真实 CLI 集成测试，不是 `--help` 冒烟。核心原则是：每个顶层命令只选一条真实且尽量最小副作用的执行路径，只通过一个环境变量切换 `core` / `smoke` / `all` 三档。

## When to Use

- CLI 改动后想确认真实命令链路没有坏
- 发布前需要做一轮真实集成回归
- 需要区分本地稳定链路与外部依赖链路
- 想跑一轮 `core`，再加一个随机 `live` case 做 smoke

不要用在这些场景：

- 只想看命令注册与 help 输出是否还在
- 需要稳定、纯本地、零外部依赖的单元测试
- 想覆盖每个子命令和所有分支细节

## Quick Reference

- `core`：`BEARTOOLS_INTEGRATION_GROUP=core uv run python scripts/run_cli_integrations.py`
- `smoke`：`BEARTOOLS_INTEGRATION_GROUP=smoke uv run python scripts/run_cli_integrations.py`
- `all`：`BEARTOOLS_INTEGRATION_GROUP=all uv run python scripts/run_cli_integrations.py`

## Assets

- bill 样例：见 `tests/assets/cli_integration_assets.yaml`
- codex prompt：见 `tests/assets/cli_integration_assets.yaml`
- fetch URL：见 `skills/testing-cli-integrations/assets/fetch-urls.txt`

## Group Rules

- `core`：`doctor`、`record`、`markdown`
- `live`：`bill`、`siyuan`、`fetch`、`gmail`、`codex`
- `smoke`：固定跑全部 `core`，再从 `live` 里随机抽 1 条
- `all`：跑全部 `core + live`

`live` case 仍然要求真实执行；但当环境不满足时，应 `skip` 并给出明确原因，而不是伪造通过。

## Common Mistakes

- 把这套测试当成稳定纯单测：它依赖真实配置、真实服务和真实网络
- 在 `fetch` 集成测试里忘记加 `--no-upload`
- 还沿用旧的 `BEARTOOLS_SMOKE` / `BEARTOOLS_SMOKE_SAMPLE` 变量
- 误把 `clear` 加回覆盖范围
- 把 `live` 环境错误硬断言成 FAIL，导致整组在不满足环境时完全不可用

## Red Flags

- 你正在把 `fetch` 的默认上传行为带进测试
- 你想让 `live` 组在没有服务/凭据时也必须全绿
- 你正在把这套 skill 当成完整端到端平台

出现这些信号时，回到“最小副作用真实集成”的范围。

## Result Reporting

执行完后，最后必须明确汇报这 5 项：

- 跑了哪个测试文件 / 测试入口
- 具体跑了哪个 CLI 子命令，参数是什么
- 使用了什么环境变量
- 结果是什么（通过、跳过、失败；必要时附关键失败点）
- 输出文件路径是什么（完整 console 输出默认落在 `output/testing/`）

推荐格式（按每个 case 逐条汇报，最后再给汇总）：

- 测试：`doctor`
  CLI：`uv run python -m beartools.cli doctor`
  环境：`BEARTOOLS_INTEGRATION_GROUP=core`
  结果：`PASSED`
  输出文件：`output/testing/cli-integrations-core-20260507-153000.log`

- 测试：`record`
  CLI：`uv run python -m beartools.cli record getall`
  环境：`BEARTOOLS_INTEGRATION_GROUP=core`
  结果：`PASSED`
  输出文件：`output/testing/cli-integrations-core-20260507-153000.log`

- 测试：`markdown`
  CLI：`uv run python -m beartools.cli markdown embed-images`
  环境：`BEARTOOLS_INTEGRATION_GROUP=core`
  结果：`PASSED`
  输出文件：`output/testing/cli-integrations-core-20260507-153000.log`

- 汇总：`3 passed, 0 skipped`
