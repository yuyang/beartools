# Google Ping Wikipedia Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `beartools doctor` 的 `google_ping` 默认目标中的 `x.com` 替换为 `wikipedia.org`，并同步更新标签、配置样例与测试，消除默认检查中的误报。

**Architecture:** 本次是一次最小范围替换，不改变 `google_ping` 的执行流程、并发模型、阈值或错误分类逻辑。先修改测试让它们表达新默认值，再修改 `google_ping.py` 与 `config/beartools.yaml.sample` 对齐，最后跑定向测试和静态检查验证没有回归。

**Tech Stack:** Python 3.13+, aiohttp, pytest, ruff, mypy

---

## File Structure

- Modify: `src/beartools/commands/doctor/checks/google_ping.py`
  - 替换默认 target URL，并把 `_label_for_target()` 的 `x` 映射改为 `wikipedia`。
- Modify: `config/beartools.yaml.sample`
  - 将样例配置中的默认 target 从 `x.com` 改成 `wikipedia.org`。
- Modify: `tests/test_doctor.py`
  - 更新默认 detail 断言、fake mapping 与标签断言。
- Modify: `tests/test_config.py`
  - 更新配置解析与 sample yaml 的默认 target 断言。

### Task 1: 先更新测试表达新的默认行为

**Files:**
- Modify: `tests/test_doctor.py`
- Modify: `tests/test_config.py`
- Test: `tests/test_doctor.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 先改 `tests/test_doctor.py` 的断言，写出失败测试**

```python
# tests/test_doctor.py
assert result.detail == "\n".join(
    [
        "google: 成功 200",
        "youtube: 成功 200",
        "facebook: 连接失败",
        "wikipedia: 连接失败",
        "instagram: 连接失败",
        "baidu: 连接失败",
    ]
)

mapping = {
    "https://www.google.com/generate_204": module._TargetCheckResult("google", True, "成功 204"),
    "https://www.youtube.com/": module._TargetCheckResult("youtube", True, "成功 200"),
    "https://www.facebook.com/": module._TargetCheckResult("facebook", True, "成功 200"),
    "https://www.wikipedia.org/": module._TargetCheckResult("wikipedia", False, "超时"),
    "https://www.instagram.com/": module._TargetCheckResult("instagram", False, "连接失败"),
    "https://www.baidu.com/": module._TargetCheckResult("baidu", False, "连接失败"),
}

assert result.detail == "\n".join(
    [
        "google: 成功 204",
        "youtube: 成功 200",
        "facebook: 成功 200",
        "wikipedia: 超时",
        "instagram: 连接失败",
        "baidu: 连接失败",
    ]
)

mapping = {
    "https://www.google.com/generate_204": module._TargetCheckResult("google", True, "成功 204"),
    "https://www.youtube.com/": module._TargetCheckResult("youtube", True, "成功 200"),
    "https://www.facebook.com/": module._TargetCheckResult("facebook", False, "DNS 解析失败"),
    "https://www.wikipedia.org/": module._TargetCheckResult("wikipedia", False, "超时"),
    "https://www.instagram.com/": module._TargetCheckResult("instagram", False, "连接失败"),
    "https://www.baidu.com/": module._TargetCheckResult("baidu", False, "连接失败"),
}

assert result.detail == "\n".join(
    [
        "google: 成功 204",
        "youtube: 成功 200",
        "facebook: DNS 解析失败",
        "wikipedia: 超时",
        "instagram: 连接失败",
        "baidu: 连接失败",
    ]
)

assert module._label_for_target("https://www.wikipedia.org/") == "wikipedia"
```

- [ ] **Step 2: 再改 `tests/test_config.py` 的默认 target 断言**

```python
# tests/test_config.py
assert google_ping.targets == [
    "https://www.google.com/generate_204",
    "https://www.youtube.com/",
    "https://www.facebook.com/",
    "https://www.wikipedia.org/",
    "https://www.instagram.com/",
    "https://www.baidu.com/",
]

