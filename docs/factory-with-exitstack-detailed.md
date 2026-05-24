# Factory + with 和 ExitStack 详细方案（结合 beartools）

## 概述

基于你现有的 `LLFactory`，我们来实现两种按需创建 LLM client 的方案。

---

## 方案一：Factory + with（单个资源，用完即丢）

### 核心思路
每次需要时创建一个新的 client，用完通过 `with` 自动关闭。

### 实现代码

```python
# src/beartools/llm/resource_factories.py
"""LLM 资源工厂 - 按需创建版本"""

from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from typing import Literal

from beartools.llm.factory import (
    LLFactory,
    ProviderType,
    AgentTier,
    SyncLLMClient,
    AsyncLLMClient,
    _close_sync_client,
    _close_async_client,
)
from beartools.logger import get_logger

logger = get_logger(__name__)


@contextmanager
def create_llm_client_context(
    llm_factory: LLFactory,
    *,
    name: str | None = None,
    type: ProviderType = "any",
    model_size: AgentTier = "small",
):
    """
    按需创建同步 LLM 客户端，用 with 管理生命周期
    
    示例:
        >>> llm_factory = LLFactory()
        >>> with create_llm_client_context(llm_factory, model_size="large") as client:
        ...     client.chat.completions.create(...)
    """
    client: SyncLLMClient | None = None
    try:
        client = llm_factory.create_client(
            name=name,
            type=type,
            model_size=model_size,
        )
        logger.debug(f"LLM 客户端已创建: type={type}, size={model_size}")
        yield client
    finally:
        if client is not None:
            _close_sync_client(client)
            logger.debug("LLM 客户端已关闭")


@asynccontextmanager
async def create_async_llm_client_context(
    llm_factory: LLFactory,
    *,
    name: str | None = None,
    type: ProviderType = "any",
    model_size: AgentTier = "small",
):
    """
    按需创建异步 LLM 客户端，用 async with 管理生命周期
    
    示例:
        >>> llm_factory = LLFactory()
        >>> async with create_async_llm_client_context(llm_factory) as client:
        ...     await client.chat.completions.create(...)
    """
    client: AsyncLLMClient | None = None
    try:
        client = await llm_factory.create_async_client(
            name=name,
            type=type,
            model_size=model_size,
        )
        logger.debug(f"异步 LLM 客户端已创建: type={type}, size={model_size}")
        yield client
    finally:
        if client is not None:
            await _close_async_client(client)
            logger.debug("异步 LLM 客户端已关闭")
```

### 使用示例

```python
# 方式一：直接使用（不依赖容器）
from beartools.llm.factory import LLFactory
from beartools.llm.resource_factories import (
    create_llm_client_context,
    create_async_llm_client_context,
)

llm_factory = LLFactory()

# 同步版本
with create_llm_client_context(llm_factory, model_size="large") as client:
    result = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "你好"}]
    )
    print(result)
# 退出 with 块时，client 自动 close

# 异步版本
import asyncio

async def do_something():
    async with create_async_llm_client_context(llm_factory) as client:
        result = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "你好"}]
        )
        print(result)

asyncio.run(do_something())
```

### 集成到 Dependency Injector 容器

```python
# src/beartools/container.py
from dependency_injector import containers, providers
from beartools.llm.factory import LLFactory
from beartools.llm.resource_factories import (
    create_llm_client_context,
    create_async_llm_client_context,
)

class Container(containers.DeclarativeContainer):
    llm_factory = providers.Singleton(LLFactory)
    
    # 同步 LLM 客户端工厂
    llm_client_factory = providers.Factory(
        create_llm_client_context,
        llm_factory=llm_factory,
    )
    
    # 异步 LLM 客户端工厂
    async_llm_client_factory = providers.Factory(
        create_async_llm_client_context,
        llm_factory=llm_factory,
    )
```

### 使用容器版本

```python
from beartools.container import Container

container = Container()

# 使用 Factory
with container.llm_client_factory(model_size="large") as client:
    result = client.chat.completions.create(...)

# 异步版本
async def main():
    async with container.async_llm_client_factory(type="anthropic") as client:
        result = await client.chat.completions.create(...)
```

