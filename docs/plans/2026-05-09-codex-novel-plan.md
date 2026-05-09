# Codex Novel TDD Plan

## 背景和目标

用户要求按商业开发流程新增 `codex novel` 子命令：输入小说 `.txt` 或 `.md` 文件，按命令参数 `n`（默认 4）从小说中选择精彩场景，将场景简化为适合 `pic` 的文本输入，并生成 `n` 张图片。处理过程需要在 console 和 log 中都有记录。

本轮遵循 `docs/workflows/codex-tdd-flow.md`：`Planner -> Test Writer -> Executor -> Verify -> Reviewer -> Fix Loop -> Documentation Sync`。当前 Planner 阶段只新增本计划文档，不修改测试和生产代码。用户确认本计划和 Verify 标准后，才进入测试编写阶段。

## 历史上下文

- `docs/codemap.md` 说明 `beartools codex` 入口在 `src/beartools/commands/codex/command.py`，业务逻辑主要在 `src/beartools/codex.py` 和 `src/beartools/codex_pic.py`。
- `docs/codemap.md` 记录现有图片生成链路：`beartools codex pic <md_path> -> commands/codex/command.py::codex_pic() -> codex_pic.py::run_codex_pic() -> run_codex_pic_async()`。
- `docs/plans/2026-05-09-superpowers-docs-compression-plan.md` 记录稳定结论：Codex 图片相关实现集中在 `codex_pic.py`，CLI 只做参数接收、错误展示和完成提示；`picbatch` 单项失败不应吞掉错误信息。
- 历史记忆中 `codex pic` 最初是追加子命令，并保持 `codex run` 不变。后续新增 `novel` 也应保持 additive，不破坏现有 `run`、`pic`、`picbatch`、`picedit` 行为。
- 发现一个文档/代码差异：历史文档曾写 `out/pic/<stem>/`，当前代码和测试实际使用 `output/pic/<stem>/`。用户已确认应以 `output` 为准；本次 `novel` 的提示词、图片和 trace log 统一放到 `output/novel/stem_<input_stem>/`，不分散到 `output/pic`。

## 非目标

- 不实现真实小说全文切章、角色设定库、连续性世界观管理或跨章节记忆。
- 不新增数据库表结构或持久化任务队列。
- 不改变现有 `codex pic`、`picbatch`、`picedit` 的 CLI 参数和输出格式。
- 不在测试中调用真实 OpenAI/第三方图片接口；外部模型调用均使用 stub/mock。
- 不新增依赖，除非实现阶段发现标准库和现有依赖无法满足需求，并需先回到 Planner 更新计划。

## Brainstorm 选项和推荐方案

### 方案 A：给图片生成链路增加可控输出目录后复用核心能力

做法：新增 `codex_novel.py`，读取 `.txt` 或 `.md` 前 10000 字，用文本模型抽取 `n` 个精彩场景并转换成图片提示词；把每个提示词写入 `output/novel/stem_<input_stem>/scene_001.md` 等临时文件；逐个调用现有图片生成核心能力，并显式指定每张图片和 trace log 输出到同一 novel 目录。

优点：最大化复用现有图片 prompt refine、图片 API、trace 脱敏、尺寸/质量/格式校验、日志记录，同时满足 novel 任务单目录归档。测试可以通过 patch 图片生成内部调用验证流程。

缺点：需要对 `codex_pic.py` 做小幅兼容改造，例如为 `run_codex_pic_async()` 增加可选 `output_dir`/`output_stem` 参数，或抽出内部 helper，使现有 `codex pic` 默认路径不变。

### 方案 B：新增专用图片生成循环，不写临时 Markdown

做法：在 `codex_novel.py` 中直接调用图片 API。

优点：输出目录可以完全按 novel 任务定制，提示词、图片和 trace 天然在同一目录。

缺点：会重复 `codex_pic.py` 的图片请求、trace、配置校验、token usage、错误处理逻辑，维护成本更高。

### 方案 C：把小说拆成 n 个 Markdown 后调用 `run_codex_picbatch`

做法：抽取场景后写多个 Markdown，再调用批量图片入口。

优点：最少新业务代码。

缺点：`picbatch` 当前固定沿用 `output/pic/<stem>/`，不满足提示词、图片和 trace 统一放到 `output/novel/stem_<input_stem>/` 的新输出契约；同时它不负责小说抽取阶段，novel 总 trace 不够清晰。

