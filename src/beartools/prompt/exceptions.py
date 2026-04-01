"""Prompt 模板异常定义"""

from __future__ import annotations


class PromptError(Exception):
    """Prompt 模块基础异常"""


class TemplateNotFoundError(PromptError):
    """模板文件不存在"""

    def __init__(self, template_name: str, search_path: str) -> None:
        self.template_name = template_name
        self.search_path = search_path
        super().__init__(f"模板 '{template_name}' 未找到，搜索路径: {search_path}")


class MissingParameterError(PromptError):
    """必填参数缺失"""

    def __init__(self, parameter_name: str, template_name: str) -> None:
        self.parameter_name = parameter_name
        self.template_name = template_name
        super().__init__(f"模板 '{template_name}' 缺少必填参数: '{parameter_name}'")


class TemplateRenderError(PromptError):
    """模板渲染失败"""

    def __init__(self, template_name: str, reason: str) -> None:
        self.template_name = template_name
        self.reason = reason
        super().__init__(f"模板 '{template_name}' 渲染失败: {reason}")
