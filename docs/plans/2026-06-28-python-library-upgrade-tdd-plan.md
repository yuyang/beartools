# Python Library 升级 TDD 计划

## 背景和目标

用户先把范围从 `uv` 工具本身扩展到 Python library 版本，随后明确选择方案 C，因此本轮目标调整为：按 TDD 方式升级一组关键 direct/dev 依赖，而不是覆盖全部 25 个显式依赖。

目标拆成两部分：

1. 盘点当前项目依赖版本。
2. 升级到当前“合适的最新 GA 版本”。

当前仓库依赖现状：

- `pyproject.toml` 里有 17 个生产依赖。
- `pyproject.toml` 里有 8 个 dev 依赖。
- `uv.lock` 当前锁定了 183 个包。
- 所有 direct 依赖和 dev 依赖都已按项目规范使用 `==` 精确版本。

当前已确认的关键包最新 GA 候选：

- `openai`: `2.33.0` -> `2.44.0`
- `anthropic`: `0.97.0` -> `0.112.0`
- `openai-agents`: `0.15.1` -> `0.17.7`
- `pydantic-ai`: `1.89.1` -> `2.0.0`
- `ruff`: `0.15.12` -> `0.15.20`
- `pytest`: `9.0.3` -> `9.1.1`
- `mypy`: `1.20.2` -> `2.1.0`
- `typer`: `0.25.1` -> `0.26.8`
- `httpx`: 当前已是 `0.28.1`
- `rich`: 当前已是 `15.0.0`

## 历史上下文

- `AGENTS.md` 明确要求：所有 `pyproject.toml` 依赖必须使用精确版本号。
- 仓库长期使用 `uv` 管理依赖和锁文件，`pyproject.toml` 中存在 `[tool.uv] package = true`。
- 当前代码库对完整验证的稳定基线是：
  - `uv run pytest tests/ -xvs`
  - `uv run ruff check .`
  - `uv run mypy .`

## 非目标

- 不升级 Python 解释器版本。
- 不修改与依赖升级无关的业务逻辑，除非是为适配新依赖版本而必须修复的兼容性问题。
- 不把版本策略从 `==` 改成范围版本。

## Brainstorm 选项和推荐方案

### 方案 A：只升级 `pyproject.toml` 中的 direct + dev 依赖，允许 `uv.lock` 自动带动传递依赖变化

做法：

- 以 `project.dependencies` 和 `dependency-groups.dev` 中声明的 25 个依赖为升级目标。
- 对每个 direct/dev 依赖确认最新稳定 GA。
- 更新 `pyproject.toml` 精确版本，随后用 `uv lock` / `uv sync` 生成新的 `uv.lock`。

优点：

- 范围清晰，符合项目维护习惯。
- 可以通过 lockfile 自然带动 183 个传递依赖重解，但不用把每个传递依赖都当成单独升级任务。

缺点：

- 传递依赖也会变化，但不会被逐个人工挑选。

### 方案 B：连 183 个传递依赖都显式追到最新可用版本

优点：

- 理论上最彻底。

缺点：

- 范围和风险显著扩大。
- 很多传递依赖不是仓库声明面，逐个确认“合适”成本极高。
- 更容易引入不可控兼容性回归。

### 方案 C：只升级部分高价值包

优点：

- 变更小。

缺点：

- 不覆盖全部 direct/dev 依赖。

### 推荐方案

用户已明确选择方案 C，因此本轮推荐的具体升级集为：

- SDK / Agent 栈：`openai`、`anthropic`、`openai-agents`、`pydantic-ai`
- 开发工具链：`ruff`、`pytest`、`mypy`
- CLI 体验层：`typer`

其中 `httpx`、`rich` 当前已是最新 GA，可只记录为“已检查，无需升级”。

## Grill Gate 问题与遗漏检查结论

问题：方案 C 里“关键包”的边界如何定义，才能既有收益又不失控？

推荐答案：聚焦在最容易带来行为变化、也最值得更新的 8 个包：`openai`、`anthropic`、`openai-agents`、`pydantic-ai`、`ruff`、`pytest`、`mypy`、`typer`。`httpx` 和 `rich` 只做版本核查，不强制改动。

遗漏检查结论：

- 依赖升级可能会要求代码适配，这意味着本轮不一定只是改 `pyproject.toml` 和 `uv.lock`。
- `openai` / `anthropic` / `pydantic-ai` 跨版本跨度较大，尤其 `pydantic-ai 2.0.0` 可能引发 API 兼容性修复。
- 即使只升级 8 个 direct/dev 依赖，`uv lock` 仍会带来一批传递依赖变化。
- 某些依赖的最新 GA 可能要求更高的 Python 版本或行为变更，需要以 `requires-python >=3.13` 为边界筛选。
- 升级 direct 依赖时，类型 stub 包也要同步考虑，例如 `types-*` 包。

## 影响范围

预计会涉及：

- `pyproject.toml`
- `uv.lock`
- 可能的兼容性修复代码和测试
- 本次计划文档

## 重要接口变更清单

新增接口：无。

删除接口：无。

修改接口：

- 关键 direct/dev 依赖版本集合会变化。
- 如果 SDK 或 CLI 库升级导致 API 兼容性变化，相关调用代码可能需要调整。

配置项变更：无新增配置项，除非某个升级后的库强制需要新配置。

文件输入输出契约：

- `pyproject.toml` 的 direct/dev 依赖版本会变化。
- `uv.lock` 会重写。

REST API 或外部调用面：

- 若 SDK 升级引入行为变化，外部 LLM / Gmail / Google API / Ark 等调用面可能需要回归验证。

## TDD / 测试策略

### Test Writer

