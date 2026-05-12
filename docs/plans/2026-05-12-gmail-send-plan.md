# Gmail Send TDD Plan

## 背景和目标

用户希望给现有 `beartools gmail` 命令增加 `send` 子命令：

1. CLI 依次询问收件人、标题和正文。
2. 收件人需要做邮箱格式检查。
3. 邮件只支持纯文本。
4. 发送能力不能只写在命令行层，后续也可以作为单独模块复用。

本轮按 `docs/workflows/codex-tdd-flow.md` 的商业开发流程执行：Planner 阶段只写计划文档，计划和 Verify 标准经用户确认后，再进入 Test Writer 和 Executor。

## 历史上下文

- `docs/codemap.md` 记录 `beartools gmail` 的 CLI 适配层在 `src/beartools/commands/gmail/command.py`，业务能力集中在 `src/beartools/gmail.py`。
- `docs/codemap.md` 记录 Gmail 当前能力是拉取 INBOX 邮件并生成摘要，相关测试集中在 `tests/test_gmail.py`。
- `docs/plans/2026-05-09-superpowers-docs-compression-plan.md` 记录 Gmail OAuth、邮件列表、正文提取和 Markdown 输出集中在 `gmail.py`，摘要逻辑不另起独立配置。
- 当前实现的 `SCOPES` 是 `https://www.googleapis.com/auth/gmail.readonly`，只能读取邮件；发送邮件需要新增 Gmail 发送权限。

## 非目标

- 不支持 HTML 邮件、附件、抄送、密送、回复、草稿箱或模板。
- 不新增数据库、持久化格式或后台任务。
- 不新增第三方依赖；邮箱格式检查优先使用标准库和轻量规则。
- 不把正文写入日志或测试快照，避免泄露用户邮件内容。
- 不在自动化测试中调用真实 Gmail API。

## Brainstorm 选项和推荐方案

### 方案 A：在 `gmail.py` 新增可复用发送函数，CLI 只负责交互

- 新增 `GmailSendInput` / `GmailSendResult` 数据结构。
- 新增 `validate_email_address()`、`create_plain_text_message()`、`send_plain_text_email()` 等业务函数。
- `send_plain_text_email()` 内部复用 `build_gmail_service()`，调用 Gmail API `users().messages().send(userId="me", body=...).execute()`。
- `commands/gmail/command.py` 新增 `send` 子命令，用 `typer.prompt()` 依次询问收件人、标题和正文。
- CLI 层只做输入循环、错误展示和成功提示，不拼 Gmail payload。

优点：模块边界清晰，后续可以从其他 Python 代码直接调用发送函数。

### 方案 B：只在命令层实现发送逻辑

- 在 `commands/gmail/command.py` 中完成输入、MIME 构造和 Gmail API 调用。

问题：后续复用困难，命令层会变胖，也不符合用户“后续可以作为单独模块使用”的目标。

### 方案 C：新增 `beartools/gmail_send.py` 独立模块

- 把发送能力放到新模块，读取摘要仍留在 `gmail.py`。

问题：当前 Gmail 相关能力都集中在 `gmail.py`，初版拆新模块会增加查找成本；等 Gmail 能力继续扩张时再拆更合适。

### 推荐方案

采用方案 A：发送业务放在 `src/beartools/gmail.py`，命令层只做交互和展示。这样最小改动、可测试、可复用，也符合现有模块边界。

## Grill Gate

问题 1：发送权限如何处理？

推荐答案：把 Gmail OAuth scope 从只读扩展为同时包含 `gmail.readonly` 和 `gmail.send`。这样保留现有 fetch 能力，同时支持发送。风险是已有 `config/gmail.token.json` 可能缺少新 scope，用户首次使用 send 时可能需要重新授权或删除旧 token 后重新登录。

用户确认结论：已确认。

问题 2：CLI 正文输入用单行还是多行？

推荐答案：初版 CLI 使用一次 `typer.prompt("内容")` 输入纯文本正文；用户输入中的字面量 `\n` 转换为真实换行，默认用户没有在正文中输入字面量 `\n` 的需求。模块函数本身接收任意字符串。

用户确认结论：已确认采用字面量 `\n` 转真实换行。

问题 3：收件人是否支持多个？

推荐答案：初版只支持单个收件人邮箱，符合“sendto什么人”的单数表述；多收件人、Cc、Bcc 后续再扩展。

用户确认结论：已确认。

## 影响范围

- `src/beartools/gmail.py`
  - 扩展 Gmail API protocol，增加 `messages().send()` 类型协议。
  - 扩展 `SCOPES`，加入 `https://www.googleapis.com/auth/gmail.send`。
  - 新增纯文本邮件构造、邮箱校验和发送函数。
