# 阶段二 · Prompt 管理 Prompt Management

> 把 Prompt 从「散落在代码里的字符串」升级成「有版本、能灰度、能回滚的配置」。
> 一句话价值：**运营/产品在 UI 改 Prompt 就能上线，工程师不介入；出问题一键回滚。**

## 0. 心智模型

```
代码里只写：get_prompt("名字", label="production")
                     ↓
        Langfuse 服务端存着这个名字的很多个版本
                     ↓
        production 标签当前指向哪一版，线上就用哪一版
```

- **版本(version)**：每次 `create_prompt` 或在 UI 保存 = 一个新版本（v1、v2、v3…），只增不改。
- **标签(label)**：像 Git 分支指针，`production` / `staging` 各指向某一个版本。改标签指向 = 改线上行为，**代码不动**。

## 1. 两种 Prompt 类型

| 类型 | 内容形态 | 适用 |
| --- | --- | --- |
| `text` | 一个字符串，含 `{{变量}}` | 单轮、补全式 |
| `chat` | 消息数组 `[{role, content}, ...]` | 多轮对话、带 system 设定 |

变量统一用 **双大括号** `{{variable}}`（mustache 风格）。

## 2. 核心 API

### 创建 / 新增版本
```python
langfuse.create_prompt(
    name="tutorial-周报助手",
    prompt="把工作流水整理成周报：\n{{content}}",   # text 是字符串；chat 是消息列表
    labels=["production"],      # 带上 production 即设为线上默认
    type="text",                # 或 "chat"
    commit_message="v1 初版",   # 变更说明，便于回溯
)
```

### 拉取（默认取 production）
```python
prompt = langfuse.get_prompt("tutorial-周报助手")                 # 默认 label=production
prompt = langfuse.get_prompt("tutorial-周报助手", label="staging")  # 指定标签
prompt = langfuse.get_prompt("tutorial-周报助手", version=2)        # 指定版本（一般用于调试）
```

### 填充变量
```python
text = prompt.compile(content="周一修 bug；周三写检索…")   # text → 返回字符串
messages = chat_prompt.compile(brand="Acme", question="…", history=[...])  # chat → 返回消息字典列表
```

### chat 的「消息占位符」——注入运行时历史
创建时放一条占位符消息：
```python
prompt=[
    {"role": "system", "content": "你是{{brand}}客服"},
    {"type": "placeholder", "name": "history"},   # ← 占位符
    {"role": "user", "content": "{{question}}"},
]
```
compile 时用同名参数注入一段消息列表：
```python
prompt.compile(brand="Acme", question="…", history=[
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "您好～"},
])
```

### 客户端缓存（零额外延迟）
```python
prompt = langfuse.get_prompt("名字", cache_ttl_seconds=60)
```
拉取一次后本地缓存 60 秒，期间再取不走网络；缓存过期后后台刷新，**不阻塞**你的请求。生产环境强烈建议开缓存。

> 生产健壮性建议：`get_prompt(..., fallback="兜底文案", max_retries=2)`，网络异常时用兜底 Prompt，保证不因拉取失败而挂。

## 3. Prompt 关联 Trace（按版本看效果）

### 手工 generation（本阶段 s7 用法）
```python
prompt = langfuse.get_prompt("tutorial-周报助手")
with langfuse.start_as_current_observation(
    as_type="generation", name="glm-answer", model="glm-4",
    input=prompt.compile(content=raw), prompt=prompt,  # ★ 关联
) as gen:
    ...
```

### LangChain 场景的关联写法
把 Langfuse prompt 转成 LangChain 模板，并在 `metadata` 里带上原始 prompt 对象：
```python
from langchain_core.prompts import ChatPromptTemplate
lf_prompt = langfuse.get_prompt("名字", type="chat")
lc_prompt = ChatPromptTemplate.from_messages(
    lf_prompt.get_langchain_prompt(),
    metadata={"langfuse_prompt": lf_prompt},   # ← Langfuse 据此自动关联
)
```

关联后，在 UI 的 **Prompts → 某 prompt → Metrics** 里能看到「该版本的调用量 / 延迟 / 关联评分」，
这就是「用数据决定 v2 要不要全量」的依据。

## 4. Playground（UI 内调试）

任意 generation 右上角 **Open in Playground** → 直接改 Prompt / 换模型 / 调参数试跑
→ 满意后 **Save as new prompt version**。适合非工程同学快速迭代。

---

## 5. 本阶段脚本与动手清单

