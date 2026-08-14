# 阶段四 · 企业级集成

> 把前面三大支柱串成「工程闭环」：可观测 + Prompt 管理 + 评估，接入 CI/CD 与合规要求。

## 场景 12 · CI/CD 回归门禁 + PII 脱敏

一个脚本演示企业上生产前的两个硬性要求。

### A. PII 脱敏（合规）

监管/合规常要求：链路里**不能落敏感信息**（手机号、身份证、银行卡…）。
Langfuse 提供 `mask` 钩子——**在数据上报前**同步脱敏，UI 里存的就是打码后的内容。

```python
from langfuse import Langfuse
import re

PHONE_RE = re.compile(r"1\d{10}")

def pii_mask(*, data, **kwargs):   # ★ 签名固定：关键字参数 data
    if isinstance(data, str):
        return PHONE_RE.sub("<PHONE>", data)
    return data   # 实际要递归处理 dict / list

langfuse = Langfuse(mask=pii_mask)   # 建 client 时传入
```

要点：
- `mask` 是**客户端级**配置，必须在创建 client 时传入，且应是**进程内第一个** client。
  所以本脚本不复用 `_bootstrap` 的默认单例，而是自建一个带 mask 的 client。
- `mask` 作用于通过 SDK API（`start_observation` / `update` / `set_trace_io` 等）写入的数据。
- 第三方 OpenTelemetry instrumentation 产生的原始 span，用另一个钩子 `mask_otel_spans`。

### B. CI 回归门禁（质量护栏）

把「场景 10 的数据集实验」塞进 CI：跑完算平均分，**低于阈值就 `exit(1)`**，卡住部署。
这样每次改 Prompt/模型走 PR，效果回退会被自动拦下，而不是上线后才发现。

```python
result = dataset.run_experiment(name="CI回归检查", task=task,
                                evaluators=[correctness], run_evaluators=[avg_correctness])
score = next(e.value for e in result.run_evaluations if e.name == "avg_correctness")
sys.exit(0 if score >= PASS_THRESHOLD else 1)   # 1 = 回归，CI 失败
```

> Langfuse 官方还提供 GitHub Action（`langfuse/experiment-action`）和 `RegressionError`，
> 可直接在 PR 流水线里跑实验并对比基线。本脚本用「本地伪 CI」把原理讲清楚，
> 迁移到真实 CI 时把阈值判断换成官方 Action 或在 workflow 里读 `$?` 即可。

### 运行
```bash
# 需先跑过 场景10 播种数据集
python "Langfuse实战/04_企业集成/s12_ci门禁与pii脱敏.py"
echo "退出码 = $?"        # 0=通过, 1=回归拦截

# 想看门禁「拦截」效果：把脚本里 PASS_THRESHOLD 调到 0.99 再跑
```

### 在真实 CI（GitHub Actions）里长这样

```yaml
# .github/workflows/eval.yml（示意）
name: LLM 回归评估
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - name: 跑回归门禁
        env:
          LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
          LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
          LANGFUSE_BASE_URL: https://us.cloud.langfuse.com
        run: python "Langfuse实战/04_企业集成/s12_ci门禁与pii脱敏.py"
        # 脚本 exit 1 会让这一步失败 → PR 被阻断
```

## 自检清单

- [ ] `s12` 的 pii-demo trace 在 UI 里手机号/身份证显示为 `<PHONE>` / `<ID>`
- [ ] `s12` 正常跑通、平均分达标、退出码为 0
- [ ] 把 `PASS_THRESHOLD` 调到 0.99，重跑，退出码变 1（门禁拦截生效）
- [ ] （进阶）把这段放进真实 CI，改坏一个 Prompt，观察 PR 被自动拦下

---

## 附录 · API 速查表（完整签名 + 逐参数说明）

> 以下签名取自已安装的 **Langfuse SDK `4.14.4`** 源码，按本章脚本的调用顺序排列。
> 标记：✅ 必填 · ⚪ 可选（带默认值）。本附录完整重复本章依赖的公共 API，无须跳转其他章节查签名。

### A. `Langfuse(...)` —— 创建可配置脱敏、环境与采样策略的客户端

