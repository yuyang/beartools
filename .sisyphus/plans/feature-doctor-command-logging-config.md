# 功能开发计划：doctor命令 + 日志系统 + YAML配置文件

## TL;DR
> **Quick Summary**: 实现doctor命令行子命令（检查www.google.com连通性）、可配置日志系统、YAML格式配置文件
> 
> **Deliverables**:
> - 新增pyproject.toml依赖：typer, pyyaml, ping3
> - 新增配置文件模板：beartools.example.yaml
> - 新增配置读取模块：src/beartools/config.py
> - 新增日志初始化模块：src/beartools/logger.py
> - 新增命令行入口：src/beartools/cli.py
> - 新增doctor命令实现：src/beartools/commands/doctor.py
> 
> **Estimated Effort**: Short (1-2小时)
> **Parallel Execution**: NO - 顺序执行
> **Critical Path**: 添加依赖 → 配置读取 → 日志系统 → doctor命令 → 测试

## Context
### Original Request
1. 增加命令行参数doctor，检查若干指定项目，首期实现检查能否ping通www.google.com
2. 增加日志功能
3. 增加YAML类型配置文件，目前仅配置log的存储位置

### 依赖说明
| 依赖包 | 版本要求 | 引入原因 |
|--------|----------|----------|
| `typer` | ^0.12.5 | 轻量级命令行框架，基于Python类型提示自动生成CLI接口，支持子命令、参数校验、自动帮助文档，替代argparse减少样板代码，开发效率高 |
| `pyyaml` | ^6.0.3 | Python生态最成熟的YAML解析库，支持YAML 1.1/1.2标准，安全稳定，用于读取项目YAML格式配置文件 |
| `ping3` | ^4.0.7 | 纯Python实现的ICMP ping工具，跨平台兼容Windows/macOS/Linux，不需要调用系统ping命令，API简单易用，可直接返回延迟时间和连通状态 |
| `rich` | ^13.9.4 | Python终端富文本输出库，支持彩色输出、进度条、表格、Emoji等，让命令行输出更美观易读，用于doctor命令结果的彩色输出 |

> 日志功能使用Python标准库`logging`实现，不需要额外引入第三方依赖。

## Work Objectives
### Core Objective
实现基础的命令行框架、可配置日志系统和配置文件管理，为后续功能扩展提供基础支撑。

### Concrete Deliverables
1. 命令行接口：支持`beartools doctor`子命令，输出google连通性检查结果
2. 配置系统：支持读取`beartools.yaml`配置文件，包含`log.path`配置项
3. 日志系统：根据配置文件路径输出日志，包含时间、级别、消息字段
4. 配置模板：提供`beartools.example.yaml`示例配置文件，说明配置项含义

### Definition of Done
- [ ] 执行`beartools doctor`命令正确返回连通性结果：成功显示延迟，失败显示错误信息
- [ ] 日志文件按配置路径生成，包含doctor命令执行的详细日志
- [ ] 修改配置文件中`log.path`后，日志自动输出到新路径
- [ ] 所有代码通过ruff检查、mypy类型检查，无错误
- [ ] 提供配置文件示例和命令行使用说明

### Must Have
- YAML配置文件支持，格式简洁易读，**仅读取当前工作目录下的`.config/beartools.yaml`**，不需要全局路径或环境变量查找
- 支持日志配置为独立文件，可在主配置中指定单独的日志配置文件路径，灵活配置日志格式、级别、输出目标等
- 日志支持文件输出，路径可配置，默认输出到`.logs/beartools.log`
- doctor命令**采用插件化可扩展架构**，支持轻松添加多种检查项，无需修改核心逻辑
- doctor命令支持彩色输出，成功绿色、失败红色、警告黄色，使用Emoji图标增强可读性，支持多检查结果统一汇总展示
- 当前版本实现两个检查项：
  1. **Google连通性检查**：ping www.google.com检查网络连通性
  2. **OpenCLI检查**：检查opencli命令是否已安装，若已安装则自动执行`opencli doctor`并解析检查结果
