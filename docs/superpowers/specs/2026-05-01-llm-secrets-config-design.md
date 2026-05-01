# LLM 与敏感配置拆分设计

## 背景

当前项目使用单一配置文件 `config/beartools.yaml` 承载全部配置。其中包含以下敏感信息：

- `siyuan.token`
- `agent.primary.api_key`
- `agent.candidates[*].api_key`

这会带来几个问题：

1. 主配置文件容易混入真实密钥，增加误提交到 Git 的风险
2. 普通配置与敏感配置混放，可读性和维护边界不清晰
3. 当前虽然已支持环境变量覆盖，但默认配置形态仍鼓励把 key 直接写进 YAML

目标是将敏感配置从主配置文件中拆分出去，并保持本地使用成本可接受。

## 目标

本次改造目标如下：

1. 将 LLM 的 `api_key` 与 `siyuan.token` 从 `config/beartools.yaml` 中移出
2. 新增本地专用的 `config/beartools.secrets.yaml` 保存敏感配置
3. 将 `config/beartools.secrets.yaml` 加入 `.gitignore`
4. 保留环境变量覆盖能力，且优先级高于 secrets 文件
5. LLM 节点通过 Dynaconf 的 `@get` 引用语法关联到 secrets 中的完整 key 路径
6. 当多个节点实际复用同一个 key 时，可以复用同一个 `@get` 引用
7. 当用户误把敏感字段继续写在 `beartools.yaml` 中时，启动阶段直接报错

## 非目标

本次不处理以下内容：

- 不改动 LLM 运行时的主备切换逻辑
- 不改动 LLM 工厂的模型构造逻辑
- 不新增加密、KMS、系统钥匙串等更复杂的 secrets 管理方案
- 不自动迁移用户现有本地配置中的真实密钥
- 不改动 LLM 运行时与工厂层对 `api_key` 的消费方式
- 不引入额外自定义占位符协议，优先复用 Dynaconf 原生 `@get` 引用能力

## 设计方案

### 1. 配置文件拆分

将配置拆为两层文件：

#### 主配置文件

`config/beartools.yaml`

只保留非敏感配置，例如：

- `log.*`
- `doctor.*`
- `siyuan.default_note`
- `siyuan.notebook`
- `siyuan.path`
- `agent.primary.name/provider/base_url/model/api_key/extra_headers/timeout_seconds`
- `agent.candidates[*].name/provider/base_url/model/api_key/extra_headers/timeout_seconds`

#### 敏感配置文件

`config/beartools.secrets.yaml`

只放敏感信息，例如：

- `siyuan.token`
- 例如 `agent.openrouter.key`
- 例如 `agent.zhizengzeng.key`

该文件用于本地私有配置，不进入版本库。

### 2. 样例文件拆分

配置样例也拆分为两份：

- `config/beartools.yaml.sample`
- `config/beartools.secrets.yaml.sample`

其中：

- `beartools.yaml.sample` 只展示非敏感结构
- `beartools.secrets.yaml.sample` 只展示敏感字段占位值和完整 key 路径结构

这样用户初始化配置时，可以明确知道哪些内容应该放在哪个文件。

### 3. 加载优先级

最终配置优先级为：

1. 环境变量
2. `config/beartools.secrets.yaml`
3. `config/beartools.yaml`

即：

- 默认值来自主配置文件
- 本地私密值可由 secrets 文件覆盖
- 临时调试或 CI 场景可通过环境变量继续覆盖

这个优先级符合常见工程实践，也保留了环境变量的灵活性。

### 4. 配置加载方式

当前 `load_config()` 只读取 `config/beartools.yaml`。本次改造后，扩展为同时读取两个配置文件。

设计要求：

1. 如果 `beartools.yaml` 存在，则参与加载
2. 如果 `beartools.secrets.yaml` 存在，则参与加载
3. secrets 文件中的字段覆盖主配置文件
4. 环境变量再覆盖合并后的结果
5. 对每个 agent 节点，允许通过 Dynaconf `@get` 在主配置中引用 secrets 路径

