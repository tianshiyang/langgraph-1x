from langchain_core.messages import HumanMessage
from langgraph.types import Command

from provider import glm_model
from .state import EmailAgentState, EmailClassification


def read_email(state: EmailAgentState):
    """提取并解析电子邮件内容"""
    return {
        "messages": [HumanMessage(content=f"处理email: {state.get('email_content')}")]
    }


def classify_intent(state: EmailAgentState):
    """意图分类"""
    structured_llm = glm_model.with_structured_output(EmailClassification)
    classification_prompt = f"""
    分析这封客户邮件并进行分类:

    邮件内容: {state['email_content']}
    发件人: {state['sender_email']}

    输出分类结果,包括意图(intent)、紧急程度(urgency)、主题(topic)和摘要(summary)。
    """

    classification = structured_llm.invoke(classification_prompt)

    if classification["intent"] == "billing" or classification["urgency"] == "critical":
        # 账单问题或者重要程度为极其重要
        goto = "human_review"
    elif classification["intent"] in ["question", "feature"]:
        # 寻找对应文档
        goto = "search_documentation"
    elif classification["intent"] == "bug":
        # bug收集
        goto = "bug_tracking"
    else:
        # 草稿
        goto = "draft_response"

    # 将分类结果作为单个 dict 存到 state 中
    return Command(update={"classification": classification}, goto=goto)
