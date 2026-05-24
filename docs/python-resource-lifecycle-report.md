# Python 资源生命周期管理方案详细报告

## 概述

本文档汇总了 Python 生态中主要的资源生命周期管理和依赖注入方案，包括 GitHub 星标数据、核心功能、适用场景等信息。

---

## 一、标准库方案（零依赖）

### 1. atexit 模块
- **简介**：程序退出时自动执行注册的清理函数
- **适用场景**：简单的全局资源清理
- **优势**：零依赖，使用简单
- **局限性**：不处理信号中断、`os._exit()`，按逆序执行

### 2. weakref.finalize
- **简介**：绑定到对象垃圾回收时执行清理
- **优势**：更灵活，程序退出时也会自动调用
- **适用场景**：需要与对象生命周期绑定的资源

### 3. contextlib.ExitStack
- **简介**：动态管理多个资源的清理栈
- **优势**：适合资源数量不固定的场景
- **适用场景**：动态获取多个资源的场景

---

## 二、第三方依赖注入容器方案

### 1. Dependency Injector（ets-labs/python-dependency-injector）
- **GitHub 星标**：⭐ 4.8k
- **Forks**：342
- **创建时间**：2015-01
- **最新版本**：4.49.0
- **Python 版本支持**：广泛支持
- **核心功能**：
  - 提供 `Factory`、`Singleton`、`Resource` 等多种提供者
  - 专门的 `Resource` 提供者，支持初始化和关闭
  - 支持同步/异步、生成器、上下文管理器
  - 提供 `ContextLocalResource` 用于请求级资源
  - 声明式容器、依赖注入、配置管理
  - 与 Django、Flask、FastAPI 等框架集成
  - 使用 Cython 编写，性能优秀
- **文档质量**：完善，有多个教程
- **成熟度**：生产就绪，成熟稳定
- **适用场景**：中大型项目，需要全面 DI 功能的场景

### 2. Injector（python-injector/injector）
- **GitHub 星标**：⭐ 1.5k
- **Forks**：94
- **创建时间**：2010-11
- **最新版本**：0.24.0（2026-01）
- **核心功能**：
  - 受 Guice 启发的依赖注入框架
  - 支持自定义作用域
  - 有 Flask 集成（flask_injector，283 stars）
  - 资源清理建议使用 ExitStack 模式
- **文档质量**：良好
- **成熟度**：成熟，历史悠久
- **适用场景**：喜欢 Guice 风格的项目

### 3. svcs（hynek/svcs）
- **GitHub 星标**：⭐ 405
- **Forks**：23
- **创建时间**：2023-07
- **最新版本**：25.1.0（2025-01）
- **Python 版本支持**：>=3.9
- **核心功能**：
  - 灵活的服务定位器/依赖容器
  - 统一的服务获取和自动清理
  - 类型安全，支持健康检查
  - 与 AIOHTTP、FastAPI、Flask、Pyramid、Starlette 无缝集成
  - 支持服务位置和依赖注入两种模式
- **作者**：Hynek Schlawack（知名 Python 开发者）
- **文档质量**：优秀
- **成熟度**：生产就绪
- **适用场景**：Web 应用，需要与框架深度集成的场景

### 4. Lagom（meadsteve/lagom）
- **GitHub 星标**：⭐ 348
- **Forks**：20
- **创建时间**：2019-06
- **最新版本**：2.7.7（2025-07）
- **Python 版本支持**：>=3.7
- **核心功能**：
  - 基于类型的自动装配，零配置
  - 与 mypy 强集成
  - 提供 `ContextContainer` 管理带清理的依赖
  - 支持 `context_singleton` 作用域内单例
  - 与 Django、FastAPI、Flask、Starlette 集成
- **文档质量**：良好
- **成熟度**：稳定
- **适用场景**：类型驱动的项目，喜欢极简风格的场景

### 5. diwire（maksimzayats/diwire）
- **GitHub 星标**：⭐ 219
- **Forks**：未明确
- **创建时间**：2026-01
- **最新版本**：1.3.2（2026-03）
- **Python 版本支持**：>=3.10
- **核心功能**：
  - 类型驱动的依赖注入
  - 零运行时依赖
  - 作用域 + 确定性清理
  - 异步解析支持
  - 编译解析器，性能极快
  - 支持无 GIL Python
