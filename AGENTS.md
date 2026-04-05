# beartools 项目 Agent 操作指南

本文件是供AI编码助手使用的项目规范文档，所有操作必须严格遵循以下规则。

## 一、项目基本信息
- 项目名称：beartools
- 项目类型：Python 工具库
- Python 版本：3.13+
- 包管理工具：uv
- 虚拟环境路径：`.venv`

## 依赖版本规范
- 所有 `pyproject.toml` 中的依赖必须使用具体版本号（`==`），禁止使用 `>=`、`<=` 等范围版本
- 添加新依赖时，先 `uv add <package>`，再查看当前安装版本并改为 `==` 锁定

## 参考文档
- 思源笔记API文档：https://github.com/siyuan-note/siyuan/blob/master/API_zh_CN.md

## 二、常用命令指南
### 环境操作
```bash
# 激活虚拟环境
source .venv/bin/activate

# 同步安装所有依赖
uv sync

# 添加依赖包
uv add <package_name>

# 添加开发依赖包
uv add --dev <package_name>

# 移除依赖包
uv remove <package_name>
```

### 运行与测试
```bash
# 运行Python脚本
uv run <script_path>

# 运行所有测试（推荐使用pytest）
uv run pytest tests/ -xvs

# 运行单个测试文件
uv run pytest tests/test_file.py -xvs

# 运行单个测试函数
uv run pytest tests/test_file.py::test_function_name -xvs

# 生成测试覆盖率报告
uv run pytest tests/ --cov=src --cov-report=html
```

### 代码质量检查
```bash
# 代码lint检查（推荐使用ruff）
uv run ruff check .

# 自动修复lint问题
uv run ruff check . --fix

# 代码格式化
uv run ruff format .

# 类型检查（推荐使用mypy）
uv run mypy .
```

## 三、功能模块说明
### 命令行功能
- `doctor`：环境健康检查，异步并发执行，内置检查项：
  - `google_ping`：Google网络连通性检查
  - `opencli`：opencli工具可用性检查
  - `siyuan`：思源笔记6806端口检查
- `siyuan`：思源笔记相关操作：
  - `ls-notebooks`：列出所有笔记本
  - `export-md`：导出指定笔记为Markdown格式
- `record`：URL记录管理：
  - `getall`：列出最近100条记录，按更新时间倒序

### 核心组件
- **日志系统**：按天自动切分，保留30天历史日志，存储在`log/`目录
- **记录管理器**：基于SQLite的URL记录存储，支持URL查询、标记、全量查询
- **配置系统**：支持配置文件+环境变量，配置文件位于`config/beartools.yaml`

### 日志与调试规范
- 默认不要把日志打印到 console，避免干扰命令行输出和测试结果
- 需要排查问题时，优先查看 `log/` 目录下的日志文件，再结合必要的临时调试信息定位问题

### 数据存储位置
- 配置文件：`config/beartools.yaml`（私有，已加入.gitignore）、`config/beartools.yaml.sample`（公开示例）
- 日志文件：`log/`目录
- SQLite数据库：`data/record/beartools.db`

## 四、代码风格规范
### 1. 基础规范
- 所有代码必须兼容Python 3.13+
- 注释、文档字符串全部使用中文书写
- 行长度建议不超过120字符
- 使用4空格缩进，禁止使用tab

### 2. 导入规范
- 导入顺序：标准库 → 第三方库 → 本地项目模块，每组之间用空行分隔
- 禁止使用`from module import *`通配符导入
- 导入排序遵循ruff默认规则，格式化时自动处理

### 3. 命名规范
- 类名：大驼峰命名法（PascalCase），例如：`UserDataLoader`
- 函数名、方法名、变量名：小写下划线命名法（snake_case），例如：`load_user_data`
- 常量名：全大写下划线命名法，例如：`MAX_RETRY_TIMES = 3`
- 私有属性/方法：前缀加单下划线，例如：`_internal_calculate()`

### 4. 类型提示规范
- 所有函数、方法的参数和返回值必须添加类型提示
- 复杂类型使用typing模块标注，例如：`list[str]`, `dict[str, int]`, `Optional[str]`
- 禁止使用`Any`类型，除非特殊情况必须说明理由

### 5. 错误处理规范
- 禁止使用空的`except:`块，必须捕获具体异常类型
- 禁止直接捕获`Exception`父类，除非明确需要
- 异常信息必须清晰说明错误原因，方便调试
- 资源操作必须使用`with`上下文管理器，确保资源正确释放

### 6. 接口规范
- 所有REST API接口返回值必须使用`APIDataVO<T>`格式
- 成功返回：code=1，data为返回数据
- 失败返回：code=-1，msg为错误信息
- 导入路径：`import com.fenbilantian.data.APIDataVO`

## 五、Git 操作规范
### 核心规则
- **禁止自动提交**：仅当用户明确要求"提交"/"commit"时才执行提交操作
- 仅执行本地Git操作（status/diff/log/add/commit/branch/stash/reset），push/pull等网络操作告知用户手动执行
- 所有提交后统一告知用户执行`git push review`

### Commit Message 规范
格式：`前缀: 描述`（标题行长度不超过50字符）
| 前缀 | 含义 | 适用场景 |
|------|------|----------|
| ADD | 新增 | 新增功能、文件、模块 |
| MOD | 修改 | 调整、优化已有功能 |
| FIX | 修复 | 修复缺陷、异常、错误行为 |
| DEL | 删除 | 移除功能、文件、废弃代码 |
| REFACTOR | 重构 | 代码结构调整，不改变外部行为 |

## 六、协作规则
### 先问再做原则
以下场景必须先确认再动手，禁止猜测：
1. 架构设计、技术选型、分层方案
2. 业务规则不明确（如状态流转、权限逻辑）
3. 存在多种实现方案且各有取舍
4. 涉及数据库表结构变更

### 分步执行原则
1. 大任务拆成小步骤，逐步推进
2. 每完成一层（如 Storage → Logic → Controller）确认后再继续
3. 不要一口气生成所有代码，跑偏会被中断

### 不确定就问原则
1. 宁可多问一句，不要假设业务逻辑
2. 遇到项目中没见过的模式，先问"现有代码是怎么处理的"
3. 不确定字段类型、命名、归属模块时，问清楚再写

### 质疑精神原则
1. 文档描述与实际代码不一致时，以代码为准，并提醒用户更新文档
2. 产品文档的字段定义、业务规则有遗漏或矛盾时，主动指出
3. 引用文档中的信息前，先与代码交叉验证，不一致时明确告知用户

## 七、禁止行为
1. 禁止使用`@ts-ignore`、`as any`等类型忽略操作
2. 禁止删除现有测试用例来"通过"测试
3. 禁止提交虚拟环境、缓存文件、敏感信息到Git
4. 禁止在没有明确需求的情况下进行大范围重构
5. 禁止盲目实现用户需求，发现设计缺陷时主动提出优化建议
