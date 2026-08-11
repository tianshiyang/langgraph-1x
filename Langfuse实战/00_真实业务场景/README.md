# 真实业务场景 · 企业知识库客服助手（实现层 / 观测层分离）

> 一个尽量贴近企业实际的完整示例：**多轮对话的知识库客服助手**。
> 用它演示真实项目里 Langfuse 到底怎么落地——**业务代码归业务，可观测性/评估/脱敏归观测层，观测不侵入业务**。

## 这个示例在演示什么

一位客户连续多轮提问 →（模拟）检索企业知识库 → 大模型生成带来源引用的回答 → 支持基于上文的追问。
在这条真实链路上，叠加了 Langfuse 的全套能力：

- **可观测**：每轮对话一个 trace，`support-turn(chain)` 下挂 `knowledge-retrieval(retriever)` 和 `generation`；
- **多轮会话**：同一 `session_id` 把多轮聚成一个 Session；
- **Prompt 托管**：客服人设托管在 Langfuse，运营在 UI 改人设即改线上行为，代码不动；
- **成本 / token**：真实调用 `glm_model`，generation 上记录真实 token 用量；
- **在线打分**：规则分 + 模拟用户👍👎 + LLM-as-judge 相关性分；
- **离线回归**：数据集 + 实验，两套人设并排对比，改动上线前先跑；
- **PII 脱敏**：手机号/身份证/邮箱/银行卡在上报前打码，UI 里存的是脱敏后的内容。

## 目录结构：两层分离

```
00_真实业务场景/
├─ langchain/          【实现层】纯业务，零 Langfuse，可独立运行
│  ├─ knowledge_base.py   mock 企业知识库 + 模拟向量检索（关键词重叠打分）
│  ├─ prompts.py          客服人设与消息拼装（本地基线）
│  ├─ rag_service.py      检索→拼上下文→调模型；多轮会话 SupportSession
│  └─ app.py              可独立运行的多轮对话 demo（不 import 任何 langfuse）
└─ langfuse/           【观测层】import 实现层，叠加观测/评估/脱敏
   ├─ _setup.py          统一的 sys.path 与 .env 准备
   ├─ pii.py             PII 脱敏函数（mask 钩子）
   ├─ client.py          带 mask 的 Langfuse 客户端（进程内第一个 client）
   ├─ hosted_prompts.py  把客服人设托管到 Langfuse
   ├─ instrumented.py    核心：在业务上叠加观测（业务代码零改动）
   ├─ feedback.py        在线打分：规则分 / 用户反馈 / LLM 裁判
   ├─ evaluate.py        离线：数据集回归实验，两套人设对比
   └─ run.py             编排入口：完整多轮会话 + 全套观测
```

**分层的意义**：`langchain/` 只依赖 LangChain 和项目内 `provider.glm_model`，可以独立跑、独立测；
所有 Langfuse 相关的东西都在 `langfuse/`，通过「组合业务原子能力 + 挂回调 + 包观测上下文」叠加，
**不改业务一行代码**。真实项目里这能让业务团队和平台/可观测团队解耦。

## 怎么运行

> 前置：项目根 `.env` 里已配好 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`
> 以及模型相关的 key（`provider` 使用的配置）。

```bash
# 1) 只跑实现层（无需 Langfuse），验证业务可独立运行
python "Langfuse实战/00_真实业务场景/langchain/app.py"

# 2) 跑观测层完整链路（多轮对话 + 全套观测 + 在线打分 + PII 脱敏）
python "Langfuse实战/00_真实业务场景/langfuse/run.py"

# 3) 离线回归实验（两套人设并排对比）
python "Langfuse实战/00_真实业务场景/langfuse/evaluate.py"
```

跑完 `run.py` 后去 Langfuse UI：

- **Sessions** → 找到本次 `support-xxxx`：4 轮对话聚在一个会话；
- **Tracing** → 每轮一个 `support-turn`，展开看 `knowledge-retrieval`（命中文档+score）与 `generation`（真实 token）；
- **Scores** → `has_citation` / `length_ok` / `user_feedback` / `relevance`；
- 含手机号那轮的输入显示为 `<PHONE>`（脱敏生效）。

## 目录同名冲突的注意事项（重要）

`langchain/` 和 `langfuse/` 这两个目录名与三方包同名。只要遵守下面两条，`import langchain` / `import langfuse`
仍然从 site-packages 正常解析，不会被本地目录遮蔽：

1. **按文件路径直接运行脚本**（如上面的命令），此时 `sys.path[0]` 是脚本自身所在目录，
   父目录 `00_真实业务场景/` 不会进入 `sys.path`；
2. **不要把 `00_真实业务场景/` 加进 `sys.path`**，也不要把这两个目录当作包 `import`。

跨层引用通过把「目标目录本身」加入 `sys.path` + 裸模块名导入实现（见 `langfuse/_setup.py`）。
两层的模块基名不重叠（观测层的 prompt 模块叫 `hosted_prompts.py`，避开业务层的 `prompts.py`），
因此两目录同时在 path 上也不会产生 `import prompts` 歧义。

## 成本显示为 0？（cost 一直是 0 的原因与修复）

Langfuse 的成本 = `token 用量 × 每模型单价`。它靠 generation 上的 **model 字符串**去匹配定价表。
本项目模型是 `glm-5.1`，Langfuse 内置定价表里没有它，**匹配不到单价 → 成本按 0 计**（token 仍会正常显示）。

修复（只影响修复之后产生的新 trace，历史 trace 不会追溯重算）：

1. Langfuse UI → **Settings → Models → New model definition**；
2. **Match pattern** 填 `(?i)^glm-5\.1$`（大小写不敏感，精确匹配 glm-5.1）；
3. 填 **input price / output price**（按你的实际采购单价，单位为每 token 价格）；
4. 保存后重新跑 `run.py`，新 generation 的成本即非 0。

> 若连 token 用量都是空的，先确认 generation 是通过 `CallbackHandler` 记录的（本示例已如此），
> 且模型返回了 usage 元数据。
