# 阶段三 · 评估 Evaluation

> 建立「改动前后到底变好还是变坏」的护栏。这是大模型应用从玩具走向生产**最关键**的一环。
> 没有评估，你的每一次 Prompt/模型改动都是在盲改。

## 0. 评估体系的原子：Score（分数）

所有评估最终都落到给 trace（或 observation / session）挂一个 **Score**。

| 数据类型 | 值 | 例子 |
| --- | --- | --- |
| `NUMERIC` | 浮点数 | 相关性 `0.87` |
| `CATEGORICAL` | 字符串 | 质量 `"好"/"中"/"差"` |
| `BOOLEAN` | `1.0` / `0.0` | 是否点赞、是否合规 |

分数从哪来？四条途径，由易到难：

```
用户反馈(👍/👎)  →  规则打分  →  LLM 裁判自动打分  →  人工标注
   场景8            场景8         场景9              场景11
```

而 **Dataset + Experiment（场景10）** 则是把这些评估器用在「离线测试集」上，做上线前的回归测试。

## 1. 在线评估 vs 离线评估

| | 在线（线上流量） | 离线（测试集） |
| --- | --- | --- |
| 对象 | 生产真实 trace | Dataset 里的固定用例 |
| 目的 | 持续监控质量、发现劣化 | 上线前验证改动、防回归 |
| 手段 | 用户反馈、LLM-as-a-Judge | run_experiment + evaluators |
| 本阶段 | 场景 8、9、11 | 场景 10 |

## 2. 打分 API（场景 8）

```python
# 上下文内：给当前 trace 打分
langfuse.score_current_trace(name="length_ok", value=1.0, data_type="BOOLEAN", comment="…")

# 事后按 trace_id 追加（典型：前端用户点赞异步回传）
langfuse.create_score(
    trace_id=tid, name="user_feedback", value=1.0, data_type="BOOLEAN", comment="用户点了赞"
)

# 分类分：值必须是字符串
langfuse.create_score(trace_id=tid, name="quality", value="好", data_type="CATEGORICAL")
```
> `create_score` 甚至可以在 trace 还没上报时先按 id 打分，之后自动关联。

## 3. LLM-as-a-Judge（场景 9）

### 方案 A：UI 托管（生产推荐，无需写代码）
1. UI → **Evaluators / LLM-as-a-Judge → + New evaluator**
2. 选内置模板（Hallucination / Relevance / Toxicity / Helpfulness…）或自定义评审 Prompt
3. 配一个「裁判模型」的凭证（LLM Connection，可用 OpenAI/Anthropic 等）
4. 设置**作用范围**：对哪些新 trace 自动打分、采样比例多少
5. 之后线上新 trace 会被自动评分，可在 Dashboard 看趋势、掉分告警

> 注意：托管裁判需要在 Langfuse 配一个可用的 LLM Connection。若你手头只有 GLM，
> 且未接入托管评审，可先用**方案 B** 跑通闭环。

### 方案 B：代码自建裁判（场景 9 脚本演示，完全可控可离线）
自己调一个模型当裁判 → 解析出分数 → `create_score` 回填到被评 trace。
适合自定义维度、内网离线、或裁判逻辑复杂的场景。

## 4. Dataset + Experiment（场景 10）—— 回归测试

```python
# 1) 建集 + 加用例（input=输入，expected_output=期望）
langfuse.create_dataset(name="tutorial-常识问答")
langfuse.create_dataset_item(dataset_name="tutorial-常识问答", input="中国首都?", expected_output="北京")

# 2) 定义任务：对每条用例做什么
def task(*, item, **kwargs):
    return glm_model.invoke([HumanMessage(item.input)]).content

# 3) 定义评估器：给单条输出打分
from langfuse import Evaluation
def correctness(*, input, output, expected_output, metadata, **kwargs):
    hit = expected_output.lower() in output.lower()
    return Evaluation(name="correctness", value=1.0 if hit else 0.0)

# 4) 跑实验（自动建 dataset run，可在 UI 对比）
dataset = langfuse.get_dataset("tutorial-常识问答")
result = dataset.run_experiment(name="简洁策略", task=task, evaluators=[correctness])
print(result.format())
```

**核心玩法**：换 Prompt / 换模型 = 换个 `task` 或改 `name`，跑第二个 run，
在 UI 的 **Datasets → Runs** 里勾选两个 run **并排对比**，用数字决定谁上线。

评估器函数签名（关键字参数固定）：
- 单条：`def ev(*, input, output, expected_output, metadata, **kwargs) -> Evaluation`
- 运行级（汇总）：`def ev(*, item_results, **kwargs) -> Evaluation`

