# 阶段一 · 可观测性 Observability

> 先把「线上到底发生了什么」看清楚。后面所有的 Prompt 管理、评估，都建立在 trace 之上。

## 0. 核心概念（先记住这 4 个词）

| 概念 | 含义 | 类比 |
| --- | --- | --- |
| **Trace（链路）** | 一次完整请求的全过程 | 一整趟快递物流 |
| **Observation（观测点）** | trace 里的一个节点，是构成树的基本单位 | 物流里的每个中转站 |
| **Span（跨度）** | 普通观测点：检索、拼 prompt、工具调用等 | 普通中转站 |
| **Generation（生成）** | 特殊的 span，专门记录**模型调用**（含 model、token、成本） | 关键分拣中心 |

一个 Trace 里可以嵌套很多层 Span / Generation，形成一棵树。

## 1. 官方推荐的三种埋点方式

Langfuse Python SDK v4（本项目 `4.14.1`，基于 OpenTelemetry）推荐：

### 方式 A：`@observe` 装饰器（最省事）
给任意函数加一行装饰器，自动记录入参、返回值、耗时、异常。嵌套调用自动形成树。
```python
from langfuse import observe

@observe(name="retrieve-docs")          # 普通 span
def retrieve_docs(query): ...

@observe(name="llm-call", as_type="generation")  # 模型调用用 generation
def call_llm(prompt): ...
```

### 方式 B：`start_as_current_observation` 上下文管理器（最灵活）
需要手工控制一个 span/generation 的字段时用：
```python
with langfuse.start_as_current_observation(
    as_type="generation", name="glm-answer", model="glm-4", input=prompt
) as gen:
    resp = call_model(prompt)
    gen.update(output=resp.content, usage_details={"input": 10, "output": 20})
```

### 方式 C：LangChain 回调（框架自动埋点）
用 LangChain 时，挂一个 `CallbackHandler`，模型调用自动变成 generation：
```python
from langfuse.langchain import CallbackHandler
handler = CallbackHandler()
model.invoke(messages, config={"callbacks": [handler]})
```
> 三种方式可以混用：外层用 `@observe` 定义业务链路，模型调用交给 LangChain 回调自动挂进去。

### LangGraph 场景：优先用 CallbackHandler（方式 C）

`CompiledGraph` 本质是一个 LangChain Runnable，所以**挂一次 `CallbackHandler`，整张图的 node / tool / 模型调用全自动记录**，不用给每个 node 手插 `@observe`。这是 LangGraph 下的默认解——尤其是平台托管（本项目有 `langgraph.json`）时，图由平台执行，你很难往每个 node 里插装饰器，callback 几乎是唯一现实选项。

```python
from langfuse.langchain import CallbackHandler
from langfuse import propagate_attributes

langfuse_handler = CallbackHandler()

with propagate_attributes(
    user_id="user-xiaotian",
    session_id="agent-session-001",   # 多轮 agent 对话靠它串到一个 Session
    tags=["langgraph", "rag-agent"],
):
    final_state = graph.invoke(
        initial_state,
        config={"callbacks": [langfuse_handler]},   # ← 整张图在这自动展开
    )
```

自动产生的 trace 树（每个 super-step / 每轮循环都会展开）：
```
trace: graph 执行
 ├─ node: retrieve   (span)
 ├─ node: llm_call   (span)
 │   └─ glm-4 调用    (generation，自动带 model / usage / 成本)
 └─ node: tool_xxx   (tool)
```

LangGraph 相比普通 LangChain 多出的几个坑：

1. **state 会被整个记进 input/output**：node 之间传的 `state` 往往很大（完整消息历史、中间结果），callback 会全部序列化进 trace，导致臃肿 / 隐私 / 成本三连。对敏感或巨型 node 用 `@observe(capture_input=False, capture_output=False)`，或只对外暴露精简字段。
2. **agent 循环让 trace 很长**：ReAct / 反思循环里 LLM 被反复调，一条 trace 可能几十个 generation。这恰好是自动记 usage 的价值——UI 上能看整条对话总成本，以及哪个 node 在烧钱。
3. **checkpointer ≠ trace**：`.langgraph_api/*.pckl` 是 LangGraph 的**状态持久化**（用于中断恢复、time-travel），和 Langfuse trace 是两套东西——前者管「状态怎么存以便恢复」，后者管「发生了什么以便观测」，互补不替代。
4. **自动产生的 span 别重复标**：node 里的工具调用已被 callback 标成 tool，别再在工具函数上加 `@observe(as_type="tool")`，否则出现两个重叠的 tool span。

