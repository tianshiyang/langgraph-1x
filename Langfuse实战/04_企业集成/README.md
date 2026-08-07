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

> 签名取自已安装的 **Langfuse SDK `4.14.3`** 源码。本章复用 02/03 章的 Prompt、Dataset、Experiment API（此处不重复），只补两个**企业级新增点**：①客户端构造的 `mask` 脱敏钩子；②CI 门禁如何从 `ExperimentResult` 取分。

### A. `Langfuse(...)` —— 直接构造客户端（用于传 `mask` 等客户端级配置）
```python
from langfuse import Langfuse
langfuse = Langfuse(
    *,
    public_key: str | None = None,           # 同 LANGFUSE_PUBLIC_KEY
    secret_key: str | None = None,           # 同 LANGFUSE_SECRET_KEY
    base_url: str | None = None,             # 默认 "https://cloud.langfuse.com"，同 LANGFUSE_BASE_URL
    timeout: int | None = None,              # API 请求超时（秒），默认 5
    debug: bool = False,
    tracing_enabled: bool | None = True,
    flush_at: int | None = None,             # 攒多少条 span 发一次，默认 512
    flush_interval: float | None = None,     # 批量上报间隔（秒），默认 5
    environment: str | None = None,          # 同 LANGFUSE_TRACING_ENVIRONMENT
    release: str | None = None,              # 应用版本/hash，用于按版本分组
    sample_rate: float | None = None,        # 采样率 0.0~1.0，默认 1.0
    mask: MaskFunction | None = None,        # ★ SDK 写入数据的同步脱敏钩子
    mask_otel_spans: MaskOtelSpansFunction | None = None,  # 第三方 OTel span 的脱敏钩子
    httpx_client=None,
    additional_headers: dict | None = None,
    should_export_span: Callable | None = None,  # 是否导出某 span 的过滤回调
    # …还有 tracer_provider / span_exporter / id_generator 等高级项
)
```

**企业常用参数**
| 参数 | 说明 |
| --- | --- |
| `mask` | ★ **本场景核心**。SDK 在创建属性时**同步**调用，对 `start_observation()`/`update()`/`set_trace_io()` 等写入的数据脱敏。只作用于「经 Langfuse SDK API 写入的数据」 |
| `mask_otel_spans` | 第三方 OpenTelemetry instrumentation 产生的**原始 span**用这个；在导出阶段对整批 span 打补丁（见正文示例） |
| `environment` | 区分 dev/staging/prod，看板互不污染（也可用环境变量 `LANGFUSE_TRACING_ENVIRONMENT`） |
| `sample_rate` | 生产大流量可 < 1 采样，降低成本 |
| `release` | 标记应用版本，便于「按发布版本」对比效果 |
| `flush_at` / `flush_interval` | 批量上报策略；短脚本配合 `flush()` 保证不丢 |

> ⚠️ `mask` 是**客户端级**配置，必须在**进程内第一个 client** 创建时传入；所以本场景不复用 `_bootstrap` 的默认单例，而是自建 `Langfuse(mask=pii_mask)`（见 `s12`）。

---

### B. `MaskFunction` —— 脱敏钩子的固定签名
```python
# 类型定义（langfuse/types.py）：def __call__(self, *, data, **kwargs) -> Any
def pii_mask(*, data: Any, **kwargs: Any) -> Any:
    # data 是即将上报的数据（可能是 str/dict/list/…）
    # 返回值必须可 JSON 序列化
    ...
    return redacted_data
```
| 要点 | 说明 |
| --- | --- |
| 签名 | 必须 `(*, data, **kwargs)` —— 关键字参数 `data` |
| 时机 | 数据**上报前**同步执行；UI 里存的就是打码后的内容 |
| 范围 | 仅对经 SDK API 写入的数据生效（`update(input=...)` 等） |
| 递归 | `data` 可能是 dict/list，脱敏函数需自己递归处理（见 `s12` 的 `_redact`） |
| 第三方 span | 用 `mask_otel_spans`（接收一批 OTel span，返回 patch） |

---

### C. CI 回归门禁 —— 从 `ExperimentResult` 取分 + 阈值判定

复用 03 章的 `dataset.run_experiment(...)`（签名见 03 章附录 E）。门禁逻辑就两步：

```python
result = dataset.run_experiment(
    name="CI回归检查",
    task=task,                         # task(*, item, **kwargs)
    evaluators=[correctness],          # 单条评估器
    run_evaluators=[avg_correctness],  # ★ 运行级（汇总）评估器，产出一个总分
)

# 从运行级评估结果里取出某个汇总分
score = next(
    (e.value for e in result.run_evaluations if e.name == "avg_correctness"),
    0.0,
)

sys.exit(0 if score >= PASS_THRESHOLD else 1)   # 1 = 回归，CI 失败
```
| 要点 | 说明 |
| --- | --- |
| `run_evaluators` | 运行级评估器 `(*, item_results, **kwargs)`，对整个数据集算一个汇总分（如平均正确率）；门禁就靠它 |
| `result.run_evaluations` | `list`，每项有 `.name` / `.value`；用名字取出要判定的那个分 |
| `sys.exit(1)` | 非零退出码让 CI 步骤失败 → PR 被阻断（真实 CI 里把这段当一步跑，读 `$?`） |
| 升级路线 | 官方还提供 GitHub Action（`langfuse/experiment-action`）与 `RegressionError`，可直接在 PR 里对比基线 |
