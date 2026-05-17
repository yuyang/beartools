# beartools CodeMap

生成时间：2026-05-09

## 1. 项目定位

`beartools` 是一个 Python 3.13+ 的个人工具集合，使用 `uv` 管理依赖，通过 Typer 暴露 `beartools` 命令行入口。当前主要能力包括账单归一化与分析、Prompt 可靠性检查、网页内容抓取、思源笔记操作、Markdown 图片内嵌、Codex Markdown/图片任务、Gmail 摘要、NewsNow 抓取、记录管理、环境健康检查和 CLI 记忆日记。

## 2. 顶层目录

```text
.
├── src/beartools/              # 主要源码
│   ├── cli.py                  # Typer 顶层 CLI 入口
│   ├── commands/               # 命令行适配层
│   ├── bill/                   # 账单归一化、分析和状态映射
│   ├── llm/                    # LLM 节点运行时与模型工厂
│   ├── memory/                 # CLI 命令记忆与日总结
│   ├── prompt/                 # Prompt 模板加载和渲染
│   ├── config.py               # 配置加载与校验
│   ├── logger.py               # 日志初始化与重载
│   ├── fetch.py                # URL 抓取业务逻辑
│   ├── markdown.py             # Markdown 图片内嵌与 URL 提取
│   ├── siyuan.py               # 思源笔记 API 封装
│   ├── record.py               # SQLite URL 记录管理
│   ├── codex.py                # Codex Markdown 任务执行
│   ├── codex_pic.py            # Codex 图片生成/编辑/批处理
│   ├── gmail.py                # Gmail 拉取与摘要生成
│   └── newsnow.py              # NewsNow 本地浏览器抓取
├── tests/                      # 单元测试
├── prompts/                    # LLM Prompt 模板
├── config/                     # 配置样例和状态映射
├── docs/                       # 代码地图、计划归档、工作流、检查清单
├── skills/                     # 项目内技能说明
├── scripts/                    # 辅助脚本
├── pyproject.toml              # 项目、依赖、ruff、mypy 配置
└── uv.lock                     # 锁文件
```

## 3. CLI 入口地图

入口脚本在 `pyproject.toml` 中声明：

```text
beartools = "beartools.cli:_main_wrapper"
```

`src/beartools/cli.py` 负责注册所有命令，并通过 `_main_wrapper()` 捕获 beartools 命令的 argv、console 输出、退出码和当前命令 help，追加写入 `memory/day/YYYY-MM-DD.md`。单次命令记忆失败不改变原命令退出码。

| 命令 | 命令模块 | 业务模块 | 说明 |
| --- | --- | --- | --- |
| `beartools doctor` | `commands/doctor/command.py` | `commands/doctor/checks/*`、`llm/runtime.py` | 并发执行健康检查，默认检查网络、opencli，可选 LLM |
| `beartools model check` | `commands/model/command.py` | `model_check.py`、`llm/runtime.py` | 对配置中的所有 LLM 模型执行选择题评测，输出正确率报告 |
| `beartools check prompt` | `commands/check/command.py` | `commands/prompt/command.py`、`prompt/checker.py`、`prompt/manager.py` | 静态检查 `prompts/*.md` 和已知动态 prompt 的输出契约 |
| `beartools check eval` | `commands/check/command.py` | `commands/prompt/command.py`、`prompt/evaluator.py`、`prompt/manager.py`、`llm/factory.py` | 读取用户显式指定 YAML，用 small/large tier 运行 Prompt golden eval |
| `beartools clear` | `commands/clear/command.py` | 无独立业务模块 | 清理临时目录内容 |
| `beartools siyuan` | `commands/siyuan/command.py` | `siyuan.py` | 列笔记本、导出 Markdown、上传 Markdown |
| `beartools record` | `commands/record/command.py` | `record.py` | 查询 SQLite URL 记录 |
| `beartools markdown` | `commands/markdown/command.py` | `markdown.py` | 将 Markdown 本地图片转为 base64 data URI |
| `beartools bill` | `commands/bill/command.py` | `bill/*` | 账单归一化、分析、完整流水线 |
| `beartools fetch` | `commands/fetch/command.py` | `fetch.py`、`markdown.py`、`siyuan.py` | 抓取 URL 内容，生成 Markdown，可上传思源 |
| `beartools gmail` | `commands/gmail/command.py` | `gmail.py` | 拉取 Gmail 收件箱并生成摘要；发送纯文本邮件 |
| `beartools newsnow` | `commands/newsnow/command.py` | `newsnow.py` | 通过本地浏览器抓取 NewsNow 可见卡片 |
| `beartools codex` | `commands/codex/command.py` | `codex.py`、`codex_pic.py` | 执行 Codex Markdown、图片生成、图片编辑、批量图片任务 |
| `beartools diary summary` | `commands/diary/command.py` | `memory/service.py`、`prompts/cli_daily_summary.md`、`llm/factory.py` | 使用 large 模型把某天 `memory/day/YYYY-MM-DD.md` 总结为 `memory/summary/YYYY-MM-DD.md` |
| `beartools diary append` | `commands/diary/command.py` | `memory/service.py`、`prompts/cli_daily_summary.md`、`llm/factory.py` | 默认补齐本月 1 号到昨天已有 day 但缺失的 summary，默认不覆盖已有 summary |