```python
from langfuse import Langfuse

langfuse = Langfuse(
    *,
    public_key: str | None = None,
    secret_key: str | None = None,
    base_url: str | None = None,
    host: str | None = None,
    timeout: int | None = None,
    httpx_client: httpx.Client | None = None,
    debug: bool = False,
    tracing_enabled: bool | None = True,
    flush_at: int | None = None,
    flush_interval: float | None = None,
    environment: str | None = None,
    release: str | None = None,
    media_upload_thread_count: int | None = None,
    sample_rate: float | None = None,
    mask: MaskFunction | None = None,
    mask_otel_spans: MaskOtelSpansFunction | None = None,
    blocked_instrumentation_scopes: list[str] | None = None,
    should_export_span: Callable[[ReadableSpan], bool] | None = None,
    additional_headers: dict[str, str] | None = None,
    tracer_provider: TracerProvider | None = None,
    id_generator: IdGenerator | None = None,
    span_exporter: SpanExporter | None = None,
)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `public_key` | str \| None | ⚪ | None | 项目公钥；未传时读 `LANGFUSE_PUBLIC_KEY`。仍缺失则客户端禁用 |
| `secret_key` | str \| None | ⚪ | None | 项目密钥；未传时读 `LANGFUSE_SECRET_KEY`。仍缺失则客户端禁用 |
| `base_url` | str \| None | ⚪ | None | 服务地址；依次回退到 `LANGFUSE_BASE_URL`、`host`、`LANGFUSE_HOST`，最终为 `https://cloud.langfuse.com` |
| `host` | str \| None | ⚪ | None | 服务地址的兼容参数；新代码优先使用 `base_url` |
| `timeout` | int \| None | ⚪ | None | HTTP 超时秒数；未传时读 `LANGFUSE_TIMEOUT`，有效默认值为 `5` |
| `httpx_client` | httpx.Client \| None | ⚪ | None | 自定义同步 HTTP 客户端，用于代理、自定义 CA 或 mTLS 等场景 |
| `debug` | bool | ⚪ | False | 是否开启 SDK 调试日志；False 时仍可由 `LANGFUSE_DEBUG=true` 开启 |
| `tracing_enabled` | bool \| None | ⚪ | True | 是否发送追踪数据；`LANGFUSE_TRACING_ENABLED=false` 也会禁用 |
| `flush_at` | int \| None | ⚪ | None | 批量达到多少条后导出；未传时使用 SDK/OTel 有效默认值 `512` |
| `flush_interval` | float \| None | ⚪ | None | 批量导出的最长等待秒数；未传时使用有效默认值 `5` |
| `environment` | str \| None | ⚪ | None（有效值 `"default"`） | 追踪环境；未传时读 `LANGFUSE_TRACING_ENVIRONMENT`，两者都无值时上报为 `default` |
| `release` | str \| None | ⚪ | None | 发布版本、Git SHA 等；未传时读 `LANGFUSE_RELEASE`，并可回退到常见部署环境变量 |
| `media_upload_thread_count` | int \| None | ⚪ | None | 媒体上传线程数；未传时读同名环境配置，有效默认值为 `1` |
| `sample_rate` | float \| None | ⚪ | None（有效值 `1.0`） | 追踪采样率，必须在 `[0.0, 1.0]` 内；未传时读 `LANGFUSE_SAMPLE_RATE` |
| `mask` | MaskFunction \| None | ⚪ | None | 同步处理 Langfuse SDK 写入的 input、output、metadata；本章 PII 脱敏核心 |
| `mask_otel_spans` | MaskOtelSpansFunction \| None | ⚪ | None | 导出阶段批量修补 OTel span 属性，适合第三方 instrumentation 产生的数据 |
| `blocked_instrumentation_scopes` | list[str] \| None | ⚪ | None | 按 instrumentation scope 阻止导出；已弃用，应改用 `should_export_span` |
| `should_export_span` | Callable[[ReadableSpan], bool] \| None | ⚪ | None | span 导出过滤器；返回 False 的 span 不会上报 |
| `additional_headers` | dict[str, str] \| None | ⚪ | None | 发往 Langfuse 的附加 HTTP 请求头 |
| `tracer_provider` | TracerProvider \| None | ⚪ | None | 注入自定义 OpenTelemetry TracerProvider |
| `id_generator` | IdGenerator \| None | ⚪ | None | 注入自定义 trace/span ID 生成器 |
| `span_exporter` | SpanExporter \| None | ⚪ | None | 注入自定义 span exporter，主要用于高级 OTel 集成或测试 |

