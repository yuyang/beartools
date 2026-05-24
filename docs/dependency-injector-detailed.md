# Dependency Injector 详细说明

## 概述

**Dependency Injector** 是一个 Python 依赖注入框架，GitHub 星标 4.8k，由 ets-labs 维护，使用 Cython 编写，性能优秀，生产就绪。

---

## 核心特性

### 1. 提供者（Providers）
提供多种对象创建方式：
- `Factory` - 工厂模式，每次创建新实例
- `Singleton` - 单例模式，只创建一次
- `Resource` - **资源生命周期管理**（重点）
- `ContextLocalResource` - 上下文级别单例
- `Callable`、`Coroutine`、`Object`、`List`、`Dict` 等
- `Configuration` - 配置管理

### 2. 资源管理（Resource Provider）
这是最相关你需求的功能：
- 支持初始化和关闭两个阶段
- 类似 `Singleton`，只初始化一次
- 可以统一调用 `init_resources()` 和 `shutdown_resources()`
- 支持同步和异步

### 3. 容器（Containers）
- 声明式容器 `DeclarativeContainer`
- 动态容器 `DynamicContainer`
- 提供者覆盖（用于测试）

### 4. 依赖注入（Wiring）
- `@inject` 装饰器
- `Provide[...]` 标记
- 与多种 Web 框架集成

---

## Resource Provider 详解

### 四种初始化方式

#### 方式一：函数初始化（最常见）
```python
def init_resource(argument1, argument2):
    return SomeResource()

class Container(containers.DeclarativeContainer):
    resource = providers.Resource(
        init_resource,
        argument1=...,
        argument2=...,
    )
```

**特点**：简单，但无法自定义关闭逻辑

#### 方式二：上下文管理器（推荐）
```python
from contextlib import contextmanager

@contextmanager
def init_resource(argument1, argument2):
    resource = SomeResource()  # 初始化
    yield resource  # 提供给使用方
    resource.close()  # 关闭逻辑

class Container(containers.DeclarativeContainer):
    resource = providers.Resource(
        init_resource,
        argument1=...,
        argument2=...,
    )
```

**特点**：可以在 `__exit__` 中进行清理，推荐使用

#### 方式三：生成器（Legacy）
```python
def init_resource(argument1, argument2):
    resource = SomeResource()  # 初始化
    yield resource  # 提供给使用方
    resource.close()  # 关闭逻辑

class Container(containers.DeclarativeContainer):
    resource = providers.Resource(
        init_resource,
        argument1=...,
        argument2=...,
    )
```

**特点**：两阶段，第一阶段 yield 前初始化，第二阶段 yield 后关闭

#### 方式四：子类化（Legacy）
```python
from dependency_injector import resources

class MyResource(resources.Resource):
    def init(self, argument1, argument2) -> SomeResource:
        return SomeResource()
    
    def shutdown(self, resource: SomeResource) -> None:
        resource.close()

class Container(containers.DeclarativeContainer):
    resource = providers.Resource(
        MyResource,
        argument1=...,
        argument2=...,
    )
```

---

## 异步支持

### 异步资源初始化
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def init_async_resource():
    connection = await connect()
    yield connection
    await connection.close()

class Container(containers.DeclarativeContainer):
    resource = providers.Resource(init_async_resource)

# 使用时需要 await
async def main():
    container = Container()
    await container.init_resources()  # 异步初始化
    
    connection = await container.resource()
    # 使用连接...
    
    await container.shutdown_resources()  # 异步关闭
```

---

## 完整使用示例

### 示例一：基础示例（类似你的 beartools）

```python
import sys
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from dependency_injector import containers, providers
from dependency_injector.wiring import Provide, inject

# 1. 定义资源初始化函数
@contextmanager
def init_thread_pool(max_workers: int):
    thread_pool = ThreadPoolExecutor(max_workers=max_workers)
    yield thread_pool
    thread_pool.shutdown(wait=True)

# 2. 定义容器
class Container(containers.DeclarativeContainer):
    config = providers.Configuration()
    
    thread_pool = providers.Resource(
        init_thread_pool,
        max_workers=config.max_workers,
    )
    
    logging = providers.Resource(
        logging.basicConfig,
        level=logging.INFO,
        stream=sys.stdout,
    )

# 3. 使用资源
@inject
def main(
    thread_pool: ThreadPoolExecutor = Provide[Container.thread_pool],
):
    logging.info("Resources are initialized")
    thread_pool.map(print, range(10))