`cli._main_wrapper()` 对 `beartools bill <input> <from>` 做了特殊处理：当 `bill` 后第一个参数不是已知子命令时，自动插入 `run`，所以 `beartools bill file.xlsx 2601-` 等价于 `beartools bill run file.xlsx 2601-`。

`cli._main_wrapper()` 也是 CLI 记忆系统入口：命令完成后用 small 模型根据 beartools 命令、CLI/console 显示信息和 help 生成单次记忆，写入 `memory/day/YYYY-MM-DD.md`。`diary` 命令自身也会进入 day 记忆。测试和冒烟验证可通过 `BEARTOOLS_MEMORY_ROOT` 指向临时目录。

## 4. 核心模块职责

### 配置与日志

- `config.py`
  - 定义 `LogConfig`、`DoctorConfig`、`SiyuanConfig`、`AgentConfig`、`GmailConfig`、`CodexConfig`、`Config` 等配置数据结构。
  - 使用 Dynaconf 读取 `config/beartools.yaml` 和环境变量。
  - 对 agent 节点、超时、API Key、extra headers、Gmail、Codex 图片配置做显式解析和校验。
  - 对外提供 `load_config()`、`get_config()`、`reset_config()`。
- `logger.py`
  - 基于配置初始化日志，默认写入 `log/`。
  - 支持简单配置和高级 logging 配置文件。
  - 对外提供 `get_logger()`、`shutdown_logging()`、`reconfigure()`。

### LLM 与 Prompt

- `llm/runtime.py`
  - 将配置中的 agent 节点转换为运行时节点池。
  - 对 `small`、`large` 两个 tier 做健康探测、去重、故障标记和轮换。
  - `openai` / `openrouter` 节点使用 OpenAI Responses API 探测；`anthropic` 节点使用 Anthropic Messages API 探测。
  - 对外提供 `get_active_llm_node()`、`mark_active_llm_node_failed()`、`get_llm_runtime()`。
- `llm/factory.py`
  - 只负责从 `large` / `small` 健康节点池中选择配置并构建 SDK client，不再依赖或返回 PydanticAI model。
  - `LLFactory.create_client()` / `create_async_client()` 按 `model`、`type=openai|openrouter|anthropic|any` 和 `model_size=small|large` 选择第一个匹配健康节点；`model` 同时匹配节点 `name` 和 `model`。
  - `create_client_for_node()` / `create_async_client_for_node()` 供 `model check` 等已经自己枚举节点的调用方按指定 `RuntimeNode` 构建 client。
  - `openai` / `openrouter` 构建 OpenAI 兼容 client；`anthropic` 构建 Anthropic client；client 的关闭由调用方负责。
- `llm/pydantic_openai.py`
  - 调用方侧 PydanticAI OpenAI Responses model 封装工具；需要结构化输出的业务模块拿到 OpenAI 兼容 client 后自行封装。
- `model_check.py`
  - 读取 `check/questions.yaml` 或指定 YAML/JSON 题库。
  - 支持用 `--id` 只测试指定题目 ID，用 `--model-name` / `-m` 只测试匹配的节点 name 或 model。
  - 遍历 `agent.large` 和 `agent.small` 中的去重模型节点，通过 `LLFactory.create_client_for_node()` 获取已选节点的 OpenAI 兼容 client，逐题调用 Responses API。
  - 只接受 `A` 到 `Z` 的单字母选择题答案，模型输出解释、标点或包装文本时判错。
  - 对外提供题库加载、进度与单题结果事件回调、单节点评测、完整评测和 Markdown 报告渲染。
- `prompt/template.py`
  - 将 `{{ variable }}` 风格模板转换为 Jinja2 模板。
  - 提取变量、渲染模板、在缺失参数时抛出明确异常。