assert google_ping["targets"] == [
    "https://www.google.com/generate_204",
    "https://www.youtube.com/",
    "https://www.facebook.com/",
    "https://www.wikipedia.org/",
    "https://www.instagram.com/",
    "https://www.baidu.com/",
]
```

- [ ] **Step 3: 运行定向测试，确认现在失败**

Run: `uv run pytest tests/test_doctor.py tests/test_config.py -xvs`
Expected: FAIL，失败点应来自实现和样例配置仍然保留 `x.com` / `x`，而不是测试语法错误。

- [ ] **Step 4: Commit**

```bash
git add tests/test_doctor.py tests/test_config.py
git commit -m "MOD: 更新 google_ping 默认目标测试"
```

### Task 2: 修改实现与样例配置让测试通过

**Files:**
- Modify: `src/beartools/commands/doctor/checks/google_ping.py`
- Modify: `config/beartools.yaml.sample`
- Test: `tests/test_doctor.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 修改 `google_ping.py` 中的默认目标和标签映射**

```python
# src/beartools/commands/doctor/checks/google_ping.py
DEFAULT_TARGETS: list[str] = [
    "https://www.google.com/generate_204",
    "https://www.youtube.com/",
    "https://www.facebook.com/",
    "https://www.wikipedia.org/",
    "https://www.instagram.com/",
    "https://www.baidu.com/",
]


def _label_for_target(target: str) -> str:
    """将目标域名映射为展示标签。"""
    if "google.com" in target:
        return "google"
    if "youtube.com" in target:
        return "youtube"
    if "facebook.com" in target:
        return "facebook"
    if "wikipedia.org" in target:
        return "wikipedia"
    if "instagram.com" in target:
        return "instagram"
    if "baidu.com" in target:
        return "baidu"
    return target
```

- [ ] **Step 2: 修改样例配置中的默认 target**

```yaml
# config/beartools.yaml.sample
doctor:
  checks:
    google_ping:
      timeout: 2
      fail_on_error: true
      success_threshold: 3
      targets:
        - "https://www.google.com/generate_204"
        - "https://www.youtube.com/"
        - "https://www.facebook.com/"
        - "https://www.wikipedia.org/"
        - "https://www.instagram.com/"
        - "https://www.baidu.com/"
```

- [ ] **Step 3: 运行定向测试，确认实现通过**

Run: `uv run pytest tests/test_doctor.py tests/test_config.py -xvs`
Expected: PASS，所有与 `google_ping` 默认目标、标签和 sample yaml 相关断言通过。

- [ ] **Step 4: Commit**

```bash
git add src/beartools/commands/doctor/checks/google_ping.py config/beartools.yaml.sample tests/test_doctor.py tests/test_config.py
git commit -m "MOD: 替换 google_ping 默认 x 检测目标"
```

### Task 3: 做最小范围验证并确认无静态检查回归

**Files:**
- Modify: `src/beartools/commands/doctor/checks/google_ping.py`
- Modify: `config/beartools.yaml.sample`
- Modify: `tests/test_doctor.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 运行 ruff 检查**

Run: `uv run ruff check .`
Expected: PASS，无新增 lint 问题。

- [ ] **Step 2: 运行 mypy 检查**

Run: `uv run mypy .`
Expected: PASS，无新增类型错误。

- [ ] **Step 3: 可选运行 doctor 做人工确认**

Run: `uv run beartools doctor`
Expected: 输出中的第四个目标不再是 `x`，而是 `wikipedia`；若网络正常，应看到类似 `wikipedia: 成功 200` 或其他明确结果。

- [ ] **Step 4: Commit**

```bash
git add src/beartools/commands/doctor/checks/google_ping.py config/beartools.yaml.sample tests/test_doctor.py tests/test_config.py
git commit -m "MOD: 验证 google_ping 默认目标替换"
```