`environment` **不是** `dev` / `staging` / `prod` 固定枚举，而是满足以下约束的自定义字符串：

| 约束 | 说明 |
| --- | --- |
| 允许字符 | 小写字母、数字、连字符 `-`、下划线 `_` |
| 禁止前缀 | 不能以 `langfuse` 开头 |
| 默认值 | `default` |
| 常用值 | `development`、`staging`、`production`（只是约定，不是枚举） |

> `sample_rate` 的边界值 `0.0` 与 `1.0` 都合法；小于 0 或大于 1 会在构造客户端时抛出 `ValueError`。
>
> `mask`、采样器和 exporter 属于按公钥复用的客户端资源配置。应在进程内使用该公钥创建**第一个客户端**时就传入；本章因此不复用 `_bootstrap` 单例。

---

### B. `MaskFunction` / `pii_mask(...)` —— 同步替换 SDK input、output 与 metadata

```python
from typing import Any
from langfuse.types import MaskFunction

class MaskFunction(Protocol):
    def __call__(
        self,
        *,
        data: Any,
        **kwargs: dict[str, Any],
    ) -> Any: ...


def pii_mask(*, data: Any, **kwargs: Any) -> Any:
    return redacted_data
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `data` | Any | ✅ | — | 即将写入 span 属性的数据，可能是 str、dict、list 或其他可序列化结构 |
| `**kwargs` | dict[str, Any] / Any | ⚪ | 空 | 为 SDK 扩展保留；实现应接收但不要依赖当前不存在的键 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 脱敏后的数据 | Any | **返回值会替代原始 `data`**，且必须可 JSON 序列化；不能只原地修改后返回 `None`，否则记录值会变成 `None` |

> `mask` 在写入属性时同步执行，应保持确定性、快速且避免网络/磁盘 I/O；需要自行递归处理 dict/list 等嵌套结构。
>
> 若 `mask` 抛异常，SDK 会记录错误并使用 `"<fully masked due to failed mask function>"` 作为失败回退，不会把原始敏感数据回退上报。业务上仍应测试规则并监控错误日志，避免整字段被兜底遮蔽。
>
> `@observe` 自动捕获的函数入参与返回值也会写成 input/output，因此同样经过客户端的 `mask`，并非只有手工 `update(...)` 才脱敏。

---

### C. `mask_otel_spans(...)` —— 在导出阶段修补 OpenTelemetry span 属性

```python
from typing import Optional
from langfuse.types import (
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanPatch,
)


def mask_otel_spans(
    *,
    params: MaskOtelSpansParams,
) -> Optional[MaskOtelSpansResult]:
    patches = {}
    for identifier, span in params.spans.items():
        if "http.request.header.authorization" in span.attributes:
            patches[identifier] = OtelSpanPatch(
                delete_attributes=("http.request.header.authorization",),
                set_attributes={"security.redacted": True},
            )
    return MaskOtelSpansResult(span_patches=patches)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `params` | MaskOtelSpansParams | ✅ | — | 当前 OTel 导出批次；`params.spans` 是只读的 `{OtelSpanIdentifier: OtelSpanData}` 映射 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 批量补丁 | MaskOtelSpansResult \| None | `None` 表示整批不修改；否则用 `span_patches` 返回稀疏补丁，未列出的 span 保持不变 |

相关补丁类型的完整签名：