- `prompt/manager.py`
  - 管理 `prompts/` 目录中的模板，提供缓存、加载、渲染和变量检查。
- `prompt/checker.py`
  - 收集 `prompts/*.md` 模板和已知动态 prompt，目前动态项包括 `model_check_question`、`gmail_summary`。
  - 静态检查输出格式、JSON 纯输出契约、小说分镜角色/风格锚点等规则。
  - 默认 warning 不阻断；`check prompt --strict` 会把 warning 当失败。
- `prompt/evaluator.py`
  - 读取用户显式指定的 eval YAML，格式为 `cases[].id`、`cases[].prompt`、`cases[].params`、`cases[].expect.json`。
  - 第一版只支持 `prompts/*.md` 模板，不支持代码内动态 prompt。
  - 模型输出必须是纯 JSON 对象，不自动剥离 Markdown 代码块或解释文字；`expect.json` 使用精确子集匹配。
  - `check eval` 必须显式传 `--tier small|large`，并通过 `LLFactory().create(tier=...)` 创建模型。

### CLI 记忆

- `memory/models.py`
  - 定义单次命令记忆输入、命令摘要器和日总结摘要器协议。
- `memory/prompts.py`
  - 只负责通过 `PromptManager` 渲染 `prompts/cli_command_memory.md` 和 `prompts/cli_daily_summary.md`，不硬编码完整 prompt 正文。
- `memory/service.py`
  - 计算 `memory/day/YYYY-MM-DD.md` 和 `memory/summary/YYYY-MM-DD.md` 路径。
  - 单次命令记忆追加写入 day 文件，保留模型摘要、退出码、help 摘要以及截断后的 console stdout/stderr。
  - 单次命令记忆使用 small 模型；`diary summary` 和 `diary append` 使用 large 模型。
  - `diary append` 只补齐缺失 summary，不覆盖已有 summary。

### 账单模块

- `bill/models.py`
  - 定义账单预览、字段映射、归一化行、状态映射、流水线结果、进度状态等数据结构。
- `bill/reader.py`
  - 读取 CSV/XLS/XLSX 输入，生成 preview，并返回原始行数据。
- `bill/agent.py`
  - 通过 LLM 解析账单结构、分析单行用途/归属人、解析部分退款金额。
  - 自行将 `LLFactory` 返回的 OpenAI 兼容 async client 封装为 PydanticAI Responses model；当前账单结构化输出不支持 Anthropic 节点。
- `bill/status_mapping.py`
  - 加载 `config/bill_status_mapping.yaml`，将原始交易状态映射为标准状态。
  - 支持交互确认后追加 exact mapping。
- `bill/service.py`
  - 账单业务主流程。
  - `normalize_bill_file()`：读取原始账单，识别结构，处理状态和金额，输出标准 Excel。
  - `analyze_bill_file()`：读取归一化 Excel，逐行分析用途/归属人，输出分析 Excel。
  - `run_bill_pipeline()`：串联归一化和分析。
- `bill/calculate_tool.py`
  - 提供安全的 Decimal 算术表达式计算，用于部分退款金额解析。

### 抓取、Markdown 与思源

- `fetch.py`
  - `fetch_handler_factory()` 根据 URL 选择处理器。
  - `WeixinFetchHandler` 处理微信文章抓取。
  - `XDotComFetchHandler` 处理 x.com/twitter.com。
  - `GenericMarkdownFetchHandler` 处理通用网页 Markdown 抽取。
  - `fetch_url()` 是异步业务入口，输出抓取目录、Markdown 目录和图片内嵌结果。
- `markdown.py`
  - `embed_images()` 批量处理 Markdown，把本地图片引用改成 base64 data URI。
  - `extract_urls_from_markdown()` 从 Markdown 文本提取 URL。
- `siyuan.py`
  - `SiyuanHandler` 封装思源笔记 API。
  - 支持列出 notebook、导出 Markdown、上传 Markdown。

### Codex 模块

- `codex.py`
  - 执行 Markdown 文件描述的 Codex 任务。
  - 解析 Codex 流式事件，写 final output 和 trace。
  - 内置 shell tool 执行器，支持命令超时和输出截断。
- `codex_pic.py`
  - 图片生成、图片编辑和批量生成业务。
  - 支持 prompt refine、尺寸/质量/格式归一化、trace 脱敏、token usage 提取。
  - 默认输出到 `out/pic/<stem>/` 或相关图片任务目录。

### 其他业务模块

