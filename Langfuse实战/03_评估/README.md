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

> 签名取自已安装的 **Langfuse SDK `4.14.3`** 源码。✅ 必填 · ⚪ 可选。
> 分数数据类型 `data_type` 取值：`"NUMERIC"` / `"BOOLEAN"` / `"CATEGORICAL"` / `"TEXT"` / `"CORRECTION"`。

### A. 打分 API —— `create_score(...)` / `score_current_trace(...)` / `score_current_span(...)`

#### `create_score(...)` —— 事后按 id 追加分数（最通用，可在任意位置调用）
```python
langfuse.create_score(
    *,
    name: str,                                  # ✅ 分数名（如 "user_feedback"）
    value: float | str,                         # ✅ 数值（NUMERIC/BOOLEAN）或字符串（CATEGORICAL/TEXT）
    trace_id: str | None = None,                # 挂到哪条 trace（与 observation_id 配合）
    observation_id: str | None = None,          # 挂到具体 observation（须同时给 trace_id）
    session_id: str | None = None,              # 挂到某 session
    dataset_run_id: str | None = None,          # 挂到某 dataset run
    score_id: str | None = None,                # 自定义分数 id（不传则自动生成）
    data_type: str | None = None,               # 见顶部取值；不传则按 value 类型推断
    comment: str | None = None,                 # 说明文字
    config_id: str | None = None,               # 关联 UI 里定义的 Score Config
    metadata: Any | None = None,
    timestamp: datetime | None = None,          # 不传则用当前 UTC 时间
    environment: str | None = None,             # 覆盖客户端级环境
) -> None
```
> 即便 trace 还没上报，也可先按 id 打分，之后自动关联。`value`：NUMERIC/BOOLEAN 用 `float`（BOOLEAN 用 `1.0`/`0.0`），CATEGORICAL/TEXT 用 `str`。

#### `score_current_trace(...)` / `score_current_span(...)` —— 上下文内给「当前 trace / span」打分
```python
langfuse.score_current_trace(
    *,
    name: str,                                  # ✅
    value: float | str,                         # ✅
    score_id: str | None = None,
    data_type: str | None = None,
    comment: str | None = None,
    config_id: str | None = None,
    metadata: Any | None = None,
) -> None
# score_current_span(...) 签名完全相同，只是挂在「当前 span」而非整条 trace
```
> 只能在 trace 上下文内调用（`@observe` 函数体 / `with start_as_current_observation(...)` 块内）。

---

### B. `Evaluation(...)` —— 评估器函数的返回值
```python
from langfuse import Evaluation

Evaluation(
    name: str,                                  # ✅ 指标名（跨 run 保持一致，便于对比）
    value: float | str | bool,                  # ✅ 分数/分类/布尔
    comment: str | None = None,                 # 说明（UI 可见）
    metadata: Any | None = None,                # 结构化补充（置信度、中间值等）
    data_type: str | None = None,               # value 非 NUMERIC 时需指定（NUMERIC/CATEGORICAL/BOOLEAN）
    config_id: str | None = None,
)
```
> 一个评估器函数可返回**单个** `Evaluation`、或**列表**（多条指标）、或 `dict`（兼容旧写法）。

---

### C. 评估器 / 任务函数的固定签名（关键字参数）

```python
# 任务：对单条用例执行，返回输出（item 有 .input / .expected_output / .metadata）
def task(*, item, **kwargs) -> Any: ...

# 单条评估器：给单条输出打分（input/output/expected_output/metadata 均可选关键字）
def evaluator(*, input, output, expected_output=None, metadata=None, **kwargs) -> Evaluation | list[Evaluation]: ...

# 运行级评估器：对整个 run 汇总（item_results 是各条结果列表）
def run_evaluator(*, item_results, **kwargs) -> Evaluation: ...

# 复合评估器（可选）：在单条评估基础上再算加权/综合分
def composite(*, input, output, expected_output=None, metadata=None, evaluations=None, **kwargs) -> Evaluation: ...
```
> 这些函数的参数**必须是关键字参数**（`*,`），名字固定；多余参数用 `**kwargs` 收。

---

### D. Dataset API

