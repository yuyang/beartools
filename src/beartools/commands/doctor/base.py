"""Doctor命令基础架构模块

定义检查框架的核心数据结构、基类和注册机制
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import importlib
import pkgutil
from typing import ClassVar


class CheckStatus(Enum):
    """检查状态枚举

    Attributes:
        SUCCESS: 检查成功
        FAILURE: 检查失败
        WARNING: 检查警告（有问题但不影响使用）
    """

    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"


@dataclass
class CheckResult:
    """检查结果数据类

    Attributes:
        name: 检查项名称
        status: 检查状态
        message: 结果描述信息
        duration: 检查执行耗时（秒）
        detail: 详细信息，可选，用于展示更多排查信息
    """

    name: str
    status: CheckStatus
    message: str
    duration: float
    detail: str | None = None


class BaseCheck(ABC):
    """检查项基类

    所有具体检查项都必须继承此类，并实现抽象方法和属性。

    Attributes:
        name: 检查项唯一名称
        description: 检查项描述
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """获取检查项名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """获取检查项描述"""
        pass

    @abstractmethod
    async def run(self) -> CheckResult:
        """执行检查

        Returns:
            CheckResult: 检查结果
        """
        pass


class CheckRegistry:
    """检查项注册器

    负责管理所有检查项的注册和查找，支持装饰器方式自动注册。
    使用单例模式维护全局注册信息。
    """

    # 全局注册字典：key为检查项名称，value为检查项实例
    _registry: ClassVar[dict[str, BaseCheck]] = {}

    @classmethod
    def register(cls, check_type: type[BaseCheck]) -> None:
        """注册一个检查项

        Args:
            check_type: 检查项类，必须继承自BaseCheck
        """
        instance = check_type()
        if instance.name in cls._registry:
            raise ValueError(f"检查项 {instance.name} 已经注册")
        cls._registry[instance.name] = instance

    @classmethod
    def get_check(cls, name: str) -> BaseCheck | None:
        """根据名称获取检查项

        Args:
            name: 检查项名称

        Returns:
            BaseCheck | None: 如果找到返回检查项实例，否则返回None
        """
        return cls._registry.get(name)

    @classmethod
    def get_all_checks(cls) -> list[BaseCheck]:
        """获取所有已注册的检查项

        Returns:
            list[BaseCheck]: 所有检查项实例列表
        """
        return list(cls._registry.values())

    @classmethod
    def clear(cls) -> None:
        """清空所有注册信息，主要用于测试"""
        cls._registry.clear()


def register_check(cls: type[BaseCheck]) -> type[BaseCheck]:
    """检查项注册装饰器

    使用方式：
    ```python
    @register_check
    class MyCheck(BaseCheck):
        @property
        def name(self) -> str:
            return "my_check"

        @property
        def description(self) -> str:
            return "我的自定义检查"

        def run(self) -> CheckResult:
            # 检查逻辑实现
            return CheckResult(...)
    ```

    Args:
        cls: 要注册的检查项类

    Returns:
        type[BaseCheck]: 原类，支持装饰器语法
    """
    CheckRegistry.register(cls)
    return cls


def auto_discover_checks(package_path: str = "beartools.commands.doctor.checks") -> None:
    """自动发现并导入指定包下的所有检查模块

    遍历checks目录下所有模块，执行导入触发装饰器注册。

    Args:
        package_path: 要扫描的包路径，默认为beartools.commands.doctor.checks
    """
    package = importlib.import_module(package_path)
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_path}.{module_name}")