- `src/beartools/commands/gmail/command.py`
  - 新增 `send` 子命令。
  - 依次提示收件人、标题、内容；邮箱不合法时提示并重新询问。
  - 捕获发送失败，写日志但不把正文打印到 console 或日志。
- `tests/test_gmail.py`
  - 增加邮箱校验、MIME payload、业务发送、CLI 交互和错误路径测试。
- `docs/codemap.md`
  - 功能完成后同步 Gmail 模块职责和 CLI 入口。
- 可选：`config/beartools.yaml.sample`
  - 发送复用现有 Gmail OAuth 配置，预计不需要新增配置。

## TDD/测试策略

先写测试，覆盖：

- `validate_email_address()` 接受常见合法邮箱，拒绝空值、缺少 `@`、缺少域名、含换行的输入。
- `create_plain_text_message()` 生成 Gmail API 需要的 base64url `raw` payload，解码后包含 `To`、`Subject` 和 `text/plain` 正文。
- `send_plain_text_email()` 调用 `build_gmail_service()` 后走 `users().messages().send(...).execute()`，返回 message id。
- `gmail send` 出现在 `beartools gmail --help`。
- CLI 依次询问收件人、标题、内容；邮箱错误时重新询问。
- CLI 成功时打印简短成功信息和 message id，不打印正文。
- CLI 失败时打印“发送失败，请查看日志文件”，不出现 traceback。

红灯策略：

- 当前没有 send 函数和命令，新增测试应先失败。
- 如果某些测试由于 patch 路径或 CLI runner 行为无法形成稳定红灯，记录原因并作为回归测试继续推进。

## Verify 标准

自动化最小验证命令：

```bash
uv run pytest tests/test_gmail.py tests/test_cli_entrypoint.py -xvs
uv run ruff check src/beartools/gmail.py src/beartools/commands/gmail/command.py tests/test_gmail.py
uv run mypy .
```

自动化完整验证命令：

```bash
uv run pytest tests/ -xvs
uv run ruff check .
uv run mypy .
```

冒烟端到端验证：

- 执行 mock 级 CLI 冒烟：通过 `CliRunner` 或测试内 fake service 验证 `gmail send` 的交互输入可以产生 Gmail API send 调用。
- 用户已确认允许真实发送到 `yuyang.liu@outlook.com`；自动化验证通过后，执行一次真实 Gmail 发送冒烟，标题和正文使用明确的测试内容。

全面端到端验证：

- 用户确认本轮不执行多分支真实全面端到端验证，只执行一次真实发送冒烟。
- 省略原因：多分支真实发送会额外产生真实邮件，且非法邮箱重试、payload 构造和 API 调用路径可由自动化测试覆盖。
- 剩余风险：真实邮箱可达性、收件侧反垃圾策略、OAuth 重新授权体验无法由 mock 测试完全覆盖。

## 分步实施计划

1. Planner：写入本计划文档，并等待用户确认计划和 Verify 标准。
2. Test Writer：新增 `tests/test_gmail.py` 中的 send 相关测试，运行最小 pytest，记录红灯或无法红灯原因。
3. Executor：按推荐方案实现 `gmail.py` 发送业务和 `gmail send` 命令。
4. Verify：运行最小验证命令；如果局部通过且风险可控，再运行完整验证命令。
5. Reviewer：按 `docs/checklists/review.md` 审查 diff；因为涉及外部邮件发送、OAuth scope 和用户内容，轻量参考 `docs/checklists/audit.md`。
6. Fix Loop：修复 verify/review 发现的问题并复测。
7. Documentation Sync：更新本计划最终状态；必要时更新 `docs/codemap.md`。

## 风险、回滚和需要用户确认的问题

风险：

- 新增 `gmail.send` scope 后，旧 token 可能权限不足，需要重新授权。
- 真实发送不可在自动化测试中安全执行，测试只能用 fake service 验证 payload 和调用路径。
- 邮箱格式校验不等同于邮箱可达性校验，只能阻止明显非法格式。
- 如果日志记录异常上下文不当，可能泄露邮件标题或正文；实现时只记录目标邮箱和错误类型，避免记录正文。

回滚：

- 从 `src/beartools/gmail.py` 移除 send 相关数据结构、函数和 `gmail.send` scope。
- 从 `src/beartools/commands/gmail/command.py` 移除 `send` 子命令。
- 删除 `tests/test_gmail.py` 中 send 相关测试。
- 如更新 `docs/codemap.md`，回滚对应 Gmail send 条目。

需要用户确认：

- 已确认扩展 OAuth scope 到 `gmail.send`，并接受必要时重新授权。
- 已确认初版 CLI 正文输入中的字面量 `\n` 转换为真实换行，业务函数支持任意纯文本字符串。
- 已确认初版只支持单个收件人。
- 已确认允许真实发送一封测试邮件到 `yuyang.liu@outlook.com`；全面端到端多分支真实发送省略。