- `gmail.py`
  - 构造 Gmail 查询，拉取邮件列表和详情，提取正文。
  - 调用 LLM 生成摘要，并写入 Markdown 文件。
  - 校验单个收件人邮箱，构造 Gmail API 纯文本 `raw` payload，并通过 `send_plain_text_email()` 发送邮件。
- `newsnow.py`
  - 通过 `opencli` / 本地浏览器能力抓取 NewsNow 当前可见卡片。
  - 将页面数据渲染为 Markdown。
- `record.py`
  - 基于 `aiosqlite` 管理 `data/record/beartools.db`。
  - 支持按 URL 查询、保存、标记、按更新时间查询最近记录。

## 5. 典型调用链

### 账单完整流程

```text
beartools bill <input> <from>
  -> cli._main_wrapper() 自动转为 bill run
  -> commands/bill/command.py::run_bill()
  -> bill/service.py::run_bill_pipeline()
  -> bill/service.py::normalize_bill_file()
       -> bill/reader.py 读取预览和数据
       -> bill/agent.py 识别字段结构
       -> bill/status_mapping.py 解析交易状态
       -> bill/service.py 写 normalized.xlsx
  -> bill/service.py::analyze_bill_file()
       -> bill/agent.py 分析每行用途和归属人
       -> bill/service.py 写 analysis.xlsx
```

### URL 抓取流程

```text
beartools fetch <url>
  -> commands/fetch/command.py::fetch()
  -> fetch.py::fetch_url()
  -> fetch.py::fetch_handler_factory()
       -> WeixinFetchHandler / XDotComFetchHandler / GenericMarkdownFetchHandler
  -> markdown.py::embed_images()
  -> 可选 siyuan.py::SiyuanHandler.upload_md()
```

### Codex 图片生成流程

```text
beartools codex pic <md_path>
  -> commands/codex/command.py::codex_pic()
  -> codex_pic.py::run_codex_pic()
  -> codex_pic.py::run_codex_pic_async()
       -> prompt/manager.py 读取 refine prompt
       -> openai image API 生成图片
       -> 写图片文件和 trace
```

### Doctor 健康检查流程

```text
beartools doctor [--run-llm]
  -> commands/doctor/command.py::doctor_command()
  -> commands/doctor/base.py::auto_discover_checks()
  -> commands/doctor/base.py::CheckRegistry
  -> commands/doctor/command.py::run_checks_stream()
       -> checks/google_ping.py
       -> checks/opencli.py
       -> checks/siyuan.py，可手动启用
       -> checks/llm.py，可选
```

### Prompt 可靠性检查流程

```text
beartools check prompt [--name <prompt>] [--strict]
  -> commands/check/command.py
  -> commands/prompt/command.py::check()
  -> prompt/checker.py::check_all_prompts()
       -> prompt/manager.py 收集 prompts/*.md
       -> 注册已知动态 prompt：model_check_question、gmail_summary
       -> 输出 pass/warning/error；strict 时 warning 也返回失败

beartools check eval <yaml_path> --tier small|large
  -> commands/check/command.py
  -> commands/prompt/command.py::eval_command()
  -> prompt/evaluator.py::load_prompt_eval_cases()
       -> prompt/manager.py 校验 prompt 模板存在并渲染 params
  -> prompt/evaluator.py::run_prompt_eval()
       -> LLFactory().create(tier=...)
       -> Pydantic AI Agent.run_sync()
       -> 解析纯 JSON 并做 expect.json 子集匹配
```

## 6. 测试地图

| 测试文件 | 覆盖重点 |
| --- | --- |
| `tests/test_cli_entrypoint.py` | 顶层 CLI 行为和入口注册 |
| `tests/test_doctor.py` | doctor 检查注册、执行、输出 |
| `tests/test_config.py` | 配置解析、默认值、错误处理 |
| `tests/test_logger.py` | 日志初始化和重配置 |
| `tests/test_record.py` | SQLite 记录管理 |
| `tests/test_markdown.py` | Markdown 图片内嵌和 URL 提取 |
| `tests/test_fetch.py` | URL handler 分发和抓取结果处理 |
| `tests/test_gmail.py` | Gmail 查询、正文提取、摘要写入 |
| `tests/test_prompt.py` | Prompt 模板变量和渲染 |
| `tests/test_prompt_checker.py` | Prompt 静态资产收集、规则检查和示例 eval YAML 存在性 |
| `tests/test_prompt_evaluator.py` | Prompt eval YAML 解析、纯 JSON 判定、子集匹配、失败继续汇总 |
| `tests/test_prompt_command.py` | Prompt CLI 注册、check/eval 命令、缺失 YAML 和 tier 参数 |
| `tests/test_llm_runtime.py` | LLM 节点池、探测、故障切换 |
| `tests/test_agent_factory.py` | LLM factory 和 provider/model 创建 |
| `tests/test_model_check.py` | 模型选择题评测、严格答案解析、报告渲染和 CLI 注册 |
| `tests/test_bill_service.py` | 账单归一化、分析、流水线 |
| `tests/test_bill_agent.py` | 账单 LLM agent 结构化输出 |
| `tests/test_bill_command.py` | 账单 CLI 命令适配层 |
| `tests/test_bill_status_mapping.py` | 状态映射加载、匹配、追加 |
| `tests/test_codex_command.py` | Codex 命令和图片命令 |
| `tests/test_clear.py` | 清理命令 |