### 推荐方案

采用方案 A：新增 `codex_novel.py` 负责小说读取、场景抽取、临时 Markdown、novel 总 trace 和任务级日志；对 `codex_pic.py` 做最小兼容改造，让 novel 可以指定图片输出目录和文件名前缀，同时保持 `codex pic` 默认行为不变。CLI 新增 `beartools codex novel <input_path> --n 4`，支持 `.txt` 和 `.md`，并透传 `--size`、`--quality`、`--output-format`。

## Grill Gate

问题：`novel` 生成的图片是否必须全部归档到一个独立 novel 目录，还是可以沿用 `codex pic` 的 `output/pic/<prompt stem>/` 输出契约？

推荐答案：按用户最新要求，`novel` 不沿用 `output/pic/<prompt stem>/` 分散目录。提示词、图片和 trace log 统一放到 `output/novel/stem_<input_stem>/`，其中 `<input_stem>` 是输入文件名去掉后缀的部分。为避免破坏现有 `codex pic`，只给图片业务层增加可选输出路径能力。

用户确认结论：用户已确认输出路径应为 `output`，并进一步要求提示词、图片和 trace log 统一放到 `output/novel/stem_<input_stem>/`；仍需确认该输出契约下的完整计划和 Verify 标准。

## 影响范围

- 新增业务模块：`src/beartools/codex_novel.py`
  - 读取 txt/md，限制前 10000 字。
  - 校验 `n`，默认 4，范围为 `1 <= n <= 12`。
  - 调用文本模型抽取场景和图片提示词。
  - 场景 JSON 解析失败时自动重试 1 次，第二次仍失败则写 trace 并退出 1。
  - 写入 `output/novel/stem_<input_stem>/scene_001.md` 等 prompt 文件和总 trace。
  - 场景拆分出的 `pic_prompt` 必须在 console 和 log 中记录，便于真实验收时直接查看模型拆分结果。
  - `scene_001.md` 只写最终 `pic_prompt`；标题、摘要、角色锚点、环境、构图等结构化信息写入总 trace 和 `summary.md`。
  - `summary.md` 同时列出 scene prompt、图片、trace 路径，并对成功图片使用相对路径嵌入预览。
  - 重复运行同一输入时默认覆盖 `output/novel/stem_<input_stem>/` 下本命令管理的 scene prompt、trace 和图片文件。
  - 受限并发调用图片生成能力，输出 `scene_001.<format>`、`scene_001.trace.log` 等文件到同一 novel 目录；并发语义复用 `picbatch` 的逻辑，默认最多同时生成 2 张。
  - 场景抽取少于 `n` 时允许继续生成已有场景，但最终结果标记为部分成功，CLI 退出码为 1。
  - 图片生成采用 best-effort：单个场景失败时记录错误并继续生成后续场景，最终结果汇总成功和失败项。
  - console 和 logger 均记录开始、读取、抽取、逐图生成、成功、失败阶段。
- 修改图片业务：`src/beartools/codex_pic.py`
  - 为图片生成增加可选输出目录/文件名前缀能力，或抽出可复用 helper。
  - 保持 `beartools codex pic`、`picbatch`、`picedit` 现有默认输出路径和 CLI 行为不变。
- 修改 CLI：`src/beartools/commands/codex/command.py`
  - 注册 `novel` 子命令。
  - 捕获 `RuntimeError`、`FileNotFoundError`、`ValueError`、`NotImplementedError`，按现有命令风格输出错误并 `typer.Exit(1)`。
  - best-effort 生成完成后若存在任何失败项，仍打印成功/失败汇总和已生成产物，但最终以 `typer.Exit(1)` 退出。
  - 成功后输出 novel 结果目录、每张图片路径和 trace 路径，并播放系统提示音。
- 修改测试：`tests/test_codex_command.py`
  - 新增 novel CLI 参数、默认 n、错误输出和成功输出测试。
  - 新增业务层单元测试，覆盖 txt 截断、scene prompt 写入、图片生成调用和 trace/log 关键字段。
- 可能修改文档：`docs/codemap.md`
  - 文档同步阶段补充 `codex_novel.py` 和 `beartools codex novel` 调用链。
  - 如确认历史 `out/pic` 已过期，修正为当前代码实际的 `output/pic`。

## TDD/测试策略