## 最终实现记录

- `beartools gmail send` 已新增，交互顺序为 `sendto`、`title`、`内容`。
- CLI 会循环校验单个收件人邮箱，直到格式合法。
- CLI 会把正文输入中的字面量 `\n` 转换成真实换行。
- Gmail 发送业务已放在 `src/beartools/gmail.py`，可由其他模块直接调用 `send_plain_text_email(send_to=..., title=..., content=...)`。
- 纯文本邮件 payload 由 `create_plain_text_message()` 构造，使用 Gmail API 需要的 base64url `raw` 字段。
- OAuth scopes 已扩展为 `gmail.readonly` 和 `gmail.send`；旧 token 可能需要重新授权。
- Gmail 网络、OAuth 或 API 异常在 CLI 层统一提示 `Gmail 发送失败，请查看日志文件`，日志只记录收件人和错误类型，不记录正文。
- 旧 token refresh 出现 Google OAuth `invalid_scope` 时，`_load_credentials()` 会自动重新发起本地 OAuth 授权，授权成功后覆盖写回 `config/gmail.token.json`，不再要求用户手动移动 token 文件；网络/代理导致的 refresh 失败不会触发重新授权流程。

## 最终 Verify 结果

红灯：

- `uv run pytest tests/test_gmail.py tests/test_cli_entrypoint.py -xvs`：新增 `test_gmail_send_command_is_registered` 后先失败，原因是 `gmail send` 尚未注册，符合 TDD 红灯预期。

自动化验证：

- `uv run pytest tests/test_gmail.py tests/test_cli_entrypoint.py -xvs`：通过，27 passed。
- `uv run ruff check src/beartools/gmail.py src/beartools/commands/gmail/command.py tests/test_gmail.py`：通过。
- `uv run mypy .`：通过，58 source files。
- `uv run pytest tests/ -xvs`：通过，318 passed。
- `uv run ruff check .`：通过。

真实发送冒烟：

- 执行 `uv run beartools gmail send`，目标邮箱为 `yuyang.liu@outlook.com`。
- 第一次真实发送在 OAuth token 刷新阶段连接 `oauth2.googleapis.com` 超时，并暴露 CLI 没有收口第三方认证异常的问题；随后已修复为统一正常失败提示。
- 第二次真实发送仍因 Gmail/OAuth 网络不可用失败，但 CLI 只输出 `Gmail 发送失败，请查看日志文件`，没有 traceback，也没有输出正文。
- 因当前网络无法连通 Google OAuth，本轮未能证明真实邮件送达；已验证真实失败路径符合用户要求“gmail 本身是可能网络异常，正常提示用户就好了”。
- 用户要求再次执行端到端测试后，执行 `uv run beartools gmail send`，目标邮箱仍为 `yuyang.liu@outlook.com`。CLI 输出 `Gmail 发送失败，请查看日志文件`，没有 traceback，也没有输出正文；最新日志根因为 `RefreshError invalid_scope: Bad Request`，推断旧 token 缺少新增的 `gmail.send` scope，需要重新授权后才能继续验证真实送达。
- 后续修复为 `invalid_scope` 自动重新授权后，再次执行 `uv run beartools gmail fetch`：程序自动输出 Google OAuth 授权 URL，授权完成后 token 文件已写入 `gmail.readonly` 和 `gmail.send` 两个 scope。该次 fetch 后续失败点变为 LLM 摘要阶段 `ModelAPIError: Request timed out`，不再是 Gmail 授权问题。
- 使用新 token 再次执行 `uv run beartools gmail send`，目标邮箱 `yuyang.liu@outlook.com`，标题 `beartools gmail send after reauth 2026-05-12`，发送成功，Gmail API 返回 message id `19e1b9cb1f4d5ced`。
- 用户指出科学上网/网络异常不应触发重新授权流程后，已收窄判断：只有 `RefreshError` 文本包含 `invalid_scope` 时才重新授权；网络类 refresh 失败会原样失败并由 CLI 正常提示。新增回归测试 `test_load_credentials_does_not_fallback_to_oauth_for_refresh_network_error` 覆盖该边界。

## Review 结论

未发现阻塞性问题。

剩余风险：

- 真实 Gmail 发送仍依赖当前机器到 Google OAuth/Gmail API 的网络可达性。
- 新增 `gmail.send` scope 后，旧 `config/gmail.token.json` 可能没有发送权限；当前实现会在 refresh scope 失败时自动发起重新授权，但仍需要用户在浏览器中完成 Google OAuth。
- 邮箱校验只做格式检查，不保证邮箱真实存在或可达。

文档同步：

- 已更新 `docs/codemap.md`，补充 `beartools gmail` 支持发送纯文本邮件，以及 `gmail.py` 中可复用发送函数的职责。