## 5. Annotation Queue（场景 11）—— 人工标注

**流程**：评估负责人在 UI 建 Score Config + Queue → 应用把可疑 trace 用 API 推进队列 → 标注同学在 UI 逐条评分。

```python
langfuse.api.annotation_queues.create_queue_item(
    queue_id=queue.id, object_id=trace_id, object_type="TRACE"
)
```
> 前置：队列依赖 Score Config，需先在 UI 建好一个打分维度再建队列。

---

## 6. 本阶段脚本与动手清单

| 脚本 | 学到的东西 | 前置 |
| --- | --- | --- |
| `s8_手动打分与反馈.py` | 三种 score 类型、上下文内打分、事后按 id 打分 | 无 |
| `s9_llm_as_a_judge.py` | 代码自建裁判打分闭环 | 无 |
| `s10_dataset与experiment.py` | 数据集 + 实验 + 评估器 + 两 run 对比 | 无 |
| `s11_annotation_queue.py` | 把 trace 推进人工标注队列 | UI 先建 Queue |

### 运行
```bash
python "Langfuse实战/03_评估/s8_手动打分与反馈.py"
python "Langfuse实战/03_评估/s9_llm_as_a_judge.py"
python "Langfuse实战/03_评估/s10_dataset与experiment.py"
python "Langfuse实战/03_评估/s11_annotation_queue.py"   # 需先在 UI 建标注队列
```

## 7. 自检清单

- [ ] `s8` 的 trace 上能看到 3 个分数，Scores 页可按分数筛选
- [ ] `s9` 裁判分数正确写回被评 trace（llm_judge_relevance）
- [ ] `s10` 在 Datasets → Runs 看到「简洁策略/详细策略」两个 run，能并排对比
- [ ] （进阶）在 UI 配一个托管 LLM-as-a-Judge，对新 trace 自动打分
- [ ] `s11` 成功把 trace 推入某个标注队列，并在 Annotation 页完成一次人工打分

---

## 附录 · API 速查表（完整签名 + 逐参数说明）

> 以下签名取自已安装的 **Langfuse SDK `4.14.4`** 源码，按本章脚本用到顺序排列。
> 标记：✅ 必填 · ⚪ 可选（带默认值）。签名中的 `*` 表示其后的参数只能按关键字传入。

### A. LangChain 回调与观测上下文

#### `CallbackHandler(...)` —— 把 LangChain / LangGraph 调用自动接入 Langfuse

```python
from langfuse.langchain import CallbackHandler

handler = CallbackHandler(
    *,
    public_key: str | None = None,
    trace_context: TraceContext | None = None,
) -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `public_key` | `str \| None` | ⚪ | `None` | 单项目通常留空并复用默认客户端；多项目时指定目标项目的 public key |
| `trace_context` | `TraceContext \| None` | ⚪ | `None` | 续接已有 trace，可传 `{"trace_id": "...", "parent_span_id": "..."}`；不传则按当前上下文自动关联 |

接入方式是把 handler 放入 LangChain Runnable 的 `config["callbacks"]` 列表：

```python
response = glm_model.invoke(
    [HumanMessage(question)],
    config={"callbacks": [handler]},
)
```

> `CallbackHandler` 构造函数在 4.14.4 中**只接受 `public_key` 和 `trace_context`**，不能传 `metadata`、`tags` 或 `session_id`。handler 必须随 `config={"callbacks": [handler]}` 传给调用，否则这次 LangChain 模型调用不会自动产生 Langfuse observation。

#### `@observe(...)` —— 自动为 Python 函数创建 observation

```python
from collections.abc import Callable, Iterable
from typing import Literal, TypeVar

F = TypeVar("F", bound=Callable)

observe(
    func: F | None = None,
    *,
    name: str | None = None,
    as_type: Literal[
        "generation",
        "embedding",
        "span",
        "agent",
        "tool",
        "chain",
        "retriever",
        "evaluator",
        "guardrail",
    ] | None = None,
    capture_input: bool | None = None,
    capture_output: bool | None = None,
    transform_to_string: Callable[[Iterable], str] | None = None,
) -> F | Callable[[F], F]
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `func` | `F \| None` | ⚪ | `None` | 被装饰函数；支持直接写 `@observe`，通常不手工传入 |
| `name` | `str \| None` | ⚪ | `None` | observation 名称；`None` 时使用函数名 |
| `as_type` | `Literal[九种观测类型] \| None` | ⚪ | `None` | observation 类型；`None` 按 `span` 处理，九种取值见下表 |
| `capture_input` | `bool \| None` | ⚪ | `None` | 是否采集函数入参；`None` 使用 SDK/环境变量配置，默认启用 |
| `capture_output` | `bool \| None` | ⚪ | `None` | 是否采集函数返回值；`None` 使用 SDK/环境变量配置，默认启用 |
| `transform_to_string` | `Callable[[Iterable], str] \| None` | ⚪ | `None` | 生成器函数专用：把迭代输出转换为最终字符串后记录为 output |