Test Writer 阶段先写失败测试：

1. CLI 注册与默认参数：
   - `beartools codex novel novel.txt` 调用 `run_codex_novel(input_path=..., n=4, size=None, quality=None, output_format=None)`。
   - `beartools codex novel novel.md` 同样进入 novel 流程。
   - `--n 2 --size 1536x1024 --quality medium --output-format webp` 能正确透传。
2. 输入校验：
   - 文件不存在时报错。
   - 输入不是文件时报错。
   - 后缀不是 `.txt` 或 `.md` 报错。
   - `n < 1` 或 `n > 12` 报错。
3. 业务流程：
   - 读取内容超过 10000 字时，只传给场景抽取模型前 10000 字。
   - 场景抽取返回不可解析 JSON 时自动重试 1 次；第二次仍失败时写入原始输出和错误，CLI 退出码为 1，且不进入图片生成。
   - 场景抽取返回少于 `n` 个有效提示词时，写 trace 后继续生成已有场景，最终 CLI 退出码为 1。
   - 正常场景会写 `output/novel/stem_<input_stem>/scene_001.md` 等 prompt 文件，scene Markdown 仅包含 `pic_prompt`，并调用图片生成能力 n 次。
   - 重复运行默认覆盖同名输出目录下本命令生成的文件，避免 prompt 迭代时旧结果干扰验收。
   - 返回结果包含 novel 输出目录、scene prompt 文件、图片文件和 trace 文件，且这些文件都位于同一 novel 目录。
   - 图片生成采用 best-effort；单图失败不阻断剩余场景，最终结果包含失败项、错误消息和对应 trace 路径；只要存在失败项，CLI 最终退出码为 1。
   - `codex pic` 的既有测试继续断言默认输出仍在 `output/pic/<stem>/`，防止回归。
4. 日志与 console：
   - 业务层用 logger 记录关键阶段。
   - 场景拆分出的每条 `pic_prompt` 必须输出到 console，并写入 log。
   - CLI 成功输出包含结果目录和每张图片路径。

如果模型抽取结构化输出实现细节导致红灯测试过度依赖 SDK 对象，则先用内部函数 mock，例如 `_select_novel_scenes_async()` 和 `run_codex_pic_async()`，保证测试聚焦业务契约。

## 最终 Prompt 策略与样本结论

新增模板 `prompts/codex_novel_scene_select.md`，用于把小说前 10000 字抽取为 `n` 个适合单张图片表达的场景。模板不写死题材风格，而是先根据文本自动推断时代、类型、视觉风格、禁用元素和主要角色锚点，再生成场景 JSON。

场景选择原则：

- 优先选择“单张图可表达”的瞬间，而不是纯剧情解释、长对话或心理活动。
- 拆分场景数量必须由命令参数 `n` 决定，prompt 中不得写死 4 组；默认 `n=4` 时才按通用组图节奏选择：地点/身份建立、核心矛盾或重要信息、处境变化或转折、冲突高潮或下一段剧情入口。
- 每个场景必须包含清晰主体、人物关系、动作/姿态、地点、道具、氛围和构图建议。
- 对话密集、低动作文本也要能选图，重点锁定递证明、翻档案、打开文件袋、送信、符纸、门口对视等可视化瞬间。
- `pic_prompt` 控制在约 80 到 180 个中文字，只保留做图必需信息，并给现有 `codex_pic_refine` 留出二次精修空间。
- `scene_00x.md` 只写最终 `pic_prompt`；完整结构化信息写入总 trace 和 `summary.md`，避免污染图片生成输入。

JSON 输出要求：

- 只返回 JSON 数组，不返回 Markdown 代码块、解释文字或编号列表。
- 数组长度必须等于命令参数 `n`。
- 每个对象必须包含 `title`、`source_summary`、`visual_moment`、`characters`、`environment`、`composition`、`mood`、`pic_prompt`。
- `pic_prompt` 必须是单行中文字符串，不包含换行、编号或额外注释。
- 如果返回被代码块包裹，代码实现可剥离后解析；JSON 不可解析时自动重试 1 次；字段缺失、第二次仍不可解析或没有任何有效场景时抛出清晰错误，并把原始返回写入 novel 总 trace。

样本校准结论：

