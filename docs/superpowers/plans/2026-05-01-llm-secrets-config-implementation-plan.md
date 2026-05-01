# LLM Secrets Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LLM `api_key` 与 `siyuan.token` 从主配置拆分到 `config/beartools.secrets.yaml`，并在主配置中用 Dynaconf `@get` 引用 secrets 路径，保持环境变量最高优先级覆盖。

**Architecture:** 变更集中在 `src/beartools/config.py`，通过 Dynaconf 多文件加载实现 `beartools.yaml + beartools.secrets.yaml + 环境变量` 的分层覆盖；对主配置中的敏感项做显式校验：`siyuan.token` 禁止出现，`agent.*.api_key` 仅允许 `@get ...` 引用，不允许明文。运行时与工厂层继续消费最终解析后的 `api_key`，不新增 secrets 读取职责。

**Tech Stack:** Python 3.13、Dynaconf、pytest、PyYAML、ruff、mypy

---

## 文件结构

- 修改：`src/beartools/config.py`
  - 责任：多文件配置加载、敏感字段校验、Dynaconf `@get` 引用约束、数据类转换。
- 修改：`src/beartools/siyuan.py`
  - 责任：更新 token 缺失时的提示文案，指向 secrets 文件或环境变量。
- 修改：`config/beartools.yaml.sample`
  - 责任：保留非敏感配置，并将 `agent.*.api_key` 改为 `@get ...` 示例。
- 创建：`config/beartools.secrets.yaml.sample`
  - 责任：提供 `siyuan.token` 与 `agent.xxx.key` 的 secrets 示例。
- 修改：`.gitignore`
  - 责任：忽略 `config/beartools.secrets.yaml`。
- 修改：`tests/test_config.py`
  - 责任：覆盖多文件加载、环境变量覆盖、主配置敏感字段校验、`@get` 引用解析、sample 校验。

### Task 1: 先用测试锁定新的配置加载行为

**Files:**
- Modify: `tests/test_config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 为测试类补一个 secrets 文件写入辅助方法**

```python
    def _write_secrets(self, content: str) -> Path:
        config_dir = Path("config")
        config_dir.mkdir(parents=True, exist_ok=True)
        secrets_path = config_dir / "beartools.secrets.yaml"
        secrets_path.write_text(content, encoding="utf-8")
        return secrets_path
```

- [ ] **Step 2: 写失败测试，覆盖主配置 `@get` + secrets 合并解析**

```python
    def test_load_config_merges_main_yaml_and_secrets_yaml(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "@get agent.openrouter.key"
    extra_headers: {}
    timeout_seconds: 30
siyuan:
  default_note: "note-1"
"""
        )
        self._write_secrets(
            """
siyuan:
  token: "secret-token"
agent:
  openrouter:
    key: "secret-key"
"""
        )

        config = load_config()

        assert config.siyuan.token == "secret-token"
        assert config.siyuan.default_note == "note-1"
        assert config.agent.primary.api_key == "secret-key"
```

- [ ] **Step 3: 运行单测确认先失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_load_config_merges_main_yaml_and_secrets_yaml -xvs`

Expected: FAIL，当前实现只加载 `beartools.yaml`，拿不到 `beartools.secrets.yaml` 中的 token/key。

- [ ] **Step 4: 写失败测试，覆盖环境变量高于 secrets 文件**

```python
    def test_env_overrides_secrets_yaml_for_agent_api_key(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "@get agent.openrouter.key"
"""
        )
        self._write_secrets(
            """
agent:
  openrouter:
    key: "secret-key"
"""
        )
        os.environ["BEARTOOLS_AGENT__OPENROUTER__KEY"] = "env-key"

        try:
            config = load_config()
        finally:
            os.environ.pop("BEARTOOLS_AGENT__OPENROUTER__KEY", None)

        assert config.agent.primary.api_key == "env-key"
```

- [ ] **Step 5: 运行单测确认先失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_env_overrides_secrets_yaml_for_agent_api_key -xvs`

Expected: FAIL，当前实现没有 secrets 分层，也不会验证新的覆盖路径。

- [ ] **Step 6: 写失败测试，覆盖主配置中禁止明文 `siyuan.token`**

```python
    def test_reject_plain_siyuan_token_in_main_yaml(self) -> None:
        self._write_config(
            """
siyuan:
  token: "plain-token"
"""
        )

        with pytest.raises(RuntimeError, match=r"siyuan\.token 属于敏感配置"):
            load_config()
```

- [ ] **Step 7: 运行单测确认先失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_reject_plain_siyuan_token_in_main_yaml -xvs`

Expected: FAIL，当前实现会直接接受主配置中的 `siyuan.token`。

- [ ] **Step 8: 写失败测试，覆盖主配置中禁止明文 `agent.primary.api_key`**

```python
    def test_reject_plain_agent_api_key_in_main_yaml(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "plain-key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.primary\.api_key 属于敏感配置"):
            load_config()
