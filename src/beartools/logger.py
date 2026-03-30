"""异步日志系统模块

使用标准库logging的QueueHandler + QueueListener实现异步日志，
支持简单配置和高级配置两种方式，提供全局日志获取接口和优雅关闭功能。
"""

from __future__ import annotations

import atexit
from collections.abc import Mapping
import json
import logging
import logging.config
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import Queue
from typing import cast

import yaml

from .config import LogConfig, get_config

# 全局日志监听器实例
_queue_listener: QueueListener | None = None
# 标记是否已经初始化
_initialized: bool = False


def _get_log_level(level_str: str) -> int:
    """将日志级别字符串转换为logging常量

    Args:
        level_str: 日志级别字符串，不区分大小写，如"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"

    Returns:
        int: logging日志级别常量
    """
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_str.upper(), logging.INFO)


def _setup_simple_config(log_config: LogConfig) -> None:
    """简单配置方式，使用log.path和log.level配置异步日志

    Args:
        log_config: 日志配置对象
    """
    global _queue_listener, _initialized

    # 确保日志目录存在
    log_dir = log_config.path.parent
    if not log_dir.exists():
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise RuntimeError(f"无法创建日志目录: {log_dir}, 权限不足 - {e}") from e
        except OSError as e:
            raise RuntimeError(f"创建日志目录失败: {log_dir} - {e}") from e

    # 获取根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(_get_log_level(log_config.level))

    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 创建内存队列
    log_queue: Queue[logging.LogRecord] = Queue(-1)

    # 创建格式化器
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 创建文件处理器
    try:
        file_handler = logging.FileHandler(log_config.path, encoding="utf-8", mode="a")
    except PermissionError as e:
        raise RuntimeError(f"无法打开日志文件: {log_config.path}, 权限不足 - {e}") from e
    except OSError as e:
        raise RuntimeError(f"打开日志文件失败: {log_config.path} - {e}") from e

    file_handler.setFormatter(formatter)

    # 创建QueueHandler并设置到根logger
    queue_handler = QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)

    # 启动QueueListener后台线程
    _queue_listener = QueueListener(log_queue, console_handler, file_handler)
    _queue_listener.start()

    # 注册退出时的清理函数
    atexit.register(shutdown_logging)

    _initialized = True


def _setup_advanced_config(config_file: Path) -> None:
    """高级配置方式，使用外部配置文件

    支持YAML和JSON格式的标准logging配置。

    Args:
        config_file: 配置文件路径

    Raises:
        RuntimeError: 配置文件读取失败或格式错误时抛出
    """
    global _queue_listener, _initialized

    # 读取配置文件
    try:
        with open(config_file, encoding="utf-8") as f:
            if config_file.suffix.lower() in (".yaml", ".yml"):
                raw_config = cast(object, yaml.safe_load(f))
            elif config_file.suffix.lower() == ".json":
                raw_config = cast(object, json.load(f))
            else:
                raise ValueError(f"不支持的配置文件格式: {config_file.suffix}")
    except yaml.YAMLError as e:
        raise RuntimeError(f"YAML配置文件格式错误: {config_file} - {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON配置文件格式错误: {config_file} - {e}") from e
    except PermissionError as e:
        raise RuntimeError(f"无法读取配置文件: {config_file}, 权限不足 - {e}") from e
    except OSError as e:
        raise RuntimeError(f"读取配置文件失败: {config_file} - {e}") from e

    if not isinstance(raw_config, dict):
        raise RuntimeError(f"配置文件内容不是字典类型: {config_file}")

    # 转换为Mapping类型，满足dictConfig参数要求
    config_dict = cast(Mapping[str, object], raw_config)

    # 使用dictConfig进行配置（dictConfig需要dict[str, Any]，这里严格模式下只能忽略
    logging.config.dictConfig(config_dict)  # type: ignore[arg-type]
    _initialized = True


def _ensure_initialized() -> None:
    """确保日志系统已经初始化

    如果未初始化，则根据配置自动初始化。
    """
    global _initialized
    if not _initialized:
        config = get_config()
        log_config = config.log

        if log_config.config_file is not None:
            _setup_advanced_config(log_config.config_file)
        else:
            _setup_simple_config(log_config)


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器

    Args:
        name: 日志器名称，通常使用__name__

    Returns:
        logging.Logger: 日志器实例
    """
    _ensure_initialized()
    return logging.getLogger(name)


def shutdown_logging() -> None:
    """优雅关闭日志系统

    确保队列中所有日志事件都被处理完毕，然后停止监听器。
    """
    global _queue_listener, _initialized

    if _queue_listener is not None and _initialized:
        try:
            _queue_listener.stop()
        except Exception:
            pass
        _queue_listener = None
        _initialized = False


def reconfigure() -> None:
    """重新配置日志系统

    在配置变更后调用，重新加载配置并初始化日志系统。

    Raises:
        RuntimeError: 重新配置失败时抛出
    """
    global _initialized

    if _initialized:
        shutdown_logging()

    _ensure_initialized()
