# Siyuan CLI Refactor TDD Plan

## 背景和目标

用户希望查看现有代码，在可以安全简化的地方按 TDD 方式执行；随后明确提示可以看看 Siyuan 相关代码。

本轮目标切换到 Siyuan 相关代码：先补测试，再简化 `src/beartools/commands/siyuan/command.py` 中重复的错误处理、配置 fallback 和文件写入逻辑，同时保持 CLI 外部行为不变。

## 历史上下文

- `docs/codemap.md` 记录 `beartools siyuan` 的 CLI 适配层在 `src/beartools/commands/siyuan/command.py`，业务封装集中在 `src/beartools/siyuan.py`。
- `docs/codemap.md` 记录 `fetch` 命令也会复用 `SiyuanHandler.upload_md()` 做自动上传；本轮不改 `fetch` 调用路径。
- 记忆中已有 SiYuan API 调研结论：`exportMdContent` 是单文档内容导出，文档树导出需要组合 filetree 相关接口和 batch export；本轮只做现有 `ls-notebooks`、`export-md`、`upload-md` 的命令层重构，不新增文档树导出能力。
- 当前没有专门的 `tests/test_siyuan.py`，Siyuan CLI 行为缺少自动化保护。

## 非目标

- 不新增思源 API 能力，不实现文档树递归导出。
- 不改变 API endpoint：继续使用 `lsNotebooks`、`exportMd`、`createDocWithMd`。
- 不改变 CLI 命令名、参数名、成功/失败核心文案和退出码。
- 不调用真实思源服务，不依赖本机 6806 端口。
- 不改 `src/beartools/siyuan.py` 的 aiohttp 请求流程，除非测试暴露出必须修复的局部问题。
- 不改 `fetch` 自动上传逻辑。

## Brainstorm 选项和推荐方案

### 方案 A：只重构 Siyuan CLI 层

- 在 `commands/siyuan/command.py` 中抽出统一的 `SiyuanError` 展示 helper。
- 抽出配置 fallback helper，减少 `noteid if noteid else config...`、`notebook if notebook else config...` 这类重复。
- 将 `export-md --output` 的文件写入改为 `Path(output).write_text(...)`，只捕获 `OSError`，去掉宽泛 `except Exception`。
- 补 CLI mock 测试，保护成功路径、配置 fallback、连接错误提示和输出文件写入错误。

优点：低风险、测试容易、符合“简化现有逻辑”的范围；不会触碰真实外部服务。

### 方案 B：重构 `SiyuanHandler` 的 HTTP 请求公共逻辑

- 在 `siyuan.py` 中抽出 `_post_json()` 或 `_request_json()`，统一 status/code/msg 检查。

问题：当前没有 HTTP mock 测试，aiohttp context manager 测试成本更高；容易把小重构扩成 API 层结构调整。

用户确认结论：不用执行。

### 方案 C：新增文档树导出能力

问题：这是新功能，不是简化；还需要重新确认业务入口、输出格式和真实 API 验证标准。

用户确认结论：不用执行。

### 推荐方案

采用方案 A：先把 Siyuan CLI 层补上测试并做小范围重构。`src/beartools/siyuan.py` 暂时保持不动，只作为被 mock 的业务边界。

用户确认结论：确认这个方案。

## Grill Gate

问题 1：这次是否要顺手实现“导出一个文档及其子树”？

推荐答案：不实现。它需要新 API 组合、输出结构设计和真实思源环境验证，不属于本轮“简化现有代码逻辑”的安全范围。

用户确认结论：不用执行文档树导出。

问题 2：是否需要真实连接本机思源 6806 做 E2E？

推荐答案：本轮省略真实思源 E2E。原因是只重构 CLI 包装逻辑，核心业务边界用 fake handler 覆盖；真实思源状态、token 和本机数据会引入环境不确定性。保留 mock 级 CLI 冒烟即可。

用户确认结论：不用执行真实思源 E2E，仅保留 mock 级 CLI 冒烟。

## 影响范围

- `src/beartools/commands/siyuan/command.py`
  - 抽出统一错误提示 helper。
  - 抽出配置 fallback helper。
  - 文件输出改用 `Path.write_text()` 并捕获 `OSError`。
  - 保持 `_handler = SiyuanHandler()` 和现有命令注册不变。
