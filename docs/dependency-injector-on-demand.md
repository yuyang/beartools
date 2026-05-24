# Dependency Injector 按需创建模式详解

## 概述

默认情况下，`Resource` 也是**懒加载**的，第一次调用 `container.resource()` 时才初始化。但还有更多灵活的按需创建方式。

---

## 方案一：Resource 懒加载（默认）

### 特点
- 第一次调用 `container.xxx()` 时才初始化
- 之后保持单例
- `shutdown_resources()` 时统一关闭

### 示例
```python
from contextlib import contextmanager
from dependency_injector import containers, providers

@contextmanager
def init_expensive_resource():
    print("🟢 正在初始化昂贵资源...")
    yield {"data": "expensive"}
    print("🔴 正在清理昂贵资源...")

class Container(containers.DeclarativeContainer):
    expensive = providers.Resource(init_expensive_resource)

# 使用
container = Container()

# 此时还没初始化！
print("ℹ️  容器已创建，但资源未初始化")

# 第一次使用时才初始化
resource = container.expensive()  # 🟢 打印初始化信息
print(f"✅ 使用资源: {resource}")

# 再次使用，返回同一实例
resource2 = container.expensive()
print(f"✅ 再次使用（同一实例）: {resource2}")

# 统一关闭
container.shutdown_resources()  # 🔴 打印清理信息
```

---

## 方案二：Factory + 上下文管理器（每次新建）

### 特点
- 每次调用都创建新实例
- 调用方需要用 `with` 管理生命周期

### 示例
```python
from contextlib import contextmanager
from dependency_injector import containers, providers

class DatabaseConnection:
    def __init__(self, db_name):
        self.db_name = db_name
        print(f"🟢 连接到 {db_name}")
    
    def close(self):
        print(f"🔴 关闭 {self.db_name} 连接")

@contextmanager
def connection_factory(db_name):
    conn = DatabaseConnection(db_name)
    try:
        yield conn
    finally:
        conn.close()

class Container(containers.DeclarativeContainer):
    db_connection = providers.Factory(connection_factory)

# 使用
container = Container()

# 按需创建，每次都不同
with container.db_connection("db1") as conn1:
    print(f"✅ 使用 {conn1.db_name}")

with container.db_connection("db2") as conn2:
    print(f"✅ 使用 {conn2.db_name}")
```

---

## 方案三：使用 ExitStack 动态管理多个资源

### 特点
- 运行时动态决定创建哪些资源
- 统一管理所有创建的资源的清理

### 示例
```python
from contextlib import ExitStack, contextmanager
from dependency_injector import containers, providers

@contextmanager
def init_resource(name):
    print(f"🟢 初始化 {name}")
    yield {"name": name}
    print(f"🔴 清理 {name}")

class Container(containers.DeclarativeContainer):
    resource_factory = providers.Factory(init_resource)

# 使用 ExitStack 动态管理
def process_tasks(task_names):
    container = Container()
    
    with ExitStack() as stack:
        resources = []
        for name in task_names:
            # 按需创建，自动加入 ExitStack 管理
            ctx = container.resource_factory(name)
            resource = stack.enter_context(ctx)
            resources.append(resource)
        
        print(f"✅ 使用 {len(resources)} 个资源")
    
    # ExitStack 退出时自动清理所有资源
```

---

## 方案四：Singleton + 手动 reset（可重置）

### 特点
- 单例模式，但可以手动重置
- 适合需要重新初始化的场景

### 示例
```python
from dependency_injector import containers, providers

class Config:
    def __init__(self):
        print("🟢 加载配置")
        self.data = {"key": "value"}
    
    def reload(self):
        print("🔄 重新加载配置")
        self.data = {"key": "new_value"}

class Container(containers.DeclarativeContainer):
    config = providers.Singleton(Config)

# 使用
container = Container()

config1 = container.config()  # 🟢 加载配置
print(f"✅ 第一次: {config1.data}")

# 重置单例
container.config.reset()

config2 = container.config()  # 🟢 重新加载配置
print(f"✅ 第二次（新实例）: {config2.data}")
```

---

## 方案五：混合方案（按需 + 统一管理）

### 特点
- 用 Factory 创建
- 但把创建的资源注册到容器统一管理

