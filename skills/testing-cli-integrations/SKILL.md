---
name: testing-cli-integrations
description: Use when validating whether beartools top-level CLI commands still work through real integrations with local files, local services, network access, or real credentials after changes or before release.
---

# Testing CLI Integrations

## Overview

这是一组真实 CLI 集成测试，不是 `--help` 冒烟。核心原则是：每个顶层命令只选一条真实且尽量最小副作用的执行路径，默认优先跑 `core`，按需跑 `live`。

## When to Use

- CLI 改动后想确认真实命令链路没有坏
- 发布前需要做一轮真实集成回归
- 需要区分本地稳定链路与外部依赖链路
- 想随机抽几个真实集成 case 做 smoke

不要用在这些场景：

- 只想看命令注册与 help 输出是否还在
- 需要稳定、纯本地、零外部依赖的单元测试
- 想覆盖每个子命令和所有分支细节

## Quick Reference

- `core` 全量：`BEARTOOLS_INTEGRATION_GROUP=core uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `live` 全量：`BEARTOOLS_INTEGRATION_GROUP=live uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `all` 全量：`BEARTOOLS_INTEGRATION_GROUP=all uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `core` smoke：`BEARTOOLS_INTEGRATION_GROUP=core BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=2 BEARTOOLS_SMOKE_SEED=42 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`
- `live` smoke：`BEARTOOLS_INTEGRATION_GROUP=live BEARTOOLS_SMOKE=1 BEARTOOLS_SMOKE_SAMPLE=2 BEARTOOLS_SMOKE_SEED=42 uv run pytest tests/test_cli_integration_commands.py::test_selected_integration_case -v`

## Assets

- bill 样例：见 `tests/assets/cli_integration_assets.yaml`
- codex prompt：见 `tests/assets/cli_integration_assets.yaml`
- fetch URL：见 `skills/testing-cli-integrations/assets/fetch-urls.txt`

## Group Rules

- `core`：`doctor`、`record`、`markdown`
- `live`：`bill`、`siyuan`、`fetch`、`gmail`、`codex`

`live` 组仍然要求真实执行；但当环境不满足时，应 `skip` 并给出明确原因，而不是伪造通过。

## Common Mistakes

- 把这套测试当成稳定纯单测：它依赖真实配置、真实服务和真实网络
- 在 `fetch` 集成测试里忘记加 `--no-upload`
- 没有提供 `seed` 就运行 smoke，导致失败不可复现
- 误把 `clear` 加回覆盖范围
- 把 `live` 环境错误硬断言成 FAIL，导致整组在不满足环境时完全不可用

## Red Flags

- 你正在把 `fetch` 的默认上传行为带进测试
- 你想让 `live` 组在没有服务/凭据时也必须全绿
- 你正在把这套 skill 当成完整端到端平台

出现这些信号时，回到“最小副作用真实集成”的范围。
