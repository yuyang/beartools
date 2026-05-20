# Codex VPlan TDD Plan

## 背景和目标

用户要求按 TDD 方式新增 `codex vplan` 子命令。它和现有 `codex pic` 的输入输出保持一致：输入 Markdown prompt 文件，输出图片文件和 trace 文件到同样形状的输出目录；唯一差异是图片生成阶段不使用现有 `codex.pic_model` + `b64_json` 流程，而是按用户给出的火山 Ark OpenAI 兼容示例调用：

- `base_url="https://ark.cn-beijing.volces.com/api/v3"`
- `api_key` 读取 `get_config().codex.vplan.key`
- `model="doubao-seedream-4-5-251128"`
- `size="2K"`
- `response_format="url"`
- `extra_body={"watermark": False}`

执行时先复用从 `codex pic` 抽取出的 prompt refine 能力，把 Markdown 原文优化为图片提示词；随后用 refined prompt 调用 Ark 图片接口。拿到 `imagesResponse.data[0].url` 后，下载 URL 对应的图片内容并写入本地 output 文件。

本轮遵循 `docs/workflows/codex-tdd-flow.md`：Planner 是硬门禁。当前阶段只新增本计划文档，不修改测试或生产代码；用户确认 Planner Exit 后才进入 Test Writer。

## 历史上下文

- `docs/codemap.md` 说明 `beartools codex` 入口在 `src/beartools/commands/codex/command.py`，图片业务集中在 `src/beartools/codex_pic.py`。
- 现有 `codex pic` 链路为 `beartools codex pic <md_path> -> command.py::codex_pic() -> codex_pic.py::run_codex_pic() -> run_codex_pic_async()`。
- `codex_pic.py` 当前负责 Markdown 输入校验、prompt refine、图片 API 调用、trace 写入、base64 解码和最终图片落盘。
- 现有 `codex pic` 默认输出路径由 `_resolve_pic_output_paths()` 决定：`output/pic/<md_stem>/<md_stem>.<format>` 和 `output/pic/<md_stem>/<md_stem>.trace.log`。
- 历史记忆里 `codex pic` 和 `codex novel` 的稳定经验是：新增 codex 子命令优先 additive，不破坏 `run`、`pic`、`picbatch`、`picedit`；图片相关输出和进度信息要包含可追踪的输入/输出路径。

## 非目标

- 不修改现有 `codex pic`、`picbatch`、`picedit` 的外部行为。
- 不引入新的包依赖；下载图片优先使用标准库 `urllib.request`，或仅在已有依赖足够时复用现有依赖。
- 不新增数据库、持久任务队列或主配置迁移。
- 不在单元测试中访问真实 Ark 或图片 URL；外部调用通过 fake client / fake downloader 验证。
- 不做批量 `vplanbatch`，除非用户后续明确要求。

## Brainstorm 选项和推荐方案

### 方案 A：新增独立 `codex_vplan.py`，复用 pic 的输入输出契约

做法：新增业务模块 `src/beartools/codex_vplan.py`。它读取 `.md` prompt，调用从 `codex_pic.py` 抽取出来的共享 prompt refine helper，使用 refined prompt 调用 Ark 图片接口，提取 URL，下载图片字节，写到 `output/vplan/<stem>/<stem>.<format>`，并写 trace。CLI 新增 `beartools codex vplan <md_path>`，参数尽量与 `pic` 一致。

优点：不会搅动现有 `pic` 的图片生成和 b64 写文件逻辑；`pic` 与 `vplan` 共用 prompt refine，避免后续两套提示词优化发散。TDD 测试可清晰验证共享 refine、Ark 请求体、URL 下载和输出契约。

缺点：需要对 `codex_pic.py` 做一次小范围重构，把 refine helper 抽成可供 `pic` 和 `vplan` 调用的函数；仍不做多 provider 大重构。

### 方案 B：把 `codex_pic.py` 改造成多 provider 图片引擎

做法：给现有 pic 增加 provider 参数或内部策略，把 OpenAI b64 和 Ark URL 作为两个后端。

优点：长期抽象更统一。

缺点：会扩大现有 `pic` 回归风险，也会引入 CLI/config 设计问题；当前用户要的是新增 `vplan`，不是改造 `pic`。

### 方案 C：让 `vplan` 先生成一个临时 Markdown 再调用 `pic`

做法：复用 `pic` 的 prompt refine，再额外替换图片请求。