这次核心是依赖升级，不适合先写全新业务测试；更合理的是先建立回归约束：

- 用当前现有测试作为 characterization baseline。
- 若发现某个库升级后暴露具体兼容性问题，再补针对性回归测试，形成红灯 -> 修复 -> 绿灯。

### Executor

- 先盘点方案 C 范围内 8 个目标包的当前版本与最新 GA。
- 升级这 8 个目标包，并记录 `httpx` / `rich` 已是最新，无需改动。
- 运行 `uv lock` / `uv sync`。
- 出现兼容性破坏时，按测试失败点补修复。

### Verify

- 最小验证先覆盖依赖解析与关键 CLI 启动。
- 完整验证执行全量 `pytest + ruff + mypy`。

## 三类 Verify 标准

### 自动化验证

最小验证命令：

```bash
uv lock --check
uv run pytest tests/test_cli_entrypoint.py -xvs
uv run ruff check .
```

预期结果：

- 锁文件状态正常。
- 最小 pytest 通过。
- `ruff` 通过。

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期结果：全部通过。

### 冒烟端到端验证

入口：

- `uv run beartools --help`
- `uv run beartools model check --help`
- `uv run beartools gmail --help`

预期结果：

- CLI 可正常启动。
- 受 SDK 影响较大的命令入口至少能完成 help / 轻量入口验证。

### 全面端到端验证

建议本轮省略单独人工全面 E2E，用完整自动化验证替代。

省略原因：

- 这次主要是依赖升级，风险面广但大多能通过自动化测试暴露。
- 真实外部服务端到端矩阵过大，不适合在第一轮全面铺开。

剩余风险：

- 某些真实第三方接口兼容性问题可能不会在本地测试里完全显现。
- 锁文件的大范围重解可能引入隐藏回归。

## 分步实施计划

1. Planner：确认方案 C 的具体升级集采用上述 8 个关键包。
2. Test Writer：确认使用 characterization / regression 策略，不强造无意义红灯测试。
3. Executor：盘点最新 GA，更新 `pyproject.toml`，重解 `uv.lock`，修复兼容性问题。
4. Verify：运行最小验证和完整验证。
5. Reviewer：重点看版本升级是否过量、兼容性修复是否足够窄、测试缺口是否可接受。
6. Documentation Sync：更新本计划文档；若依赖升级引发稳定使用方式变化，再考虑补充 `AGENTS.md` 或 `docs/codemap.md`。

## 执行结果

实际升级的 direct/dev 依赖：

- `openai`: `2.33.0` -> `2.44.0`
- `anthropic`: `0.97.0` -> `0.112.0`
- `openai-agents`: `0.15.1` -> `0.17.7`
- `pydantic-ai`: `1.89.1` -> `2.0.0`
- `ruff`: `0.15.12` -> `0.15.20`
- `pytest`: `9.0.3` -> `9.1.1`
- `mypy`: `1.20.2` -> `2.1.0`
- `typer`: `0.25.1` -> `0.26.8`

已确认但无需修改：

- `httpx`: 已是 `0.28.1`
- `rich`: 已是 `15.0.0`

执行中发生的环境事件：

- `uv run` 发现本地 `.venv` 状态不匹配后，按锁文件重新创建环境并使用 CPython `3.13.14`。
- `uv lock` 完成重解，锁文件包数量由 183 个变为 155 个；期间出现第三方包元数据版本范围规范化 warning，不影响解析结果。

为适配升级做的兼容性修复：

- Typer `0.26.8` 下缺少子命令时会抛出 vendored click 风格异常，CLI wrapper 增加 click-like 异常识别，保持原有无 traceback 的友好输出与退出码。
- 新版 OpenAI / Anthropic stubs 下，LLM runtime 用基于真实 SDK surface 的 `TypeGuard` 分支识别 OpenAI 与 Anthropic client，减少无意义 `cast`。
- `model check` 复用 runtime 的 client 类型判定，保持 OpenAI 与 Anthropic 路径清晰。
- Gmail 纯文本邮件改用 `MIMEText` 生成 payload，避开新版类型检查对 `EmailMessage[Any, Any]` 的不稳定推断。
- Memory summarizer 的 Anthropic PydanticAI model 构造保留最小范围 `cast`，并把测试 fake client 的识别收敛到一个可 monkeypatch 的 helper。
- `codex_vplan` 移除新版 OpenAI stubs 下已不需要的 `type: ignore[call-overload]`。

最终验证：

```bash
uv lock --check
uv run pytest tests/test_cli_entrypoint.py -xvs
uv run beartools --help
uv run beartools model check --help
uv run beartools gmail --help
uv run ruff check .
uv run mypy .
uv run pytest tests/ -xvs
```

结果：

- `uv lock --check` 通过。
- 轻量 CLI 冒烟命令均通过。
- `uv run ruff check .` 通过。
- `uv run mypy .` 通过，72 个 source files 无问题。
- `uv run pytest tests/ -xvs` 通过，370 个测试全部通过。

## 风险与回滚

风险：

- 一次性升级 8 个关键依赖，尤其 SDK 栈，仍可能触发多处兼容性变更。
- `uv.lock` diff 可能很大，review 成本上升。

回滚：

- 保留升级前的 `pyproject.toml` 和 `uv.lock` diff 边界。
- 若兼容性成本过高，可进一步收缩到“先升 SDK 栈”或“先升开发工具链”并重新做 Planner 确认。

## 需确认问题

已确认：用户选择方案 C，并已授权进入实现。

- 是否接受方案 C 的具体范围：升级 `openai`、`anthropic`、`openai-agents`、`pydantic-ai`、`ruff`、`pytest`、`mypy`、`typer`，并仅核查 `httpx`、`rich` 为最新无需改动？