`as_type` 的九种取值：

| 值 | 含义 | 典型场景 |
| --- | --- | --- |
| `"generation"` | 大语言模型生成调用，可记录模型、token 与成本 | 聊天、补全、LLM-as-a-Judge 的模型调用 |
| `"embedding"` | 嵌入模型调用，可记录模型、token 与成本 | 文本向量化、查询向量化 |
| `"span"` | 通用工作单元，也是默认语义 | 格式化、业务逻辑、无法细分的步骤 |
| `"agent"` | 可自主决策的 Agent 整体执行 | ReAct Agent、动态路径 LangGraph |
| `"tool"` | Agent 调用的外部工具 | 搜索、数据库、业务 API |
| `"chain"` | 固定顺序的编排流程 | LCEL chain、固定 RAG pipeline |
| `"retriever"` | 检索相关资料的步骤 | 向量检索、关键词检索 |
| `"evaluator"` | 对输出进行评估的步骤 | 规则评分、LLM 裁判外层 |
| `"guardrail"` | 安全或合规护栏 | 越狱检测、PII 检测、内容过滤 |

> `score_current_trace(...)` 和 `get_current_trace_id()` 依赖 OpenTelemetry 的「当前活动上下文」。`@observe` 只在进入被装饰函数时建立该上下文，并在函数返回时退出，所以两者必须在装饰器函数体内调用；放在函数调用之后，当前 trace 可能已不存在，无法可靠获得或定位目标 trace。事后打分应先在函数体内取出 trace id，再在外部调用 `create_score(trace_id=...)`。

---

### B. 客户端鉴权、上报与当前 Trace

#### `langfuse.auth_check()` —— 阻塞校验当前客户端凭证

```python
langfuse.auth_check() -> bool
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| 无 | — | — | — | 此方法不接收参数 |

> 该方法会同步发送 HTTP 请求；凭证有效返回 `True`，无效返回 `False`。适合教程脚本启动时快速失败，不建议放在每个线上请求的热路径中。

#### `langfuse.flush()` —— 立即发送客户端缓冲区中的待上报数据

```python
langfuse.flush() -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| 无 | — | — | — | 此方法不接收参数 |

> Langfuse 默认异步批量上报。短命令行脚本结束前应调用 `flush()`，避免进程退出时 trace、observation 或 score 仍留在本地缓冲区；它只保证客户端完成发送，不代表服务端 UI 已即时完成异步处理。

#### `langfuse.get_current_trace_id()` —— 获取当前活动上下文的 trace id

```python
langfuse.get_current_trace_id() -> str | None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| 无 | — | — | — | 此方法不接收参数 |

> 仅在活动的 Langfuse 上下文内可靠返回 trace id，例如 `@observe` 函数体内；没有活动上下文时返回 `None`。若后续需要异步反馈，应在上下文内保存返回值，再传给 `create_score(...)`。

---

### C. Score 打分 API

#### `langfuse.create_score(...)` —— 按目标 id 创建或挂载分数

```python
from datetime import datetime
from typing import Any, Literal

langfuse.create_score(
    *,
    name: str,
    value: float | str,
    session_id: str | None = None,
    dataset_run_id: str | None = None,
    trace_id: str | None = None,
    observation_id: str | None = None,
    score_id: str | None = None,
    data_type: Literal[
        "NUMERIC",
        "CATEGORICAL",
        "BOOLEAN",
        "TEXT",
        "CORRECTION",
    ] | None = None,
    comment: str | None = None,
    config_id: str | None = None,
    metadata: Any | None = None,
    timestamp: datetime | None = None,
    environment: str | None = None,
) -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | `str` | ✅ | — | 指标名，如 `user_feedback`、`relevance`；跨运行保持一致才便于聚合比较 |
| `value` | `float \| str` | ✅ | — | 分数值；具体值类型应与 `data_type` 匹配 |
| `session_id` | `str \| None` | ⚪ | `None` | 把分数挂到整个会话，适合多轮对话整体满意度 |
| `dataset_run_id` | `str \| None` | ⚪ | `None` | 把分数挂到一次 Dataset Run，适合整轮离线实验的汇总评价 |
| `trace_id` | `str \| None` | ⚪ | `None` | 把分数挂到整条 trace，适合一次请求的整体质量或用户反馈 |
| `observation_id` | `str \| None` | ⚪ | `None` | 把分数精确挂到 trace 内某个 observation；使用时必须同时传 `trace_id` |
| `score_id` | `str \| None` | ⚪ | `None` | 自定义 score id；不传时由 SDK 生成 |
| `data_type` | `Literal[...] \| None` | ⚪ | `None` | 分数数据类型；五种取值见下表，不传时由后端/配置按值处理 |
| `comment` | `str \| None` | ⚪ | `None` | 人类可读的评分理由或备注 |
| `config_id` | `str \| None` | ⚪ | `None` | 关联 UI 中的 Score Config，以复用类别、范围等配置 |
| `metadata` | `Any \| None` | ⚪ | `None` | 结构化补充信息，如裁判版本、置信度或规则命中详情 |
| `timestamp` | `datetime \| None` | ⚪ | `None` | 分数发生时间；不传时使用当前时间 |
| `environment` | `str \| None` | ⚪ | `None` | 覆盖客户端级环境，用于区分开发、预发、生产数据 |