```python
MaskOtelSpansResult(
    span_patches: Mapping[OtelSpanIdentifier, OtelSpanPatch | None] = {},
)

OtelSpanPatch(
    set_attributes: Mapping[str, AttributeValue] = {},
    delete_attributes: Sequence[str] = (),
)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `span_patches` | Mapping[OtelSpanIdentifier, OtelSpanPatch \| None] | ⚪ | 空映射 | 使用 `params.spans` 中的 identifier 作为键；值为 None 时该 span 不变 |
| `set_attributes` | Mapping[str, AttributeValue] | ⚪ | 空映射 | 新增或替换属性；值须符合 OTel 标量或同类标量序列类型 |
| `delete_attributes` | Sequence[str] | ⚪ | 空元组 | 删除属性键；先删除再 set，因此同一键同时出现时最终保留 set 的值 |

| 对比项 | `mask` | `mask_otel_spans` |
| --- | --- | --- |
| 处理对象 | Langfuse SDK 写入的 input、output、metadata | 本客户端即将导出的 OTel span 属性 |
| 调用粒度 | 每次写属性时处理一个 data | 每个导出批次处理一组 span 快照 |
| 修改方式 | 直接返回替换后的数据 | 返回 identifier → `OtelSpanPatch` 的稀疏映射 |
| 典型来源 | `@observe`、`update_current_span` 等 Langfuse API | OpenAI、HTTP 等第三方 OTel instrumentation |

> 此钩子同步运行，通常位于 OTel 批处理工作线程；`flush()` / shutdown 时也可能在调用方线程执行。应保持快速、确定性、避免异步或阻塞 I/O，也不要依赖 request local 或当前活动 span。
>
> 它只能修补 span attributes，不能修改 span 名称、ID、父子关系、resource attributes、events、links 或 instrumentation scope。要丢弃整个 span，请使用 `should_export_span`。
>
> 钩子抛异常或返回错误类型时，SDK 会丢弃整个导出批次；单个 `OtelSpanPatch` 无效时，只丢弃对应 span。因此该钩子必须有单元测试与错误监控。

---

### D. `@observe(...)` —— 自动捕获函数调用并建立观测层级

```python
from collections.abc import Callable, Iterable
from langfuse import observe

observe(
    func: F | None = None,
    *,
    name: str | None = None,
    as_type: ObservationType | None = None,
    capture_input: bool | None = None,
    capture_output: bool | None = None,
    transform_to_string: Callable[[Iterable], str] | None = None,
) -> F | Callable[[F], F]
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `func` | F \| None | ⚪ | None | 被装饰函数；支持 `@observe` 无括号写法，通常不手工传入 |
| `name` | str \| None | ⚪ | None（有效值为函数名） | UI 中的观测名称 |
| `as_type` | ObservationType \| None | ⚪ | None（按 `span` 处理） | 观测语义类型，九种合法值见下表 |
| `capture_input` | bool \| None | ⚪ | None（有效默认开启） | 是否自动把函数参数捕获为 input；可受 `LANGFUSE_OBSERVE_DECORATOR_IO_CAPTURE_ENABLED` 全局关闭 |
| `capture_output` | bool \| None | ⚪ | None（有效默认开启） | 是否自动把返回值捕获为 output；同样受全局 I/O 捕获开关影响 |
| `transform_to_string` | Callable[[Iterable], str] \| None | ⚪ | None | 对生成器函数，把产出的片段转换/汇总成可记录的 output 字符串 |

`as_type` 九种枚举：

| 值 | 说明 |
| --- | --- |
| `"generation"` | 大语言模型生成调用，可记录 model、usage、cost |
| `"embedding"` | 嵌入模型调用，可记录 model、usage、cost |
| `"span"` | 通用工作单元，默认类型 |
| `"agent"` | Agent 的整体执行 |
| `"tool"` | 外部工具调用 |
| `"chain"` | 固定编排链路 |
| `"retriever"` | 检索步骤 |
| `"evaluator"` | 评估步骤 |
| `"guardrail"` | 安全或合规护栏 |

> 支持 `@observe` 和 `@observe(name="...")` 两种形式；嵌套调用会自动建立父子 span。
>
> 自动捕获开启时，入参与返回值会经过本客户端的 `mask`。关闭 capture 只能避免捕获，不应代替脱敏策略。

---

### E. `langfuse.update_current_span(...)` —— 更新当前活动 span 的通用字段

```python
langfuse.update_current_span(
    *,
    name: str | None = None,
    input: Any | None = None,
    output: Any | None = None,
    metadata: Any | None = None,
    version: str | None = None,
    level: Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"] | None = None,
    status_message: str | None = None,
) -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | str \| None | ⚪ | None | 覆盖当前 span 名称 |
| `input` | Any \| None | ⚪ | None | 记录输入；本章传入原始文本，写入前会经过 `mask` |
| `output` | Any \| None | ⚪ | None | 记录输出；写入前会经过 `mask` |
| `metadata` | Any \| None | ⚪ | None | 合并/记录元数据；写入前会经过 `mask` |
| `version` | str \| None | ⚪ | None | 代码、Prompt 或组件版本 |
| `level` | Literal[...] \| None | ⚪ | None | span 级别，四种合法值见下表 |
| `status_message` | str \| None | ⚪ | None | 状态或错误说明 |

`level` 四种枚举：

| 值 | 说明 |
| --- | --- |
| `"DEBUG"` | 调试信息 |
| `"DEFAULT"` | 普通默认级别 |
| `"WARNING"` | 警告，不一定导致流程失败 |
| `"ERROR"` | 错误或失败 |

> 必须在 `@observe` 函数体或其他活动观测上下文中调用；没有活动 span 时无法更新预期目标。

---

### F. `langfuse.auth_check()` —— 阻塞校验当前凭证

```python
langfuse.auth_check() -> bool
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| — | — | — | — | 无参数 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 鉴权状态 | bool | 同步发送 HTTP 请求；凭证有效返回 True，失败返回 False |

