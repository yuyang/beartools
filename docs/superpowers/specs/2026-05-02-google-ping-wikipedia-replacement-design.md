# Google Ping Wikipedia 替换设计文档

## 目标

修正 `beartools doctor` 中 `google_ping` 检查对 `x.com` 的误报问题。当前 `x.com` 在本机通过 `curl` 和 `urllib` 可访问，但使用项目现有的 `aiohttp` 检查方式会因为响应头过长而失败，导致 `doctor` 输出中出现误导性的 `x: 请求失败`。本次通过将默认检测目标从 `https://x.com/` 替换为 `https://www.wikipedia.org/`，降低误报概率，并保持“科学上网 HTTPS 连通性检查”的定位不变。

## 范围

本次只包含以下改动：

- 将 `google_ping` 默认 targets 列表中的 `https://x.com/` 替换为 `https://www.wikipedia.org/`。
- 将展示标签从 `x` 调整为 `wikipedia`。
- 同步更新配置样例中的默认 targets。
- 同步更新依赖默认 targets 和标签名的测试。

本次不包含以下改动：

- 不修改 `google_ping` 的并发执行方式。
- 不调整 `success_threshold` 默认值。
- 不引入新的 HTTP 客户端、请求头或代理逻辑。
- 不改变“请求成功即记为成功”的判定方式。
- 不处理用户自定义配置中的旧 `x.com` 目标，若用户手工配置仍保留 `x.com`，行为维持现状。

## 背景与根因

现有实现位于 `src/beartools/commands/doctor/checks/google_ping.py`，默认目标包含 Google、YouTube、Facebook、X、Instagram、Baidu 六个站点。实测中：

- `curl` 与 `urllib` 访问 `https://x.com/`、`https://twitter.com/` 都能得到有效 HTTP 响应；
- 项目当前 `aiohttp.ClientSession(timeout=..., trust_env=False)` 访问 `x.com/twitter.com` 时，会抛出 `Got more than 8190 bytes ... when reading Header value is too long.`；
- 因此 `doctor` 中的 `x` 失败不是域名写错，也不能直接说明网络不通，而是当前探测方式与该站点返回头的兼容性问题。

既然用户明确要求“直接替换 x”，则本次不在实现层面修复 `aiohttp` 与该站点的交互，而是换成更适合作为默认探测样本的被墙站点 `wikipedia.org`。

## 方案对比

### 方案一：直接替换 `x.com` 为 `wikipedia.org`（推荐）

- 优点：改动最小，能直接消除当前默认配置下的误报。
- 优点：不改变 `doctor` 的整体行为和阈值逻辑，风险低。
- 缺点：仍然沿用现有“只要拿到 HTTP 响应就算成功”的简单判定方式。

### 方案二：保留 `x.com`，但不计入成功阈值

- 优点：输出里还能看到 `x` 的探测结果。
- 缺点：复杂度上升，且会让默认目标与判定目标不一致，增加理解成本。

### 方案三：保留目标列表，只改 HTTP 实现

- 优点：理论上更彻底。
- 缺点：超出本次“直接替换 x”的范围，需要重新评估请求头、状态码、代理和客户端兼容性，改动面更大。

本次采用方案一。

## 设计

### 默认目标列表

将 `google_ping.py` 中的默认目标：

```python
"https://x.com/"
```

替换为：

```python
"https://www.wikipedia.org/"
```

其余默认目标保持不变，仍为 6 个目标，默认成功阈值仍为 3。

### 标签映射

`_label_for_target()` 当前通过域名子串映射短标签。这里将：

- `if "x.com" in target: return "x"`

替换为：

- `if "wikipedia.org" in target: return "wikipedia"`

这样 `doctor` 输出详情会从：

```text
x: 超时
```

变为：

```text
wikipedia: 超时
```

### 配置样例

更新 `config/beartools.yaml.sample` 中 `doctor.checks.google_ping.targets` 的默认示例值，使样例配置与代码默认值一致。

### 测试调整

现有测试对默认 targets 和标签名有显式耦合，因此需要同步更新：

1. `tests/test_doctor.py`
   - 默认结果明细中的 `x: ...` 改为 `wikipedia: ...`
   - fake mapping 中的 `https://x.com/` 改为 `https://www.wikipedia.org/`
   - `_label_for_target()` 的断言从 `x` 改为 `wikipedia`

2. `tests/test_config.py`
   - 配置解析测试中的默认 targets 列表改为包含 `https://www.wikipedia.org/`
   - sample yaml 校验同样改为 `https://www.wikipedia.org/`

不新增额外测试场景，因为本次只是替换默认目标，不改变控制流和异常分类逻辑。

## 数据流与行为影响

本次改动不改变 `google_ping` 的执行流程：

1. 读取配置；
2. 若用户未配置 targets，则使用代码默认 targets；
3. 并发请求各目标；
4. 汇总成功数量并输出 detail；
5. 成功数量达到阈值则通过，否则失败。

唯一变化是默认样本中的第四个目标从 `x.com` 变成 `wikipedia.org`，以及对应输出标签变化。

对用户的影响：

- 未自定义 `google_ping.targets` 的用户：后续默认会检测 Wikipedia，而不是 X。
- 已自定义 `google_ping.targets` 的用户：行为不变，本次不会迁移或覆盖已有配置。

## 错误处理

本次不新增错误处理分支，继续沿用现有 `_summary_for_error()` 分类逻辑。`wikipedia.org` 若超时、DNS 失败或 HTTPS 请求失败，仍按当前逻辑输出中文摘要。

## 测试与验证

实现完成后应验证：

- `tests/test_doctor.py` 相关单测通过；
- `tests/test_config.py` 相关单测通过；
- `uv run pytest tests/test_doctor.py tests/test_config.py -xvs` 通过；
- `uv run ruff check .` 通过；
- `uv run mypy .` 通过；
- 可选执行 `uv run beartools doctor`，确认输出中第四个目标变为 `wikipedia`。

## 风险与约束

- `wikipedia.org` 未来也可能改变响应行为，但从当前目标看，作为默认探测样本比 `x.com` 更稳妥。
- 本次不处理“用户显式把 `x.com` 配到 targets 里”时的误报问题，因为那属于自定义配置行为，不在本次范围内。
- 当前检查仍然没有基于状态码做更细粒度判定，这一限制保留到后续需求再处理。

## 结论

本次以最小改动方式，将 `google_ping` 默认目标中的 `x.com` 替换为 `wikipedia.org`，同步更新标签、配置样例和测试，解决默认 `doctor` 场景下 `x` 误报造成的困扰，同时避免引入额外的 HTTP 实现调整。
