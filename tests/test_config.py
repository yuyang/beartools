from collections.abc import Callable
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from typing import Protocol, cast

import yaml

pytest = importlib.import_module("pytest")


class _ConfigModule(Protocol):
    AgentNodeConfig: object

    def get_config(self) -> object: ...

    def load_config(self) -> object: ...

    def reset_config(self) -> None: ...


class _AgentNode(Protocol):
    name: str
    provider: str
    base_url: str
    model: str
    api_key: str
    extra_headers: dict[str, str]
    timeout_seconds: int


class _AgentConfig(Protocol):
    primary: _AgentNode
    candidates: list[_AgentNode]


class _DoctorConfig(Protocol):
    enabled_checks: list[str]
    checks: dict[str, "_DoctorCheckConfig"]


class _DoctorCheckConfig(Protocol):
    timeout: int
    fail_on_error: bool
    success_threshold: int
    targets: list[str]


class _SiyuanConfig(Protocol):
    token: str
    default_note: str


class _CodexConfig(Protocol):
    base_url: str
    api_key: str
    model: str
    pic_model: str
    instructions: str
    output_dir: Path
    timeout_seconds: int
    pic_size: str
    pic_quality: str
    pic_output_format: str
    pic_response_format: str


class _Config(Protocol):
    doctor: _DoctorConfig
    agent: _AgentConfig
    siyuan: _SiyuanConfig
    codex: _CodexConfig


class _AgentNodeConfigClass(Protocol):
    __dataclass_fields__: dict[str, object]


def _load_config_module() -> _ConfigModule:
    module_name = "beartools_config_for_tests"
    existing_module = sys.modules.get(module_name)
    if existing_module is not None:
        return cast(_ConfigModule, existing_module)

    module_path = Path(__file__).resolve().parents[1] / "src" / "beartools" / "config.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载配置模块: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return cast(_ConfigModule, module)


_CONFIG_MODULE = _load_config_module()
AgentNodeConfig = cast(_AgentNodeConfigClass, _CONFIG_MODULE.AgentNodeConfig)
get_config = cast(Callable[[], _Config], _CONFIG_MODULE.get_config)
load_config = cast(Callable[[], _Config], _CONFIG_MODULE.load_config)
reset_config = cast(Callable[[], None], _CONFIG_MODULE.reset_config)