`data_type` 的五种取值：

| 值 | 含义 | `value` 形式 | 示例 |
| --- | --- | --- | --- |
| `"NUMERIC"` | 连续或离散数值评分，可做均值、趋势等数值聚合 | `float` | 相关性 `0.87`、质量 `4.0` |
| `"BOOLEAN"` | 二元判断 | `float`，通常 `1.0` / `0.0` | 点赞/点踩、合规/不合规 |
| `"CATEGORICAL"` | 从有限类别中选择一个标签 | `str` | `"好"`、`"中"`、`"差"` |
| `"TEXT"` | 自由文本反馈，不用于数值聚合 | `str` | `"回答遗漏了边界条件"` |
| `"CORRECTION"` | 对原输入或输出给出建议的纠正内容 | `str` | 人工修订后的标准答案 |

目标挂载区别：

| 目标参数 | 分数归属 | 典型用途 |
| --- | --- | --- |
| `trace_id` | 单次请求的整条 trace | 用户反馈、整体正确性 |
| `trace_id` + `observation_id` | trace 内一个具体步骤 | 单次模型生成、检索步骤或工具调用质量；`observation_id` 不能脱离 `trace_id` 单独使用 |
| `session_id` | 跨多条 trace 的会话 | 多轮对话满意度、会话是否解决问题 |
| `dataset_run_id` | 一次离线数据集运行 | 实验整体评价、Run 级质量 |

> `create_score(...)` 不依赖当前活动上下文，适合前端点赞回传、异步质检和离线回填。trace 尚未完成上报时也可先按 id 创建分数，之后由服务端关联；但目标 id 必须来自同一 Langfuse 项目。

#### `langfuse.score_current_trace(...)` —— 给当前活动 trace 打分

```python
from typing import Any, Literal

langfuse.score_current_trace(
    *,
    name: str,
    value: float | str,
    score_id: str | None = None,
    data_type: Literal[
        "NUMERIC",
        "CATEGORICAL",
        "BOOLEAN",
        "TEXT",
        "CORRECTION",
    ] | None = None,
    comment: str | None = None,
    config_id: str | None = None,
    metadata: Any | None = None,
) -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | `str` | ✅ | — | 指标名 |
| `value` | `float \| str` | ✅ | — | 分数值，须与 `data_type` 的语义匹配 |
| `score_id` | `str \| None` | ⚪ | `None` | 自定义 score id；不传时由 SDK 生成 |
| `data_type` | `Literal[...] \| None` | ⚪ | `None` | `NUMERIC` / `CATEGORICAL` / `BOOLEAN` / `TEXT` / `CORRECTION`，含义同上一节 |
| `comment` | `str \| None` | ⚪ | `None` | 评分理由或备注 |
| `config_id` | `str \| None` | ⚪ | `None` | 关联 UI 中的 Score Config |
| `metadata` | `Any \| None` | ⚪ | `None` | 结构化补充信息 |

`data_type` 的五种取值：

| 值 | 含义 | `value` 形式 | 示例 |
| --- | --- | --- | --- |
| `"NUMERIC"` | 连续或离散数值评分，可做均值、趋势等数值聚合 | `float` | 相关性 `0.87`、质量 `4.0` |
| `"BOOLEAN"` | 二元判断 | `float`，通常 `1.0` / `0.0` | 点赞/点踩、合规/不合规 |
| `"CATEGORICAL"` | 从有限类别中选择一个标签 | `str` | `"好"`、`"中"`、`"差"` |
| `"TEXT"` | 自由文本反馈，不用于数值聚合 | `str` | `"回答遗漏了边界条件"` |
| `"CORRECTION"` | 对原输入或输出给出建议的纠正内容 | `str` | 人工修订后的标准答案 |

> 该方法不接收 `trace_id`，目标由当前活动上下文决定，因此必须在 `@observe` 函数体等上下文内调用。需要在函数返回后打分时，改用 `create_score(trace_id=...)`。

---

### D. `Evaluation(...)` —— 实验评估器的标准返回对象

```python
from typing import Any, Literal