优点：理论上可复用 prompt refine。

缺点：如果直接调用 `pic`，会连图片生成后端也一起复用，不能满足 Ark URL 生成差异；但抽取 refine helper 后，`vplan` 可以只复用提示词优化，不复用 b64 图片后端。

### 推荐方案

采用方案 A，并按用户最新确认抽取共享 prompt refine。新增 `codex_vplan.py` 和 `codex vplan` 子命令，保持 `codex pic` 的输入输出形状；`pic` 和 `vplan` 都调用共享 refine helper，差异只在图片生成阶段：`pic` 继续走现有 b64 图片接口，`vplan` 走 Ark URL 图片接口。输出目录改为 `output/vplan/<stem>/`；trace 中明确记录 `provider="volcengine_ark"`、原始 prompt、refined prompt、模型、size、watermark、响应 URL、下载耗时和输出路径。

## Grill Gate

问题：`vplan` 是否应该直接使用用户示例中的 Ark base URL 和默认模型，同时从项目 secrets 的 `codex.vplan.key` 读取 API key，而不是复用 `config/beartools.yaml` 的 `codex.base_url`、`codex.api_key`、`codex.pic_model` 或环境变量 `ARK_API_KEY`？

用户确认答案：是。`vplan` 的价值就是提供一个与 `codex pic` 并列的火山 Ark 图片通道，因此 base URL 使用示例文档的 `https://ark.cn-beijing.volces.com/api/v3`，模型使用 `doubao-seedream-4-5-251128`，API key 从 `get_config().codex.vplan.key` 读取。本轮只新增 `codex.vplan.key` 配置路径；如未来需要，再在单独需求中把 Ark 其他参数配置化。

遗漏检查结论：

- Ark `size="2K"` 不属于现有 `codex pic` 的尺寸枚举，因此 `vplan` 需要自己的 size 校验，默认 `2K`。
- Ark 返回 URL 后必须下载图片内容；只把 URL 写入文本文件不满足“写入 output 文件”的图片产物契约。
- `--quality` 按用户确认保留为兼容参数，但不传给 Ark，只写入 trace。
- `--output-format` 按用户确认直接忽略，不传给 Ark，也不决定本地扩展名；返回 URL 后下载图片字节，落盘扩展名根据 URL 路径后缀决定。若 URL 没有可识别图片后缀，则使用 `.png` 兜底并在 trace 中记录。
- `watermark` 按用户最新要求固定为 `False`；本轮不暴露 CLI 开关。
- 用户确认方案 A 但要求把 `pic` prompt refine 部分抽取出来，`pic` 和 `vplan` 都调用它。因此本轮允许对 `codex_pic.py` 做小范围内部重构，但不能改变 `codex pic` 的外部行为、输出路径和 trace 关键字段。
- 输出目录按用户最新确认使用 `output/vplan/<stem>/`。
- `size` 默认 `2K`，直接传给 Ark；平台不支持时由 Ark 返回错误并写 trace。
- `vplan` 按用户确认成功后播放系统提示音，失败不播放。
- 真实 smoke E2E 按用户确认需要实际跑一次 Ark 图片生成；如遇网络或沙箱限制，按审批流程请求批准。
- `config/beartools.secrets.yaml.sample` 按用户确认需要补充 `codex.vplan.key` 占位示例。

## 影响范围

- 新增业务模块：`src/beartools/codex_vplan.py`
  - 定义 `CodexVPlanResult`。
  - 校验输入必须存在、是文件、后缀为 `.md`。
  - 读取 prompt 文本。
  - 调用共享 prompt refine helper，得到 refined prompt。
  - 从 `get_config().codex.vplan.key` 读取并校验必填。
  - 调用 `OpenAI(base_url=ARK_BASE_URL, api_key=config.codex.vplan.key).images.generate(...)`。
  - 提取 `response.data[0].url`，缺失时报清晰错误。
  - 下载 URL 图片字节并写到 output 文件。
  - 写 trace log，包含 original prompt、refined prompt、refine 耗时、模型、size、quality、response_format、watermark、url、URL 后缀推断结果、耗时、错误和 output 路径；trace 不写图片二进制。
- 修改图片业务：`src/beartools/codex_pic.py`
  - 抽取 prompt refine helper，例如 `refine_codex_pic_prompt_async(prompt, config, client)` 或同等命名。
  - `run_codex_pic_async()` 改为调用共享 helper，保持现有行为、console 输出、trace 字段和错误语义不变。
  - `picedit` 的编辑提示词 refine 不纳入本次共享，除非实现时发现可以零风险复用；默认只抽取做图 prompt refine。
