import os
from pathlib import Path
import tempfile

import pytest
import yaml

from beartools.config import AgentNodeConfig, get_config, load_config, reset_config


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
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://large1.example.com"
      model: "gpt-5"
      api_key: "@get test.large-key"
      extra_headers:
        "X-Env": "test"
      timeout_seconds: "45"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
      api_key: "@get test.small-1-key"
      extra_headers: {}
      timeout_seconds: 20
    - name: "small-2"
      provider: "openai"
      base_url: "https://small2.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get test.small-2-key"
      extra_headers:
        "X-Region": "cn"
"""
        )
        self._write_secrets(
            """
test:
  large-key: "large-key"
  small-1-key: "small-1-key"
  small-2-key: "small-2-key"
"""
        )

        config = load_config()

        assert len(config.agent.large) == 1
        assert config.agent.large[0].name == "large-1"
        assert config.agent.large[0].provider == "openai"
        assert config.agent.large[0].base_url == "https://large1.example.com"
        assert config.agent.large[0].model == "gpt-5"
        assert config.agent.large[0].api_key == "large-key"
        assert config.agent.large[0].extra_headers == {"X-Env": "test"}
        assert config.agent.large[0].timeout_seconds == 45
        assert len(config.agent.small) == 2
        assert config.agent.small[0].name == "small-1"
        assert config.agent.small[0].provider == "openai"
        assert config.agent.small[0].timeout_seconds == 20
        assert config.agent.small[1].name == "small-2"
        assert config.agent.small[1].provider == "openai"
        assert config.agent.small[1].api_key == "small-2-key"
        assert config.agent.small[1].extra_headers == {"X-Region": "cn"}
        assert config.agent.small[1].timeout_seconds == 30

    def test_reject_duplicate_agent_name_across_tiers(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "shared-name"
      provider: "openai"
      base_url: "https://large1.example.com"
      model: "gpt-5"
      api_key: "large-key"
  small:
    - name: "shared-name"
      provider: "anthropic"
      base_url: "https://small1.example.com"
      model: "claude-haiku"
      api_key: "small-key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent candidate name 必须全局唯一: shared-name"):
            load_config()

    def test_reject_duplicate_agent_name_inside_same_tier(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://large1.example.com"
      model: "gpt-5"
      api_key: "large-key"
  small:
    - name: "same-name"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
      api_key: "small-1-key"
    - name: "same-name"
      provider: "openai"
      base_url: "https://small2.example.com"
      model: "gpt-4.1-mini"
      api_key: "small-2-key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent candidate name 必须全局唯一: same-name"):
            load_config()

    def test_reject_missing_large_provider(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "large-1"
      base_url: "https://large1.example.com"
      model: "gpt-5"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.large\[0\]\.provider 必填"):
            load_config()

    def test_reject_invalid_provider_value(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "large-1"
      provider: "bad-provider"
      base_url: "https://large1.example.com"
      model: "gpt-5"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"provider 仅支持 openai/anthropic"):
            load_config()

    def test_reject_openrouter_provider_value(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "large-1"
      provider: "openrouter"
      base_url: "https://large1.example.com"
      model: "gpt-5"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"provider 仅支持 openai/anthropic"):
            load_config()

    def test_parse_anthropic_agent_provider(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "claude-large"
      provider: "anthropic"
      base_url: "https://api.anthropic.com"
      model: "claude-sonnet"
      api_key: "anthropic-key"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
      api_key: "small-key"
"""
        )

        config = load_config()

        assert config.agent.large[0].provider == "anthropic"
        assert config.agent.large[0].model == "claude-sonnet"

    def test_reject_missing_large(self) -> None:
        self._write_config(
            """
agent:
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.large 必填"):
            load_config()

    def test_reject_missing_small(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://large1.example.com"
      model: "gpt-5"
      api_key: "large-key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.small 必填"):
            load_config()

    def test_reject_invalid_large_shape(self) -> None:
        self._write_config(
            """
agent:
  large:
    name: "broken-large"
  small:
    - name: "small-1"
      provider: "openai"
      base_url: "https://small1.example.com"
      model: "gpt-4o-mini"
      api_key: "small-key"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.large 必须是列表"):
            load_config()

    def test_reject_invalid_small_shape(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "large-1"
      provider: "openai"
      base_url: "https://large1.example.com"
      model: "gpt-5"
      api_key: "large-key"
  small:
    name: "broken-small"
"""
        )

        with pytest.raises(RuntimeError, match=r"agent\.small 必须是列表"):
            load_config()

    def test_reset_config_reloads_new_yaml(self) -> None:
        config_path = self._write_config(
            """
agent:
  large:
    - name: "primary-a"
      provider: "openai"
      base_url: "https://primary-a.example.com"
      model: "gpt-4o-mini"
      api_key: "@get test.keys.a"
  small:
    - name: "small-a"
      provider: "openai"
      base_url: "https://small-a.example.com"
      model: "gpt-4.1-mini"
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
        assert first_config.agent.large[0].name == "primary-a"

        config_path.write_text(
            """
agent:
  large:
    - name: "primary-b"
      provider: "openai"
      base_url: "https://primary-b.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get test.keys.b"
  small:
    - name: "candidate-b"
      provider: "openai"
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
        assert reloaded_config.agent.large[0].name == "primary-b"
        assert reloaded_config.agent.large[0].model == "gpt-4.1-mini"
        assert len(reloaded_config.agent.small) == 1
        assert reloaded_config.agent.small[0].name == "candidate-b"
        assert reloaded_config.agent.small[0].timeout_seconds == 18

    def test_doctor_enabled_checks_defaults_exclude_siyuan(self) -> None:
        self._write_config("doctor: {}\n")

        config = load_config()

        assert config.doctor.enabled_checks == ["google_ping", "opencli", "llm"]

    def test_invalid_doctor_enabled_checks_falls_back_to_default(self) -> None:
        self._write_config(
            """
doctor:
  enabled_checks: "broken"
"""
        )

        config = load_config()

        assert config.doctor.enabled_checks == ["google_ping", "opencli", "llm"]

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

        assert set(agent_data.keys()) == {"large", "small"}
        for tier_name in ["large", "small"]:
            nodes = agent_data[tier_name]
            assert isinstance(nodes, list)
            assert nodes
            for node in nodes:
                assert set(node.keys()) == allowed_fields
                assert node["provider"] in {"openai", "anthropic"}

        siyuan_data = sample_data["siyuan"]
        assert siyuan_data["token"] == "@get siyuan.token"
        assert siyuan_data["default_note"] == "REPLACE_ME_NOTE_ID"
        assert siyuan_data["notebook"] == "REPLACE_ME_NOTEBOOK_ID"
        assert siyuan_data["path"] == "/REPLACE_ME_PATH"

    def test_load_config_merges_main_yaml_and_secrets_yaml(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "primary"
      provider: "openai"
      base_url: "https://primary.example.com"
      model: "gpt-4o-mini"
      api_key: "@get agent.openai.key"
      extra_headers: {}
      timeout_seconds: 30
  small:
    - name: "small"
      provider: "openai"
      base_url: "https://small.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get agent.openai.key"
      extra_headers: {}
      timeout_seconds: 20
siyuan:
  default_note: "note-1"
"""
        )
        self._write_secrets(
            """
siyuan:
  token: "secret-token"
agent:
  openai:
    key: "secret-key"
"""
        )

        config = load_config()

        assert config.siyuan.token == "secret-token"
        assert config.siyuan.default_note == "note-1"
        assert config.agent.large[0].api_key == "secret-key"
        assert config.agent.small[0].api_key == "secret-key"

    def test_agent_api_key_can_be_resolved_from_shared_secret_for_both_tiers(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "primary"
      provider: "openai"
      base_url: "https://primary.example.com"
      model: "gpt-4o-mini"
      api_key: "@get agent.openai.key"
  small:
    - name: "small"
      provider: "openai"
      base_url: "https://small.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get agent.openai.key"
"""
        )
        self._write_secrets(
            """
agent:
  openai:
    key: "secret-key"
"""
        )
        config = load_config()

        assert config.agent.large[0].api_key == "secret-key"
        assert config.agent.small[0].api_key == "secret-key"

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
              large:
                - name: "primary"
                  provider: "openai"
                  base_url: "https://primary.example.com"
                  model: "gpt-4o-mini"
                  api_key: "plain-key"
              small:
                - name: "small"
                  provider: "openai"
                  base_url: "https://small.example.com"
                  model: "gpt-4.1-mini"
                  api_key: "plain-key"
            """
        )

        # 允许在主配置中直接写入明文 api_key（测试已放宽）
        config = load_config()
        assert config.agent.large[0].api_key == "plain-key"
        assert config.agent.small[0].api_key == "plain-key"

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
  large:
    - name: "primary"
      provider: "openai"
      base_url: "https://primary.example.com"
      model: "gpt-4o-mini"
      api_key: "@get agent.missing.key"
  small:
    - name: "small"
      provider: "openai"
      base_url: "https://small.example.com"
      model: "gpt-4.1-mini"
      api_key: "@get agent.missing.key"
"""
        )

        with pytest.raises(Exception, match=r"(引用的配置路径不存在|not found in settings)"):
            load_config()

    def test_multiple_nodes_can_share_same_get_reference(self) -> None:
        self._write_config(
            """
agent:
  large:
    - name: "primary"
      provider: "openai"
      base_url: "https://primary.example.com"
      model: "gpt-4o-mini"
      api_key: "@get agent.shared.key"
  small:
    - name: "backup"
      provider: "openai"
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

        assert config.agent.large[0].api_key == "shared-secret"
        assert config.agent.small[0].api_key == "shared-secret"

    def test_sample_yaml_uses_get_reference_for_agent_api_key(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        assert sample_data["siyuan"]["token"] == "@get siyuan.token"
        assert sample_data["agent"]["large"][0]["api_key"] == "@get agent.openai.key"
        assert sample_data["agent"]["small"][0]["api_key"] == "@get agent.openai.key"
        assert sample_data["codex"]["api_key"] == "@get codex.api_key"
        assert sample_data["codex"]["vplan"]["key"] == "@get codex.vplan.key"

    def test_secrets_sample_contains_sensitive_values(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.secrets.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        assert sample_data["siyuan"]["token"] == "REPLACE_ME"
        assert sample_data["agent"]["openai"]["key"] == "REPLACE_ME"
        assert sample_data["agent"]["zhizengzeng"]["key"] == "REPLACE_ME"
        assert sample_data["codex"]["vplan"]["key"] == "REPLACE_ME"

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
  vplan:
    key: "vplan-secret-key"
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
        assert config.codex.vplan.key == "vplan-secret-key"