Evaluation(
    *,
    name: str,
    value: int | float | str | bool,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
    data_type: Literal["NUMERIC", "CATEGORICAL", "BOOLEAN"] | None = None,
    config_id: str | None = None,
)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | `str` | ✅ | — | 评估指标名；多个 Run 对比时应保持一致 |
| `value` | `int \| float \| str \| bool` | ✅ | — | 评估结果；支持整数、浮点数、字符串或布尔值 |
| `comment` | `str \| None` | ⚪ | `None` | 对该结果的可读解释 |
| `metadata` | `dict[str, Any] \| None` | ⚪ | `None` | 置信度、规则版本、中间计算值等结构化信息 |
| `data_type` | `Literal[...] \| None` | ⚪ | `None` | 实验 Evaluation 仅支持三种类型，见下表 |
| `config_id` | `str \| None` | ⚪ | `None` | 关联已有 Score Config |

`data_type` 的三种取值：

| 值 | 含义 | 常用 `value` |
| --- | --- | --- |
| `"NUMERIC"` | 可聚合的数值指标 | `int` / `float`，如 `0.92` |
| `"CATEGORICAL"` | 分类标签 | `str`，如 `"PASS"` / `"FAIL"` |
| `"BOOLEAN"` | 真/假判断 | `bool`，如 `True` / `False` |

> 注意这里与 `create_score(...)` 不同：`Evaluation.data_type` 没有 `TEXT` 和 `CORRECTION`。所有参数均为关键字参数，因为签名中 `name` 前有 `*`。

---

### E. Dataset API

#### `langfuse.create_dataset(...)` —— 创建数据集

```python
from typing import Any

langfuse.create_dataset(
    *,
    name: str,
    description: str | None = None,
    metadata: Any | None = None,
    input_schema: Any | None = None,
    expected_output_schema: Any | None = None,
) -> Dataset
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | `str` | ✅ | — | 数据集名称，也是后续添加 item 和获取数据集时使用的标识 |
| `description` | `str \| None` | ⚪ | `None` | 数据集用途、数据来源或维护规则说明 |
| `metadata` | `Any \| None` | ⚪ | `None` | 数据集级结构化元数据 |
| `input_schema` | `Any \| None` | ⚪ | `None` | `item.input` 的 JSON Schema，用于约束输入结构 |
| `expected_output_schema` | `Any \| None` | ⚪ | `None` | `item.expected_output` 的 JSON Schema，用于约束期望输出结构 |

> 数据集名称应稳定；实验基于名称重新获取同一数据集。结构化数据集建议设置 schema，尽早发现用例格式漂移。

#### `langfuse.create_dataset_item(...)` —— 创建或更新数据集用例

```python
from typing import Any
from langfuse.api import DatasetStatus

langfuse.create_dataset_item(
    *,
    dataset_name: str,
    input: Any | None = None,
    expected_output: Any | None = None,
    metadata: Any | None = None,
    source_trace_id: str | None = None,
    source_observation_id: str | None = None,
    status: DatasetStatus | None = None,
    id: str | None = None,
) -> DatasetItem
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `dataset_name` | `str` | ✅ | — | 目标数据集名称 |
| `input` | `Any \| None` | ⚪ | `None` | 任务输入，可为字符串或结构化 JSON 数据 |
| `expected_output` | `Any \| None` | ⚪ | `None` | 期望输出或黄金答案，供评估器对比 |
| `metadata` | `Any \| None` | ⚪ | `None` | 难度、类别、来源等用例级元数据 |
| `source_trace_id` | `str \| None` | ⚪ | `None` | 用例来源 trace id，用于保留线上样本血缘 |
| `source_observation_id` | `str \| None` | ⚪ | `None` | 来源 observation id；定位到 trace 内具体生成或步骤 |
| `status` | `DatasetStatus \| None` | ⚪ | `None` | 用例状态；不传时服务端默认为 `ACTIVE` |
| `id` | `str \| None` | ⚪ | `None` | 自定义全局唯一 item id；同一 id 已存在时执行 upsert，而不是重复新增 |

`DatasetStatus` 枚举：