- 架构预留扩展能力，后续可轻松添加更多检查项
- 跨平台兼容Windows/macOS/Linux

### Must NOT Have
- 不引入不必要的第三方依赖
- 不破坏现有项目结构
- 不硬编码任何配置项，所有可配置项都放到配置文件中

## Execution Strategy
### 执行步骤（顺序执行）
```
Step 1: 添加所需依赖到pyproject.toml
Step 2: 实现配置文件读取模块
Step 3: 实现日志系统初始化模块
Step 4: 实现命令行入口和doctor子命令
Step 5: 编写配置文件模板
Step 6: 功能测试和验证
Step 7: 代码质量检查
```

### TODOs
- [ ] 1. 添加依赖到pyproject.toml
  **What to do**:
  - 执行`uv add typer pyyaml ping3`添加生产依赖
  - 验证依赖安装成功

  **QA Scenarios**:
  - 执行`uv sync`无错误
  - 执行`uv run python -c "import typer, yaml, ping3"`无导入错误

- [ ] 2. 实现配置文件读取模块（src/beartools/config.py）
  **What to do**:
  - 仅读取当前工作目录下的`.config/beartools.yaml`配置文件，不需要多路径查找或环境变量支持
  - 定义配置数据结构（@dataclass），包含：
    - `log.path`: 日志文件输出路径，默认值为`.logs/beartools.log`
    - `log.level`: 日志级别，默认值为`INFO`
    - `log.config_file`: 可选，单独的日志配置文件路径，若指定则优先使用该文件的日志配置
    - `doctor.timeout`: ping操作超时时间，默认2秒
  - 配置文件不存在时自动使用默认配置值，不报错
  - 处理配置文件格式错误、权限不足等异常情况，输出友好提示
  - 不使用unsafe_load解析YAML，防止注入风险
  - 自动创建`.config`目录（如果不存在），避免路径不存在错误

  **Must NOT do**:
  - 不读取用户主目录、环境变量等其他位置的配置文件，仅识别当前目录下的`.config/beartools.yaml`
  - 不泄露配置文件中的敏感信息到日志或输出

  **QA Scenarios**:
  - 配置文件存在且格式正确时，正确读取`log.path`配置项
  - 配置文件不存在时，使用默认配置值
  - 配置文件格式错误时，抛出清晰的错误提示
  - mypy类型检查无错误

- [ ] 3. 实现日志系统初始化模块（src/beartools/logger.py）
  **What to do**:
  - 基于标准库`logging`实现**异步日志系统**，采用官方推荐的`QueueHandler + QueueListener`方案（无额外第三方依赖）：
    1. 所有日志事件先写入内存队列，不阻塞业务线程
    2. 启动独立的后台线程负责日志的实际IO操作（写文件、输出控制台）
    3. 程序退出时自动停止Listener线程，确保所有日志都被持久化到文件
  - 支持两种配置方式：
    1. 简单配置：使用主配置文件中的`log.path`和`log.level`参数生成默认日志配置
    2. 高级配置：如果主配置中指定了`log.config_file`，则优先加载该独立日志配置文件（支持YAML/JSON格式的完整logging配置）
  - 默认日志格式包含：时间、日志级别、模块名、日志内容
  - 日志同时输出到控制台和配置的文件路径
  - 自动创建日志文件所在目录（如果不存在），默认`.logs/`目录不存在时自动创建
  - 对外接口保持和标准logging完全兼容，提供全局get_logger函数，上层业务代码无需感知异步实现
  - 日志级别默认INFO，支持通过配置调整
  - 提供`shutdown_logging()`函数，用于程序退出前优雅关闭日志系统，确保所有日志写入完成

  **Must NOT do**:
  - 不引入第三方日志库，使用标准库实现异步能力
  - 不修改日志调用接口，上层代码仍然使用标准的`logger.info()`/`logger.error()`方法
  - 不输出敏感信息到日志文件
  - 不丢失日志事件，程序退出时必须确保队列中所有日志都被处理

  **QA Scenarios**:
  - 未指定独立日志配置文件时，按主配置的log.path和log.level生成日志，格式正确
  - 指定独立日志配置文件时，优先使用该文件的配置，格式、输出目标等完全按配置生效
  - INFO/ERROR级别日志正确区分
  - 日志同时输出到控制台和文件
  - 多次调用初始化函数不重复创建队列和Listener线程
  - 日志目录不存在时自动创建，不报错
  - 异步写入不阻塞主线程：批量打印大量日志时，主线程不会被IO操作阻塞
  - 程序退出时所有日志完整写入：即使有大量日志在队列中，程序退出前都会被处理完成，不丢失日志
  - 支持并发写入：多线程/协程同时写日志不会出现内容错乱或丢失

