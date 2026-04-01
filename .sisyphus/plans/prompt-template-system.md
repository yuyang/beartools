# Prompt 模板管理系统

## 需求

设计一个 prompt 管理系统，满足：
- 每个 prompt 保存在单独的 `.md` 文件中
- 支持 Jinja2 风格变量语法 `{{var}}`
- 支持带默认值的可选变量 `{{var:default}}`（用 `:` 分隔）
- 支持嵌套变量 `{{user.name}}`（点号访问）
- 缺失必填参数时抛出异常
- 不支持条件渲染

## 架构设计

### 模块结构

```
src/beartools/prompt/
├── __init__.py          # 公共导出
├── exceptions.py        # 自定义异常类
├── template.py          # PromptTemplate — 单个模板的加载/解析/渲染
└── manager.py           # PromptManager — 模板目录管理/缓存/便捷渲染

prompts/                  # 模板文件存放目录（项目根目录下）
├── code_review.md
├── bug_analysis.md
└── feature_design.md
```

### 核心类

| 类 | 职责 |
|---|---|
| `PromptTemplate` | 从文件加载单个模板，提取变量信息，渲染模板 |
| `PromptManager` | 管理模板目录，提供缓存，便捷渲染接口 |
| `VariableInfo` | 变量元数据（名称、是否有默认值、默认值） |

### 异常体系

| 异常 | 触发场景 |
|---|---|
| `PromptError` | 基础异常类 |
| `TemplateNotFoundError` | 模板文件不存在 |
| `MissingParameterError` | 必填参数缺失 |
| `TemplateRenderError` | 渲染过程其他错误 |

### 变量语法

```
{{var}}              → 必填，缺失抛 MissingParameterError
{{var:default}}      → 可选，缺失时使用 default
{{user.name}}        → 嵌套访问，要求 params={"user": {"name": "..."}}
```

### 实现策略

- 底层使用 Jinja2 引擎渲染
- 自定义 `{{var:default}}` 语法在传给 Jinja2 前通过正则预处理为 `{{var}}`
- 默认值填充在 `render()` 方法中自行处理
- 使用自定义 `StrictUndefined` 类确保任何未定义变量都抛异常

## 实现状态

- [x] 添加 jinja2 依赖
- [x] 创建 `prompt/exceptions.py` — 4 个异常类
- [x] 创建 `prompt/template.py` — PromptTemplate + VariableInfo + StrictUndefined
- [x] 创建 `prompt/manager.py` — PromptManager + 单例 `get_prompt_manager()` + `reset_prompt_manager()`
- [x] 创建 `prompt/__init__.py` — 公共导出（含单例函数）
- [x] 创建示例模板：code_review.md, bug_analysis.md, feature_design.md
- [x] 编写 32 个单元测试（含 3 个单例测试）
- [x] 通过 pytest (32/32), ruff lint, mypy typecheck

## 单例模式

采用与 `config.py` 一致的模块级变量 + `get_xxx()` 函数风格：

```python
# 全局单例
_instance: PromptManager | None = None

def get_prompt_manager(prompt_dir: str | Path | None = None) -> PromptManager:
    """获取全局 PromptManager 单例，仅首次调用时 prompt_dir 生效"""
    global _instance
    if _instance is None:
        _instance = PromptManager(prompt_dir=prompt_dir)
    return _instance

def reset_prompt_manager() -> None:
    """重置单例（主要用于测试）"""
    global _instance
    _instance = None
```

## 使用示例

```python
from beartools.prompt import get_prompt_manager, MissingParameterError

# 推荐：全局单例
pm = get_prompt_manager()

# 渲染 — 缺失必填参数抛 MissingParameterError
result = pm.render("code_review", {
    "file_path": "src/main.py",
    "language": "python",
    "code": "def hello(): ...",
})

# 查看模板变量
vars = pm.get_variables("code_review")

# 列出所有可用模板
templates = pm.list_templates()
```