- 修改 CLI：`src/beartools/commands/codex/command.py`
  - 注册 `vplan` 子命令。
  - 参数与 `pic` 对齐：`md_path`、`--size`、`--quality`、`--output-format`。
  - `--quality` 为兼容输入形状保留，但 Ark 示例未使用；实现可以接受并记录到 trace，不传给 Ark。
  - `--output-format` 为兼容输入形状保留，但按用户确认直接忽略；本地图片扩展名根据 Ark 返回 URL 决定。
  - 成功时输出结果目录、图片路径和 trace 路径，并播放系统提示音。
  - 捕获 `RuntimeError`、`FileNotFoundError`、`ValueError` 等，按现有命令风格退出 1。
- 修改测试：`tests/test_codex_command.py`
  - 覆盖 CLI 注册、参数透传、成功输出和错误输出。
  - 覆盖共享 refine helper 被 `pic` 和 `vplan` 调用、Ark 请求参数、URL 提取、下载写文件、trace 写入、输入校验和缺失 API key。
- 可能修改文档：`docs/codemap.md`
  - Documentation Sync 阶段补充 `codex_vplan.py` 和 `beartools codex vplan` 调用链。
- 修改配置示例：`config/beartools.secrets.yaml.sample`
  - 增加 `codex.vplan.key: "REPLACE_ME"` 占位示例，不写入真实密钥。

## 重要接口变更清单

新增接口：

- CLI：`beartools codex vplan <md_path> [--size 2K] [--quality <value>] [--output-format <ignored>]`
- Python 业务函数：`run_codex_vplan(...)` 和 `run_codex_vplan_async(...)` 或同步等价函数，具体以实现阶段测试约束为准。
- Python 内部共享函数：从 `codex_pic.py` 暴露或内部复用的做图 prompt refine helper，供 `pic` 与 `vplan` 调用；该 helper 不是稳定公开 API。
- 输出文件：默认写入 `output/vplan/<md_stem>/<md_stem>.<url_extension>`；URL 没有可识别图片后缀时兜底为 `.png`。
- Trace 文件：默认写入 `output/vplan/<md_stem>/<md_stem>.trace.log`。
- 敏感配置读取：`config/beartools.secrets.yaml` 中的 `codex.vplan.key`。
- 外部 API 调用：`POST https://ark.cn-beijing.volces.com/api/v3/images/generations`，通过 OpenAI SDK `client.images.generate()` 发起。

删除接口：

- 无。

修改接口：

- 无现有公开接口修改；`codex pic` 行为保持不变。

配置项：

- 本轮新增 `codex.vplan.key` 配置路径。
- 本轮依赖配置解析后的 `get_config().codex.vplan.key`，并更新 `config/beartools.yaml.sample` / `config/beartools.secrets.yaml.sample` 增加占位示例。

数据库/REST API：

- 无数据库表结构变更。
- 无 REST API 接口变更。

## TDD/测试策略

Test Writer 阶段先写红灯测试：

1. CLI 层：
   - `beartools codex --help` 包含 `vplan`。
   - `beartools codex vplan prompt.md` 调用业务函数，默认 `size="2K"`，`quality=None`，`output_format=None`。
   - `--size 2K --quality high --output-format webp` 能透传到业务函数，但业务函数只记录 `quality`，并忽略 `output_format`。
   - `vplan` 成功后播放系统提示音；业务失败时不播放。
   - 业务抛错时 CLI 输出 `错误: ...` 且退出码为 1。
2. 业务层：
   - 非 `.md`、不存在路径、目录路径分别报错。
   - 缺少 `codex.vplan.key` 报错。
   - fake prompt refine 返回 `refined prompt`，fake OpenAI client 断言 Ark 请求中的 `prompt` 使用 refined prompt，而不是 Markdown 原文。
   - fake OpenAI client 断言请求参数包含 `model="doubao-seedream-4-5-251128"`、`prompt`、`size="2K"`、`response_format="url"`、`extra_body={"watermark": False}`。
   - `size` 直接传给 Ark，不做本地枚举校验。
   - fake response 返回 `https://example.com/image.webp` 后，fake downloader 返回图片字节，最终写入 `output/vplan/<stem>/<stem>.webp`。
   - fake response 返回没有图片后缀的 URL 时，最终写入 `output/vplan/<stem>/<stem>.png` 并在 trace 中记录 fallback。
   - trace 文件包含 response URL、output path 和 completed status。
   - trace 文件包含 original prompt 和 refined prompt。
   - response 缺少 `data[0].url` 时写失败 trace 并报错。
   - 下载失败时写失败 trace 并报错。
   - secrets sample 包含 `codex.vplan.key` 占位。