class TestConfig:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir.name)

    def teardown_method(self) -> None:
        reset_config()
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _write_config(self, content: str) -> Path:
        config_dir = Path("config")
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "beartools.yaml"
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def _write_secrets(self, content: str) -> Path:
        config_dir = Path("config")
        config_dir.mkdir(parents=True, exist_ok=True)
        secrets_path = config_dir / "beartools.secrets.yaml"
        secrets_path.write_text(content, encoding="utf-8")
        return secrets_path

    def test_parse_valid_agent_config(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary-openai"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "@get test.primary-key"
    extra_headers:
      "X-Env": "test"
    timeout_seconds: "45"
  candidates:
    - name: "candidate-1"
      provider: "openrouter"
      base_url: "https://candidate1.example.com"
      model: "gpt-4o-mini"
      api_key: "@get test.candidate-1-key"
      extra_headers: {}
      timeout_seconds: 20
    - name: "candidate-2"
      provider: "openai"
      base_url: "https://candidate2.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get test.candidate-2-key"
      extra_headers:
        "X-Region": "cn"
"""
        )
        self._write_secrets(
            """
test:
  primary-key: "primary-key"
  candidate-1-key: "candidate-key"
  candidate-2-key: "candidate-2-key"
"""
        )

        config = load_config()

        assert config.agent.primary.name == "primary-openai"
        assert config.agent.primary.provider == "openai"
        assert config.agent.primary.base_url == "https://primary.example.com"
        assert config.agent.primary.model == "gpt-4o-mini"
        assert config.agent.primary.api_key == "primary-key"
        assert config.agent.primary.extra_headers == {"X-Env": "test"}
        assert config.agent.primary.timeout_seconds == 45
        assert len(config.agent.candidates) == 2
        assert config.agent.candidates[0].name == "candidate-1"
        assert config.agent.candidates[0].provider == "openrouter"
        assert config.agent.candidates[0].timeout_seconds == 20
        assert config.agent.candidates[1].name == "candidate-2"
        assert config.agent.candidates[1].provider == "openai"
        assert config.agent.candidates[1].api_key == "candidate-2-key"
        assert config.agent.candidates[1].extra_headers == {"X-Region": "cn"}
        assert config.agent.candidates[1].timeout_seconds == 30

    def test_reject_missing_primary_provider(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary-openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.primary\.provider 必填"):
            load_config()

    def test_reject_invalid_provider_value(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary-openai"
    provider: "anthropic"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"provider 仅支持 openai/openrouter"):
            load_config()

    def test_reject_missing_primary(self) -> None:
        self._write_config(
            """
agent:
  candidates:
    - name: "candidate-1"
      base_url: "https://candidate1.example.com"
      model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.primary 必填"):
            load_config()

    def test_reject_invalid_candidate_shape(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary-openai"
    provider: "openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "@get agent.primary.key"
  candidates:
    name: "broken-candidate"
"""
        )
        self._write_secrets(
            """
agent:
  primary:
    key: "primary-key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.candidates 必须是列表"):
            load_config()

    def test_reset_config_reloads_new_yaml(self) -> None:
        config_path = self._write_config(
            """
agent:
  primary:
    name: "primary-a"
    provider: "openai"
    base_url: "https://primary-a.example.com"
    model: "gpt-4o-mini"
    api_key: "@get test.keys.a"
"""
        )
        self._write_secrets(
            """
test:
  keys:
    a: "test-key-a"
    b: "test-key-b"
  candidate-b: "candidate-b-key"
"""
        )

        first_config = get_config()
        second_config = get_config()

        assert first_config is second_config
        assert first_config.agent.primary.name == "primary-a"

        config_path.write_text(
            """
agent:
  primary:
    name: "primary-b"
    provider: "openai"
    base_url: "https://primary-b.example.com"
    model: "gpt-4.1-mini"
    api_key: "@get test.keys.b"
  candidates:
    - name: "candidate-b"
      provider: "openrouter"
      base_url: "https://candidate-b.example.com"
      model: "gpt-4o-mini"
      api_key: "@get test.candidate-b"
      timeout_seconds: 18
""",
            encoding="utf-8",
        )

        reset_config()
        reloaded_config = get_config()

        assert reloaded_config is not first_config
        assert reloaded_config.agent.primary.name == "primary-b"
        assert reloaded_config.agent.primary.model == "gpt-4.1-mini"
        assert len(reloaded_config.agent.candidates) == 1
        assert reloaded_config.agent.candidates[0].name == "candidate-b"
        assert reloaded_config.agent.candidates[0].timeout_seconds == 18

    def test_doctor_enabled_checks_defaults_include_siyuan(self) -> None:
        self._write_config("doctor: {}\n")

        config = load_config()

        assert config.doctor.enabled_checks == ["google_ping", "opencli", "siyuan", "llm"]

    def test_invalid_doctor_enabled_checks_falls_back_to_default(self) -> None:
        self._write_config(
            """
doctor:
  enabled_checks: "broken"
"""
        )

        config = load_config()

        assert config.doctor.enabled_checks == ["google_ping", "opencli", "siyuan", "llm"]

    def test_google_ping_extended_config_is_parsed(self) -> None:
        self._write_config(
            """
doctor:
  checks:
    google_ping:
      timeout: 4
      fail_on_error: true
      success_threshold: 3
      targets:
        - "https://www.google.com/generate_204"
        - "https://www.youtube.com/"
        - "https://www.facebook.com/"
        - "https://x.com/"
        - "https://www.instagram.com/"
        - "https://www.baidu.com/"
"""
        )

        config = load_config()
        google_ping = config.doctor.checks["google_ping"]

        assert google_ping.timeout == 4
        assert google_ping.fail_on_error is True
        assert google_ping.success_threshold == 3
        assert google_ping.targets == [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
            "https://x.com/",
            "https://www.instagram.com/",
            "https://www.baidu.com/",
        ]

    def test_google_ping_timeout_only_uses_default_success_threshold(self) -> None:
        self._write_config(
            """
doctor:
  checks:
    google_ping:
      timeout: 5
"""
        )

        config = load_config()
        google_ping = config.doctor.checks["google_ping"]

        assert google_ping.timeout == 5
        assert google_ping.success_threshold == 3
        assert google_ping.targets == []

    def test_google_ping_sample_yaml_contains_extended_fields(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        google_ping = sample_data["doctor"]["checks"]["google_ping"]

        assert google_ping["timeout"] == 2
        assert google_ping["fail_on_error"] is True
        assert google_ping["success_threshold"] == 3
        assert google_ping["targets"] == [
            "https://www.google.com/generate_204",
            "https://www.youtube.com/",
            "https://www.facebook.com/",
            "https://www.wikipedia.org/",
            "https://www.instagram.com/",
            "https://www.baidu.com/",
        ]

    def test_sample_yaml_matches_agent_schema(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        agent_data = sample_data["agent"]
        allowed_fields = set(AgentNodeConfig.__dataclass_fields__.keys())

        assert set(agent_data.keys()) == {"primary", "candidates"}
        assert set(agent_data["primary"].keys()) == allowed_fields
        assert agent_data["primary"]["api_key"] == "@get agent.primary.key"
        assert agent_data["primary"]["provider"] in {"openai", "openrouter"}

        candidates = agent_data["candidates"]
        assert isinstance(candidates, list)
        assert candidates
        for candidate in candidates:
            assert set(candidate.keys()) == allowed_fields
            assert candidate["api_key"] == "@get agent.candidate_1.key"
            assert candidate["provider"] in {"openai", "openrouter"}

        siyuan_data = sample_data["siyuan"]
        assert siyuan_data["token"] == "@get siyuan.token"
        assert siyuan_data["default_note"] == "REPLACE_ME_NOTE_ID"
        assert siyuan_data["notebook"] == "REPLACE_ME_NOTEBOOK_ID"
        assert siyuan_data["path"] == "/REPLACE_ME_PATH"

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

    def test_allow_plain_siyuan_token_in_main_yaml(self) -> None:
        self._write_config(
            """
            siyuan:
              token: "plain-token"
            """
        )

        # 不再拒绝主配置中的明文敏感字段，允许在主配置中直接写入 token
        config = load_config()
        assert config.siyuan.token == "plain-token"

    def test_allow_plain_agent_api_key_in_main_yaml(self) -> None:
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

        # 允许在主配置中直接写入明文 api_key（测试已放宽）
        config = load_config()
        assert config.agent.primary.api_key == "plain-key"

    def test_siyuan_token_can_be_resolved_from_secrets_with_get(self) -> None:
        # 主配置不包含 token，secrets 使用 @get 懒引用并提供真实值
        self._write_config(
            """
siyuan:
  token: "@get test.siyuan_token"
"""
        )
        self._write_secrets(
            """
test:
  siyuan_token: "resolved-token"
"""
        )

        config = load_config()
        assert config.siyuan.token == "resolved-token"

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

    def test_sample_yaml_uses_get_reference_for_agent_api_key(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        assert sample_data["siyuan"]["token"] == "@get siyuan.token"
        assert sample_data["agent"]["primary"]["api_key"] == "@get agent.primary.key"
        assert sample_data["agent"]["candidates"][0]["api_key"] == "@get agent.candidate_1.key"
        assert sample_data["codex"]["api_key"] == "@get codex.api_key"

    def test_secrets_sample_contains_sensitive_values(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.secrets.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        assert sample_data["siyuan"]["token"] == "REPLACE_ME"
        assert sample_data["agent"]["openrouter"]["key"] == "REPLACE_ME"
        assert sample_data["agent"]["zhizengzeng"]["key"] == "REPLACE_ME"

    def test_load_config_parses_codex_section(self) -> None:
        self._write_config(
            """
codex:
  base_url: "https://api-xai.ainaibahub.com/v1"
  model: "grok-3-mini"
  pic_model: "gpt-image-2"
  output_dir: "codex-output"
  timeout_seconds: 45
  pic_size: "1536x1024"
  pic_quality: "medium"
  pic_output_format: "webp"
  pic_response_format: "b64_json"
"""
        )
        self._write_secrets(
            """
codex:
  api_key: "secret-key"
"""
        )

        config = load_config()

        assert config.codex.base_url == "https://api-xai.ainaibahub.com/v1"
        assert config.codex.api_key == "secret-key"
        assert config.codex.model == "grok-3-mini"
        assert config.codex.pic_model == "gpt-image-2"
        assert config.codex.instructions == "你是 Codex 助手"
        assert config.codex.output_dir == Path("codex-output")
        assert config.codex.timeout_seconds == 45
        assert config.codex.pic_size == "1536x1024"
        assert config.codex.pic_quality == "medium"
        assert config.codex.pic_output_format == "webp"
        assert config.codex.pic_response_format == "b64_json"
