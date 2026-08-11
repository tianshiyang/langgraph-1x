"""实现层（业务）：企业知识库客服助手。

本包只依赖 LangChain 与项目内 `provider.glm_model`，**完全不感知 Langfuse**。
体现真实项目里「业务归业务」的分层：业务代码可独立运行、独立测试，
可观测性/评估/脱敏都在同级的 `langfuse/` 目录里叠加，不侵入这里。

模块：
  - knowledge_base : mock 企业知识库 + 模拟向量检索
  - prompts        : 客服人设与消息拼装
  - rag_service    : 检索→拼上下文→调模型；多轮会话 SupportSession
  - app            : 可独立运行的多轮对话 demo
"""
