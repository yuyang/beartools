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


class _Config(Protocol):
    doctor: _DoctorConfig
    agent: _AgentConfig


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

    def test_parse_valid_agent_config(self) -> None:
        self._write_config(
            """
agent:
  primary:
    name: "primary-openai"
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
    api_key: "primary-key"
    extra_headers:
      "X-Env": "test"
    timeout_seconds: "45"
  candidates:
    - name: "candidate-1"
      base_url: "https://candidate1.example.com"
      model: "gpt-4o-mini"
      api_key: "candidate-key"
      extra_headers: {}
      timeout_seconds: 20
    - name: "candidate-2"
      base_url: "https://candidate2.example.com"
      model: "gpt-4.1-mini"
      api_key: null
      extra_headers:
        "X-Region": "cn"
"""
        )

        config = load_config()

        assert config.agent.primary.name == "primary-openai"
        assert config.agent.primary.base_url == "https://primary.example.com"
        assert config.agent.primary.model == "gpt-4o-mini"
        assert config.agent.primary.api_key == "primary-key"
        assert config.agent.primary.extra_headers == {"X-Env": "test"}
        assert config.agent.primary.timeout_seconds == 45
        assert len(config.agent.candidates) == 2
        assert config.agent.candidates[0].name == "candidate-1"
        assert config.agent.candidates[0].timeout_seconds == 20
        assert config.agent.candidates[1].name == "candidate-2"
        assert config.agent.candidates[1].api_key == ""
        assert config.agent.candidates[1].extra_headers == {"X-Region": "cn"}
        assert config.agent.candidates[1].timeout_seconds == 30

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
    base_url: "https://primary.example.com"
    model: "gpt-4o-mini"
  candidates:
    name: "broken-candidate"
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
    base_url: "https://primary-a.example.com"
    model: "gpt-4o-mini"
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
    base_url: "https://primary-b.example.com"
    model: "gpt-4.1-mini"
  candidates:
    - name: "candidate-b"
      base_url: "https://candidate-b.example.com"
      model: "gpt-4o-mini"
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

        assert config.doctor.enabled_checks == ["google_ping", "opencli", "siyuan"]

    def test_invalid_doctor_enabled_checks_falls_back_to_default(self) -> None:
        self._write_config(
            """
doctor:
  enabled_checks: "broken"
"""
        )

        config = load_config()

        assert config.doctor.enabled_checks == ["google_ping", "opencli", "siyuan"]

    def test_sample_yaml_matches_agent_schema(self) -> None:
        sample_path = self.original_cwd / "config" / "beartools.yaml.sample"
        sample_data = yaml.safe_load(sample_path.read_text(encoding="utf-8"))

        agent_data = sample_data["agent"]
        allowed_fields = set(AgentNodeConfig.__dataclass_fields__.keys())

        assert set(agent_data.keys()) == {"primary", "candidates"}
        assert set(agent_data["primary"].keys()) == allowed_fields
        assert agent_data["primary"]["api_key"] == "REPLACE_ME"

        candidates = agent_data["candidates"]
        assert isinstance(candidates, list)
        assert candidates
        for candidate in candidates:
            assert set(candidate.keys()) == allowed_fields
            assert candidate["api_key"] == "REPLACE_ME"

        siyuan_data = sample_data["siyuan"]
        assert siyuan_data["token"] == "REPLACE_ME"
        assert siyuan_data["default_note"] == "REPLACE_ME_NOTE_ID"
        assert siyuan_data["notebook"] == "REPLACE_ME_NOTEBOOK_ID"
        assert siyuan_data["path"] == "/REPLACE_ME_PATH"