> LangGraph 的埋点优先级：**callback 自动埋点 → `propagate_attributes` 打 user/session/tags → 个别 node 用 `@observe` 加业务命名或控制 state 暴露 → `start_as_current_observation` 兜底（自定义 trace_id、跨进程续接）**。

## 2. 设置 Trace 级别的属性

`user_id` / `session_id` / `tags` / `metadata` 这类**整条 trace 的属性**，官方推荐用
`propagate_attributes` 上下文管理器统一设置（块内所有 span 自动继承）：
```python
from langfuse import propagate_attributes

with propagate_attributes(
    user_id="user-xiaotian",
    session_id="session-001",
    tags=["rag", "weekly-report"],
    metadata={"department": "研发部"},
):
    do_something()   # 里面所有 span 都会带上以上属性
```

而只想更新**当前这个 span** 的字段，用 `langfuse.update_current_span(...)` /
`langfuse.update_current_generation(...)`。

## 3. 两个必须记住的细节

1. **短脚本结尾一定要 `langfuse.flush()`**：SDK 是异步批量上报的，脚本直接退出会丢数据。
2. **`get_current_trace_id()` 只能在 trace 上下文内调用**：`@observe` 函数返回后上下文就关了，要拿 trace_id 得在函数**内部**取（见 `s1` 的写法）。

---

## 4. 本阶段脚本与动手清单

| 脚本 | 学到的东西 | 跑完去 UI 看什么 |
| --- | --- | --- |
| `s1_基础trace嵌套span.py` | `@observe` + generation 上下文，组一棵三层树；顺带演示 retriever / span / generation 三种类型 | Tracing → 名为 `rag-qa` 的树 |
| `s2_session会话串联.py` | `propagate_attributes(session_id=...)` 串多轮对话 | Sessions → `demo-session-xiaotian-001` |
| `s3_user_tags_metadata_环境.py` | user / tags / metadata / environment | Tracing 用 tag、user、环境筛选 |
| `s4_成本与dashboard.py` | 批量调用 → 成本 / 延迟看板 | Dashboards 成本与延迟曲线 |

### 运行方式
```bash
# 在项目根目录执行
python "Langfuse实战/01_可观测性/s1_基础trace嵌套span.py"
python "Langfuse实战/01_可观测性/s2_session会话串联.py"
python "Langfuse实战/01_可观测性/s3_user_tags_metadata_环境.py"
python "Langfuse实战/01_可观测性/s4_成本与dashboard.py"
```

## 5. 给自定义模型（glm-4）配置定价 —— 让成本不为 0

Langfuse 内置了 OpenAI/Anthropic 等主流模型的定价，但 GLM 需要自己配：

1. UI 左下角 **Settings → Models → + New model definition**
2. 填写：
   - **Model name**：`glm-4`（要和代码里 generation 的 `model` 完全一致）
   - **Match pattern**：`(?i)^glm-4$`（正则匹配模型名）
   - **Input/Output price**：按你的实际单价填（单位：美元/1 token，注意换算）
   - **Tokenizer**：可留空或选通用
3. 保存后，**新产生**的 trace 就会带上成本（历史 trace 不会追溯）。

## 6. 自检清单

- [ ] `s1` 在 UI 看到 `retrieve-docs → build-prompt → glm-answer` 三层，且三者类型分别是 retriever / span / generation
- [ ] `s2` 在 Sessions 看到 3 轮对话，且第 3 轮模型「记得名字」
- [ ] `s3` 能用 tag=`weekly-report` 筛出 trace，且环境是 `development`
- [ ] `s4` Dashboard 出现成本/延迟曲线（配完定价后成本非 0）

---

## 附录 · API 速查表（完整签名 + 逐参数说明）

> 以下签名取自已安装的 **Langfuse SDK `4.14.3`** 源码，按本章脚本用到顺序排列。
> 标记：✅ 必填 · ⚪ 可选（带默认值）。所有「更新类」方法的参数都是关键字参数（`*,`）。

### A. 客户端获取与生命周期

#### `get_client(...)` —— 获取/创建全局单例客户端
```python
from langfuse import get_client
langfuse = get_client(*, public_key: str | None = None) -> Langfuse
```
| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `public_key` | str | ⚪ | None | 单项目留空即可；多项目（实验特性）须指定，否则返回「禁用客户端」防串数据 |

> 鉴权信息从环境变量读取：`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`（见 `.env`）。

