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
| `s1_基础trace嵌套span.py` | `@observe` + generation 上下文，组一棵三层树 | Tracing → 名为 `rag-qa` 的树 |
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

- [ ] `s1` 在 UI 看到 `retrieve-docs → build-prompt → glm-answer` 三层
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
| `as_type` | str | ⚪ | `"span"` | 观测类型：`"span"`/`"generation"`/`"agent"`/`"tool"`/`"chain"`/`"retriever"`/`"embedding"`/`"evaluator"`/`"guardrail"`。只有 `generation`/`embedding` 才能再设 model/usage/cost |
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
| `CallbackHandler` | 已用 LangChain，懒得改业务代码 | 框架自动填 |