实现上仍由 `config.py` 统一负责，避免把 secrets 解析逻辑散落到 `llm/runtime.py`、`llm/factory.py` 或命令层。

这里不采用 `agent.candidates[0].api_key` 这种位置绑定的 secrets 文件结构，也不增加 `key_name` 中间字段，而是直接采用 Dynaconf 的 `@get` 路径引用：

- 主配置中的 `api_key` 允许写成 `@get agent.xxx.key`
- secrets 文件负责提供 `agent.xxx.key` 的真实值
- 多个节点如果实际使用同一个 key，可以配置相同的 `@get` 引用，从而复用同一个 secrets 项

### 5. 敏感字段约束

为防止用户继续把 secrets 写回主配置文件，需要对 `config/beartools.yaml` 做显式校验。

以下字段在主配置文件中的约束如下：

- `siyuan.token`
- `agent.primary.api_key`
- `agent.candidates[*].api_key`

报错原则：

- 只指出字段路径
- 明确提示应迁移到 `config/beartools.secrets.yaml` 或环境变量
- 不回显真实敏感值

校验规则：

- `siyuan.token` 不允许出现在主配置文件中
- `agent.*.api_key` 允许出现在主配置文件中，但只允许 `@get ...` 引用语法，不允许明文 key

示例报错：

- `siyuan.token 属于敏感配置，请改放到 config/beartools.secrets.yaml 或环境变量`
- `agent.primary.api_key 属于敏感配置，请改放到 config/beartools.secrets.yaml 或环境变量`

### 6. 运行时边界

本次改造尽量把变更收敛在配置层。

#### `src/beartools/config.py`

主要改动集中在这里：

- 读取多个 YAML 配置源
- 按优先级合并配置
- 校验主配置文件中不得出现敏感字段
- 校验 `api_key` 若出现在主配置中，只允许为 Dynaconf `@get ...` 引用，不允许为明文 key
- 产出与当前兼容的 `Config` 数据类

#### `src/beartools/llm/runtime.py`

不调整主业务逻辑。运行时仍直接读取解析后的 `config.agent.*.api_key`。

#### `src/beartools/llm/factory.py`

不调整主业务逻辑。工厂继续消费 `RuntimeNode.api_key`。

#### `doctor llm`

不增加独立 secrets 解析逻辑，继续复用统一配置加载结果。

这样可以保持职责边界清晰：

- 配置层负责“从哪里读”
- 运行时与工厂层负责“怎么用”

## 示例结构

### `config/beartools.yaml`

```yaml
log:
  path: "log/beartools.log"
  level: "INFO"

doctor:
  enabled_checks:
    - "google_ping"
    - "opencli"
    - "siyuan"
    - "llm"

siyuan:
  default_note: "REPLACE_ME_NOTE_ID"
  notebook: "REPLACE_ME_NOTEBOOK_ID"
  path: "/REPLACE_ME_PATH"

agent:
  primary:
    name: "primary"
    provider: "openai"
    base_url: "https://api.example.com/v1"
    model: "gpt-4.1-mini"
    api_key: "@get agent.openrouter.key"
    extra_headers: {}
    timeout_seconds: 30
  candidates:
    - name: "candidate-1"
      provider: "openrouter"
      base_url: "https://api-backup.example.com/v1"
      model: "gpt-4.1-mini"
      api_key: "@get agent.zhizengzeng.key"
      extra_headers: {}
      timeout_seconds: 30
```

### `config/beartools.secrets.yaml`

```yaml
siyuan:
  token: "REPLACE_ME"

agent:
  openrouter:
    key: "REPLACE_ME"
  zhizengzeng:
    key: "REPLACE_ME"
```
说明：