3. 回归保护：
   - 现有 `codex pic` 测试继续通过，证明新增命令没有改变旧路径。
   - 新增或调整测试证明 `run_codex_pic_async()` 调用了共享 refine helper，且现有 trace 字段不丢失。

## Verify 标准

自动化验证：

最小验证命令：

```bash
uv run pytest tests/test_codex_command.py -xvs
uv run ruff check src/beartools/codex_vplan.py src/beartools/commands/codex/command.py tests/test_codex_command.py config/beartools.secrets.yaml.sample
uv run ruff check src/beartools/codex_pic.py
uv run mypy src/beartools/codex_vplan.py src/beartools/codex_pic.py src/beartools/commands/codex/command.py
```

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

冒烟端到端验证：

- `uv run beartools codex vplan --help` 能看到子命令说明。
- 准备一个小 Markdown prompt，例如 `input/codex/vplan-smoke.md`。
- 在 `config/beartools.secrets.yaml` 存在 `codex.vplan.key` 且允许网络访问时，运行 `uv run beartools codex vplan input/codex/vplan-smoke.md`；该真实 Ark smoke 是本轮必须执行的 E2E 验证，除非 key、网络或平台权限不可用。
- 预期命令成功，`output/vplan/vplan-smoke/` 下有图片文件和 trace log，trace 记录 Ark URL，图片文件非空。

全面端到端验证：

- 建议本轮省略全面端到端验证，只做一个真实 smoke。原因：真实图片生成有耗时、费用和网络/凭据依赖；本需求主要风险可由单元测试覆盖，真实 smoke 证明链路可用即可。
- 如果用户要求全面 E2E，则补跑至少 3 个 prompt：中文长 prompt、英文短 prompt、特殊字符/换行 prompt，分别验证输出文件非空和 trace 完整。

## 分步实施计划

1. Test Writer：在 `tests/test_codex_command.py` 增加 `vplan` CLI 与业务层红灯测试。
2. Executor 第一层：从 `codex_pic.py` 抽取共享做图 prompt refine helper，并让现有 `pic` 调用它，保持旧测试通过。
3. Executor 第二层：新增 `src/beartools/codex_vplan.py`，实现输入校验、输出路径、共享 refine 调用和 trace 写入。
4. Executor 第三层：实现 Ark OpenAI client 调用和 URL 提取，测试用 fake client 注入。
5. Executor 第四层：实现 URL 下载和图片字节落盘，测试用 fake downloader 注入。
6. Executor 第五层：在 `commands/codex/command.py` 注册 `vplan`，保持 CLI 输出风格一致。
7. Verify：先跑最小验证，再跑完整验证；如 uv cache 权限触发沙箱失败，按审批流程重新运行。
8. Reviewer：按 `docs/checklists/review.md` 审查 diff；因为涉及外部 API key 和网络请求，也参考 `docs/checklists/audit.md` 的敏感配置与外部调用项。
9. Documentation Sync：更新计划文档实际结果，必要时更新 `docs/codemap.md`。

## 实际结果

- 新增 `src/beartools/codex_vplan.py`，实现 `run_codex_vplan()` / `run_codex_vplan_async()`。
- 新增 CLI `beartools codex vplan <md_path>`，参数包含 `--size`、`--quality`、`--output-format`。
- `vplan` 读取 Markdown 原文后，先调用 `codex_pic.py::refine_codex_pic_prompt_async()` 得到 refined prompt，再调用 Ark URL 图片接口。
- Ark base URL 固定为 `https://ark.cn-beijing.volces.com/api/v3`，模型为 `doubao-seedream-4-5-251128`，API key 从 `get_config().codex.vplan.key` 读取。
- Ark 请求固定 `response_format="url"`、`extra_body={"watermark": False}`；`--quality` 只写入 trace，不传 Ark；`--output-format` 被忽略。
- 图片输出目录使用 `output/vplan/<stem>/`；图片扩展名根据 Ark 返回 URL 后缀决定，无图片后缀时兜底 `.png`。
- `codex_pic.py` 新增共享做图 prompt refine helper，`run_codex_pic_async()` 已改为调用该 helper，外部行为保持不变。
- `config/beartools.yaml.sample` 和 `config/beartools.secrets.yaml.sample` 已补充 `codex.vplan.key` 占位示例。
- `docs/codemap.md` 已同步 `codex_vplan.py`、`beartools codex vplan` 调用链和 `output/vplan/<stem>/` 输出位置。