- **文档质量**：良好
- **成熟度**：新兴但活跃
- **适用场景**：需要高性能、零依赖的项目

### 6. pyinj / injx（QriusGlobal）
- **pyinj GitHub 星标**：⭐ 0（已废弃）
- **injx GitHub 星标**：⭐ 3
- **创建时间**：2025-09
- **Python 版本支持**：>=3.13
- **状态**：pyinj 已废弃，迁移到 injx
- **核心功能**：
  - 类型安全的依赖注入
  - 自动资源清理（LIFO 顺序）
  - 零外部依赖
- **适用场景**：不推荐生产使用

---

## 三、方案对比表

| 方案 | GitHub 星标 | 创建时间 | 零依赖 | 资源管理 | 类型安全 | Web 框架集成 | 推荐度 |
|------|-------------|----------|--------|----------|----------|--------------|--------|
| atexit | 标准库 | - | ✅ | ⭐⭐ | - | - | ⭐⭐⭐ |
| Dependency Injector | 4.8k | 2015 | ❌ | ⭐⭐⭐⭐⭐ | ✅ | ✅ | ⭐⭐⭐⭐⭐ |
| Injector | 1.5k | 2010 | ❌ | ⭐⭐⭐ | ✅ | ✅ | ⭐⭐⭐ |
| svcs | 405 | 2023 | ❌ | ⭐⭐⭐⭐ | ✅ | ✅ | ⭐⭐⭐⭐ |
| Lagom | 348 | 2019 | ❌ | ⭐⭐⭐⭐ | ✅ | ✅ | ⭐⭐⭐ |
| diwire | 219 | 2026 | ✅ | ⭐⭐⭐⭐ | ✅ | - | ⭐⭐⭐⭐ |
| pyinj/injx | 3 | 2025 | ✅ | ⭐⭐⭐ | ✅ | - | ⭐ |

---

## 四、针对 beartools 项目的建议

### 当前项目状态分析
- **Python 版本**：3.13+
- **现有模式**：模块级单例 + `atexit`（config.py、logger.py）
- **项目类型**：CLI 工具集
- **依赖管理**：使用 uv，所有依赖固定版本

### 推荐方案

#### 方案一：保持现状（零依赖）
**适用场景**：项目规模适中，当前模式满足需求
**优势**：
- 零新依赖
- 与现有代码风格一致
- 简单直接

#### 方案二：引入 Dependency Injector（推荐）
**适用场景**：未来可能扩展，需要更完善的资源管理
**优势**：
- 4.8k stars，最成熟稳定
- 专门的 Resource 提供者，完美匹配需求
- Cython 编写，性能优秀
- 文档完善，社区活跃
- 支持同步/异步，满足 beartools 的异步需求

#### 方案三：引入 svcs（轻量现代）
**适用场景**：主要是 CLI，但未来可能有 Web 界面
**优势**：
- 作者是知名 Python 开发者（Hynek Schlawack）
- 自动清理，类型安全
- 轻量现代

---

## 五、Dependency Injector 快速示例（针对 beartools）

```python
from dependency_injector import containers, providers
from beartools.config import load_config
from beartools.logger import get_logger

class Container(containers.DeclarativeContainer):
    config = providers.Resource(load_config)
    logger = providers.Factory(get_logger)
    
    # LLM 客户端示例
    llm_client = providers.Resource(
        providers.Factory(
            # 你的 LLM 客户端创建函数
        )
    )

if __name__ == "__main__":
    container = Container()
    container.init_resources()
    
    try:
        # 使用资源
        config = container.config()
        logger = container.logger("my_module")
        logger.info("Hello")
    finally:
        container.shutdown_resources()
```

---

## 六、总结

1. **最成熟**：Dependency Injector（4.8k stars）
2. **最现代轻量**：svcs（405 stars，Hynek 出品）
3. **零依赖高性能**：diwire（219 stars）
4. **最简单**：标准库 atexit + 模块单例

对于 **beartools** 项目，建议：
- 如果想保守，保持现状即可
- 如果想为未来扩展做准备，引入 **Dependency Injector**
