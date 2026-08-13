"""
场景 1 · 基础 Trace 与嵌套 Span
============================================================
目标：把「一次请求」拆成一棵可观测的树，看清每一步的输入/输出/耗时/token。

本脚本演示官方推荐的两种埋点方式，并把它们组合成一棵树：
  1) @observe 装饰器      —— 给普通 Python 函数自动埋点（最省事）
  2) start_as_current_observation 上下文管理器 —— 手工控制 span / generation（最灵活）

同时演示 3 种观测类型，对照本阶段 README 附录 I：
  - retrieve-docs → retriever （检索：从知识库取回文档）
  - build-prompt  → span      （通用步骤：拼 prompt）
  - glm-answer    → generation（模型调用：可记 model / token / 成本）

运行：
    python "Langfuse实战/01_可观测性/s1_基础trace嵌套span.py"
运行后去 Langfuse UI 的 Tracing 页面查看这棵树。
"""


import pathlib
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from langfuse._client.observe import observe

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 项目根：使绝对导入 Langfuse实战.* 生效
from Langfuse实战._bootstrap import glm_model, langfuse


# ------------------------------------------------------------
# 第 1 层：检索（用 @observe 装饰器，自动记录入参与返回值）
# ------------------------------------------------------------
# 模拟从知识库检索资料
# 标成 retriever 类型：这一步的语义是「从知识库取回相关文档」，
# 用 retriever 而非默认 span，UI 才能把它当检索环节单独分析（召回、延迟）。
@observe(name="retrieve-docs", as_type="retriever")
def retrieve_docs(query: str) -> list[str]:
    # 真实场景这里会查向量库；这里用假数据代替
    return [
        f"资料A：与「{query}」相关的背景说明",
        f"资料B：与「{query}」相关的关键数据",
    ]


# 模拟把检索结果拼进 prompt
# 纯字符串拼接，无特殊语义，用默认 span 即可
@observe(name="build-prompt")
def build_prompt(query: str, docs: list[str]) -> str:
    context = "\n".join(docs)
    return f"请根据以下资料回答问题。\n\n资料：\n{context}\n\n问题：{query}"


# ------------------------------------------------------------
# 第 2 层：真正的模型调用（用 generation 类型的 observation 手工记录）
# ------------------------------------------------------------
# 调用大模型并把它记录成一个 generation
def call_llm(prompt_text: str) -> str:
    # generation 是一种特殊的 span，专门记录模型调用（含 model / usage / cost）
    with langfuse.start_as_current_observation(
        as_type="generation",
        name="glm-answer",
        model="glm-4",  # 显式写清用了哪个模型，UI 才能按模型聚合成本
        input=prompt_text,
    ) as generation:
        messages = [
            SystemMessage("你是严谨的资料问答助手，只根据给定资料作答。"),
            HumanMessage(prompt_text),
        ]
        response = glm_model.invoke(messages)

        # 把模型返回和 token 用量补充回这个 generation
        usage = response.usage_metadata or {}
        generation.update(
            output=response.content,
            usage_details={
                "input": usage.get("input_tokens", 0),  # 输入 token
                "output": usage.get("output_tokens", 0),  # 输出 token
                "total": usage.get("total_tokens", 0),  # 总 token
            },
        )
        return response.content


# ------------------------------------------------------------
# 顶层：用 @observe 把整条链路串成一个 trace
# ------------------------------------------------------------
# 一次完整的 RAG 问答流程（顶层函数即 trace 根节点）
@observe(name="rag-qa")
def rag_qa(query: str) -> tuple[str, str | None]:
    docs = retrieve_docs(query)  # → 子 span
    prompt_text = build_prompt(query, docs)  # → 子 span
    answer = call_llm(prompt_text)  # → 子 generation
    # trace_id 必须在 trace 上下文内获取（函数返回后上下文即关闭）
    trace_id = langfuse.get_current_trace_id()
    return answer, trace_id


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    answer, trace_id = rag_qa("LangGraph 的检查点(checkpoint)是用来做什么的？")
    print("模型回答：\n", answer)
    print("\n本次 trace_id =", trace_id)

    # 短生命周期脚本必须 flush，确保数据上报完成再退出
    langfuse.flush()
    print("已上报，去 Langfuse UI 的 Tracing 查看名为 rag-qa 的三层链路。")