- [ ] 4. 实现命令行入口和doctor子命令（可扩展架构）
  **What to do**:
  **架构设计（支持多check扩展）**：
  1. 定义统一检查接口：
     - 数据类`CheckResult`：包含`name`(检查项名称)、`status`(success/failure/warning)、`message`(结果描述)、`duration`(耗时)、`detail`(详细信息)字段
     - 基类`BaseCheck`：所有检查项继承此基类，必须实现`name`属性、`description`属性和`run() -> CheckResult`方法
  2. 实现检查项注册机制：
     - `CheckRegistry`类：负责注册、发现、管理所有检查项
     - 支持通过装饰器`@register_check`自动注册新检查项，添加新检查不需要修改核心逻辑
  3. 检查项独立存放目录：`src/beartools/commands/doctor/checks/`，每个检查项为独立文件，解耦各检查逻辑

  **当前版本实现**：
  - 实现两个检查项：
    1. `GooglePingCheck`（`checks/google_ping.py`）：ping www.google.com检查网络连通性，默认超时2秒
    2. `OpenCliCheck`（`checks/opencli.py`）：
       - 第一步：跨平台检查`opencli`命令是否已安装（使用`shutil.which`）
       - 第二步：若已安装，自动执行`opencli doctor`命令，捕获返回码和输出
       - 第三步：解析`opencli doctor`的执行结果，返回对应状态
  - 配置支持：
    - 可在配置文件中配置`doctor.enabled_checks`指定要运行的检查项，默认两个检查都启用
    - 支持每个检查项独立参数配置：
      - `doctor.checks.google_ping.timeout`: ping超时时间（默认2秒）
      - `doctor.checks.opencli.timeout`: `opencli doctor`执行超时时间（默认10秒）
      - `doctor.checks.opencli.fail_on_error`: 是否将`opencli doctor`的失败作为检查失败（默认true）

  **doctor命令执行逻辑**：
  1. 初始化rich Console，支持自动检测终端彩色支持
  2. 从配置读取要运行的检查项列表和全局超时配置
  3. 从CheckRegistry获取对应检查项实例
  4. 串行执行所有检查（后续可扩展为并行执行），捕获每个检查的异常情况
  5. 统一汇总所有检查结果，彩色格式化输出：
     - 成功：绿色✅ + 绿色检查项名称 + 黄色延迟 + 结果描述
     - 失败：红色❌ + 红色检查项名称 + 错误原因
     - 警告：黄色⚠️ + 黄色检查项名称 + 警告信息
  6. 输出结果到终端，同时记录每个检查的详细信息到日志文件
  7. 支持命令行参数`--check`指定仅运行特定检查项（预留参数，当前版本可先不实现）

  **异常处理**：
  - 单个检查项失败不影响其他检查项执行
  - GooglePingCheck异常处理：捕获ping超时、权限不足、域名解析失败等各类异常，自动转换为对应检查结果
  - OpenCliCheck异常处理：
    - `opencli`命令不存在：返回失败状态，提示"opencli未安装，请先安装opencli"
    - `opencli doctor`执行超时：返回失败状态，提示"opencli doctor执行超时"
    - `opencli doctor`执行失败（非0返回码）：返回失败状态，展示错误输出摘要
    - 执行成功（0返回码）：返回成功状态，展示检查通过信息
  - 所有检查项执行超时自动终止，标记为失败

  **Must NOT do**:
  - 不使用系统ping命令，使用ping3库实现跨平台兼容
  - 不硬编码检查项列表，所有检查项通过注册机制动态发现
  - 不输出无意义的调试信息，保持命令行输出简洁美观

  **QA Scenarios**:
  - Google连通性检查正常：彩色输出✅ [green]Google连通性检查[/green] - 连通正常，延迟: [yellow]25 ms[/yellow]
  - Google连通性检查失败：彩色输出❌ [red]Google连通性检查[/red] - 连通失败 ([dim]网络不可达[/dim])
  - Google检查无权限：彩色输出⚠️ [yellow]Google连通性检查[/yellow] - 需要管理员/root权限执行ping操作
  - OpenCLI检查正常（已安装且doctor通过）：彩色输出✅ [green]OpenCLI环境检查[/green] - opencli已安装，doctor检查全部通过
  - OpenCLI检查未安装：彩色输出❌ [red]OpenCLI环境检查[/red] - opencli命令未找到，请先安装opencli
  - OpenCLI检查失败（已安装但doctor不通过）：彩色输出❌ [red]OpenCLI环境检查[/red] - opencli doctor检查失败 ([dim]2项检查未通过: 配置错误、依赖缺失[/dim])
  - OpenCLI执行超时：彩色输出⚠️ [yellow]OpenCLI环境检查[/yellow] - opencli doctor执行超时（10秒）
  - 多检查项并行执行：两个检查项都运行，单个失败不影响另一个，结果分别展示，最终汇总成功/失败数量
  - 执行日志正确写入到日志文件，包含每个检查的详细执行过程、参数和结果
  - 命令行帮助信息完整：`beartools --help`显示doctor子命令说明
  - 架构可扩展性验证：新增一个检查项只需要在`checks/`目录下添加新文件，实现BaseCheck接口，用装饰器注册即可，无需修改doctor命令主逻辑
  - 单个检查失败不影响整体执行，所有检查项都会运行完成并展示结果

