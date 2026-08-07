# Langfuse 实战学习路线图

> 环境：Langfuse Cloud 美区（`https://us.cloud.langfuse.com`）· Python SDK `4.14.1`（OpenTelemetry 架构）
> 已跑通：LangChain `CallbackHandler` 回调、`get_prompt()` 拉取远程 Prompt
> 目标：按下面的场景**挨个动手**，每个场景在对应子目录里写一个可运行的最小脚本，跑完在本文件的「进度」里打勾。

---

## Langfuse 是什么（一句话）

一个**开源的 LLM 工程平台**，围绕三根支柱把「大模型应用从 Demo 到生产」全链路管起来：

| 支柱 | 解决的问题 | 你现在的状态 |
| --- | --- | --- |
| 🔭 **可观测性 Observability** | 线上到底发生了什么？慢在哪、贵在哪、错在哪 | 已接回调，只用了皮毛 |
| 📝 **Prompt 管理 Prompt Management** | Prompt 改一版要不要发版？谁改的、能不能回滚 | 已会拉取，未做版本/灰度 |
| ✅ **评估 Evaluation** | 改完 Prompt/模型，效果是变好还是变差？ | 完全没碰 |

---

## 学习顺序总览（由浅入深，共 12 个场景）

```
可观测性 (1-4)  →  Prompt 管理 (5-7)  →  评估 (8-11)  →  企业级集成 (12)
   打好埋点地基        把 Prompt 当代码管        建立效果护栏         把三者串成工程闭环
```

---

## 一、可观测性 Observability（目录 `01_可观测性/`）

> 先把「看得见」这件事做扎实，后面所有分析都建立在 trace 之上。

### 场景 1 · 基础 Trace 与嵌套 Span
- **作用**：把一次请求拆成一棵树（模型调用 / 工具调用 / 检索），看清每一步的输入输出、耗时、token。
- **动手**：用 `@observe()` 装饰器手工埋一个「检索 → 拼 prompt → 调模型」的三层链路；对比只挂 `CallbackHandler` 时自动生成的树。
- **企业实践**：RAG / Agent 出问题时，第一时间定位是「检索召回差」还是「模型没用好上下文」。

### 场景 2 · Session 会话串联
- **作用**：把同一个用户的多轮对话归到一个 `session_id` 下，在 UI 里像看聊天记录一样回放整个会话。
- **动手**：模拟一个 3 轮的多轮对话，全部挂同一个 `langfuse_session_id`（你 `provider/langfuse.py` 里已经预留了这个字段）。
- **企业实践**：客服 / Copilot 类产品排查「用户投诉某次对话答非所问」，按会话回溯。

### 场景 3 · User、Tags、Metadata 与环境隔离
- **作用**：给 trace 打上 `user_id`、业务标签、自定义元数据，并用 `environment` 区分 dev/staging/prod，让后续能按维度筛选和聚合。
- **动手**：给调用打上 `user_id`、`tags=["weekly-report"]`、`metadata={业务字段}`，再设置 `LANGFUSE_TRACING_ENVIRONMENT`。
- **企业实践**：按客户 / 租户统计用量与成本；测试流量和生产流量物理隔离，dashboard 不互相污染。

### 场景 4 · 成本、延迟与 Dashboard
- **作用**：Langfuse 自动按模型定价算 token 成本，聚合出成本 / 延迟 / 调用量的看板。
- **动手**：跑几十条不同模型的调用，去 UI 的 Dashboard 看成本曲线；给自定义模型配一份 price（如果 GLM 没内置定价）。
- **企业实践**：给老板出「本月各业务线大模型花了多少钱」、发现某个 prompt 悄悄把 token 打爆了。

---

## 二、Prompt 管理 Prompt Management（目录 `02_Prompt管理/`）

> 把 Prompt 从「散落在代码里的字符串」升级成「有版本、能灰度、能回滚的配置」。

### 场景 5 · Prompt 版本管理与 Label 灰度发布
- **作用**：在 UI 建 Prompt，用 `production` / `staging` 等 label 控制线上到底用哪一版，改 Prompt **不用发版**。
- **动手**：把你现有的「数学」prompt 建多个版本，代码里从 `version=2` 改成按 `label="production"` 拉取；然后在 UI 切 label，观察代码不变但行为变了。
- **企业实践**：运营 / 产品同学自己在 UI 调 Prompt 上线，工程师不介入；出问题一键切回上一版。