## Verify 结果

- TDD 红灯：首次运行新增测试时因 `beartools.codex_vplan` 不存在失败。
- 最小 pytest：`uv run pytest tests/test_codex_command.py tests/test_config.py::TestConfig::test_secrets_sample_contains_sensitive_values -xvs`，61 passed。
- 最小 ruff：`uv run ruff check src/beartools/codex_vplan.py src/beartools/codex_pic.py src/beartools/commands/codex/command.py tests/test_codex_command.py tests/test_config.py`，passed。
- 最小 mypy：`uv run mypy src/beartools/codex_vplan.py src/beartools/codex_pic.py src/beartools/commands/codex/command.py`，passed。
- 完整 pytest：`uv run pytest tests/ -xvs`，368 passed。
- 完整 ruff：`uv run ruff check .`，passed。
- 完整 mypy：`uv run mypy .`，72 source files passed。
- CLI smoke：`uv run beartools codex vplan --help`，显示 `vplan` 参数说明。
- 真实 Ark smoke：`env BEARTOOLS_MEMORY_FAKE_SUMMARY='vplan smoke' uv run beartools codex vplan input/p1.md` 曾在旧输出目录口径下成功；输出目录改为 `output/vplan/<stem>/` 后需在最终 Verify 中按新路径复验。
- Reviewer/Audit：未发现阻塞性问题；剩余风险是 trace 会记录 Ark 返回的临时签名图片 URL，便于排查但短期内可访问该图片。

## 风险、回滚和需确认问题

风险：

- Ark 模型 `doubao-seedream-4-5-251128`、`size="2K"` 或 `watermark` 参数可能随平台变化；本轮按用户示例实现，失败时把平台错误写入 trace。
- `codex.vplan.key` 通常位于 secrets 文件并经配置系统解析，不应写入 trace、console 或 git；真实 E2E 依赖用户本地配置存在该值。
- 下载 URL 可能过期或需要跳转；实现应允许标准库处理常规跳转，并在失败 trace 里记录错误。
- `--output-format` 在 `vplan` 中被忽略，可能让用户误以为会控制输出格式；CLI help 和 trace 需要说明扩展名由 URL 决定。
- 抽取 `pic` prompt refine 有回归风险；通过现有 `codex pic` 测试和新增共享 helper 测试约束，不改变外部行为。
- 真实 smoke 可能产生外部调用费用；本轮已由用户确认执行一次。

回滚：

- 删除 `src/beartools/codex_vplan.py`。
- 移除 `commands/codex/command.py` 中 `vplan` 导入、函数和注册。
- 如共享 refine 抽取导致回滚，恢复 `codex_pic.py` 原有 `_refine_pic_prompt_async()` 调用形状。
- 删除新增测试和文档同步内容。

需用户在 Planner Exit 确认：

- 确认 `vplan` 默认使用 `config/beartools.secrets.yaml` 的 `codex.vplan.key`、示例文档 Ark base URL、`doubao-seedream-4-5-251128`、`size="2K"`、`watermark=False`。
- 确认 `pic` prompt refine 抽取为共享 helper，`pic` 和 `vplan` 都调用它；`vplan` 使用 refined prompt 调 Ark。
- 确认 `vplan --output-format` 仅为兼容参数，业务直接忽略；本地落盘扩展名从 Ark 返回 URL 决定。
- 确认输出目录使用 `output/vplan/<stem>/`。
- 确认 `vplan --quality` 仅记录 trace，不传 Ark；`size` 默认 `2K` 并直接传给 Ark。
- 确认 `vplan` 成功播放系统提示音，失败不播放。
- 确认实现后实际跑一次 Ark smoke E2E。
- 确认更新 `config/beartools.secrets.yaml.sample`，加入 `codex.vplan.key` 占位示例。
- 确认本轮只新增 `codex.vplan.key` 配置路径，不做 `vplanbatch`。
- 确认三类 Verify 标准；尤其是是否同意全面端到端验证本轮省略，只做真实 smoke。