---

## 方案二：ExitStack（动态管理多个资源）

### 核心思路
运行时动态决定需要哪些资源，统一用 ExitStack 管理所有资源的清理。

### 实现代码

```python
# src/beartools/llm/resource_factories.py（续）

from contextlib import ExitStack, AsyncExitStack


class MultiLLMClientManager:
    """
    多 LLM 客户端管理器 - 使用 ExitStack 动态管理
    
    示例:
        >>> manager = MultiLLMClientManager(llm_factory)
        >>> with manager:
        ...     client1 = manager.get_client(model_size="small")
        ...     client2 = manager.get_client(model_size="large", name="my-model")
        ...     # 使用两个客户端...
        >>> # 退出 with 块时，两个客户端自动 close
    """
    
    def __init__(self, llm_factory: LLFactory):
        self.llm_factory = llm_factory
        self._stack: ExitStack | None = None
        self._clients: list[SyncLLMClient] = []
    
    def __enter__(self) -> "MultiLLMClientManager":
        self._stack = ExitStack()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        self._clients.clear()
    
    def get_client(
        self,
        *,
        name: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> SyncLLMClient:
        """按需获取一个 LLM 客户端，自动加入 ExitStack 管理"""
        if self._stack is None:
            raise RuntimeError("请在 with 块中使用 get_client")
        
        ctx = create_llm_client_context(
            self.llm_factory,
            name=name,
            type=type,
            model_size=model_size,
        )
        client = self._stack.enter_context(ctx)
        self._clients.append(client)
        return client
    
    @property
    def active_clients(self) -> int:
        return len(self._clients)


class AsyncMultiLLMClientManager:
    """异步版本的多 LLM 客户端管理器"""
    
    def __init__(self, llm_factory: LLFactory):
        self.llm_factory = llm_factory
        self._stack: AsyncExitStack | None = None
        self._clients: list[AsyncLLMClient] = []
    
    async def __aenter__(self) -> "AsyncMultiLLMClientManager":
        self._stack = AsyncExitStack()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._clients.clear()
    
    async def get_client(
        self,
        *,
        name: str | None = None,
        type: ProviderType = "any",
        model_size: AgentTier = "small",
    ) -> AsyncLLMClient:
        """按需获取一个异步 LLM 客户端，自动加入 AsyncExitStack 管理"""
        if self._stack is None:
            raise RuntimeError("请在 async with 块中使用 get_client")
        
        ctx = create_async_llm_client_context(
            self.llm_factory,
            name=name,
            type=type,
            model_size=model_size,
        )
        client = await self._stack.enter_async_context(ctx)
        self._clients.append(client)
        return client
    
    @property
    def active_clients(self) -> int:
        return len(self._clients)
```

### 使用示例

```python
# 示例一：动态决定需要哪些模型
from beartools.llm.factory import LLFactory
from beartools.llm.resource_factories import MultiLLMClientManager

llm_factory = LLFactory()

def analyze_with_multiple_models(prompt: str):
    with MultiLLMClientManager(llm_factory) as manager:
        # 按需创建多个客户端
        small_client = manager.get_client(model_size="small")
        large_client = manager.get_client(model_size="large")
        
        # 同时使用多个模型
        small_result = small_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        
        large_result = large_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        
        print(f"活跃客户端数: {manager.active_clients}")
        return small_result, large_result

# 调用
small_res, large_res = analyze_with_multiple_models("你好")
# 退出 with 块时，两个客户端都自动 close


# 示例二：循环中动态创建
def batch_process(tasks: list[dict]):
    with MultiLLMClientManager(llm_factory) as manager:
        results = []
        for task in tasks:
            # 每个任务按需创建对应模型的客户端
            client = manager.get_client(
                type=task.get("provider", "any"),
                model_size=task.get("size", "small"),
                name=task.get("node_name"),
            )
            result = client.chat.completions.create(
                model=task["model"],
                messages=[{"role": "user", "content": task["prompt"]}]
            )
            results.append(result)
        
        print(f"总共创建了 {manager.active_clients} 个客户端")
        return results


# 异步版本示例
import asyncio

async def async_batch_process(tasks: list[dict]):
    manager = AsyncMultiLLMClientManager(llm_factory)
    
    async with manager:
        results = []
        for task in tasks:
            client = await manager.get_client(
                type=task.get("provider", "any"),
                model_size=task.get("size", "small"),
            )
            result = await client.chat.completions.create(
                model=task["model"],
                messages=[{"role": "user", "content": task["prompt"]}]
            )
            results.append(result)
        return results

asyncio.run(async_batch_process(tasks))
```