- `tests/test_siyuan.py`
  - 新增 Siyuan CLI 测试，使用 fake handler 和 fake config，不调用真实思源。
- `docs/plans/2026-05-12-siyuan-cli-refactor-plan.md`
  - 实现后记录最终 Verify 结果、红灯情况和文档同步结论。
- `docs/codemap.md`
  - 预计无需更新，因为模块职责和入口不变；Documentation Sync 阶段再确认。

## TDD/测试策略

Test Writer 阶段先新增 `tests/test_siyuan.py`：

- `siyuan --help` 注册并展示 `ls-notebooks`、`export-md`、`upload-md`。
- `ls-notebooks` 成功时格式化输出 notebook 名称、id、icon 和 closed 标记。
- `ls-notebooks` 遇到连接类 `SiyuanError` 时退出码为 1，并提示检查思源是否启动。
- `export-md` 未传 `--noteid` 时使用配置中的 `default_note`。
- `export-md --output` 成功时写入目标文件。
- `export-md --output` 写入失败时退出码为 1，并输出写入失败提示。
- `upload-md` 未传 `--notebook` / `--path` 时使用配置 fallback；配置也为空时退出码为 1。
- `upload-md` 成功时输出文档 ID。

红灯策略：

- 由于当前命令已经存在，大部分测试可能作为 characterization tests 直接通过。
- 写入失败测试会约束后续把宽泛 `except Exception` 收窄为 `OSError` 后仍保持用户可见行为。
- 如果无法形成红灯，记录为重构型 characterization test，然后进入 Refactor，确保重构前后测试都绿。

## Verify 标准

### 自动化验证

最小验证命令：

```bash
uv run pytest tests/test_siyuan.py tests/test_cli_entrypoint.py -xvs
uv run ruff check src/beartools/commands/siyuan/command.py tests/test_siyuan.py
uv run mypy .
```

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

预期结果：所有命令通过。当前 sandbox 对 `~/.cache/uv` 访问受限，正式运行 `uv` 命令时需要按规则请求提升权限。

### 冒烟端到端验证

执行 mock 级 CLI 冒烟，不调用真实思源：

- 使用 `CliRunner` 调用 `beartools siyuan ls-notebooks`、`export-md`、`upload-md`。
- fake handler 返回固定 notebook、Markdown 内容和 doc id，证明 CLI 入口、参数 fallback 和输出逻辑可工作。

### 全面端到端验证

建议本轮省略真实思源全面端到端验证。

省略原因：本轮只重构命令层包装逻辑，不改变 HTTP endpoint、payload、token 读取或业务 API 调用；真实思源验证依赖本机服务状态、token、目标 notebook/path 和用户数据。

剩余风险：真实思源服务的 endpoint 行为、token 权限和目标路径写入仍只能由真实环境最终证明；但本轮不触碰这些业务路径，风险较低。

用户确认结论：同意省略真实思源全面端到端验证。

## 分步实施计划

1. Planner：写入本计划文档，并等待用户确认计划和三类 Verify 标准。
2. Test Writer：新增 `tests/test_siyuan.py` characterization tests，运行最小 pytest，记录红灯或无法红灯原因。
3. Executor：按方案 A 简化 `commands/siyuan/command.py`。
4. Verify：执行最小验证命令；通过后按风险执行完整验证命令。
5. Reviewer：按 `docs/checklists/review.md` 审查 diff；本轮不涉及敏感配置写入、数据库、外部发布，预计不单独执行 audit。
6. Fix Loop：修复 verify/review 发现的问题并复测。
7. Documentation Sync：更新本计划最终状态；确认 `docs/codemap.md` 是否无需变更。

## 风险、回滚和需要用户确认的问题

风险：

- fake handler 测试只能证明 CLI 包装逻辑，不能证明真实思源服务可用。
- 如果 helper 抽象过度，可能让简单命令层变得更难读；实现时只抽重复且稳定的逻辑。
- 如果错误文案变动过大，可能影响用户脚本或使用习惯；测试会尽量保护核心文案。