```

- [ ] **Step 9: 运行单测确认先失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_reject_plain_agent_api_key_in_main_yaml -xvs`

Expected: FAIL，当前实现会直接接受明文 `api_key`。

- [ ] **Step 10: 写失败测试，覆盖 `@get` 路径缺失时报错**

```python
    def test_reject_missing_get_target_for_agent_api_key(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "@get agent.missing.key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.primary\.api_key 引用的配置路径不存在"):
            load_config()
```

- [ ] **Step 11: 运行单测确认先失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_reject_missing_get_target_for_agent_api_key -xvs`

Expected: FAIL，当前实现没有 `@get` 目标存在性校验。

- [ ] **Step 12: 写失败测试，覆盖多个节点复用同一个 `@get` 引用**

```python
    def test_multiple_nodes_can_share_same_get_reference(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "@get agent.shared.key"
  candidates:
    - name: "backup"
      provider: "openrouter"
      base_url: "https://backup.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get agent.shared.key"
"""
        )
        self._write_secrets(
            """
agent:
  shared:
    key: "shared-secret"
"""
        )

        config = load_config()

        assert config.agent.primary.api_key == "shared-secret"
        assert config.agent.candidates[0].api_key == "shared-secret"
```

- [ ] **Step 13: 运行单测确认先失败**

Run: `uv run pytest tests/test_config.py::TestConfig::test_multiple_nodes_can_share_same_get_reference -xvs`

Expected: FAIL，在多文件与 `@get` 解析未完成前拿不到共享 key。

### Task 2: 在配置层实现多文件加载与敏感字段校验

**Files:**
- Modify: `src/beartools/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 为主配置原始内容增加单独读取与校验辅助函数**

```python
def _load_yaml_file(path: Path) -> object:
    if not path.exists():
        return {}
    import yaml

    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file)
    return {} if loaded is None else loaded


def _validate_main_config_sensitive_fields(main_config: object) -> None:
    config_dict = _as_dict(main_config, "config/beartools.yaml")

    siyuan_dict = _as_dict(config_dict.get("siyuan", {}), "siyuan")
    if "token" in siyuan_dict and str(siyuan_dict["token"]).strip():
        raise RuntimeError("siyuan.token 属于敏感配置，请改放到 config/beartools.secrets.yaml 或环境变量")

    agent_dict = _as_dict(config_dict.get("agent", {}), "agent") if config_dict.get("agent") is not None else {}
    primary_dict = _as_dict(agent_dict.get("primary", {}), "agent.primary") if agent_dict.get("primary") is not None else {}
    _validate_agent_api_key_reference(primary_dict, "agent.primary")

    candidates = _as_list(agent_dict.get("candidates", []), "agent.candidates") if "candidates" in agent_dict else []
    for index, candidate in enumerate(candidates):
        candidate_dict = _as_dict(candidate, f"agent.candidates[{index}]")
        _validate_agent_api_key_reference(candidate_dict, f"agent.candidates[{index}]")
```

- [ ] **Step 2: 实现 `api_key` 只能为 `@get ...` 的辅助校验**

```python
def _validate_agent_api_key_reference(node_dict: dict[str, object], path: str) -> None:
    if "api_key" not in node_dict:
        return
    api_key_value = node_dict["api_key"]
    if not isinstance(api_key_value, str) or not api_key_value.startswith("@get "):
        raise RuntimeError(f"{path}.api_key 属于敏感配置，请改为 @get 引用并将真实值放到 config/beartools.secrets.yaml 或环境变量")
```

- [ ] **Step 3: 扩展 `load_config()` 同时加载主配置与 secrets 配置**

```python
def load_config() -> Config:
    global _config_instance
    _ensure_config_dir()
    cwd = Path.cwd()
    config_path = cwd / "config" / "beartools.yaml"
    secrets_path = cwd / "config" / "beartools.secrets.yaml"

    main_config_raw = _load_yaml_file(config_path)
    _validate_main_config_sensitive_fields(main_config_raw)

    settings = _create_lazy_settings(
        envvar_prefix="BEARTOOLS",
        settings_files=[str(config_path), str(secrets_path)],
        load_dotenv=True,
        core_loaders=["YAML", "ENV"],
    )

    config = _convert_to_dataclass(settings)
    _validate_resolved_agent_api_keys(config)
    _config_instance = config
    return config
```

- [ ] **Step 4: 实现解析后 `api_key` 不得为空的最小校验**

```python
def _validate_resolved_agent_api_keys(config: Config) -> None:
    nodes = [config.agent.primary, *config.agent.candidates]
    for index, node in enumerate(nodes):
        if not _is_configured_node(node):
            continue
        if not node.api_key.strip():
            path = "agent.primary" if index == 0 else f"agent.candidates[{index - 1}]"
            raise RuntimeError(f"{path}.api_key 引用的配置路径不存在或解析结果为空")
```

- [ ] **Step 5: 更新模块文档字符串与 `load_config()` 注释**

```python
"""配置文件读取模块

读取当前工作目录下的 config/beartools.yaml 与 config/beartools.secrets.yaml，
支持 .env 文件和环境变量覆盖（BEARTOOLS_ 前缀）。
"""
```

- [ ] **Step 6: 运行本任务相关测试，确认转绿**

Run: `uv run pytest tests/test_config.py -k "merges_main_yaml_and_secrets_yaml or env_overrides_secrets_yaml_for_agent_api_key or reject_plain_siyuan_token_in_main_yaml or reject_plain_agent_api_key_in_main_yaml or reject_missing_get_target_for_agent_api_key or multiple_nodes_can_share_same_get_reference" -xvs`

Expected: PASS。

### Task 3: 更新 sample 文件、.gitignore 与提示文案

**Files:**
- Modify: `config/beartools.yaml.sample`
- Create: `config/beartools.secrets.yaml.sample`
- Modify: `.gitignore`
- Modify: `src/beartools/siyuan.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 修改主配置 sample，移除敏感值并改为 `@get` 示例**

```yaml
# 思源笔记配置
siyuan:
  default_note: "REPLACE_ME_NOTE_ID"
  notebook: "REPLACE_ME_NOTEBOOK_ID"
  path: "/REPLACE_ME_PATH"

# 智能体节点配置
agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://api.example.com/v1"
    model: "gpt-4.1-mini"
    api_key: "@get agent.openrouter.key"
    extra_headers: {}
    timeout_seconds: 30
  candidates:
    - name: "candidate-1"
      provider: "openrouter"
      base_url: "https://api-backup.example.com/v1"
      model: "gpt-4.1-mini"
      api_key: "@get agent.zhizengzeng.key"
      extra_headers: {}
      timeout_seconds: 30
```

- [ ] **Step 2: 新建 secrets sample 文件**

```yaml
# beartools 敏感配置示例
# 将此文件复制为 beartools.secrets.yaml 并填写真实密钥

siyuan:
  token: "REPLACE_ME"

agent:
  openrouter:
    key: "REPLACE_ME"
  zhizengzeng:
    key: "REPLACE_ME"
```

- [ ] **Step 3: 更新 `.gitignore` 忽略 secrets 文件**

```gitignore
# beartools 本地配置和日志
config/beartools.yaml
config/beartools.secrets.yaml
log/
.worktrees/
```

- [ ] **Step 4: 更新思源 token 缺失提示文案**

```python
    def _get_token(self) -> str:
        config = get_config()
        token = config.siyuan.token
        if not token:
            raise SiyuanError("请先在 config/beartools.secrets.yaml 或环境变量中配置 siyuan.token")
        return token
```

- [ ] **Step 5: 为 sample 文件补失败测试并确认通过**

```python
    def test_sample_yaml_uses_get_reference_for_agent_api_key(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        assert sample_data["siyuan"].get("token") is None
        assert sample_data["agent"]["primary"]["api_key"] == "@get agent.openrouter.key"
        assert sample_data["agent"]["candidates"][0]["api_key"] == "@get agent.zhizengzeng.key"

    def test_secrets_sample_contains_sensitive_values(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.secrets.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        assert sample_data["siyuan"]["token"] == "REPLACE_ME"
        assert sample_data["agent"]["openrouter"]["key"] == "REPLACE_ME"
        assert sample_data["agent"]["zhizengzeng"]["key"] == "REPLACE_ME"
```

- [ ] **Step 6: 运行 sample 与提示文案相关测试**

Run: `uv run pytest tests/test_config.py -k "sample_yaml_uses_get_reference_for_agent_api_key or secrets_sample_contains_sensitive_values" -xvs`

Expected: PASS。

### Task 4: 做最终静态检查与回归验证

**Files:**
- Modify: `src/beartools/config.py`
- Modify: `src/beartools/siyuan.py`
- Modify: `config/beartools.yaml.sample`
- Create: `config/beartools.secrets.yaml.sample`
- Modify: `.gitignore`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 运行配置与测试相关 ruff 检查**

Run: `uv run ruff check src/beartools/config.py src/beartools/siyuan.py tests/test_config.py`

Expected: `All checks passed!`

- [ ] **Step 2: 运行配置模块 mypy 检查**

Run: `uv run mypy src/beartools/config.py src/beartools/siyuan.py`

Expected: `Success: no issues found in 2 source files`

- [ ] **Step 3: 运行 LSP diagnostics 检查关键文件**

Check:
- `src/beartools/config.py`
- `src/beartools/siyuan.py`
- `tests/test_config.py`

Expected: 无 diagnostics。

- [ ] **Step 4: 运行最终回归测试**

Run: `uv run pytest tests/test_config.py tests/test_llm_runtime.py tests/test_doctor.py -xvs`

Expected: PASS，确认配置改造不破坏 LLM 运行时与健康检查相关行为。