> 这是阻塞式网络检查，适合本章短脚本启动时快速失败；不要放进每次业务请求的热路径。

### G. `langfuse.flush()` —— 阻塞排空客户端缓冲区

```python
langfuse.flush() -> None
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| — | — | — | — | 无参数 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 无 | None | 强制导出 OTel span，并等待 score ingestion 与 media upload 队列处理完毕 |

> 短命脚本应在退出前调用，避免尚在缓冲区的数据随进程结束而丢失。它可能阻塞，不应在高频请求路径中逐次调用。

---

### H. `langfuse.get_dataset(...)` —— 按名称获取远端数据集及其条目

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
| `name` | str | ✅ | — | 数据集名称；本章使用 `tutorial-常识问答` |
| `fetch_items_page_size` | int \| None | ⚪ | 50 | 拉取数据集条目时的分页大小 |
| `version` | datetime \| None | ⚪ | None | 获取该时间点的数据集版本；必须是**带时区的 UTC datetime**，None 表示当前版本 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 数据集客户端 | DatasetClient | 提供数据集条目与 `run_experiment(...)` 方法 |

> `get_dataset` 会访问服务端；找不到数据集或网络失败会抛异常。本章将该情况视为门禁失败并返回退出码 1。

---

### I. `dataset.run_experiment(...)` —— 并发执行任务、单条评估与运行级汇总

```python
dataset.run_experiment(
    *,
    name: str,
    run_name: str | None = None,
    description: str | None = None,
    task: TaskFunction,
    evaluators: list[EvaluatorFunction] = [],
    composite_evaluator: CompositeEvaluatorFunction | None = None,
    run_evaluators: list[RunEvaluatorFunction] = [],
    max_concurrency: int = 50,
    metadata: dict[str, Any] | None = None,
) -> ExperimentResult
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | str | ✅ | — | 实验名称；本章为 `CI回归检查` |
| `run_name` | str \| None | ⚪ | None | 本次运行名称；用于区分同一实验的多次运行 |
| `description` | str \| None | ⚪ | None | 实验目的、基线或方法说明 |
| `task` | TaskFunction | ✅ | — | 对每条数据执行的同步/异步函数；本章签名为 `task(*, item, **kwargs)` |
| `evaluators` | list[EvaluatorFunction] | ⚪ | `[]` | 单条评估器列表；本章传 `[correctness]`，逐条生成正确性分数 |
| `composite_evaluator` | CompositeEvaluatorFunction \| None | ⚪ | None | 组合评估器，可基于一条 item 的多个评估结果再汇总 |
| `run_evaluators` | list[RunEvaluatorFunction] | ⚪ | `[]` | 运行级评估器；本章传 `[avg_correctness]`，对成功 item 的结果计算门禁总分 |
| `max_concurrency` | int | ⚪ | 50 | task 与评估执行的最大并发数；CI 中可按模型限流下调 |
| `metadata` | dict[str, Any] \| None | ⚪ | None | 关联到实验运行的结构化元数据，如 commit SHA、分支或模型版本 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 实验结果 | ExperimentResult | 包含成功 item 结果、运行级评估、实验 ID 与数据集运行链接 |

> 签名中的 `evaluators=[]` 与 `run_evaluators=[]` 是 SDK `4.14.4` 的真实默认值；调用方不要修改默认列表，按需传入新列表即可。
>
> `run_evaluator` 收到的 `item_results` **只包含成功处理的 item**；task 或 item 处理失败的条目不会进入平均分分母，可能让平均分虚高。严格门禁应额外校验成功数量/覆盖率，不能只看平均正确率。

---

### J. `Evaluation(...)` —— 构造单条或运行级评估结果