if __name__ == "__main__":
    container = Container(config={"max_workers": 4})
    
    # 初始化所有资源
    container.init_resources()
    
    # 注入依赖
    container.wire(modules=[__name__])
    
    try:
        main()
    finally:
        # 关闭所有资源
        container.shutdown_resources()
```

### 示例二：针对 beartools 的集成方案

```python
# src/beartools/container.py
from dependency_injector import containers, providers
from beartools import config as beartools_config
from beartools import logger as beartools_logger
from beartools.llm.factory import LLFactory

class Container(containers.DeclarativeContainer):
    """beartools 容器"""
    
    # 配置
    config = providers.Resource(beartools_config.load_config)
    
    # 日志
    logger = providers.Callable(beartools_logger.get_logger)
    
    # LLM 工厂
    llm_factory = providers.Singleton(LLFactory)
    
    # 示例：LLM 客户端作为资源
    @staticmethod
    @contextmanager
    def _init_llm_client(llm_factory, type="any", model_size="small"):
        client = llm_factory.create_client(type=type, model_size=model_size)
        yield client
        # 如果有 close 方法，调用它
        if hasattr(client, "close"):
            client.close()
    
    llm_client = providers.Resource(
        _init_llm_client.__get__(providers.Resource),
        llm_factory=llm_factory,
    )


# 使用方式
from beartools.container import Container

def main():
    container = Container()
    container.init_resources()
    
    try:
        config = container.config()
        logger = container.logger("main")
        
        llm_client = container.llm_client()
        # 使用 llm_client...
        
    finally:
        container.shutdown_resources()
```

---

## 资源管理 API

### 统一管理所有资源
```python
container = Container()

# 初始化所有资源
container.init_resources()

# 关闭所有资源
container.shutdown_resources()
```

### 单个资源管理
```python
container = Container()

# 初始化单个资源
container.thread_pool.init()

# 关闭单个资源
container.thread_pool.shutdown()

# 获取资源
thread_pool = container.thread_pool()
```

### 按类型分组管理资源
```python
from dependency_injector import resources

# 定义作用域资源类型
class ScopedResource(resources.Resource):
    pass

class Container(containers.DeclarativeContainer):
    scoped = ScopedResource(init_service, "scoped")
    generic = providers.Resource(init_service, "generic")

# 只初始化作用域资源
container.init_resources(ScopedResource)

# 只关闭作用域资源
container.shutdown_resources(ScopedResource)
```

---

## ContextLocalResource（上下文级别单例）

适合 Web 应用的请求级别资源：

```python
from fastapi import Depends, FastAPI
from dependency_injector import containers, providers
from dependency_injector.wiring import Closing, Provide, inject

class Container(containers.DeclarativeContainer):
    db_session = providers.ContextLocalResource(AsyncSessionLocal)

app = FastAPI()

@app.get("/")
@inject
async def index(db: AsyncSessionLocal = Depends(Closing[Provide["db_session"]])):
    # 同一个请求内共享同一个 db_session
    # 请求结束后自动 close
    res = await db.execute("SELECT 1")
    return str(res)
```

---

## 测试支持：提供者覆盖

```python
with container.api_client.override(mock.Mock()):
    # 这里使用 mock 替代真实的 api_client
    main()
```

---

## 推荐的 beartools 集成方案

### 方案 A：最小侵入式（推荐）

保持现有代码结构，只在入口处使用容器：

```python
# src/beartools/container.py
from contextlib import contextmanager
from dependency_injector import containers, providers

import beartools.config
import beartools.logger

@contextmanager
def _init_config():
    config = beartools.config.load_config()
    yield config
    beartools.config.reset_config()

class Container(containers.DeclarativeContainer):
    config = providers.Resource(_init_config)
    get_logger = providers.Callable(beartools.logger.get_logger)

# 在 cli.py 中使用
from beartools.container import Container

def main():
    container = Container()
    container.init_resources()
    
    try:
        # 现有代码继续使用 beartools.config.get_config()
        # 不需要修改现有业务代码
        existing_main()
    finally:
        container.shutdown_resources()
```

### 方案 B：完全迁移

逐步将所有资源管理迁移到 Dependency Injector。

---

## 文档链接

- **官方文档**：https://python-dependency-injector.ets-labs.org/
- **Resource Provider 文档**：https://python-dependency-injector.ets-labs.org/providers/resource.html
- **CLI 教程**：https://python-dependency-injector.ets-labs.org/tutorials/cli.html
- **GitHub**：https://github.com/ets-labs/python-dependency-injector

---

## 安装

```bash
# 使用 uv 添加依赖
uv add dependency-injector

# 然后在 pyproject.toml 中固定版本
# dependency-injector = "==4.49.0"
```