#### `langfuse.auth_check() -> bool`
无参数。**阻塞式**校验密钥有效性（同步发 HTTP 请求）。生产代码慎用，脚本里用于启动时快速失败。

#### `langfuse.flush() -> None`
无参数。强制把缓冲区所有 span/score/event 立即上报。**短脚本结尾必调**，否则进程退出丢数据。
注意：flush 只保证「送达 API」；服务端异步入库后才能查询（约 15–30s）。

#### `langfuse.shutdown() -> None`
无参数。`flush()` + 关闭后台线程。长驻服务退出时调用；脚本一般 `flush()` 即可（SDK 在 atexit 会自动 shutdown）。

#### `langfuse.get_current_trace_id() -> str | None`
无参数。返回当前上下文的 trace id。**只能在 trace 上下文内调用**（`@observe` 函数体内、或 `with start_as_current_observation(...)` 块内），函数返回/离开块后即 `None`。

---

### B. `@observe(...)` 装饰器 —— 给函数自动埋点（最省事）
```python
from langfuse import observe

@observe(
    name: str | None = None,
    as_type: str | None = None,
    capture_input: bool | None = None,
    capture_output: bool | None = None,
    transform_to_string: Callable[[Iterable], str] | None = None,
)
```
| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | str | ⚪ | 函数名 | span 在 UI 显示的名字 |
| `as_type` | str | ⚪ | `"span"` | 观测类型，共九种，含义与选型见 [附录 I · 九种观测类型](#i-九种观测类型分别用在什么场景)。只有 `generation`/`embedding` 才能再设 model/usage/cost |
| `capture_input` | bool | ⚪ | True（受环境变量 `LANGFUSE_OBSERVE_DECORATOR_IO_CAPTURE_ENABLED` 控制） | 是否把函数入参记为 input |
| `capture_output` | bool | ⚪ | True | 是否把返回值记为 output |
| `transform_to_string` | Callable | ⚪ | None | 生成器函数：把 yield 的片段拼成 output 字符串 |

> 两种写法：`@observe`（无括号）或 `@observe(name="...")`（带括号）。嵌套装饰的函数自动形成父子 span 树。

---

### C. `propagate_attributes(...)` —— 给一段上下文统一打 trace 级属性（上下文管理器）
```python
from langfuse import propagate_attributes

with propagate_attributes(
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    version: str | None = None,
    tags: list[str] | None = None,
    trace_name: str | None = None,
    environment: str | None = None,
    prompt: PromptClient | Mapping | None = None,
    as_baggage: bool = False,
): ...
```
| 参数 | 说明 |
| --- | --- |
| `user_id` | 用户/租户 id；US-ASCII、≤200 字符；用于按用户聚合成本 |
| `session_id` | 会话 id；≤200 字符；把多轮对话归到一个 Session（UI 的 Sessions 页） |
| `metadata` | 自定义维度；key 需 ASCII、value 转字符串后 ≤200 字符；勿放大对象/敏感数据 |
| `version` | 应用/Agent 的版本号 |
| `tags` | 业务标签列表，用于筛选 |
| `trace_name` | 整条 trace 的名字 |
| `environment` | 覆盖 client 级环境（`"development"`/`"staging"`/`"production"`） |
| `prompt` | 关联的 PromptClient（或 `{"name":..,"version":..}`）；用于自动埋点库产生的 generation |
| `as_baggage` | 是否用 OTel baggage 跨进程传播（一般场景不用） |

> ⚠️ **尽早包裹**：只对「当前 span 及其后新建的子 span」生效，不回填已有 span。建议在 trace 根节点一进来就包。

---

### D. `start_as_current_observation(...)` —— 手工创建并成为当前 span（上下文管理器，最灵活）
```python
with langfuse.start_as_current_observation(
    *,
    name: str,                              # ✅ 观测点名字
    as_type: str = "span",
    trace_context: TraceContext | None = None,
    input: Any | None = None,
    output: Any | None = None,
    metadata: Any | None = None,
    version: str | None = None,
    level: "DEBUG" | "DEFAULT" | "WARNING" | "ERROR" | None = None,
    status_message: str | None = None,
    end_on_exit: bool | None = None,
    # —— 以下仅当 as_type 为 "generation" / "embedding" 时有意义 ——
    completion_start_time: datetime | None = None,
    model: str | None = None,
    model_parameters: dict | None = None,
    usage_details: dict[str, int] | None = None,
    cost_details: dict[str, float] | None = None,
    prompt: PromptClient | None = None,
) as generation:   # 类型随 as_type 变化：LangfuseSpan / LangfuseGeneration / LangfuseTool …
```
| 参数 | 说明 |
| --- | --- |
| `name` | ✅ 必填，观测点名字 |
| `as_type` | 观测类型，默认 `span`；要记模型成本就设 `generation` |
| `trace_context` | 链接/续接已有 trace（分布式追踪、自定义 trace_id），如 `{"trace_id": "...", "parent_span_id": "..."}` |
| `input` / `output` | 输入输出，任意可 JSON 序列化对象 |
| `metadata` | 自定义元数据 |
| `version` | 代码/组件版本 |
| `level` | 级别：`DEBUG` / `DEFAULT` / `WARNING` / `ERROR` |
| `status_message` | 状态描述 |
| `end_on_exit` | 默认 `True`：离开 `with` 时自动结束 span；设 `False` 须手工 end（否则内存泄漏） |
| `model` | 模型名（如 `"glm-4"`），UI 按此聚合成本 |
| `model_parameters` | 模型调用参数，如 `{"temperature": 0.7, "max_tokens": 1024}` |
| `usage_details` | token 用量，如 `{"input": 120, "output": 80, "total": 200}` |
| `cost_details` | 自定义成本明细；不填则按 `model` 的定价自动算 |
| `prompt` | 关联的 PromptClient（见 02 章） |

---

### E. `observation.update(...)` —— 更新当前观测点（span/generation **对象**方法）
```python
generation.update(
    *,
    name=None, input=None, output=None, metadata=None, version=None,
    level=None, status_message=None,
    completion_start_time=None, model=None, model_parameters=None,
    usage_details=None, cost_details=None, prompt=None,
)
```
参数与上面 D 节同名项含义一致。脚本里的典型用法：拿到模型返回后 `generation.update(output=..., usage_details={...})` 把输出和 token 补回去。

---

### F. `update_current_span(...)` / `update_current_generation(...)` —— 就地更新「当前活动 span」（不持对象引用）
```python
langfuse.update_current_span(
    *, name=None, input=None, output=None, metadata=None,
    version=None, level=None, status_message=None,
)
langfuse.update_current_generation(
    *, name=None, input=None, output=None, metadata=None, version=None,
    level=None, status_message=None,
    completion_start_time=None, model=None, model_parameters=None,
    usage_details=None, cost_details=None, prompt=None,
)
```
> 在 `@observe` 函数体内、或某个 `with` 块内，想就地改「当前这个 span」就用它（不必拿到 generation 对象）。`update_current_span` 只能改 span 通用字段；要改 model/usage 等用 `update_current_generation`。

---

### G. `CallbackHandler(...)` —— LangChain 自动埋点
```python
from langfuse.langchain import CallbackHandler
handler = CallbackHandler(*, public_key: str | None = None, trace_context: TraceContext | None = None)
```
| 参数 | 说明 |
| --- | --- |
| `public_key` | 多项目时指定；单项目留空 |
| `trace_context` | 续接上游 trace，或指定自定义 trace_id，如 `{"trace_id": "xxx"}` |

> 用法：`model.invoke(messages, config={"callbacks": [handler]})`，模型调用会被自动记为 generation。
> ⚠️ 该构造函数**只接受 `public_key` 与 `trace_context`**，不接 `metadata`/`tags`/`session_id`。这些 trace 级属性请用 `propagate_attributes(...)` 包裹调用（见 C 节）。

---

### H. 三种埋点怎么选（一句话）

| 方式 | 何时用 | 谁来设 model/usage |
| --- | --- | --- |
| `@observe` 装饰器 | 业务函数，想零侵入自动记入参/返回 | 不设；或 `as_type="generation"` 后在函数内 `update` |
| `start_as_current_observation` | 需要手工控制字段（自定义 trace_id、提前写 model） | 创建时 / 块内 `.update()` |
| `CallbackHandler` | 已用 LangChain / LangGraph，懒得改业务代码 | 框架自动填 |

---

### I. 九种观测类型分别用在什么场景

`as_type` 是一个**语义标签**：它不影响数据能不能记，但决定 UI 怎么分类、怎么筛选、成本看板怎么聚合。选对类型 = trace 一眼能读懂「每步在干什么」。

| 类型 | 是什么 | 典型场景 | 烧 token |
| --- | --- | --- | :---: |
| **span** | 最通用的「一段工作」，无特殊语义，默认类型 | 拼 prompt、格式化、任何不好归类的业务逻辑 | ✗ |
| **generation** | 调一次**大语言模型**（聊天/补全） | `glm_model.invoke(...)`、GPT、Claude 调用 | ✓ |
| **embedding** | 调一次**嵌入模型**（文本→向量） | 入库前向量化、查询向量化 | ✓ |
| **agent** | 一个**能自主决策**的实体的整体执行 | 整个 ReAct agent、有动态路径的 LangGraph | ✗（本身不烧，内部的 generation 才烧） |
| **tool** | agent 调用的**外部工具** | 搜索、计算器、查数据库、调业务 API | ✗ |
| **chain** | 多步串起来的**固定编排/流程** | LCEL chain、固定顺序的 RAG pipeline | ✗ |
| **retriever** | **检索**步骤（从知识库取回相关文档） | 向量检索、关键词检索、Milvus 查询 | ✗（检索本身是 DB 操作） |
| **evaluator** | **评估**环节（给输出打分） | LLM-as-judge、规则校验、自动评分 | ✗（若用 LLM 评，内部那次调用才是 generation） |
| **guardrail** | **护栏**（安全/合规校验） | 越狱检测、PII 脱敏、敏感词过滤、输出过滤 | ✗ |

#### 为什么只有 generation / embedding 能设 model / usage / cost

token 和模型成本这个概念，**只在「代码向一个按 token 计费的模型发了一次请求」时才存在**：
- `generation` 调 LLM → 有 input/output tokens → 有成本；
- `embedding` 调嵌入模型 → 也按 token 计费 → 有成本；
- 其余七种描述的是应用里的一个**步骤/组件**，它们本身不产生一次模型计费调用，衡量它们的是耗时、成败、input/output 数据，而不是 token。

#### 关键辨析：类型看「抽象形态」，不一定等于「功能语义」

用自动埋点（CallbackHandler）时，类型是**按 LangChain 的抽象形态自动判定的**，不一定等于这步的功能语义。最典型的例子：把 Milvus 检索包成 `@tool`——

| 你的实现方式 | 自动埋点判定的类型 |
| --- | --- |
| 用 LangChain retriever 抽象（`Milvus.as_retriever()`） | **retriever** ✓ |
| 用 `@tool` 把检索包成工具给 agent 调 | **tool**（callback 触发的是 `on_tool` 事件，据此标 tool） |

判断某步语义上该标什么，只问一句：**它的主要职责是不是「从某处取回相关数据」？** 是就是 retriever（哪怕被 `@tool` 包着），否则才是 tool。

想同时保住「实现形态」和「功能语义」，用**分层**——外层 tool 自动产生，内层手动补一个 retriever：

```python
from langchain_core.tools import tool
from Langfuse实战._bootstrap import langfuse


@tool
def search_knowledge_base(query: str) -> str:
    """从知识库检索资料，供 agent 调用。"""
    # 外层「tool」span 由 agent 的 CallbackHandler 自动产生，不用手标。
    # 这里手动补「纯检索」这一层，标成 retriever：
    with langfuse.start_as_current_observation(
        as_type="retriever",              # ← 功能语义：检索
        name="milvus-search",
        input={"query": query, "top_k": 3},
    ) as ret:
        docs = _query_milvus(query)       # ← 真正打向量的那一步
        ret.update(
            output={"hits": len(docs)},
            metadata={"scores": [d["score"] for d in docs]},
        )
    return "\n".join(d["text"] for d in docs)
```

UI 上得到两层，各记各的字段：
```
tool: search_knowledge_base      ← 自动（callback 的 on_tool 事件）
 └─ retriever: milvus-search     ← 手动（上面的 with 块）
```

> 同理，evaluator / retriever 内部若调了 LLM（如 LLM-as-judge、用 LLM 重排检索结果），那次调用应是它**内部一个单独的 generation 子节点**，而不是把 usage 塞到外层节点上——外层是语义，内层才是烧 token 的 generation。

#### 对应到本章代码

本章正式脚本 `s1_基础trace嵌套span.py` 已按语义标好类型：`retrieve-docs` → retriever、`build-prompt` → span、`glm-answer` → generation，可直接跑起来对照 UI。

而根目录的极简示例 `demo.py` 只用了 span / generation 两种，下表是它「现用类型 vs 语义更精确类型」的对照，帮你体会差异：

| 函数 | demo.py 现用 | 语义上更精确的类型 |
| --- | --- | --- |
| `call_llm` | generation ✓ | generation |
| `retrieve_docs` | span（默认） | retriever |
| `build_prompt` | span ✓ | span |
| `rag_qa` | span（`@observe` 默认） | 固定流程用 chain；若含 LLM 自主决策则 agent |