```python
from langfuse import Evaluation

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
| `name` | str | ✅ | — | 指标名；跨运行应保持稳定，本章使用 `correctness` / `avg_correctness` |
| `value` | int \| float \| str \| bool | ✅ | — | 指标值；本章门禁要求汇总值为 `[0.0, 1.0]` 内数值 |
| `comment` | str \| None | ⚪ | None | 人类可读的评分理由或异常说明 |
| `metadata` | dict[str, Any] \| None | ⚪ | None | 置信度、评估器版本、中间计算等结构化信息 |
| `data_type` | Literal[...] \| None | ⚪ | None（数值按 `NUMERIC`） | 分数数据类型；非数值 value 应显式填写对应类型 |
| `config_id` | str \| None | ⚪ | None | 关联 Langfuse Score Config 的 ID |

`data_type` 三种枚举：

| 值 | 适用 value | 说明 |
| --- | --- | --- |
| `"NUMERIC"` | int / float | 数值指标，如正确率、延迟评分 |
| `"CATEGORICAL"` | str | 分类标签，如 `pass` / `fail` / `unknown` |
| `"BOOLEAN"` | bool | 布尔判定，如是否通过安全检查 |

> 构造函数中的 `*` 表示所有参数都必须按关键字传入；`Evaluation("accuracy", 1.0)` 不合法。

---

### K. `ExperimentResult.format(...)` —— 把实验结果格式化为可读文本

```python
result.format(*, include_item_results: bool = False) -> str
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `include_item_results` | bool | ⚪ | False | False 仅输出汇总；True 额外输出每条 item 的输入、期望、实际输出与评分 |

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| 格式化报告 | str | 可打印、写日志或保存为 CI artifact 的多行文本 |

`ExperimentResult` 属性：

| 属性 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | :---: | --- | --- |
| `name` | str | ✅ | — | 实验名称 |
| `run_name` | str | ✅ | — | 本次运行名称 |
| `description` | str \| None | ✅ | — | 实验说明 |
| `item_results` | list[ExperimentItemResult] | ✅ | — | 成功处理的 item 结果；每项含 item、output、evaluations、trace_id、dataset_run_id |
| `run_evaluations` | list[Evaluation] | ✅ | — | 运行级评估结果；本章从这里读取 `avg_correctness` |
| `experiment_id` | str | ✅ | — | 本次实验 ID；远端数据集实验中与 dataset run ID 对齐 |
| `dataset_run_id` | str \| None | ⚪ | None | Langfuse 数据集运行 ID |
| `dataset_run_url` | str \| None | ⚪ | None | 在 Langfuse UI 查看本次实验的直达链接 |

> `format()` 只生成展示文本，不改变结果，也不替代基于 `run_evaluations` 的程序化门禁判断。

---

### L. CI 门禁语义 —— 阈值、缺失指标与退出码约定

```python
PASS_THRESHOLD = 0.6

score = next(
    (e.value for e in result.run_evaluations if e.name == "avg_correctness"),
    0.0,
)
exit_code = 0 if score >= PASS_THRESHOLD else 1
```

| 约定 | 说明 |
| --- | --- |
| 阈值范围 | `PASS_THRESHOLD` 必须在 `[0.0, 1.0]` 内，与本章正确率的取值范围一致 |
| 边界判定 | `score >= PASS_THRESHOLD` 通过；`score < PASS_THRESHOLD` 失败；**等于阈值时通过** |
| 指标缺失 | `next(..., 0.0)` 在找不到 `avg_correctness` 时回退到 `0.0`，这是 fail-closed：正常正阈值下会拦住 CI，而不是误放行 |
| 汇总分母 | `run_evaluator` 的 `item_results` 只含成功 item；失败 item 不进入平均分分母，可能导致分数虚高 |
| `exit(0)` | 门禁通过，CI 步骤成功，允许继续部署 |
| `exit(1)` | 发现回归或前置条件失败，CI 步骤失败并拦截部署 |

> 若允许把阈值配置为 `0.0`，指标缺失时的回退值也会满足 `score >= threshold`。要在所有合法阈值下都严格 fail-closed，应先显式检查目标指标是否存在，再执行分数比较；本章默认阈值 `0.6` 时，回退 `0.0` 会可靠拦截。
>
> 生产 CI 建议同时检查：目标指标存在、value 为数值且在 `[0.0, 1.0]`、成功 item 数与数据集条目数一致，再比较阈值。