- `input/novel1.md`：古典水浒/江湖动作片段。`n=4` 验收参考覆盖败寺山门、槐树酒肉对峙、松林遇史进、石桥决战；实际输出数量必须跟随参数 `n`，并避免把“飞天夜叉”“生铁佛”画成真实妖怪或金属佛像。
- `input/novel2.md`：1950 年代四九城/年代现实片段。`n=4` 验收参考覆盖递出烈士后代证明、军管会档案噩耗、打开遗产文件袋、进入南锣鼓巷 95 号院；实际输出数量必须跟随参数 `n`，且不得继承 `novel1` 的宋代、水浒、禅杖、朴刀、古装打斗风格。
- `input/novel3.md`：古典仙侠/文气小镇送信片段。`n=4` 验收参考覆盖福禄街青石板与卢家门首、桃叶巷老人与黄雀、算命摊黄纸符、乡塾旭日先生；实际输出数量必须跟随参数 `n`，并保留小镇、青石板、桃树、黄雀、符纸、竹林、书声和旭日等意象，不要强行制造打斗或现代化场景。

真实验收时若图片跑偏，优先调整 `prompts/codex_novel_scene_select.md` 的风格推断、角色锚点、禁用元素和组图节奏，不优先改业务代码。

## Verify 标准

最小验证命令：

```bash
uv run pytest tests/test_codex_command.py -xvs
uv run ruff check src/beartools/codex_novel.py src/beartools/commands/codex/command.py tests/test_codex_command.py
uv run mypy src/beartools/codex_novel.py src/beartools/commands/codex/command.py
```

完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

人工验收：

- `uv run beartools codex novel --help` 能看到子命令说明和 `--n` 默认值。
- 使用 fake/stub 测试不访问真实模型和图片接口。
- 必须增加 `input/novel1.md` 的实际端到端验收：运行 novel 命令后不报错，图片可以正常生成，数据能正常写入 `output/novel/stem_novel1/`，目录内至少包含抽取出的 scene prompt、单图 trace log 和生成图片结果。
- 必须增加 `input/novel2.md` 的 prompt 质量验收：确认 scene prompt 能落盘到 `output/novel/stem_novel2/`，且不继承 `novel1` 的水浒/古装/打斗风格；场景应覆盖身份核验、噩耗、遗产、四合院入口等年代文画面。若执行真实图片生成，则图片和 trace log 也必须写入同一目录。
- `input/novel3.md` 仅作为 Planner 阶段 prompt 策略校准样本，不纳入本轮必跑 Verify。
- 真实端到端验收依赖用户本地 `config/beartools.yaml` 中 `codex.base_url`、`codex.api_key`、`codex.model`、`codex.pic_model` 可用；用户已说明图片可以正常生成且没有报错，因此本轮 Verify 必须执行该实际验收。

完成标准：

- 新测试先红灯，随后实现通过。
- 最小验证和完整验证通过，或明确说明环境/凭据导致的不可运行项。
- `input/novel1.md` 的实际端到端写入验收通过，且图片生成成功、命令无报错。
- `input/novel2.md` 的 prompt 质量验收通过，能证明模板不会过拟合 `novel1` 的古典打斗风格。
- `input/novel3.md` 的低动作、高意境样本结论已纳入 prompt 策略，但不作为本轮 Verify 门禁。
- console 和 log 均覆盖关键流程阶段。
- 总 trace 不落真实图片 base64。

## 分步实施计划

1. Test Writer：在 `tests/test_codex_command.py` 写 CLI 和业务流程测试，先运行最小测试确认红灯。
2. Executor 第一层：新增 `src/beartools/codex_novel.py` 的数据结构、输入校验、txt/md 截断和 `output/novel/stem_<input_stem>/` 输出路径解析。
3. Executor 第二层：实现场景抽取函数，使用现有 Codex 文本配置和 Agents SDK，要求返回结构化 JSON 或可解析文本；失败时写总 trace 和 log。
4. Executor 第三层：对 `codex_pic.py` 做最小兼容改造，使图片生成可指定输出目录和文件名前缀，现有默认路径不变。
5. Executor 第四层：写 scene Markdown prompts，把拆分出的 `pic_prompt` 输出到 console 和 log，然后受限并发生成图片和单图 trace，全部聚合在 novel 输出目录。
6. Executor 第五层：在 `commands/codex/command.py` 注册 `novel` 子命令，保持现有 CLI 风格。
7. Verify：先跑最小验证，再跑完整验证。
8. Reviewer：按 `docs/checklists/review.md` 审查 diff；如涉及配置、外部调用和输出文件，再参考 `docs/checklists/audit.md`。
9. Documentation Sync：更新本计划实际结果，必要时更新 `docs/codemap.md`。