README 中提到的 CLI 集成测试入口为 `tests/test_cli_integration_commands.py`，但当前文件列表中没有该文件；如果要恢复集成测试，需要先确认是否已移动、未提交或尚未创建。

## 7. 数据与输出位置

| 类型 | 默认位置 |
| --- | --- |
| 私有配置 | `config/beartools.yaml` |
| 配置样例 | `config/beartools.yaml.sample`、`config/beartools.secrets.yaml.sample` |
| Model Check 默认题库 | `check/questions.yaml` |
| Model Check 默认报告 | `output/report-YYYYMMDD-HHMMSS.md` |
| Prompt Eval 示例题库 | `check/prompts/bill-transaction-analysis-eval.yaml` |
| 日志 | `log/` |
| URL 记录数据库 | `data/record/beartools.db` |
| 账单输出 | `data/bill/*.normalized.xlsx`、`data/bill/*.analysis.xlsx` |
| Codex 图片输出 | `out/pic/<stem>/` |
| Prompt 模板 | `prompts/*.md` |

## 8. 变更落点速查

| 需求类型 | 优先查看/修改 |
| --- | --- |
| 新增 CLI 子命令 | `src/beartools/cli.py`、`src/beartools/commands/<name>/command.py` |
| 新增账单规则 | `bill/status_mapping.py`、`config/bill_status_mapping.yaml`、`bill/service.py` |
| 调整账单字段识别 | `prompts/bill_structure_identification*.md`、`bill/agent.py`、`bill/models.py` |
| 调整账单分析结果 | `prompts/bill_transaction_analysis.md`、`bill/agent.py`、`bill/service.py` |
| 新增 URL 抓取站点 | `fetch.py`、`commands/fetch/command.py`、`tests/test_fetch.py` |
| 调整思源上传/导出 | `siyuan.py`、`commands/siyuan/command.py` |
| 调整 Codex Markdown 执行 | `codex.py`、`commands/codex/command.py` |
| 调整 Codex 图片生成 | `codex_pic.py`、`prompts/codex_pic_refine.md`、`prompts/codex_picedit_refine.md` |
| 调整 LLM 节点策略 | `config.py`、`llm/runtime.py`、`llm/factory.py` |
| 调整模型选择题评测 | `model_check.py`、`commands/model/command.py`、`check/questions.yaml`、`tests/test_model_check.py` |
| 调整 Prompt 模板系统 | `prompt/template.py`、`prompt/manager.py`、`prompts/` |
| 调整 Prompt 可靠性检查 | `prompt/checker.py`、`prompt/evaluator.py`、`commands/prompt/command.py`、`check/prompts/*.yaml`、`tests/test_prompt_checker.py`、`tests/test_prompt_evaluator.py`、`tests/test_prompt_command.py` |
| 新增 doctor 检查项 | `commands/doctor/checks/<name>.py`，用 `register_check` 注册 |
| 调整日志行为 | `logger.py`、`config/beartools.yaml.sample` |

## 9. 当前注意点

- `pyproject.toml` 中依赖已全部固定为 `==`，符合项目规范；`requires-python` 使用 `>=3.13` 是允许的例外。
- 当前工作区已有多处未提交改动和未跟踪文件，新增功能前应先用 `git status --short` 区分用户改动与本次改动。
- README 提到的集成测试文件 `tests/test_cli_integration_commands.py` 当前不存在，文档与文件树存在不一致。
- `config/beartools.yaml` 是私有配置文件，生成文档或提交时不要泄露其中内容。
- 项目开启严格 mypy，并禁止显式 `Any`；新增代码时要尽量沿用现有 Protocol、TypedDict、dataclass/Pydantic 结构。
- 未来所有计划文档统一维护在 `docs/plans/`；`docs/superpowers` 下的一次性 plan/spec 已压缩为历史计划归档。