| 脚本 | 学到的东西 |
| --- | --- |
| `s5_prompt版本与label灰度.py` | 创建多版本、用 label 控制线上版本、UI 里灰度切换 + 回滚 |
| `s6_prompt变量与缓存.py` | chat 模板、`{{变量}}`、历史占位符、客户端缓存 |
| `s7_prompt关联trace.py` | 把 Prompt 版本关联到 generation，按版本分析效果 + Playground |

### 运行
```bash
python "Langfuse实战/02_Prompt管理/s5_prompt版本与label灰度.py"
python "Langfuse实战/02_Prompt管理/s6_prompt变量与缓存.py"
python "Langfuse实战/02_Prompt管理/s7_prompt关联trace.py"   # 依赖 s5 播种的 prompt
```

> 注：`s5`/`s6` 内置了「已存在则跳过播种」，可安全重复运行，不会疯狂造版本。

## 6. 自检清单

- [ ] 在 UI Prompts 看到 `tutorial-周报助手`（≥2 版）和 `tutorial-客服助手`
- [ ] 在 UI 把 production 从 v1 挪到 v2，重跑 `s5`，production 结果随之改变（代码没动）
- [ ] 再把 production 挪回 v1，验证「一键回滚」
- [ ] `s6` 打印出的 compile 结果里，history 两条历史消息被正确注入
- [ ] `s7` 的 trace 里 generation 显示了关联的 Prompt 版本

---

## 附录 · API 速查表（完整签名 + 逐参数说明）

> 以下签名取自已安装的 **Langfuse SDK `4.14.3`** 源码，按本章脚本用到顺序排列。
> 标记：✅ 必填 · ⚪ 可选（带默认值）。所有带 `*,` 的参数都必须以关键字传入。

### A. 客户端鉴权、上报与当前 Trace

#### `langfuse.auth_check()` —— 阻塞式校验当前鉴权配置

```python
langfuse.auth_check() -> bool
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| — | — | — | — | 无参数；同步发起 HTTP 请求，鉴权有效返回 `True`，否则返回 `False` |

> 本章三个短脚本都在启动时调用它以便快速失败。它会产生网络请求，不要放在每次业务调用的热路径上。

#### `langfuse.flush()` —— 立即上报客户端缓冲区中的数据

```python
langfuse.flush() -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| — | — | — | — | 无参数；阻塞至当前缓冲区中的 span、score、event 等数据发送完毕 |

> 短脚本退出前应调用 `flush()`，避免进程结束时缓冲数据尚未发出。它保证数据送达 API，但服务端查询界面仍可能因异步处理而稍后才显示。

#### `langfuse.get_current_trace_id()` —— 读取当前活动上下文的 Trace ID

```python
langfuse.get_current_trace_id() -> str | None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| — | — | — | — | 无参数；活动观测上下文内返回 Trace ID，没有活动上下文时返回 `None` |

> 必须在 `@observe` 函数体内或 `with start_as_current_observation(...)` 块内读取。本章 `s7` 在外层 `@observe` 尚未结束时读取，因此能够返回该次调用的 Trace ID。

---

### B. `create_prompt(...)` —— 创建 Prompt 或为同名 Prompt 新增版本

```python
langfuse.create_prompt(
    *,
    name: str,
    prompt: str | list[ChatMessageDict | ChatMessagePlaceholder],
    labels: list[str] = [],
    tags: list[str] | None = None,
    type: "chat" | "text" | None = "text",
    config: Any | None = None,
    commit_message: str | None = None,
) -> TextPromptClient | ChatPromptClient
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | str | ✅ | — | Prompt 名；同名再次创建会新增一个不可变版本，而不是覆盖旧版本 |
| `prompt` | str \| list[ChatMessageDict \| ChatMessagePlaceholder] | ✅ | — | `text` 使用字符串；`chat` 使用普通消息与消息占位符组成的列表 |
| `labels` | list[str] | ⚪ | `[]` | 为新版本绑定的标签；标签可使用任意自定义字符串 |
| `tags` | list[str] \| None | ⚪ | None | Prompt 级标签，用于分类和筛选；与指向具体版本的 label 不同 |
| `type` | `"chat"` \| `"text"` \| None | ⚪ | `"text"` | Prompt 内容类型 |
| `config` | Any \| None | ⚪ | None | 随 Prompt 保存的额外结构化配置，例如模型参数 |
| `commit_message` | str \| None | ⚪ | None | 当前版本的变更说明，便于审计与回溯 |

`type` 枚举：

| 值 | 含义 |
| --- | --- |
| `"text"` | 文本 Prompt；`prompt` 为字符串，`compile()` 返回字符串 |
| `"chat"` | 对话 Prompt；`prompt` 为消息列表，`compile()` 返回消息序列 |