| 值 | 含义 |
| --- | --- |
| `DatasetStatus.ACTIVE` / `"ACTIVE"` | 活跃用例，正常参与当前数据集实验 |
| `DatasetStatus.ARCHIVED` / `"ARCHIVED"` | 已归档用例，保留历史但不作为当前活跃样本 |

> 若需要脚本可重复执行且不产生重复用例，应为每条业务用例生成稳定的 `id`；id 已存在时会 upsert。省略 `id` 时，每次调用通常都会创建新 item。

#### `langfuse.get_dataset(...)` —— 获取数据集及其用例

```python
from datetime import datetime

langfuse.get_dataset(
    name: str,
    *,
    fetch_items_page_size: int | None = 50,
    version: datetime | None = None,
) -> DatasetClient
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | `str` | ✅ | — | 数据集名称；这是唯一可按位置传入的参数 |
| `fetch_items_page_size` | `int \| None` | ⚪ | `50` | SDK 拉取 item 时每页的数量；用于控制分页请求大小 |
| `version` | `datetime \| None` | ⚪ | `None` | 获取指定时刻的数据集快照；必须传带时区的 UTC `datetime` |

> 返回的 `DatasetClient.items` 是一次性拉取完成的全部 item 列表，不是只含当前一页。数据量很大时，调大 `fetch_items_page_size` 可减少请求次数，但也会增加单次响应体积。`version` 示例：`datetime(2026, 8, 11, tzinfo=timezone.utc)`，不要传无时区 datetime。

---

### F. Experiment 回调协议

Langfuse 按参数名注入回调数据；教程建议显式使用 `*` 声明关键字参数，并用 `**kwargs` 兼容 SDK 后续增加的注入项。

#### Task 回调 —— 对每条 item 执行被测任务

```python
from typing import Any, Awaitable

class TaskFunction(Protocol):
    def __call__(
        self,
        *,
        item: ExperimentItem,
        **kwargs: dict[str, Any],
    ) -> Any | Awaitable[Any]: ...
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `item` | `ExperimentItem` | ✅ | — | 当前实验用例；Dataset 场景可读 `.input`、`.expected_output`、`.metadata` |
| `**kwargs` | `dict[str, Any]` | ⚪ | `{}` | SDK 额外注入的关键字参数，建议保留以兼容扩展 |

> Task 可同步或异步，返回值类型不限；返回结果会成为 evaluator 的 `output`，并写入 `ExperimentItemResult.output`。

#### Evaluator 回调 —— 对单条任务输出打分

```python
from typing import Any, Awaitable

class EvaluatorFunction(Protocol):
    def __call__(
        self,
        *,
        input: Any,
        output: Any,
        expected_output: Any,
        metadata: dict[str, Any] | None,
        **kwargs: dict[str, Any],
    ) -> Evaluation | list[Evaluation] | Awaitable[Evaluation | list[Evaluation]]: ...
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `input` | `Any` | ✅ | — | 当前 item 的原始输入 |
| `output` | `Any` | ✅ | — | Task 对当前 item 的返回值 |
| `expected_output` | `Any` | ✅ | — | 当前 item 的期望输出；数据集未设置时值可能为 `None` |
| `metadata` | `dict[str, Any] \| None` | ✅ | — | 当前 item 的元数据；未设置时可能为 `None` |
| `**kwargs` | `dict[str, Any]` | ⚪ | `{}` | SDK 额外注入参数，建议保留 |

> Evaluator 可同步或异步，可返回一个 `Evaluation` 或 `list[Evaluation]`。虽然值可能为 `None`，协议仍会按关键字注入 `expected_output` 和 `metadata`，不要把“值可空”误解成“参数不会出现”。

#### Composite evaluator 回调 —— 基于单条已有评估结果计算综合指标

```python
from typing import Any, Awaitable

class CompositeEvaluatorFunction(Protocol):
    def __call__(
        self,
        *,
        input: Any,
        output: Any,
        expected_output: Any,
        metadata: dict[str, Any] | None,
        evaluations: list[Evaluation],
        **kwargs: dict[str, Any],
    ) -> Evaluation | list[Evaluation] | Awaitable[Evaluation | list[Evaluation]]: ...
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `input` | `Any` | ✅ | — | 当前 item 的原始输入 |
| `output` | `Any` | ✅ | — | Task 对当前 item 的返回值 |
| `expected_output` | `Any` | ✅ | — | 当前 item 的期望输出，可能为 `None` |
| `metadata` | `dict[str, Any] \| None` | ✅ | — | 当前 item 的元数据，可能为 `None` |
| `evaluations` | `list[Evaluation]` | ✅ | — | 普通 item evaluator 已产生的结果列表，用于加权或综合计算 |
| `**kwargs` | `dict[str, Any]` | ⚪ | `{}` | SDK 额外注入参数，建议保留 |

