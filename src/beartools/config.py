"""配置文件读取模块

读取当前工作目录下的config/beartools.yaml配置文件，
支持.env文件和环境变量覆盖（BEARTOOLS_前缀）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from pathlib import Path
from typing import Protocol, cast

DEFAULT_DOCTOR_ENABLED_CHECKS = ["google_ping", "opencli", "siyuan", "llm"]

# 全局配置单例
_config_instance: Config | None = None


class _SettingsLike(Protocol):
    """配置读取接口。"""

    def get(self, key: str, default: object = ...) -> object: ...


def _create_lazy_settings(**kwargs: object) -> _SettingsLike:
    dynaconf_module = importlib.import_module("dynaconf")
    lazy_settings_class = cast(type[_SettingsLike], dynaconf_module.LazySettings)
    return lazy_settings_class(**kwargs)


@dataclass
class LogConfig:
    """日志配置"""

    path: Path = field(default_factory=lambda: Path("log") / "beartools.log")
    level: str = "INFO"
    config_file: Path | None = None


@dataclass
class DoctorCheckConfig:
    """健康检查单项配置"""

    timeout: int = 2
    fail_on_error: bool = True


@dataclass
class DoctorConfig:
    """健康检查总配置"""

    enabled_checks: list[str] = field(default_factory=lambda: list(DEFAULT_DOCTOR_ENABLED_CHECKS))
    checks: dict[str, DoctorCheckConfig] = field(default_factory=dict)


@dataclass
class SiyuanConfig:
    """思源笔记全局配置"""

    token: str = ""  # 思源笔记API访问令牌
    default_note: str = ""  # 默认操作的笔记ID
    notebook: str = ""  # 上传目标笔记本ID
    path: str = ""  # 上传目标路径


@dataclass
class AgentNodeConfig:
    """智能体节点配置"""

    name: str = ""
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30


@dataclass
class AgentConfig:
    """智能体配置"""

    primary: AgentNodeConfig = field(default_factory=AgentNodeConfig)
    candidates: list[AgentNodeConfig] = field(default_factory=list)


@dataclass
class Config:
    """主配置"""

    log: LogConfig = field(default_factory=LogConfig)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    siyuan: SiyuanConfig = field(default_factory=SiyuanConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)


def _ensure_config_dir() -> None:
    """确保config目录存在"""
    cwd = Path.cwd()
    config_dir = cwd / "config"
    if not config_dir.exists():
        try:
            config_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise RuntimeError(f"无法创建config目录: 权限不足 - {e}") from e
        except OSError as e:
            raise RuntimeError(f"无法创建config目录: {e}") from e


def _parse_timeout_seconds(value: object, field_name: str) -> int:
    """解析超时时间字段"""
    if isinstance(value, bool):
        raise RuntimeError(f"agent.{field_name} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as e:
            raise RuntimeError(f"agent.{field_name} 必须是整数") from e
    raise RuntimeError(f"agent.{field_name} 必须是整数")


def _as_dict(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} 必须是字典")
    return {str(key): val for key, val in value.items()}


def _as_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError(f"{path} 必须是列表")
    return list(value)


def _require_non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{path} 必填且必须是非空字符串")
    return value


def _parse_api_key(value: object, path: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise RuntimeError(f"{path}.api_key 必须是字符串")


def _parse_extra_headers(value: object, path: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}.extra_headers 必须是字典")

    extra_headers: dict[str, str] = {}
    for header_name, header_value in value.items():
        if not isinstance(header_name, str) or not isinstance(header_value, str):
            raise RuntimeError(f"{path}.extra_headers 必须是字符串键值对字典")
        extra_headers[header_name] = header_value
    return extra_headers


def _parse_provider(value: object, path: str) -> str:
    """解析并校验 provider。"""
    provider = _require_non_empty_string(value, f"{path}.provider")
    if provider not in {"openai", "openrouter"}:
        raise RuntimeError(f"{path}.provider 仅支持 openai/openrouter")
    return provider


def _parse_agent_node_config(node_settings: object, path: str) -> AgentNodeConfig:
    """解析单个智能体节点配置"""
    node_dict = _as_dict(node_settings, path)

    name_val = _require_non_empty_string(node_dict.get("name"), f"{path}.name")
    provider_val = _parse_provider(node_dict.get("provider"), path)
    base_url_val = _require_non_empty_string(node_dict.get("base_url"), f"{path}.base_url")
    model_val = _require_non_empty_string(node_dict.get("model"), f"{path}.model")
    api_key = _parse_api_key(node_dict.get("api_key", ""), path)
    extra_headers = _parse_extra_headers(node_dict.get("extra_headers", {}), path)
    timeout_seconds = _parse_timeout_seconds(node_dict.get("timeout_seconds", 30), f"{path}.timeout_seconds")

    return AgentNodeConfig(
        name=name_val,
        provider=provider_val,
        base_url=base_url_val,
        model=model_val,
        api_key=api_key,
        extra_headers=extra_headers,
        timeout_seconds=timeout_seconds,
    )


def _parse_agent_config(settings: _SettingsLike) -> AgentConfig:
    """解析智能体配置"""
    agent_settings = settings.get("agent")
    if agent_settings is None:
        return AgentConfig()
    agent_dict = _as_dict(agent_settings, "agent")

    if "primary" not in agent_dict:
        raise RuntimeError("agent.primary 必填")
    primary = _parse_agent_node_config(agent_dict["primary"], "agent.primary")

    candidates: list[AgentNodeConfig] = []
    if "candidates" in agent_dict:
        candidates_val = agent_dict["candidates"]
        if candidates_val is None:
            raise RuntimeError("agent.candidates 必须是列表")
        for index, candidate_settings in enumerate(_as_list(candidates_val, "agent.candidates")):
            candidates.append(_parse_agent_node_config(candidate_settings, f"agent.candidates[{index}]"))

    return AgentConfig(primary=primary, candidates=candidates)


def _convert_to_dataclass(settings: _SettingsLike) -> Config:
    """将dynaconf设置转换为Config数据类，保持接口兼容"""
    # 处理log配置
    log_settings = _as_dict(settings.get("log", {}), "log")
    path_val = log_settings.get("path", "log/beartools.log")
    log_path = Path(str(path_val))
    level_val = log_settings.get("level", "INFO")
    log_level = str(level_val)
    log_config_file = log_settings.get("config_file")
    log_config_file_path = Path(str(log_config_file)) if log_config_file is not None else None
    log_config = LogConfig(path=log_path, level=log_level, config_file=log_config_file_path)

    # 处理doctor配置
    doctor_settings = _as_dict(settings.get("doctor", {}), "doctor")
    default_enabled = list(DEFAULT_DOCTOR_ENABLED_CHECKS)
    enabled_checks_val = doctor_settings.get("enabled_checks", default_enabled)
    if isinstance(enabled_checks_val, list):
        enabled_checks = [str(item) for item in enabled_checks_val]
    else:
        enabled_checks = default_enabled

    # 处理checks配置
    merged_checks: dict[str, DoctorCheckConfig] = {}
    checks_dict_val = doctor_settings.get("checks", {})
    if isinstance(checks_dict_val, dict):
        for check_name, check_config in checks_dict_val.items():
            if isinstance(check_config, dict):
                normalized_check_config = _as_dict(check_config, f"doctor.checks.{check_name}")
                timeout_val = normalized_check_config.get("timeout", 2)
                timeout = int(timeout_val) if isinstance(timeout_val, (int, str, float)) else 2
                fail_on_error_val = normalized_check_config.get("fail_on_error", True)
                fail_on_error = bool(fail_on_error_val) if isinstance(fail_on_error_val, (bool, int, str)) else True
                merged_checks[str(check_name)] = DoctorCheckConfig(timeout=timeout, fail_on_error=fail_on_error)

    doctor_config = DoctorConfig(enabled_checks=enabled_checks, checks=merged_checks)

    # 处理siyuan配置
    siyuan_settings = _as_dict(settings.get("siyuan", {}), "siyuan")
    token_val = siyuan_settings.get("token", "")
    default_note_val = siyuan_settings.get("default_note", "")
    notebook_val = siyuan_settings.get("notebook", "")
    path_val2 = siyuan_settings.get("path", "")
    siyuan_config = SiyuanConfig(
        token=str(token_val),
        default_note=str(default_note_val),
        notebook=str(notebook_val),
        path=str(path_val2),
    )

    agent_config = _parse_agent_config(settings)

    return Config(log=log_config, doctor=doctor_config, siyuan=siyuan_config, agent=agent_config)


def load_config() -> Config:
    """加载配置，从config/beartools.yaml读取，支持环境变量覆盖

    Returns:
        Config: 加载完成的配置对象

    Raises:
        RuntimeError: 配置文件格式错误或权限不足时抛出
    """
    global _config_instance
    _ensure_config_dir()
    cwd = Path.cwd()
    config_path = cwd / "config" / "beartools.yaml"

    # 使用dynaconf加载配置
    settings = _create_lazy_settings(
        envvar_prefix="BEARTOOLS",
        settings_file=str(config_path),
        load_dotenv=True,
        core_loaders=["YAML", "ENV"],
    )

    # 转换为数据类保持接口兼容
    config = _convert_to_dataclass(settings)
    _config_instance = config
    return config


def get_config() -> Config:
    """获取全局配置单例，如果未加载则自动加载

    Returns:
        Config: 全局配置对象
    """
    global _config_instance
    if _config_instance is None:
        return load_config()
    return _config_instance


def reset_config() -> None:
    """重置配置单例"""
    global _config_instance
    _config_instance = None