> `labels` **不是** `production` / `staging` 固定枚举，可以使用任意业务字符串。只有 `production` 具有“不指定 `version` 和 `label` 时默认拉取”的 SDK 语义；`staging` 只是本教程采用的灰度命名约定。
>
> `labels=[]` 是 SDK `4.14.3` 的真实签名默认值。调用时不要在外部持有并修改这个默认列表。

---

### C. `get_prompt(...)` —— 按名称、版本或标签拉取 Prompt

```python
prompt = langfuse.get_prompt(
    name: str,
    *,
    version: int | None = None,
    label: str | None = None,
    type: "chat" | "text" = "text",
    cache_ttl_seconds: int | None = None,
    fallback: list[ChatMessageDict] | str | None = None,
    max_retries: int | None = None,
    fetch_timeout_seconds: int | None = None,
) -> TextPromptClient | ChatPromptClient
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | str | ✅ | — | 要拉取的 Prompt 名；这是唯一一个位置参数 |
| `version` | int \| None | ⚪ | None | 指定不可变版本号；通常与 `label` 二选一 |
| `label` | str \| None | ⚪ | None | 指定任意自定义标签；`version`、`label` 都不传时按 `production` 拉取 |
| `type` | `"chat"` \| `"text"` | ⚪ | `"text"` | 声明要拉取的 Prompt 类型，并决定客户端与 fallback 的内容形态 |
| `cache_ttl_seconds` | int \| None | ⚪ | None | `None` 使用 SDK 默认 TTL 60 秒；`0` 禁用缓存；正整数设置自定义缓存秒数 |
| `fallback` | list[ChatMessageDict] \| str \| None | ⚪ | None | 拉取失败时的兜底内容：text 传 `str`，chat 传消息字典列表 |
| `max_retries` | int \| None | ⚪ | None | 覆盖客户端默认的最大重试次数 |
| `fetch_timeout_seconds` | int \| None | ⚪ | None | 覆盖客户端默认的单次拉取超时秒数 |

`type` 枚举：

| 值 | 返回类型 | `fallback` 类型 |
| --- | --- | --- |
| `"text"` | `TextPromptClient` | `str` |
| `"chat"` | `ChatPromptClient` | `list[ChatMessageDict]` |

`cache_ttl_seconds` 取值语义：

| 值 | 含义 |
| --- | --- |
| `None` | 使用 SDK 默认 TTL，即 60 秒 |
| `0` | 禁用本地 Prompt 缓存 |
| 正整数 | 使用指定秒数作为缓存 TTL |

> 签名默认值确实是 `None`，但其运行语义是“采用默认 TTL 60 秒”，两者不矛盾。命中有效缓存时不发网络请求；使用 fallback 创建的 Prompt，其 `version` 为 `0`。

---

### D. PromptClient 编译方法与关键属性

#### `TextPromptClient.compile(**kwargs)` —— 填充文本模板变量并返回字符串

```python
TextPromptClient.compile(**kwargs: str | Any) -> str
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `**kwargs` | str \| Any | 由模板决定 | — | key 对应模板中的 `{{变量名}}`，value 是要填入的运行时值 |

#### `ChatPromptClient.compile(**kwargs)` —— 填充对话模板并展开消息占位符

```python
ChatPromptClient.compile(**kwargs: str | Any) -> Sequence[ChatMessageDict]
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `**kwargs` | str \| Any | 由模板决定 | — | key 可对应 `{{变量名}}`，也可对应 `{"type": "placeholder", "name": "..."}` 的 `name`；消息占位符传消息列表 |

`kwargs` 的 key **没有固定枚举**，完全由当前 Prompt 内容动态决定：

| 来源 | 示例 key | 传值示例 |
| --- | --- | --- |
| `{{变量}}` | `brand`、`tone`、`question` | `brand="Acme 商城"` |
| chat placeholder 的 `name` | `history` | `history=[{"role": "user", "content": "你好"}]` |

> Text Prompt 不存在消息占位符；Chat Prompt 才能通过 placeholder 注入一段运行时消息。缺少模板要求的 key 时不能得到完整编译结果，多传的 key 也不应当作固定 API 参数理解。

#### `prompt.version` / `prompt.variables` —— 查看版本与模板变量

```python
prompt.version: int
prompt.variables: list[str]
```

| 属性 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `prompt.version` | int | — | 服务端版本；fallback 为 `0` | 当前 Prompt 的不可变版本号 |
| `prompt.variables` | list[str] | — | `[]`（无模板变量时） | 从内容中的 `{{变量}}` 解析出的变量名列表 |

> Chat Prompt 的 `variables` 会扫描各消息内容里的 `{{变量}}`，但**不会**把消息占位符的 `name` 计入。例如本章客服模板的结果是 `brand`、`tone`、`question`，不包含 `history`；`history` 仍须在 `compile()` 时按 placeholder 名传入。

---

### E. `@observe(...)` —— 给函数自动创建观测节点

```python
from langfuse import observe

