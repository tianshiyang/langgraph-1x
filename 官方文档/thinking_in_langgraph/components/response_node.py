from typing import Literal

from langgraph.constants import END
from langgraph.types import Command, interrupt

from llms import glm_model
from 官方文档.thinking_in_langgraph.components.state import EmailAgentState


def draft_response(
    state: EmailAgentState,
) -> Command[Literal["human_review", "send_reply"]]:
    """使用上下文生成回复，并根据质量进行路由分发"""
    classification = state.get("classification", {})

    # 按需将原始状态数据格式化为上下文
    context_sections = []

    if state.get("search_results"):
        # 格式化搜索结果给prompt
        formatted_docs = "\n".join([f"- {doc}" for doc in state["search_results"]])
        context_sections.append(f"相关的文档：\n{formatted_docs}")

    if state.get("customer_history"):
        # 格式化用于 prompt 的客户数据
        context_sections.append(
            f"Customer tier: {state['customer_history'].get('tier', 'standard')}"
        )

    # 使用格式化的上下文构建 prompt
    draft_prompt = f"""份针对该客户邮件的回复：
        {state['email_content']}
    
        邮件意图：{classification.get('intent', 'unknown')}
        紧急程度：{classification.get('urgency', 'medium')}
    
        {chr(10).join(context_sections)}
    
        指南：
        - 保持专业且乐于助人
        - 解决他们的具体问题
        - 在相关时使用提供的文档"""

    response = glm_model.invoke(draft_prompt)

    # 根据紧急程度和意图判断是否需要人工审核。
    needs_review = (
        classification.get("urgency") in ["high", "critical"]
        or classification.get("intent") == "complex"
    )

    # 路由到合适的下一个节点
    goto = "human_review" if needs_review else "send_reply"

    return Command(
        update={"draft_response": response.content},
        goto=goto,
    )


def human_review(state: EmailAgentState) -> Command[Literal["send_reply", "__end__"]]:
    """使用 `interrupt` 暂停以等待人工审查，并根据决策进行路由。"""
    classification = state.get("classification", {})

    # `interrupt()` 必须放在最前面 —— 恢复执行时，位于它之前的任何代码都会重新运行。
    human_decision = interrupt(
        {
            "email_id": state.get("email_id", ""),
            "original_email": state.get("email_content", ""),
            "draft_response": state.get("draft_response", ""),
            "urgency": classification.get("urgency"),
            "intent": classification.get("intent"),
            "action": "请审阅并approve/edit此回复",
        }
    )

    # 现在处理人类的决定
    if human_decision.get("approved"):
        return Command(
            update={
                "draft_response": human_decision.get(
                    "edited_response", state.get("draft_response", "")
                )
            },
            goto="send_reply",
        )
    else:
        # 拒绝(Rejection)意味着将由人工直接处理。
        return Command(update={}, goto=END)


def send_reply(
    state: EmailAgentState,
) -> dict:
    """发送email响应"""
    print(f"正在发送回复：{state['draft_response'][:100]}...")
    return {}
