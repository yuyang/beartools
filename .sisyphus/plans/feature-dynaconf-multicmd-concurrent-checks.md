# 功能开发计划：dynaconf配置 + 多子命令支持 + 并发check

## TL;DR
> **Quick Summary**: 重构配置模块使用dynaconf，支持多个子命令，实现check项并发执行
> 
> **Deliverables**:
> - 新增pyproject.toml依赖：dynaconf
> - 重构配置模块，使用dynaconf替代现有实现
> - 重构CLI入口，支持多个子命令，默认输出help
> - 修改doctor命令，使用ThreadPoolExecutor并发执行check项
> 
> **Estimated Effort**: Short (1-2小时)
> **Parallel Execution**: NO - 顺序执行
> **Critical Path**: 添加dynaconf → 重构配置模块 → 重构CLI → 并发check → 测试

## Context
### Original Request
1. 配置采用dynaconf
2. 这个程序有多个子命令，doctor只是其中之一；用户没有输入子命令时，直接输出help信息即可
3. check的时候，并发多个check项

## Work Objectives
### Core Objective
重构现有代码，实现更灵活的配置管理、更规范的多子命令CLI架构、以及check项的并发执行。

### Concrete Deliverables
1. 配置管理：使用dynaconf替代现有yaml解析，支持.env、环境变量覆盖等功能
2. 多子命令CLI：使用typer的子命令功能，主命令无参数时输出help
3. 并发check：使用concurrent.futures.ThreadPoolExecutor并发执行多个check项

### Definition of Done
- [ ] 配置采用dynaconf，支持从.config/beartools.yaml、.env和环境变量读取配置
- [ ] CLI支持多个子命令，主命令无参数时输出help信息
- [ ] doctor命令的多个check项并发执行，提高效率
- [ ] 所有代码通过ruff检查、mypy类型检查，无错误
- [ ] 测试beartools、beartools --help、beartools doctor都能正常工作

### Must Have
- 使用dynaconf管理配置
- typer多子命令架构，默认无参数输出help
- check项并发执行，使用线程池
- 保持现有功能不变：两个check项、日志系统、彩色输出

### Must NOT Have
- 不破坏现有功能
- 不硬编码配置值
- 不使用多进程并发（check项都是IO密集型，线程池更合适）

## Execution Strategy
### 执行步骤（顺序执行）
```
Step 1: 添加dynaconf依赖
Step 2: 重构配置模块，使用dynaconf
Step 3: 重构CLI入口，支持多子命令
Step 4: 修改doctor命令，支持并发check
Step 5: 测试所有功能
Step 6: 代码质量检查
```

### TODOs
- [ ] 1. 添加dynaconf依赖（已完成）
- [ ] 2. 重构配置模块
  **What to do**:
  - 创建新的config.py，使用dynaconf.LazySettings
  - 配置文件路径：.config/beartools.yaml
  - 支持.env和环境变量覆盖（BEARTOOLS_前缀）
  - 保持get_config()接口不变，兼容现有代码
  - 移除MergeConfig等旧逻辑

  **QA Scenarios**:
  - 配置文件存在时能正确读取
  - 环境变量能正确覆盖配置
  - get_config()返回值类型兼容现有代码

- [ ] 3. 重构CLI入口
  **What to do**:
  - 创建typer.Typer()主应用
  - 将doctor作为子命令注册：@app.command()
  - 主应用无参数时自动输出help信息
  - 保持entry point为beartools = "beartools.cli:app"

  **QA Scenarios**:
  - 运行beartools输出help信息
  - 运行beartools --help输出完整帮助
  - 运行beartools doctor正常工作

- [ ] 4. 修改doctor命令，支持并发check
  **What to do**:
  - 使用concurrent.futures.ThreadPoolExecutor
  - 并发执行所有enabled_checks
  - 等待所有check完成，然后统一输出结果
  - 保持彩色输出和汇总统计不变

  **QA Scenarios**:
  - 多个check项能并发执行，总耗时接近最长单个check耗时
  - 输出结果和之前一致，顺序可以不同
  - 异常处理正确，单个check失败不影响其他check

- [ ] 5. 功能测试和验证
- [ ] 6. 代码质量检查

## Final Verification
- [ ] 所有功能按需求实现
- [ ] 所有代码质量检查通过
- [ ] 文档和示例配置齐全

## Success Criteria
```bash
# 运行beartools，输出help
beartools
# 预期输出完整的help信息

# 运行beartools doctor
beartools doctor
# 预期输出并发执行的check结果
```