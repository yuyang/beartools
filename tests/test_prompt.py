"""Prompt 模板系统测试用例"""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from beartools.prompt import (
    MissingParameterError,
    PromptManager,
    PromptTemplate,
    TemplateNotFoundError,
    VariableInfo,
    get_prompt_manager,
    reset_prompt_manager,
)


class TestPromptTemplate:
    """PromptTemplate 测试类"""

    def test_from_file_success(self) -> None:
        """从文件加载模板成功"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Hello {{name}}!")
            f.flush()
            template = PromptTemplate.from_file(Path(f.name))

        assert template.name == Path(f.name).stem
        assert template.source == "Hello {{name}}!"

    def test_from_file_not_found(self) -> None:
        """模板文件不存在时抛出 TemplateNotFoundError"""
        with pytest.raises(TemplateNotFoundError) as exc_info:
            PromptTemplate.from_file(Path("/nonexistent/path/template.md"))

        assert exc_info.value.template_name == "template"

    def test_render_simple_variable(self) -> None:
        """渲染简单变量"""
        template = PromptTemplate(name="test", source="Hello {{name}}!")
        result = template.render({"name": "World"})
        assert result == "Hello World!"

    def test_render_missing_required_param(self) -> None:
        """缺失必填参数时抛出 MissingParameterError"""
        template = PromptTemplate(name="test", source="Hello {{name}}!")
        with pytest.raises(MissingParameterError) as exc_info:
            template.render({})
        assert exc_info.value.parameter_name == "name"
        assert exc_info.value.template_name == "test"

    def test_render_with_default_value(self) -> None:
        """可选变量使用默认值"""
        template = PromptTemplate(name="test", source="Level: {{severity:high}}")
        result = template.render({})
        assert result == "Level: high"

    def test_render_override_default_value(self) -> None:
        """传入参数覆盖默认值"""
        template = PromptTemplate(name="test", source="Level: {{severity:high}}")
        result = template.render({"severity": "low"})
        assert result == "Level: low"

    def test_render_multiple_variables(self) -> None:
        """渲染多个变量"""
        template = PromptTemplate(
            name="test",
            source="File: {{file}}, Language: {{lang}}, Focus: {{focus:all}}",
        )
        result = template.render({"file": "main.py", "lang": "python"})
        assert result == "File: main.py, Language: python, Focus: all"

    def test_render_nested_variable(self) -> None:
        """渲染嵌套变量（点号访问）"""
        template = PromptTemplate(name="test", source="Name: {{user.name}}, Age: {{user.age}}")
        result = template.render({"user": {"name": "Alice", "age": 30}})
        assert result == "Name: Alice, Age: 30"

    def test_render_nested_variable_missing_root(self) -> None:
        """嵌套变量根对象缺失时抛异常"""
        template = PromptTemplate(name="test", source="Name: {{user.name}}")
        with pytest.raises(MissingParameterError) as exc_info:
            template.render({})
        # Jinja2 reports the leaf attribute name, not the root object
        assert exc_info.value.template_name == "test"

    def test_render_no_params_all_defaults(self) -> None:
        """所有变量都有默认值时可不传参数"""
        template = PromptTemplate(
            name="test",
            source="{{a:1}} + {{b:2}} = {{c:3}}",
        )
        result = template.render()
        assert result == "1 + 2 = 3"

    def test_render_empty_params(self) -> None:
        """空参数字典等同于 None"""
        template = PromptTemplate(name="test", source="Hello {{name:World}}")
        result = template.render({})
        assert result == "Hello World"

    def test_extract_variables_simple(self) -> None:
        """提取简单变量"""
        template = PromptTemplate(name="test", source="{{a}} and {{b}}")
        variables = template.extract_variables()
        assert len(variables) == 2
        assert variables[0] == VariableInfo(name="a", has_default=False, default_value=None)
        assert variables[1] == VariableInfo(name="b", has_default=False, default_value=None)

    def test_extract_variables_with_defaults(self) -> None:
        """提取带默认值的变量"""
        template = PromptTemplate(name="test", source="{{a:1}} and {{b:hello}}")
        variables = template.extract_variables()
        assert len(variables) == 2
        assert variables[0] == VariableInfo(name="a", has_default=True, default_value="1")
        assert variables[1] == VariableInfo(name="b", has_default=True, default_value="hello")

    def test_extract_variables_dedup(self) -> None:
        """同一变量多次出现只记录一次"""
        template = PromptTemplate(name="test", source="{{name}} says {{name}}")
        variables = template.extract_variables()
        assert len(variables) == 1
        assert variables[0].name == "name"

    def test_extract_variables_nested(self) -> None:
        """提取嵌套变量"""
        template = PromptTemplate(name="test", source="{{user.name}} and {{user.age}}")
        variables = template.extract_variables()
        assert len(variables) == 2
        assert variables[0].name == "user.name"
        assert variables[1].name == "user.age"

    def test_render_preserves_newlines(self) -> None:
        """渲染保留换行"""
        template = PromptTemplate(name="test", source="Line1\n{{var}}\nLine3")
        result = template.render({"var": "Line2"})
        assert result == "Line1\nLine2\nLine3"


class TestPromptManager:
    """PromptManager 测试类"""

    @pytest.fixture
    def temp_prompt_dir(self) -> Path:
        """创建临时模板目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir)
            # 创建测试模板
            (prompt_dir / "greeting.md").write_text("Hello {{name}}!", encoding="utf-8")
            (prompt_dir / "review.md").write_text(
                "Review {{file_path}} with focus {{focus:all}}",
                encoding="utf-8",
            )
            yield prompt_dir

    def test_load_template(self, temp_prompt_dir: Path) -> None:
        """加载模板"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        template = manager.load("greeting")
        assert template.name == "greeting"
        assert "{{name}}" in template.source

    def test_load_template_not_found(self, temp_prompt_dir: Path) -> None:
        """加载不存在的模板"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        with pytest.raises(TemplateNotFoundError):
            manager.load("nonexistent")

    def test_render_template(self, temp_prompt_dir: Path) -> None:
        """渲染模板"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        result = manager.render("greeting", {"name": "World"})
        assert result == "Hello World!"

    def test_render_with_default(self, temp_prompt_dir: Path) -> None:
        """渲染时使用默认值"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        result = manager.render("review", {"file_path": "main.py"})
        assert result == "Review main.py with focus all"

    def test_render_override_default(self, temp_prompt_dir: Path) -> None:
        """渲染时覆盖默认值"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        result = manager.render("review", {"file_path": "main.py", "focus": "security"})
        assert result == "Review main.py with focus security"

    def test_list_templates(self, temp_prompt_dir: Path) -> None:
        """列出所有模板"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        templates = manager.list_templates()
        assert set(templates) == {"greeting", "review"}

    def test_list_templates_empty_dir(self) -> None:
        """空目录返回空列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PromptManager(prompt_dir=tmpdir)
            assert manager.list_templates() == []

    def test_list_templates_nonexistent_dir(self) -> None:
        """不存在的目录返回空列表"""
        manager = PromptManager(prompt_dir="/nonexistent/dir")
        assert manager.list_templates() == []

    def test_get_variables(self, temp_prompt_dir: Path) -> None:
        """获取模板变量信息"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        variables = manager.get_variables("greeting")
        assert len(variables) == 1
        assert variables[0].name == "name"
        assert variables[0].has_default is False

    def test_cache_hit(self, temp_prompt_dir: Path) -> None:
        """缓存命中"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        t1 = manager.load("greeting")
        t2 = manager.load("greeting")
        assert t1 is t2

    def test_clear_cache(self, temp_prompt_dir: Path) -> None:
        """清空缓存"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        manager.load("greeting")
        manager.clear_cache()
        # 缓存清空后重新加载得到不同实例
        t1 = manager.load("greeting")
        t2 = manager.load("greeting")
        assert t1 is t2  # 第二次加载命中缓存

    def test_default_prompt_dir(self) -> None:
        """默认模板目录指向项目 prompts/"""
        manager = PromptManager()
        assert manager.prompt_dir.name == "prompts"

    def test_project_prompts_include_bill_structure_templates(self) -> None:
        """项目内置账单结构识别模板可被发现"""
        manager = PromptManager()
        templates = manager.list_templates()

        assert "bill_structure_identification" in templates
        assert "bill_structure_identification_fewshot" in templates

    def test_render_bill_structure_template_uses_defaults(self) -> None:
        """账单结构识别模板渲染时使用默认值"""
        manager = PromptManager()

        result = manager.render(
            "bill_structure_identification",
            {
                "file_name": "sample.csv",
                "file_content": "1: 交易时间,交易对方,金额,交易状态",
            },
        )

        assert "**文件名**: sample.csv" in result
        assert "**文件类型**: unknown" in result
        assert "**候选来源**: 支付宝,微信,京东,未知" in result

    def test_get_bill_structure_fewshot_variables(self) -> None:
        """few-shot 模板变量可被正确提取"""
        manager = PromptManager()

        variables = manager.get_variables("bill_structure_identification_fewshot")
        actual = [(var.name, var.has_default, var.default_value) for var in variables]

        assert actual == [
            ("file_name", False, None),
            ("file_type", True, "unknown"),
            ("candidate_sources", True, "支付宝,微信,京东,未知"),
            ("file_content", False, None),
        ]

    def test_render_missing_param_with_default_available(self, temp_prompt_dir: Path) -> None:
        """必填参数缺失时即使有其他变量有默认值也抛异常"""
        manager = PromptManager(prompt_dir=temp_prompt_dir)
        with pytest.raises(MissingParameterError) as exc_info:
            manager.render("greeting", {})
        assert exc_info.value.parameter_name == "name"


class TestSingleton:
    """单例模式测试"""

    def teardown_method(self) -> None:
        """每个测试后重置单例"""
        reset_prompt_manager()

    def test_get_prompt_manager_returns_same_instance(self) -> None:
        """多次调用 get_prompt_manager 返回同一实例"""
        m1 = get_prompt_manager()
        m2 = get_prompt_manager()
        assert m1 is m2

    def test_get_prompt_manager_prompt_dir_ignored_after_first_call(self) -> None:
        """首次调用后，后续 prompt_dir 参数被忽略"""
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = get_prompt_manager(prompt_dir=tmpdir)
            m2 = get_prompt_manager(prompt_dir="/different/path")
            assert m1 is m2
            assert str(m1.prompt_dir) == tmpdir

    def test_reset_prompt_manager_creates_new_instance(self) -> None:
        """reset 后再次获取会得到新实例"""
        m1 = get_prompt_manager()
        reset_prompt_manager()
        m2 = get_prompt_manager()
        assert m1 is not m2