#### `create_dataset(...)` —— 建数据集
```python
langfuse.create_dataset(
    *,
    name: str,                                  # ✅ 数据集名
    description: str | None = None,
    metadata: Any | None = None,
    input_schema: Any | None = None,            # 校验 item.input 的 JSON Schema
    expected_output_schema: Any | None = None,  # 校验 item.expected_output 的 JSON Schema
) -> Dataset
```

#### `create_dataset_item(...)` —— 给数据集加一条用例
```python
langfuse.create_dataset_item(
    *,
    dataset_name: str,                          # ✅ 目标数据集名
    input: Any | None = None,                   # 用例输入
    expected_output: Any | None = None,         # 期望输出（评估器对比用）
    metadata: Any | None = None,
    source_trace_id: str | None = None,         # 从某条 trace 派生
    source_observation_id: str | None = None,
    status: "ACTIVE" | "ARCHIVED" | None = None,# 默认 ACTIVE
    id: str | None = None,                      # 自定义 id 用于去重（全局唯一）
) -> DatasetItem
```

#### `get_dataset(...)` —— 取数据集（含全部用例）
```python
dataset = langfuse.get_dataset(
    name: str,                                  # ✅ 数据集名
    *,
    fetch_items_page_size: int | None = 50,     # 分页拉取每页条数
    version: datetime | None = None,            # 取某历史时刻的快照（UTC 带时区）
) -> DatasetClient
```
返回的 `DatasetClient` 有 `.items`（`list[DatasetItem]`，每条有 `.input/.expected_output/.metadata`）。

---

### E. `dataset.run_experiment(...)` —— 跑一次实验（自动建 dataset run）
```python
result = dataset.run_experiment(
    *,
    name: str,                                  # ✅ 实验/Run 名（UI 里显示）
    task: TaskFunction,                         # ✅ 见 C 节
    evaluators: list = [],                      # 单条评估器列表
    run_evaluators: list = [],                  # 运行级（汇总）评估器列表
    run_name: str | None = None,                # 精确 run 名；不传则 name+ISO 时间戳
    description: str | None = None,
    composite_evaluator: Callable | None = None,# 复合评估器
    max_concurrency: int = 50,                  # 并发执行数（按 API 限速调整）
    metadata: dict | None = None,               # 附到本次 run 及所有 trace
) -> ExperimentResult
```

#### `ExperimentResult` —— 返回值（`.format()` 打印摘要）
| 属性 | 说明 |
| --- | --- |
| `.name` / `.run_name` / `.description` | 实验/Run 名与描述 |
| `.item_results` | 各条用例的结果（含 output、evaluations） |
| `.run_evaluations` | 运行级评估器产出的汇总分（list，每项有 `.name`/`.value`） |
| `.dataset_run_id` / `.dataset_run_url` | dataset run 的 id 与 UI 直达链接 |
| `.format(include_item_results=False)` | 人类可读摘要；传 `True` 带逐条明细 |

> CI 门禁（见 04 章）就是从 `result.run_evaluations` 里取出某个汇总分，与阈值比较。

---

### F. Annotation Queue API —— 人工标注队列（走底层 REST `langfuse.api.annotation_queues`）

```python
from langfuse.api import AnnotationQueueObjectType
```

#### `list_queues(...)` —— 列出所有队列
```python
queues = langfuse.api.annotation_queues.list_queues(
    *, page: int | None = None, limit: int | None = None, request_options=None,
) -> PaginatedAnnotationQueues      # .data 是队列列表，每项有 .id / .name
```

#### `create_queue_item(...)` —— 把一条 trace/observation 推进队列
```python
item = langfuse.api.annotation_queues.create_queue_item(
    queue_id: str,                              # ✅ 目标队列 id（位置参数，也可用关键字）
    *,
    object_id: str,                             # ✅ trace_id 或 observation_id
    object_type: AnnotationQueueObjectType,     # ✅ AnnotationQueueObjectType.TRACE 或 "TRACE"
    status: str | None = None,                  # 默认 PENDING
    request_options=None,
) -> AnnotationQueueItem         # 返回对象有 .id
```

#### `create_queue(...)` —— 建队列（一般在 UI 建；代码也可建）
```python
langfuse.api.annotation_queues.create_queue(
    *, name: str, score_config_ids: Sequence[str], description=..., ...
) -> AnnotationQueue
```
> 前置：队列依赖 **Score Config**，需先在 UI 建好一个打分维度（如 `relevance`）再建队列并勾选它。
