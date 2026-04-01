"""Prompt 模板管理器 — 负责模板加载、缓存和便捷渲染"""

from __future__ import annotations

from pathlib import Path

from .template import PromptTemplate, VariableInfo

# 全局单例
_instance: PromptManager | None = None


class PromptManager:
    """Prompt 模板管理器

    负责从指定目录加载模板文件，提供缓存和便捷渲染接口。

    Usage:
        manager = PromptManager(prompt_dir="prompts")
        result = manager.render("code_review", {"file_path": "main.py", "code": "..."})
    """

    def __init__(self, prompt_dir: str | Path | None = None) -> None:
        """初始化 PromptManager

        Args:
            prompt_dir: 模板目录路径，默认为项目根目录下的 prompts/
        """
        if prompt_dir is None:
            self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"
        else:
            self.prompt_dir = Path(prompt_dir)

        self._cache: dict[str, PromptTemplate] = {}

    def _resolve_path(self, template_name: str) -> Path:
        """解析模板文件路径"""
        return self.prompt_dir / f"{template_name}.md"

    def load(self, template_name: str, use_cache: bool = True) -> PromptTemplate:
        """加载模板

        Args:
            template_name: 模板名称（不含 .md 后缀）
            use_cache: 是否使用缓存，默认 True

        Returns:
            PromptTemplate 实例

        Raises:
            TemplateNotFoundError: 模板文件不存在时抛出
        """
        if use_cache and template_name in self._cache:
            return self._cache[template_name]

        file_path = self._resolve_path(template_name)
        template = PromptTemplate.from_file(file_path)
        self._cache[template_name] = template
        return template

    def render(self, template_name: str, params: dict[str, object] | None = None) -> str:
        """加载并渲染模板

        Args:
            template_name: 模板名称（不含 .md 后缀）
            params: 渲染参数

        Returns:
            渲染后的字符串

        Raises:
            TemplateNotFoundError: 模板文件不存在时抛出
        """
        template = self.load(template_name)
        return template.render(params)

    def get_variables(self, template_name: str) -> list[VariableInfo]:
        """获取模板的变量信息

        Args:
            template_name: 模板名称

        Returns:
            变量信息列表
        """
        template = self.load(template_name)
        return template.extract_variables()

    def list_templates(self) -> list[str]:
        """列出所有可用模板

        Returns:
            模板名称列表（不含 .md 后缀）
        """
        if not self.prompt_dir.exists():
            return []
        return [f.stem for f in self.prompt_dir.glob("*.md")]

    def clear_cache(self) -> None:
        """清空模板缓存"""
        self._cache.clear()


def get_prompt_manager(prompt_dir: str | Path | None = None) -> PromptManager:
    """获取全局 PromptManager 单例

    Args:
        prompt_dir: 模板目录路径，仅首次调用时生效

    Returns:
        PromptManager 单例
    """
    global _instance
    if _instance is None:
        _instance = PromptManager(prompt_dir=prompt_dir)
    return _instance


def reset_prompt_manager() -> None:
    """重置单例（主要用于测试）"""
    global _instance
    _instance = None