### 示例
```python
from contextlib import contextmanager
from dependency_injector import containers, providers

class LLMClient:
    def __init__(self, model_name):
        self.model_name = model_name
        print(f"🟢 创建 {model_name} 客户端")
    
    def close(self):
        print(f"🔴 关闭 {self.model_name} 客户端")

@contextmanager
def create_client(model_name):
    client = LLMClient(model_name)
    try:
        yield client
    finally:
        client.close()

class Container(containers.DeclarativeContainer):
    # 工厂：按需创建
    client_factory = providers.Factory(create_client)
    
    # 资源：全局单例（可选）
    default_client = providers.Resource(create_client, "gpt-4")

# 使用
container = Container()
active_clients = []

try:
    # 按需创建不同模型
    with container.client_factory("gpt-4") as gpt4:
        print(f"✅ 使用 {gpt4.model_name}")
    
    with container.client_factory("claude-3") as claude:
        print(f"✅ 使用 {claude.model_name}")
    
    # 也可以用全局单例
    default_client = container.default_client()
    print(f"✅ 使用默认客户端: {default_client.model_name}")
    
finally:
    # 关闭全局单例
    container.shutdown_resources()
```

---

## 方案六：ContextLocalResource（请求级别）

### 特点
- 同一上下文内共享实例
- 不同上下文不同实例
- 上下文结束后自动清理
- 适合 Web 应用

### 示例
```python
from dependency_injector import containers, providers
from dependency_injector.wiring import Closing, Provide, inject

class RequestContext:
    def __init__(self, request_id):
        self.request_id = request_id
        print(f"🟢 为请求 {request_id} 创建上下文")
    
    def close(self):
        print(f"🔴 清理请求 {self.request_id}")

class Container(containers.DeclarativeContainer):
    request_ctx = providers.ContextLocalResource(RequestContext)

@inject
def handle_request(
    request_id: str,
    ctx: RequestContext = Closing[Provide[Container.request_ctx]],
):
    ctx.request_id = request_id  # 假设 RequestContext 可以设置
    print(f"✅ 处理请求 {ctx.request_id}")

# 使用
container = Container()
container.wire(modules=[__name__])

# 每个请求有独立的上下文
handle_request("req1")  # 创建 -> 使用 -> 清理
handle_request("req2")  # 创建 -> 使用 -> 清理
```

---

## 针对 beartools 的按需方案推荐

### 场景 1：LLM 客户端按需创建
```python
# src/beartools/container.py
from contextlib import contextmanager
from dependency_injector import containers, providers

from beartools.llm.factory import LLFactory

@contextmanager
def _create_llm_client(llm_factory, type="any", model_size="small", name=None):
    """按需创建 LLM 客户端"""
    client = llm_factory.create_client(type=type, model_size=model_size, name=name)
    try:
        yield client
    finally:
        if hasattr(client, "close"):
            client.close()

class Container(containers.DeclarativeContainer):
    llm_factory = providers.Singleton(LLFactory)
    
    # 按需工厂
    llm_client_factory = providers.Factory(
        _create_llm_client,
        llm_factory=llm_factory,
    )
    
    # 可选的全局单例
    default_llm_client = providers.Resource(
        _create_llm_client,
        llm_factory=llm_factory,
    )

# 使用
def process_some_task():
    container = Container()
    
    # 按需创建，用完即丢
    with container.llm_client_factory(type="openai", model_size="small") as client:
        result = client.chat(...)
        print(result)
    
    # 或者用全局单例（保持连接）
    global_client = container.default_llm_client()
    global_client.chat(...)
    
    container.shutdown_resources()
```

### 场景 2：数据库连接按需创建
```python
# src/beartools/container.py
from contextlib import contextmanager, ExitStack
from dependency_injector import containers, providers

@contextmanager
def _create_db_connection(db_name):
    conn = create_db_connection(db_name)
    try:
        yield conn
    finally:
        conn.close()

class Container(containers.DeclarativeContainer):
    db_factory = providers.Factory(_create_db_connection)

# 使用
def multi_database_task():
    container = Container()
    
    # 动态决定用哪些数据库
    with ExitStack() as stack:
        dbs = []
        for db_name in ["users", "orders", "logs"]:
            ctx = container.db_factory(db_name)
            db = stack.enter_context(ctx)
            dbs.append(db)
        
        # 同时使用多个数据库连接
        query_data(dbs)
```

---

## 总结对比

| 方案 | 特点 | 适用场景 |
|------|------|----------|
| **Resource 懒加载** | 默认懒加载，单例，统一关闭 | 配置、日志等全局资源 |
| **Factory + 上下文管理器** | 每次新建，调用方管理 | 数据库连接、临时资源 |
| **ExitStack** | 动态管理多个 | 运行时才知道需要哪些资源 |
| **Singleton + reset** | 单例可重置 | 配置需要重新加载 |
| **ContextLocalResource** | 上下文级别单例 | Web 请求、任务队列 |

### 推荐组合

对于 beartools 这种 CLI 工具：

- **全局资源**（config、logger）→ `Resource` 懒加载
- **按需资源**（LLM client、db）→ `Factory + with` 或 `ExitStack`
