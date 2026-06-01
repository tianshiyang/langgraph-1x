from typing import TypedDict, Literal


# 定义电子邮件分类的结构
class EmailClassification(TypedDict):
    intent: Literal["question", "bug", "billing", "feature", "complex"]  # 意图
    urgency: Literal["low", "medium", "high", "critical"]  # 紧急性
    topic: str  # 主题
    summary: str  # 总结


class EmailAgentState(TypedDict):
    # 原始邮件信息
    email_content: str
    sender_email: str
    email_id: str

    # 分类结果
    classification: EmailClassification | None

    # 原始搜索/API结果
    search_results: list[str] | None  # 原始文档片段列表
    customer_history: dict | None  # 来自CRM的原始客户数据

    # 生成的内容
    draft_response: str | None
    messages: list[str] | None