observe(
    func=None,
    *,
    name=None,
    as_type=None,
    capture_input=None,
    capture_output=None,
    transform_to_string=None,
)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `func` | Callable \| None | ⚪ | None | 被装饰函数；支持直接写 `@observe`，通常不手工传入 |
| `name` | str \| None | ⚪ | None | 观测名称；`None` 时使用函数名 |
| `as_type` | str \| None | ⚪ | None | 观测类型；`None` 按 `span` 处理，九种取值见下表 |
| `capture_input` | bool \| None | ⚪ | None | 是否记录函数入参；`None` 使用 SDK 默认行为，默认捕获，并受 `LANGFUSE_OBSERVE_DECORATOR_IO_CAPTURE_ENABLED` 控制 |
| `capture_output` | bool \| None | ⚪ | None | 是否记录函数返回值；`None` 使用 SDK 默认行为，默认捕获 |
| `transform_to_string` | Callable \| None | ⚪ | None | 生成器函数专用：把产生的片段转换并汇总为可记录的输出字符串 |

`as_type` 九种枚举：

| 值 | 含义 | 典型场景 |
| --- | --- | --- |
| `"span"` | 通用工作单元，也是默认类型 | 格式化、普通业务逻辑 |
| `"generation"` | 大语言模型生成 | 对话或文本补全调用 |
| `"embedding"` | 嵌入模型调用 | 文本向量化 |
| `"agent"` | 可自主决策的执行体 | ReAct Agent、动态 LangGraph |
| `"tool"` | 外部工具调用 | 搜索、数据库、业务 API |
| `"chain"` | 固定编排流程 | LCEL Chain、固定 RAG 流程 |
| `"retriever"` | 检索步骤 | 向量检索、关键词检索 |
| `"evaluator"` | 评估步骤 | 规则评分、LLM-as-judge 外层 |
| `"guardrail"` | 安全或合规护栏 | PII 脱敏、越狱检测 |

> `capture_input=False` / `capture_output=False` 可对单个装饰器显式关闭采集；传 `None` 不是“不采集”，而是采用 SDK 默认行为。`@observe` 与 `@observe(...)` 两种形式都受 `func` 参数支持。

---

### F. `start_as_current_observation(...)` —— 手工创建当前观测上下文