### 集成到 Dependency Injector

```python
# src/beartools/container.py（续）

class Container(containers.DeclarativeContainer):
    llm_factory = providers.Singleton(LLFactory)
    
    # 单个客户端工厂
    llm_client_factory = providers.Factory(
        create_llm_client_context,
        llm_factory=llm_factory,
    )
    
    async_llm_client_factory = providers.Factory(
        create_async_llm_client_context,
        llm_factory=llm_factory,
    )
    
    # 多客户端管理器
    multi_llm_manager = providers.Factory(
        MultiLLMClientManager,
        llm_factory=llm_factory,
    )
    
    async_multi_llm_manager = providers.Factory(
        AsyncMultiLLMClientManager,
        llm_factory=llm_factory,
    )
```

### 使用容器

```python
from beartools.container import Container

container = Container()

# 方式一：单个客户端
with container.llm_client_factory(model_size="small") as client:
    client.chat.completions.create(...)

# 方式二：多个客户端
with container.multi_llm_manager() as manager:
    client1 = manager.get_client(model_size="small")
    client2 = manager.get_client(model_size="large")
    # 使用...

# 异步版本
async def main():
    async with container.async_multi_llm_manager() as manager:
        client = await manager.get_client()
        # 使用...
```

---

## 方案对比

| 特性 | Factory + with（单个） | ExitStack（多个） |
|------|----------------------|-----------------|
| **适用场景** | 只需要一个 client | 需要多个 client，或运行时才知道需要几个 |
| **创建时机** | 进入 with 块时 | 调用 get_client 时 |
| **关闭时机** | 退出 with 块时 | 退出 with 块时，统一关闭所有 |
| **复杂度** | 简单 | 稍复杂但更灵活 |
| **推荐场景** | 单次任务，简单使用 | 批量处理，多模型对比 |

---

## 数据库连接的类似实现

同样的模式也适用于数据库连接：

```python
# src/beartools/db/resource_factories.py
from contextlib import contextmanager

@contextmanager
def create_db_connection(db_name: str):
    conn = connect_to_db(db_name)
    try:
        yield conn
    finally:
        conn.close()

# 使用
with create_db_connection("users") as conn:
    conn.execute("SELECT * FROM users")
```

---

## 完整集成到 beartools 的建议

### 步骤一：添加依赖

```toml
# pyproject.toml
[project]
dependencies = [
    # ... 现有依赖 ...
    "dependency-injector==4.49.0",  # 固定版本
]
```

### 步骤二：创建资源工厂模块

创建 `src/beartools/llm/resource_factories.py`，内容如上面所示。

### 步骤三：创建容器模块

创建 `src/beartools/container.py`，内容如上面所示。

### 步骤四：在业务代码中使用

```python
# src/beartools/commands/some_command.py
from beartools.container import Container

def main():
    container = Container()
    
    # 方式一：简单使用
    with container.llm_client_factory(model_size="large") as client:
        result = client.chat.completions.create(...)
    
    # 方式二：多模型使用
    with container.multi_llm_manager() as manager:
        small_client = manager.get_client(model_size="small")
        large_client = manager.get_client(model_size="large")
        # 使用...
```

---

## 总结

- **Factory + with**：简单直接，适合单次使用一个 client
- **ExitStack**：灵活强大，适合动态管理多个资源

两种方案都不需要修改你现有的 `LLFactory` 代码，可以直接用！
