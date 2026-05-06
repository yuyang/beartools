"""配置文件读取模块

读取当前工作目录下的 config/beartools.yaml 和 config/beartools.secrets.yaml，
支持 .env 文件和环境变量覆盖（BEARTOOLS_前缀）。

配置优先级：环境变量 > beartools.secrets.yaml > beartools.yaml
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
    success_threshold: int = 3
    targets: list[str] = field(default_factory=list)


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

    large: list[AgentNodeConfig] = field(default_factory=list)
    small: list[AgentNodeConfig] = field(default_factory=list)


@dataclass
class GmailConfig:
    """Gmail 配置"""

    client_secret_file: Path = Path("config/client_secret.json")
    token_file: Path = Path("config/gmail.token.json")
    output_dir: Path = Path("email")
    default_days: int = 3
    max_results: int = 100


@dataclass
class CodexConfig:
    """Codex 配置"""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    pic_model: str = ""
    instructions: str = "你是 Codex 助手"
    output_dir: Path = Path("output/codex")
    timeout_seconds: int = 60
    bin_path: str = ""
    pic_size: str = "1024x1024"
    pic_quality: str = "high"
    pic_output_format: str = "png"
    pic_response_format: str = "b64_json"


@dataclass
class Config:
    """主配置"""

    log: LogConfig = field(default_factory=LogConfig)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    siyuan: SiyuanConfig = field(default_factory=SiyuanConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)


# 删除对节点是否配置的额外校验，保持错误更直接由解析阶段抛出


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
            parsed_value = int(value)
            return parsed_value
        except ValueError as e:
            raise RuntimeError(f"agent.{field_name} 必须是整数") from e
    raise RuntimeError(f"agent.{field_name} 必须是整数")


def _as_dict(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} 必须是字典")
    result: dict[str, object] = {}
    # 遍历每个key的时候可能触发dynaconf @get的懒解析，需要捕获解析错误
    for key, val in value.items():
        try:
            # 访问value的时候可能触发@get解析
            result[str(key)] = val
        except Exception as e:
            raise RuntimeError(f"{path}.{str(key)} 引用的配置路径不存在: {e}") from e
    return result


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
    # 如果是dynaconf的lazy求值，访问时会自动解析，需要捕获解析错误
    try:
        if isinstance(value, str):
            return value
        str_val = str(value)
        return str_val
    except Exception as e:
        raise RuntimeError(f"{path}.api_key 引用的配置路径不存在: {e}") from e
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


def _parse_positive_int(value: object, path: str, default: int) -> int:
    """解析正整数配置。"""

    if value is None:
        return default
    if isinstance(value, bool):
        raise RuntimeError(f"{path} 必须是正整数")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError as e:
            raise RuntimeError(f"{path} 必须是正整数") from e
        if parsed > 0:
            return parsed
    raise RuntimeError(f"{path} 必须是正整数")


def _parse_agent_node_config(node_settings: object, path: str) -> AgentNodeConfig:
    """解析单个智能体节点配置"""

    # 直接单独获取每个字段，避免提前触发所有字段的懒解析导致错误无法捕获
    # 因为node_settings是Box，每个字段访问都会触发懒解析（比如@get），所以单独获取可以正确捕获api_key的解析错误
    def get_field(field: str, default: object = None) -> object:
        if isinstance(node_settings, dict):
            dict_node_settings = cast(dict[str, object], node_settings)
            return dict_node_settings.get(field, default)
        # 如果是dynaconf的Box对象，使用get方法
        if not hasattr(node_settings, "get"):
            return default
        settings_like = cast(_SettingsLike, node_settings)
        return settings_like.get(field, default)

    name_val = _require_non_empty_string(get_field("name"), f"{path}.name")
    provider_val = _parse_provider(get_field("provider"), path)
    base_url_val = _require_non_empty_string(get_field("base_url"), f"{path}.base_url")
    model_val = _require_non_empty_string(get_field("model"), f"{path}.model")

    # api_key单独处理，捕获解析错误
    try:
        api_key_val = get_field("api_key", "")
        api_key = _parse_api_key(api_key_val, path)
    except Exception as e:
        raise RuntimeError(f"{path}.api_key 引用的配置路径不存在: {e}") from e

    extra_headers = _parse_extra_headers(get_field("extra_headers", {}), path)
    timeout_seconds = _parse_timeout_seconds(get_field("timeout_seconds", 30), f"{path}.timeout_seconds")

    return AgentNodeConfig(
        name=name_val,
        provider=provider_val,
        base_url=base_url_val,
        model=model_val,
        api_key=api_key,
        extra_headers=extra_headers,
        timeout_seconds=timeout_seconds,
    )


def _parse_agent_node_list(node_list_settings: object, path: str) -> list[AgentNodeConfig]:
    """解析节点列表配置。"""

    node_list = _as_list(node_list_settings, path)
    if not node_list:
        raise RuntimeError(f"{path} 必须是非空列表")
    return [
        _parse_agent_node_config(node_settings, f"{path}[{index}]") for index, node_settings in enumerate(node_list)
    ]


def _parse_agent_config(settings: _SettingsLike) -> AgentConfig:
    """解析智能体配置"""
    agent_settings = settings.get("agent")
    if agent_settings is None:
        return AgentConfig()
    agent_dict = _as_dict(agent_settings, "agent")

    if "large" not in agent_dict:
        raise RuntimeError("agent.large 必填")
    if "small" not in agent_dict:
        raise RuntimeError("agent.small 必填")

    large = _parse_agent_node_list(agent_dict["large"], "agent.large")
    small = _parse_agent_node_list(agent_dict["small"], "agent.small")

    return AgentConfig(large=large, small=small)


def _parse_gmail_config(settings: _SettingsLike) -> GmailConfig:
    """解析 Gmail 配置。"""

    gmail_settings = _as_dict(settings.get("gmail", {}), "gmail")
    return GmailConfig(
        client_secret_file=Path(str(gmail_settings.get("client_secret_file", "config/client_secret.json"))),
        token_file=Path(str(gmail_settings.get("token_file", "config/gmail.token.json"))),
        output_dir=Path(str(gmail_settings.get("output_dir", "email"))),
        default_days=_parse_positive_int(gmail_settings.get("default_days", 3), "gmail.default_days", 3),
        max_results=_parse_positive_int(gmail_settings.get("max_results", 100), "gmail.max_results", 100),
    )


def _parse_codex_config(settings: _SettingsLike) -> CodexConfig:
    """解析 Codex 配置。"""

    codex_settings = _as_dict(settings.get("codex", {}), "codex")
    return CodexConfig(
        base_url=str(codex_settings.get("base_url", "")),
        api_key=str(codex_settings.get("api_key", "")),
        model=str(codex_settings.get("model", "")),
        pic_model=str(codex_settings.get("pic_model", codex_settings.get("model", ""))),
        instructions=str(codex_settings.get("instructions", "你是 Codex 助手")),
        output_dir=Path(str(codex_settings.get("output_dir", "output/codex"))),
        timeout_seconds=_parse_positive_int(codex_settings.get("timeout_seconds", 60), "codex.timeout_seconds", 60),
        bin_path=str(codex_settings.get("bin_path", "")),
        pic_size=str(codex_settings.get("pic_size", "1024x1024")),
        pic_quality=str(codex_settings.get("pic_quality", "high")),
        pic_output_format=str(codex_settings.get("pic_output_format", "png")),
        pic_response_format=str(codex_settings.get("pic_response_format", "b64_json")),
    )


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
                success_threshold_val = normalized_check_config.get("success_threshold", 3)
                if isinstance(success_threshold_val, bool):
                    success_threshold = 3
                elif isinstance(success_threshold_val, int):
                    success_threshold = success_threshold_val
                elif isinstance(success_threshold_val, float):
                    success_threshold = int(success_threshold_val)
                elif isinstance(success_threshold_val, str) and success_threshold_val.strip():
                    success_threshold = int(success_threshold_val)
                else:
                    success_threshold = 3
                targets_val = normalized_check_config.get("targets", [])
                targets = [str(item) for item in targets_val] if isinstance(targets_val, list) else []
                merged_checks[str(check_name)] = DoctorCheckConfig(
                    timeout=timeout,
                    fail_on_error=fail_on_error,
                    success_threshold=success_threshold,
                    targets=targets,
                )

    doctor_config = DoctorConfig(enabled_checks=enabled_checks, checks=merged_checks)

    # 处理siyuan配置
    token_val = settings.get("siyuan.token", "")
    default_note_val = settings.get("siyuan.default_note", "")
    notebook_val = settings.get("siyuan.notebook", "")
    path_val2 = settings.get("siyuan.path", "")
    siyuan_config = SiyuanConfig(
        token=str(token_val),
        default_note=str(default_note_val),
        notebook=str(notebook_val),
        path=str(path_val2),
    )

    agent_config = _parse_agent_config(settings)

    gmail_config = _parse_gmail_config(settings)

    codex_config = _parse_codex_config(settings)

    return Config(
        log=log_config,
        doctor=doctor_config,
        siyuan=siyuan_config,
        agent=agent_config,
        gmail=gmail_config,
        codex=codex_config,
    )


def load_config() -> Config:
    """加载配置，从config/beartools.yaml和config/beartools.secrets.yaml读取，支持环境变量覆盖

    配置优先级：环境变量 > beartools.secrets.yaml > beartools.yaml

    Returns:
        Config: 加载完成的配置对象

    Raises:
        RuntimeError: 配置文件格式错误或权限不足时抛出
    """
    global _config_instance
    _ensure_config_dir()
    cwd = Path.cwd()
    config_path = cwd / "config" / "beartools.yaml"
    secrets_path = cwd / "config" / "beartools.secrets.yaml"

    settings = _create_lazy_settings(
        envvar_prefix="BEARTOOLS",
        settings_files=[str(config_path), str(secrets_path)],
        load_dotenv=True,
        core_loaders=["YAML", "ENV"],
        merge_enabled=True,
        environments=False,
    )

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