- `agent.primary.api_key="@get agent.openrouter.key"` 表示该节点实际读取 `agent.openrouter.key`
- `agent.candidates[0].api_key="@get agent.zhizengzeng.key"` 表示该节点实际读取 `agent.zhizengzeng.key`
- 如果多个节点使用同一把 key，可以配置相同的 `@get` 引用，从而合并相同的 key
- 若 `@get` 指向的路径不存在，应在配置解析阶段尽早报错

## 测试设计

采用 TDD，先补失败测试，再改配置实现。

### 重点覆盖行为

1. **主配置 + secrets 合并成功**
   - `beartools.yaml` 提供非敏感字段
   - `beartools.secrets.yaml` 提供 `siyuan.token` 和 `@get` 指向的完整路径配置
   - 最终 `Config` 能正确拿到完整配置

2. **环境变量覆盖 secrets**
   - 当环境变量存在时，应覆盖 `beartools.secrets.yaml` 中同名敏感字段

3. **主配置中出现非法敏感字段时报错**
   - `beartools.yaml` 包含 `siyuan.token`
   - 或 `agent.*.api_key` 为明文值而非 `@get ...`
   - `load_config()` 直接失败，并返回明确报错

4. **节点按 `@get` 正确解析真实 key**
   - `primary.api_key="@get agent.openrouter.key"`
   - secrets 中存在 `agent.openrouter.key`
   - 最终 `config.agent.primary.api_key` 为对应真实值

5. **多个节点复用同一个 `@get` 引用时可合并同一把 key**
   - 多个节点配置相同 `@get` 引用
   - 最终都解析到同一个真实 key

6. **只有主配置、没有 secrets 时仍可加载非敏感配置**
   - 前提是调用路径没有强依赖对应敏感字段
   - 这样可保持部分命令在无 secrets 场景下仍可运行

7. **sample 文件结构正确**
   - `beartools.yaml.sample` 不再出现敏感字段
   - `beartools.secrets.yaml.sample` 包含敏感字段占位值

8. **`@get` 路径不存在或语法非法时尽早报错**
   - 避免运行时才发现节点没有可用 key

### 受影响测试文件

- `tests/test_config.py`
  - 新增 secrets 合并、敏感字段禁用、环境变量覆盖、sample 校验相关测试

如有必要，可补充运行时层回归测试，但本次核心验证应放在配置层。

## 影响范围

### 代码文件

- `src/beartools/config.py`
  - 扩展多文件加载与敏感字段校验

### 配置文件

- `config/beartools.yaml.sample`
  - 移除敏感字段
- `config/beartools.secrets.yaml.sample`
  - 新增 secrets 示例
- `.gitignore`
  - 新增忽略 `config/beartools.secrets.yaml`

### 测试文件

- `tests/test_config.py`

## 风险与兼容性

### 风险

1. **`@get` 路径写错会导致节点取错 key**
   - 如果节点的 `@get` 路径写错，可能导致取到错误 key 或取不到 key
   - 因此需要在配置解析阶段显式校验引用路径是否存在

2. **主配置报错会影响已有本地配置**
   - 已有用户需要把敏感字段拆到 secrets 文件
   - 这是有意的行为收敛，用于消除误提交风险

### 兼容性结论

这是一次配置组织方式调整，不改变 `Config` 对外数据结构，也不改变 LLM 运行时和工厂的调用接口。

对调用方而言：

- 成功加载后的使用方式保持不变
- 仅配置来源与校验规则发生变化

## 实施后预期结果

完成后，项目将具备以下行为：

1. `config/beartools.yaml` 可安全提交到仓库
2. `config/beartools.secrets.yaml` 用于本地私有密钥，不进入 Git
3. 环境变量仍可作为最高优先级覆盖手段
4. 若用户把 `siyuan.token` 或 `agent.*.api_key` 写回主配置，会在加载阶段立即收到明确报错
5. 多个节点可通过相同 `@get` 引用复用同一把真实 key，避免重复维护相同 secrets
6. `llm/runtime.py` 与 `llm/factory.py` 无需承担额外的 secrets 读取职责
