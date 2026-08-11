"""观测层：在业务层（../langchain）之上叠加 Langfuse 可观测性、Prompt 托管、在线打分与 PII 脱敏。

设计原则：业务代码零改动，这里通过「组合业务原子能力 + 挂回调 + 包观测上下文」的方式叠加观测。
模块：
  - pii           : PII 脱敏函数（建 client 时作为 mask 钩子）
  - client        : 带 mask 的 Langfuse 客户端（进程内第一个 client）
  - hosted_prompts: 把客服人设托管到 Langfuse（create_prompt / get_prompt）
  - instrumented  : 带观测的多轮客服会话
  - feedback      : 在线打分（规则分 / 用户反馈 / LLM 裁判）
  - evaluate      : 离线数据集回归实验
  - run           : 编排入口，跑一段完整多轮对话并附全套观测
"""
