"""单个 Prompt 模板的加载与渲染"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Never

from jinja2 import BaseLoader, Environment, Template, Undefined, UndefinedError

from .exceptions import MissingParameterError, TemplateNotFoundError, TemplateRenderError

# 匹配 {{var}} 和 {{var:default}} 的正则
_VARIABLE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\s*(?::\s*([^}]*))?\}\}")
# 将 {{var:default}} 转换为 {{var}} 的正则（用于 Jinja2 兼容）
_JINJA_COMPAT_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\s*:\s*[^}]*\}\}")


@dataclass(frozen=True)
class VariableInfo:
    """模板变量信息"""

    name: str
    has_default: bool
    default_value: str | None = None


def _to_jinja2_source(source: str) -> str:
    """将自定义语法 {{var:default}} 转换为 Jinja2 兼容的 {{var}}"""
    return _JINJA_COMPAT_PATTERN.sub(r"{{\1}}", source)


@dataclass
class PromptTemplate:
    """单个 Prompt 模板"""

    name: str
    source: str
    _jinja_template: Template | None = field(default=None, repr=False)

    @classmethod
    def from_file(cls, file_path: Path) -> PromptTemplate:
        """从文件加载模板

        Args:
            file_path: 模板文件路径

        Returns:
            PromptTemplate 实例

        Raises:
            TemplateNotFoundError: 文件不存在时抛出
        """
        if not file_path.exists():
            raise TemplateNotFoundError(file_path.stem, str(file_path.parent))

        source = file_path.read_text(encoding="utf-8")
        return cls(name=file_path.stem, source=source)

    @property
    def jinja_template(self) -> Template:
        """懒加载 Jinja2 模板对象"""
        if self._jinja_template is None:
            env = Environment(
                loader=BaseLoader(),
                undefined=StrictUndefined,  # type: ignore[misc]
                keep_trailing_newline=True,
            )
            jinja_source = _to_jinja2_source(self.source)
            object.__setattr__(self, "_jinja_template", env.from_string(jinja_source))
        return self._jinja_template  # type: ignore[return-value]

    def extract_variables(self) -> list[VariableInfo]:
        """提取模板中所有变量及其默认值信息

        Returns:
            变量信息列表
        """
        variables: list[VariableInfo] = []
        seen: set[str] = set()

        for match in _VARIABLE_PATTERN.finditer(self.source):
            var_name = match.group(1)
            default_raw = match.group(2)

            if var_name not in seen:
                seen.add(var_name)
                has_default = default_raw is not None
                default_value = (
                    default_raw.strip() if default_raw is not None else None  # type: ignore[misc]
                )
                variables.append(
                    VariableInfo(
                        name=var_name,
                        has_default=has_default,
                        default_value=default_value,  # type: ignore[misc]
                    )
                )

        return variables

    def render(self, params: dict[str, object] | None = None) -> str:
        """渲染模板

        Args:
            params: 参数字典，必填参数缺失时抛出 MissingParameterError

        Returns:
            渲染后的字符串

        Raises:
            MissingParameterError: 必填参数缺失时抛出
            TemplateRenderError: 渲染过程中发生其他错误时抛出
        """
        params = params or {}

        # 预处理：为有默认值的变量填充默认值
        merged_params: dict[str, object] = dict(params)
        for var_info in self.extract_variables():
            if var_info.has_default and var_info.name not in merged_params:
                merged_params[var_info.name] = var_info.default_value

            # 处理嵌套变量 {{user.name}} — 需要确保嵌套路径存在
            if "." in var_info.name:
                parts = var_info.name.split(".")
                root = parts[0]
                if root not in merged_params:
                    merged_params[root] = {}
                # 逐层构建嵌套字典
                current: dict[str, object] = merged_params[root]  # type: ignore[assignment]
                for part in parts[1:-1]:
                    if not isinstance(current, dict):
                        current = {}
                    if part not in current:
                        current[part] = {}
                    current = current[part]  # type: ignore[assignment]

        try:
            return self.jinja_template.render(merged_params)
        except UndefinedError as e:
            # 从 Jinja2 的 UndefinedError 中提取缺失的变量名
            var_name = _extract_undefined_name(str(e))
            raise MissingParameterError(var_name, self.name) from e
        except Exception as e:
            raise TemplateRenderError(self.name, str(e)) from e


class StrictUndefined(Undefined):
    """严格的未定义变量处理 — 任何未定义变量访问都会抛出异常"""

    def _fail(self) -> Never:
        raise UndefinedError(f"'{self._undefined_name}' is undefined")

    def __getattr__(self, item: str) -> Never:
        self._fail()

    def __str__(self) -> str:
        self._fail()

    def __repr__(self) -> str:
        self._fail()

    def __bool__(self) -> bool:
        self._fail()


def _extract_undefined_name(error_message: str) -> str:
    """从 Jinja2 UndefinedError 消息中提取变量名"""
    match = re.search(r"'([^']+)' is undefined", error_message)
    if match:
        return match.group(1)
    return error_message