### 场景 6 · Prompt 变量、消息占位符与客户端缓存
- **作用**：Prompt 里用 `{{变量}}` 和 message placeholder 做模板；SDK 客户端缓存，拉取零延迟。
- **动手**：写一个带变量的 chat prompt（system + 占位历史消息 + user），用 `.compile()` 填充；观察缓存命中（关掉网络仍能跑）。
- **企业实践**：多语言 / 多场景复用同一套模板骨架，只换变量；缓存保证拉 Prompt 不拖慢线上响应。

### 场景 7 · Prompt 与 Trace 关联 + Playground 调试
- **作用**：调用时把用的 Prompt 版本关联到 trace，UI 里能「按 Prompt 版本」分析效果；在 Playground 里直接改 Prompt 试跑。
- **动手**：调用时传入 `prompt=` 关联；在 UI 找到某条 trace，点进 Playground 微调后另存为新版本。
- **企业实践**：对比「v3 上线后平均延迟 / 用户点赞率」是否优于 v2，用数据决定要不要全量。

---

## 三、评估 Evaluation（目录 `03_评估/`）

> 建立「改动前后到底变好还是变坏」的护栏，这是从玩具走向生产最关键的一环。

### 场景 8 · 手动打分与用户反馈（Scores）
- **作用**：给 trace 挂分数——可以是线上用户的👍/👎，也可以是你自己回捞后人工评。
- **动手**：用 SDK 给某条 trace `create_score()` 打一个数值分和一个分类分；模拟前端点赞回传。
- **企业实践**：收集真实用户反馈，找出「被踩最多」的那批回答集中改进。

### 场景 9 · LLM-as-a-Judge 自动评估
- **作用**：配一个「裁判模型」自动给**线上生产 trace**打分（相关性 / 是否幻觉 / 是否有害等），无需人工。
- **动手**：在 UI 配置一个 LLM-as-a-Judge evaluator，挂到某类 trace 上，跑几条看自动评分。
- **企业实践**：生产流量大到没法人工看，用裁判模型 7×24 抽检质量，掉分自动告警。

### 场景 10 · Dataset 数据集 + Experiment 实验对比
- **作用**：把典型 case 攒成可复用的测试集，改 Prompt/模型后在同一数据集上跑 Experiment，**并排对比**新旧效果。
- **动手**：建一个 10 条的 dataset，写脚本对 `模型A` vs `模型B`（或 prompt v2 vs v3）各跑一遍，UI 里看对比。
- **企业实践**：上线前的「回归测试」——像跑单测一样跑效果测试，避免改 A 功能带崩 B 功能。

### 场景 11 · Annotation Queue 人工标注队列
- **作用**：把需要人看的 trace 推进一个队列，让标注同学统一评分 / 写备注，产出高质量评估数据。
- **动手**：把场景 8 里被踩的 trace 加入 annotation queue，在 UI 里走一遍人工标注流程。
- **企业实践**：组建标注小组做质量抽检；把人工标注结果反哺成场景 10 的 golden dataset。

---

## 四、企业级集成（目录 `04_企业集成/`）

### 场景 12 · CI/CD 回归门禁 + PII 脱敏
- **作用**：把场景 10 的 Experiment 塞进 CI，**效果回退就卡住部署**；同时用 masking 对输入输出里的敏感信息（手机号 / 身份证）脱敏后再上报。
- **动手**：写一个跑在本地的「伪 CI」脚本：跑 dataset 实验，分数低于阈值就 `exit(1)`；给 client 配 `mask` 函数正则打码。
- **企业实践**：Prompt 变更走 PR + 自动评估门禁，合规团队要求 trace 不落敏感数据。

---

## 进度追踪

- [ ] 场景 1 · 基础 Trace 与嵌套 Span
- [ ] 场景 2 · Session 会话串联
- [ ] 场景 3 · User / Tags / Metadata / 环境隔离
- [ ] 场景 4 · 成本、延迟与 Dashboard
- [ ] 场景 5 · Prompt 版本 + Label 灰度
- [ ] 场景 6 · Prompt 变量 / 占位符 / 缓存
- [ ] 场景 7 · Prompt↔Trace 关联 + Playground
- [ ] 场景 8 · 手动打分与用户反馈
- [ ] 场景 9 · LLM-as-a-Judge 自动评估
- [ ] 场景 10 · Dataset + Experiment 实验对比
- [ ] 场景 11 · Annotation Queue 人工标注
- [ ] 场景 12 · CI/CD 门禁 + PII 脱敏

---

## 参考

- 官方文档总览：https://langfuse.com/docs
- 可观测性：https://langfuse.com/docs/observability/overview
- Prompt 管理：https://langfuse.com/docs/prompt-management/overview
- 评估：https://langfuse.com/docs/evaluation/overview