```python
with langfuse.start_as_current_observation(
    *,
    trace_context=None,
    name,
    as_type="span",
    input=None,
    output=None,
    metadata=None,
    version=None,
    level=None,
    status_message=None,
    completion_start_time=None,
    model=None,
    model_parameters=None,
    usage_details=None,
    cost_details=None,
    prompt=None,
    end_on_exit=None,
) as observation:
    ...
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `trace_context` | TraceContext \| None | ⚪ | None | 续接已有 Trace 或指定父节点，例如传入 `trace_id` / `parent_span_id` |
| `name` | str | ✅ | — | 观测节点名称 |
| `as_type` | str | ⚪ | `"span"` | 观测类型；九种枚举与 E 节完全相同 |
| `input` | Any \| None | ⚪ | None | 观测输入 |
| `output` | Any \| None | ⚪ | None | 创建时已知的观测输出；也可稍后通过对象 `update()` 补充 |
| `metadata` | Any \| None | ⚪ | None | 自定义元数据 |
| `version` | str \| None | ⚪ | None | 应用、组件或业务逻辑版本 |
| `level` | str \| None | ⚪ | None | 日志级别；四种枚举见下表 |
| `status_message` | str \| None | ⚪ | None | 状态补充说明 |
| `completion_start_time` | datetime \| None | ⚪ | None | 首个模型输出开始时间，用于计算首 token 延迟 |
| `model` | str \| None | ⚪ | None | 模型名称，用于模型维度聚合与成本计算 |
| `model_parameters` | dict \| None | ⚪ | None | 模型调用参数，例如 temperature、max_tokens |
| `usage_details` | dict[str, int] \| None | ⚪ | None | token 用量明细 |
| `cost_details` | dict[str, float] \| None | ⚪ | None | 自定义成本明细 |
| `prompt` | TextPromptClient \| ChatPromptClient \| None | ⚪ | None | 关联本次模型调用所使用的 Langfuse Prompt 版本 |
| `end_on_exit` | bool \| None | ⚪ | None | `None` 使用上下文管理器默认行为；通常离开 `with` 时自动结束观测 |

`as_type` 九种枚举：

| 值 | 含义 |
| --- | --- |
| `"span"` | 通用工作单元，也是默认类型 |
| `"generation"` | 大语言模型生成 |
| `"embedding"` | 嵌入模型调用 |
| `"agent"` | 可自主决策的执行体 |
| `"tool"` | 外部工具调用 |
| `"chain"` | 固定编排流程 |
| `"retriever"` | 检索步骤 |
| `"evaluator"` | 评估步骤 |
| `"guardrail"` | 安全或合规护栏 |

`level` 四种枚举：

| 值 | 含义 |
| --- | --- |
| `"DEBUG"` | 调试信息 |
| `"DEFAULT"` | 默认级别 |
| `"WARNING"` | 警告 |
| `"ERROR"` | 错误 |

> `model`、`completion_start_time`、`model_parameters`、`usage_details`、`cost_details`、`prompt` 这些模型调用字段仅对 `generation` / `embedding` 类型有意义，不应把 token 或成本信息塞到普通 span、tool、retriever 等外层节点。

---

### G. `generation.update(...)` —— 补写当前 Generation 对象的输出与模型用量

```python
generation.update(
    *,
    name=None,
    input=None,
    output=None,
    metadata=None,
    version=None,
    level=None,
    status_message=None,
    completion_start_time=None,
    model=None,
    model_parameters=None,
    usage_details=None,
    cost_details=None,
    prompt=None,
    **kwargs,
) -> LangfuseObservationWrapper
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | str \| None | ⚪ | None | 更新观测名称 |
| `input` | Any \| None | ⚪ | None | 更新模型输入 |
| `output` | Any \| None | ⚪ | None | 更新模型输出；本章 `s7` 在模型返回后写入回答 |
| `metadata` | Any \| None | ⚪ | None | 更新自定义元数据 |
| `version` | str \| None | ⚪ | None | 更新应用或组件版本 |
| `level` | str \| None | ⚪ | None | 更新日志级别；枚举为 `DEBUG`、`DEFAULT`、`WARNING`、`ERROR` |
| `status_message` | str \| None | ⚪ | None | 更新状态说明 |
| `completion_start_time` | datetime \| None | ⚪ | None | 更新首个模型输出开始时间 |
| `model` | str \| None | ⚪ | None | 更新模型名称 |
| `model_parameters` | dict \| None | ⚪ | None | 更新模型调用参数 |
| `usage_details` | dict[str, int] \| None | ⚪ | None | 更新 token 用量；值必须是整数 |
| `cost_details` | dict[str, float] \| None | ⚪ | None | 更新自定义成本明细 |
| `prompt` | TextPromptClient \| ChatPromptClient \| None | ⚪ | None | 补充或更新关联的 Prompt 版本 |
| `**kwargs` | Any | ⚪ | — | SDK 兼容扩展关键字；常规代码优先使用上面的显式字段 |

本教程的 `usage_details` 键约定：

| key | 类型 | 含义 |
| --- | --- | --- |
| `"input"` | int | 输入 token 数 |
| `"output"` | int | 输出 token 数 |
| `"total"` | int | 总 token 数 |

> `usage_details` 的正式类型是 `dict[str, int]`；字典允许 SDK 支持的其他用量键，本教程脚本使用 `input` / `output` / `total`。
>
> 本章脚本持有 `with ... as generation` 返回的对象，因此应调用 `generation.update(...)`。`langfuse.update_current_generation(...) -> None` 是“不持有对象引用时，更新当前活动 generation”的客户端方法，使用场景不同；它不是本章 `s7` 的实际写法，也没有 `generation.update()` 的返回对象与 `**kwargs`。

---

### H. Prompt 与 Trace 关联的完整调用链

```python
prompt = langfuse.get_prompt("tutorial-周报助手", label="production")
compiled = prompt.compile(content=raw)

with langfuse.start_as_current_observation(
    name="glm-answer",
    as_type="generation",
    model="glm-4",
    input=compiled,
    prompt=prompt,
) as generation:
    response = glm_model.invoke([HumanMessage(compiled)])
    generation.update(
        output=response.content,
        usage_details={"input": 120, "output": 80, "total": 200},
    )
```

关联后，UI 的 **Prompts → 某 Prompt → Metrics** 可按具体版本查看调用量、延迟和关联评分。LangChain 场景使用 `get_langchain_prompt()` 与 `metadata={"langfuse_prompt": lf_prompt}` 的方式见正文第 3 节。
