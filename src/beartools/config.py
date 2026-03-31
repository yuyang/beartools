"""配置文件读取模块

读取当前工作目录下的config/beartools.yaml配置文件，
支持.env文件和环境变量覆盖（BEARTOOLS_前缀）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dynaconf import LazySettings

# 全局配置单例
_config_instance: Config | None = None


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

    enabled_checks: list[str] = field(default_factory=lambda: ["google_ping", "opencli", "siyuan"])
    checks: dict[str, DoctorCheckConfig] = field(default_factory=dict)


@dataclass
class SiyuanConfig:
    """思源笔记全局配置"""

    token: str = ""  # 思源笔记API访问令牌
    default_note: str = ""  # 默认操作的笔记ID


@dataclass
class Config:
    """主配置"""

    log: LogConfig = field(default_factory=LogConfig)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    siyuan: SiyuanConfig = field(default_factory=SiyuanConfig)


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


def _convert_to_dataclass(settings: LazySettings) -> Config:  # type: ignore
    """将dynaconf设置转换为Config数据类，保持接口兼容"""
    # 处理log配置
    log_settings: dict[str, object] = settings.get("log", {})  # type: ignore
    path_val = log_settings.get("path", "log/beartools.log")
    log_path = Path(str(path_val))
    level_val = log_settings.get("level", "INFO")
    log_level = str(level_val)
    log_config_file = log_settings.get("config_file")
    log_config_file_path = Path(str(log_config_file)) if log_config_file is not None else None
    log_config = LogConfig(path=log_path, level=log_level, config_file=log_config_file_path)

    # 处理doctor配置
    doctor_settings: dict[str, object] = settings.get("doctor", {})  # type: ignore
    default_enabled = ["google_ping", "opencli"]
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
                timeout_val = check_config.get("timeout", 2)
                timeout = int(timeout_val) if isinstance(timeout_val, (int, str, float)) else 2
                fail_on_error_val = check_config.get("fail_on_error", True)
                fail_on_error = bool(fail_on_error_val) if isinstance(fail_on_error_val, (bool, int, str)) else True
                merged_checks[str(check_name)] = DoctorCheckConfig(timeout=timeout, fail_on_error=fail_on_error)

    doctor_config = DoctorConfig(enabled_checks=enabled_checks, checks=merged_checks)

    # 处理siyuan配置
    siyuan_settings: dict[str, object] = settings.get("siyuan", {})  # type: ignore
    token_val = siyuan_settings.get("token", "")
    default_note_val = siyuan_settings.get("default_note", "")
    siyuan_config = SiyuanConfig(token=str(token_val), default_note=str(default_note_val))

    return Config(log=log_config, doctor=doctor_config, siyuan=siyuan_config)


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
    settings = LazySettings(  # type: ignore
        envvar_prefix="BEARTOOLS",
        settings_file=str(config_path),
        load_dotenv=True,
        core_loaders=["YAML", "ENV"],
    )

    # 转换为数据类保持接口兼容
    config = _convert_to_dataclass(settings)  # type: ignore
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
