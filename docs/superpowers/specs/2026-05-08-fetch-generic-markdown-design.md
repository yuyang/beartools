# 未知域名 Markdown 抓取设计

## 背景

当前 `fetch` 能力仅对 `weixin.qq.com`、`mp.weixin.qq.com`、`x.com` 与 `twitter.com` 做了专用分发。
当用户传入其他域名时，`fetch_handler_factory()` 会直接抛出 `ValueError("暂不支持域名")`，导致命令无法继续执行。

本次需求要求：对于未知域名，不再直接报“不支持”，而是使用 `opencli` 直接下载内容，并转换为 Markdown 文件写入输出目录。

目标示例为：`fetch https://newsnow.busiyi.world/`。

## 目标

- 保留微信与 X/Twitter 的现有专用处理逻辑
- 为未知域名增加通用 Markdown 下载能力
- 下载结果必须落盘为 `.md` 文件
- 继续复用现有 `FetchResult` 返回结构与 CLI 输出行为

## 非目标

- 不重构现有微信处理器图片内嵌流程
- 不修改 X/Twitter 处理器的现有文件命名策略
- 不引入新的下载后上传逻辑
- 不为未知域名新增浏览器渲染、正文抽取或 HTML-to-Markdown 自研实现

## 方案对比

### 方案一：未知域名继续报错

- 优点：实现成本最低
- 缺点：不满足当前需求

该方案直接排除。

### 方案二：所有域名统一改成 opencli 通用下载

- 优点：处理器数量更少
- 缺点：会破坏微信当前的图片内嵌输出，也会影响 X/Twitter 现有落盘行为

该方案风险较高，不采用。

### 方案三：保留专用处理器，未知域名走通用 fallback（推荐）

- 优点：改动范围最小，兼容现有行为，便于测试
- 缺点：`fetch.py` 中会新增一个通用处理器类

本次采用该方案。

## 设计

### 处理器分发

`fetch_handler_factory()` 继续保持以下分发规则：

- 微信域名：返回 `WeixinFetchHandler`
- `x.com` / `twitter.com`：返回 `XDotComFetchHandler`
- 其他域名：返回新的通用处理器

这样可以确保已有域名的行为保持不变，仅为未知域名补充默认能力。

### 通用处理器职责

新增 `GenericMarkdownFetchHandler`，职责如下：

1. 复用 `BaseFetchHandler` 的目录准备逻辑
2. 调用 `opencli` 的通用 Markdown 下载能力
3. 将结果写入 `data/format/<url_id>/` 目录下的 `.md` 文件
4. 返回 `FetchResult`
5. 失败时抛出 `RuntimeError`，并尽量保留命令输出，便于 CLI 直接展示

### 文件输出约定

未知域名的 Markdown 结果需要稳定落盘，优先保证可预期和可测试，因此文件命名采用：

- 成功：`<url_id>.md`
- 失败：仍写入 `<url_id>.md`，内容包含原始 URL 与错误信息

这样可以避免依赖页面标题、正文前缀或命令输出片段命名，减少不稳定因素。

### 命令调用约定

已确认用户要求使用 `opencli` 的“直接下载成 markdown”能力。

因此实现层面遵循以下原则：

- 只封装 `opencli` 调用，不在项目内实现 HTML 转 Markdown
- 命令成功时，将产物整理到 `format_dir`
- 命令失败时，将失败信息写入目标 `.md` 文件后抛错

具体参数会在实现与测试阶段按项目内可执行环境验证后定稿。

## 数据流

1. CLI 调用 `fetch_url(url)`
2. `fetch_handler_factory(url)` 根据域名返回处理器
3. 若为未知域名，则返回 `GenericMarkdownFetchHandler`
4. 处理器准备下载目录与输出目录
5. 调用 `opencli` 生成 Markdown 内容
6. 将 Markdown 内容写入 `format_dir` 下的 `.md` 文件
7. 返回 `FetchResult`
8. CLI 输出下载目录、Markdown 输出目录与成功信息

## 错误处理

- `opencli` 未安装：抛出 `FileNotFoundError("未找到 opencli 命令，请确认已安装")`
- 命令超时：抛出 `TimeoutError("命令执行超时（超过5分钟）")`
- 命令返回失败：写入失败 Markdown 文件后抛出 `RuntimeError`

错误处理方式与 X/Twitter 处理器保持一致，便于 CLI 复用现有异常分支。

## 测试策略

本次实现采用 TDD，先补测试再实现：

1. 增加 `fetch_handler_factory()` 对未知域名返回通用处理器的测试
2. 增加未知域名成功抓取并写入 Markdown 文件的测试
3. 增加未知域名抓取失败时写入错误 Markdown 并抛出 `RuntimeError` 的测试
4. 保留现有微信与 X/Twitter 测试，确保回归不受影响

端到端验证目标为：

- 运行 `fetch https://newsnow.busiyi.world/`
- 验证命令不再因“不支持域名”失败
- 验证 `data/format/<url_id>/` 下产生 Markdown 文件

## 影响文件

- 修改：`src/beartools/fetch.py`
- 修改：`tests/test_fetch.py`
- 新增：`docs/superpowers/specs/2026-05-08-fetch-generic-markdown-design.md`

## 风险与约束

- 当前执行环境尚未确认 `uv` 与 Python 3.13 可直接使用，端到端命令需要在项目可用环境中验证
- `opencli` 的通用 Markdown 下载命令参数需要以实际工具行为为准
- 如果 `opencli` 输出的是文件而非 stdout，需要在实现时补充文件归集逻辑，但不改变本设计目标