- [ ] 5. 编写配置文件模板
  **What to do**:
  - 在项目`.config`目录下创建`beartools.example.yaml`示例配置文件，包含所有配置项示例和详细注释
  - 提供可选的单独日志配置文件示例：`.config/logging.example.yaml`，演示高级日志配置方式
  - 在`.gitignore`中添加：
    - `.config/beartools.yaml`（实际配置文件不提交）
    - `.logs/`（所有日志文件不提交）
    - 保留`.config/beartools.example.yaml`和`.config/logging.example.yaml`作为模板提交到仓库

  **QA Scenarios**:
  - 示例配置文件格式正确，可直接复制为`beartools.yaml`使用
  - 注释清晰说明每个配置项的作用和可选值
  - 单独日志配置文件示例包含完整的logging配置选项说明

- [ ] 6. 功能测试和验证
  **What to do**:
  - 复制示例配置文件为`beartools.yaml`，修改日志路径
  - 执行`beartools doctor`命令，验证输出结果
  - 检查日志文件是否生成，内容是否正确
  - 测试配置文件不存在的场景，验证默认配置生效

- [ ] 7. 代码质量检查
  **What to do**:
  - 执行`ruff check .`无错误
  - 执行`ruff format .`格式化代码
  - 执行`mypy .`无类型错误
  - 执行`pre-commit run --all-files`所有检查通过

## Final Verification
- [ ] 所有功能按需求实现
- [ ] 所有代码质量检查通过
- [ ] 文档和示例配置齐全

## Success Criteria
```bash
# 确保.config目录存在并复制配置模板
mkdir -p .config
cp .config/beartools.example.yaml .config/beartools.yaml

# 执行doctor命令
uv run python -m beartools doctor
# 预期彩色输出：✅ [green]www.google.com 连通正常[/green]，延迟: [yellow]25 ms[/yellow] 或 ❌ [red]www.google.com 连通失败[/red]

# 检查日志文件存在
cat .logs/beartools.log
# 预期输出包含：[2026-03-29 18:00:00] INFO: 开始执行doctor命令，检查www.google.com连通性
```