回滚：

- 删除 `tests/test_siyuan.py` 中本轮新增测试。
- 恢复 `src/beartools/commands/siyuan/command.py` 中三个命令各自处理错误、配置 fallback 和文件写入的原始结构。
- 删除或保留本计划最终记录，视用户是否要保留 Planner 历史。

用户已确认：

- 同意本轮只简化 Siyuan CLI 层，不改 `SiyuanHandler` HTTP 请求流程。
- 同意自动化验证按“最小验证 + 完整验证”执行。
- 同意冒烟端到端验证采用 mock 级 CLI 路径。
- 明确同意省略真实思源全面端到端验证，并接受上述剩余风险。

## 最终实现记录

- 新增并精简 `tests/test_siyuan.py`，覆盖 `siyuan --help`、`ls-notebooks`、`export-md`、`upload-md` 的关键成功路径、配置 fallback、连接错误提示、输出文件写入失败和缺少配置错误。
- `src/beartools/commands/siyuan/command.py` 新增 `_option_or_config()`，统一处理命令行参数优先、配置兜底的逻辑。
- `src/beartools/commands/siyuan/command.py` 新增 `_print_siyuan_error()` 和 `_run_siyuan_task()`，统一处理 `SiyuanError` 和连接提示。
- `export-md --output` 改为 `Path.write_text(..., encoding="utf-8")`，并只捕获 `OSError`。
- 修复 `ls-notebooks` 输出中 notebook id 被 Rich markup 解析吞掉的问题：notebook 行使用 `markup=False`，现在会正确显示 `[notebook_id]`。
- 未修改 `src/beartools/siyuan.py` 的 HTTP 请求流程，未修改 `fetch` 自动上传逻辑。

## 最终 Verify 结果

红灯：

- `uv run pytest tests/test_siyuan.py tests/test_cli_entrypoint.py -xvs`：新增 `test_ls_notebooks_prints_notebook_fields` 后先失败，原因是 `console.print(f"... [{id_}]")` 被 Rich 当成 markup，实际输出没有 notebook id。该失败符合 TDD 红灯，且暴露了现有 CLI 显示问题。

自动化验证：

- `uv run pytest tests/test_siyuan.py tests/test_cli_entrypoint.py -xvs`：通过，11 passed。
- `uv run ruff check src/beartools/commands/siyuan/command.py tests/test_siyuan.py`：通过。
- `uv run mypy .`：通过，58 source files。
- `uv run pytest tests/ -xvs`：通过，331 passed。
- `uv run ruff check .`：通过。

冒烟端到端验证：

- 已通过 `CliRunner` mock 级 CLI 冒烟覆盖 `beartools siyuan ls-notebooks`、`export-md`、`upload-md`。
- fake handler 返回固定 notebook、Markdown 内容和 doc id，证明 CLI 入口、参数 fallback、输出文件写入和错误展示均可工作。

全面端到端验证：

- 按用户确认，本轮不执行真实思源服务 E2E。
- 省略原因：本轮只重构命令层包装逻辑，不改变 HTTP endpoint、payload、token 读取或业务 API 调用；真实思源验证依赖本机服务状态、token、目标 notebook/path 和用户数据。
- 剩余风险：真实思源服务的 endpoint 行为、token 权限和目标路径写入仍只能由真实环境最终证明。

## Review 结论

未发现阻塞性问题。

剩余风险：

- 测试使用 fake handler，只证明 CLI 包装逻辑，不证明真实思源服务可用。
- `SiyuanError` 连接提示仍沿用字符串包含 `连接` 的判断，保持了现有行为；如果后续需要更稳定分类，可在业务层增加错误类型。

测试覆盖：

- 新增测试覆盖成功路径、连接失败、配置 fallback、缺少配置、输出写入失败和 help 注册；后续按用户要求压缩了重复测试，保留关键行为保护。
- 全量测试、全量 ruff 和 mypy 均通过。

## 文档同步

- 本计划文档已更新为最终实现和验证结果。
- `docs/codemap.md` 无需更新：模块职责、CLI 入口、输出位置和业务调用链均未变化；本轮只是命令层内部简化和 bug 修复。