## 风险、回滚和需要用户确认的问题

风险：

- 场景抽取模型可能返回非 JSON 或少于 `n` 个场景，需要实现稳健解析和清晰错误。
- 用户已确认 JSON 解析失败时自动重试 1 次，第二次失败才退出 1。
- 用户已确认抽取数量少于 `n` 时仍生成已有场景，但必须在 console 和 trace 中标记缺口，并最终退出 1。
- 用户已确认重复运行默认覆盖同名输出目录；实现时只覆盖本命令管理的文件，避免误删用户手工放入的其他文件。
- 用户已确认 `scene_00x.md` 只写 `pic_prompt`，结构化调试信息写入总 trace 和 `summary.md`。
- 用户已确认 `summary.md` 同时嵌入图片并列出路径；失败项列出错误原因，不嵌图。
- 用户新增要求：拆分出的 prompt 需要 console 和 log 输出。
- 用户新增要求：图片绘制走 picbatch 风格的受限并发逻辑，默认最多同时 2 张。
- 真实图片生成耗时长，`n` 越大越慢；先串行实现更容易追踪失败，后续再考虑并发。
- 用户已确认 `n` 范围限制为 `1 <= n <= 12`，避免误传超大任务导致耗时和成本失控。
- 图片生成采用 best-effort 后，命令可能出现“部分成功”。CLI 必须清晰展示成功/失败数量，并在 trace 中记录每个失败场景，避免用户误以为全部成功。
- best-effort 下部分失败最终退出码为 1；自动化脚本能识别未完全成功，但用户仍可使用已生成图片和 trace 继续排查。
- 小说内容可能含敏感或不适合生成图片的场景，实际图片 API 可能拒绝；失败应在总 trace 和单图 trace 中体现。
- 现有 `run_codex_pic_async()` 自带 prompt refine，因此 novel 阶段只做“把小说片段变成简洁做图输入”，不直接生成最终精修提示词，避免重复职责。
- 修改 `codex_pic.py` 时必须保持现有默认输出路径不变，否则会影响已有 `pic` 和 `picbatch` 用户。

回滚：

- 删除 `src/beartools/codex_novel.py`。
- 回退 `src/beartools/codex_pic.py` 的可选输出路径改造。
- 移除 `commands/codex/command.py` 中 `novel` 注册和导入。
- 删除对应测试和 `docs/codemap.md` 增量说明。

需要用户确认：

1. 是否接受推荐输出契约：提示词、图片和 trace log 统一放到 `output/novel/stem_<input_stem>/`，其中 `<input_stem>` 是输入文件名去掉后缀的部分。
2. 输入格式已确认：本轮只支持 `.txt` 和 `.md`。
3. 抽取数量不足策略已确认：允许少于 `n`，生成已有场景，但最终 CLI 退出码为 1。
4. JSON 解析失败策略已确认：自动重试 1 次，第二次仍失败则写 trace 并退出 1。
5. 重复运行策略已确认：默认覆盖 `output/novel/stem_<input_stem>/` 下本命令管理的文件。
6. `n` 范围已确认：`1 <= n <= 12`。
7. scene prompt 文件内容已确认：`scene_00x.md` 只写最终 `pic_prompt`。
8. summary 文件已确认：写 `summary.md`。
9. `summary.md` 内容已确认：嵌入成功图片并列出 scene prompt、图片、trace 路径；失败项列出错误原因。
10. 拆分 prompt 输出已确认：每条 `pic_prompt` 输出到 console 和 log。
11. 图片生成并发策略已确认：复用 picbatch 风格的受限并发逻辑，默认最多同时 2 张。
12. 图片生成失败策略已确认：采用 best-effort，单图失败继续后续场景，最终汇总成功和失败项；只要存在失败项，CLI 退出码为 1。
13. 是否确认本轮 Verify 标准：先跑 `tests/test_codex_command.py`、局部 ruff/mypy，再跑完整 `pytest/ruff/mypy`，并增加 `input/novel1.md` 的实际端到端验收，以及 `input/novel2.md` 的 prompt 质量验收。