> `composite_evaluator` 与普通 `evaluators` 的核心差别是多收到 `evaluations`：它适合把正确性、简洁度、安全性等已有分数组合成一个综合指标。

#### Run evaluator 回调 —— 对整个实验运行做汇总评估

```python
from typing import Any, Awaitable

class RunEvaluatorFunction(Protocol):
    def __call__(
        self,
        *,
        item_results: list[ExperimentItemResult],
        **kwargs: dict[str, Any],
    ) -> Evaluation | list[Evaluation] | Awaitable[Evaluation | list[Evaluation]]: ...
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `item_results` | `list[ExperimentItemResult]` | ✅ | — | 所有成功处理用例的结果；每项含 `.item`、`.output`、`.evaluations`、`.trace_id`、`.dataset_run_id` |
| `**kwargs` | `dict[str, Any]` | ⚪ | `{}` | SDK 额外注入参数，建议保留 |

> `item_results` 只包含成功处理的 item；失败项会被记录，但不会注入此列表。汇总成功率时不能仅用该列表长度推断原始总数。

回调注入参数总览：

| 注入参数 | 类型 | 注入对象 | 含义 |
| --- | --- | --- | --- |
| `item` | `ExperimentItem` | Task | 完整当前用例 |
| `input` | `Any` | Evaluator、Composite evaluator | 当前用例输入 |
| `output` | `Any` | Evaluator、Composite evaluator | Task 返回值 |
| `expected_output` | `Any` | Evaluator、Composite evaluator | 黄金答案，可能为 `None` |
| `metadata` | `dict[str, Any] \| None` | Evaluator、Composite evaluator | 用例元数据 |
| `evaluations` | `list[Evaluation]` | Composite evaluator | 当前 item 已有的普通评估结果 |
| `item_results` | `list[ExperimentItemResult]` | Run evaluator | 整个 Run 中成功处理的逐条结果 |

---

### G. `dataset.run_experiment(...)` —— 在数据集上运行实验

```python
result = dataset.run_experiment(
    *,
    name: str,
    run_name: str | None = None,
    description: str | None = None,
    task: TaskFunction,
    evaluators: list[EvaluatorFunction] = [],
    composite_evaluator: CompositeEvaluatorFunction | None = None,
    run_evaluators: list[RunEvaluatorFunction] = [],
    max_concurrency: int = 50,
    metadata: dict[str, str] | None = None,
) -> ExperimentResult
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | `str` | ✅ | — | 实验名称，用于表达被测策略，如 `简洁策略` |
| `run_name` | `str \| None` | ⚪ | `None` | 本次 Run 的精确名称；不传时 SDK 基于 `name` 和时间生成 |
| `description` | `str \| None` | ⚪ | `None` | 本次实验目的、Prompt/模型差异等说明 |
| `task` | `TaskFunction` | ✅ | — | 对每条数据集 item 执行的同步或异步任务 |
| `evaluators` | `list[EvaluatorFunction]` | ⚪ | `[]` | 单条 item 评估器列表，每个 item 的 task 完成后执行 |
| `composite_evaluator` | `CompositeEvaluatorFunction \| None` | ⚪ | `None` | 单条复合评估器，接收普通 evaluator 的 `evaluations` 后生成综合分 |
| `run_evaluators` | `list[RunEvaluatorFunction]` | ⚪ | `[]` | Run 级汇总评估器列表，在逐条处理结束后执行 |
| `max_concurrency` | `int` | ⚪ | `50` | 最大并发任务数；应按模型/API 限流和本机资源调整 |
| `metadata` | `dict[str, str] \| None` | ⚪ | `None` | 附加到 Dataset Run 及实验 trace 的字符串元数据 |

> `evaluators=[]` 和 `run_evaluators=[]` 是 SDK 4.14.4 的真实签名默认值。实际调用中建议显式传入列表；`max_concurrency=50` 对限流严格的模型可能过高，应主动调低。

#### `ExperimentResult.format(...)` —— 将实验结果格式化为可读文本

```python
result.format(
    *,
    include_item_results: bool = False,
) -> str
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `include_item_results` | `bool` | ⚪ | `False` | 是否在摘要中加入每条 item 的输入、输出和评分明细；开启后文本可能很长 |

> `format()` 只生成并返回字符串，不会自动打印或写文件。使用 `print(result.format())` 查看摘要；排查单条失败时使用 `include_item_results=True`。

#### `ExperimentResult` 完整属性表

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `.name` | `str` | 调用 `run_experiment(...)` 时传入的实验名称 |
| `.run_name` | `str` | 当前实际 Run 名称，可能由 SDK 自动生成 |
| `.description` | `str \| None` | 实验描述 |
| `.item_results` | `list[ExperimentItemResult]` | 逐条成功结果；每项包含原 item、task output、evaluations、trace id 和 dataset run id |
| `.run_evaluations` | `list[Evaluation]` | `run_evaluators` 产出的运行级汇总指标 |
| `.experiment_id` | `str` | 整个实验运行共享的 id；Dataset 实验中与 dataset run id 对应 |
| `.dataset_run_id` | `str \| None` | Langfuse Dataset Run id；本地实验时可能为 `None` |
| `.dataset_run_url` | `str \| None` | Langfuse UI 中该 Dataset Run 的直达 URL；不可用时为 `None` |

> 做 CI 门禁时优先从 `.run_evaluations` 按 `name` 找汇总指标；做失败定位时遍历 `.item_results`。不要从 `format()` 的展示字符串反向解析数值。

---

### H. Annotation Queue API

#### `langfuse.api.annotation_queues.list_queues(...)` —— 分页列出标注队列

```python
from langfuse.api.core.request_options import RequestOptions

langfuse.api.annotation_queues.list_queues(
    *,
    page: int | None = None,
    limit: int | None = None,
    request_options: RequestOptions | None = None,
) -> PaginatedAnnotationQueues
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `page` | `int \| None` | ⚪ | `None` | 页码，**从 1 开始**；不传时使用服务端默认页 |
| `limit` | `int \| None` | ⚪ | `None` | 每页返回数量；不传时使用服务端默认值 |
| `request_options` | `RequestOptions \| None` | ⚪ | `None` | 底层请求选项，如超时或附加请求配置；普通业务通常不传 |

> 返回值不是队列列表本身；当前页队列位于 `.data`。因此应使用 `queues = ...list_queues()` 后读取 `queues.data`。该 API 是分页接口，队列超过一页时需递增 `page` 拉取后续页。

#### `langfuse.api.annotation_queues.create_queue_item(...)` —— 将对象加入标注队列

```python
from langfuse.api import AnnotationQueueObjectType, AnnotationQueueStatus
from langfuse.api.core.request_options import RequestOptions

langfuse.api.annotation_queues.create_queue_item(
    queue_id: str,
    *,
    object_id: str,
    object_type: AnnotationQueueObjectType,
    status: AnnotationQueueStatus | None = ...,
    request_options: RequestOptions | None = None,
) -> AnnotationQueueItem
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `queue_id` | `str` | ✅ | — | 目标标注队列 id；可按位置传入，也可写成关键字参数 |
| `object_id` | `str` | ✅ | — | 被标注对象 id，其实际种类必须与 `object_type` 一致 |
| `object_type` | `AnnotationQueueObjectType` | ✅ | — | 对象类型：`TRACE`、`OBSERVATION` 或 `SESSION` |
| `status` | `AnnotationQueueStatus \| None` | ⚪ | `...`（服务端默认 `PENDING`） | 队列项状态；省略时创建为待处理 |
| `request_options` | `RequestOptions \| None` | ⚪ | `None` | 底层请求选项，普通业务通常不传 |

`AnnotationQueueObjectType` 完整枚举：

| 枚举成员 | 值 | 含义 | `object_id` 应传 |
| --- | --- | --- | --- |
| `AnnotationQueueObjectType.TRACE` | `"TRACE"` | 标注整条请求链路 | trace id |
| `AnnotationQueueObjectType.OBSERVATION` | `"OBSERVATION"` | 标注 trace 内某个具体步骤 | observation id |
| `AnnotationQueueObjectType.SESSION` | `"SESSION"` | 标注跨多条 trace 的整个会话 | session id |

`AnnotationQueueStatus` 完整枚举：

| 枚举成员 | 值 | 含义 |
| --- | --- | --- |
| `AnnotationQueueStatus.PENDING` | `"PENDING"` | 待标注或待复核；新建队列项的默认状态 |
| `AnnotationQueueStatus.COMPLETED` | `"COMPLETED"` | 已完成标注 |

> 签名里的 `status=...` 是生成式 REST 客户端表示「参数省略、交给服务端默认」的哨兵值，不是 Python 的 `None` 默认。通常直接省略 `status` 即可得到 `PENDING`。加入队列前应先 `flush()`，确保对应 trace/observation 已发送并可被服务端关联；队列本身依赖 UI 中预先配置好的 Score Config。
