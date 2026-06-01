"""
Agent 要做的事：
1. 读取收到的客户邮件
2. 按紧急程度和主题分类
3. 搜索相关文档来回答问题
4. 起草合适的回复
5. 复杂问题升级给人工客服
6. 必要时安排后续跟进

要处理的场景：
1. 简单产品问题：「怎么重置密码？」
2. Bug 报告：「选 PDF 格式导出功能就崩」
3. 紧急账单问题：「我被重复扣费了！」
4. 功能请求：「能给移动端加个 dark mode 吗？」
5. 复杂技术问题：「我们的 API 集成时不时报 504」
"""

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy

from 官方文档.thinking_in_langgraph.components.classification_node import (
    read_email,
    classify_intent,
)
from 官方文档.thinking_in_langgraph.components.draft_response_node import (
    search_documentation,
    bug_tracking,
)
from 官方文档.thinking_in_langgraph.components.response_node import (
    draft_response,
    human_review,
    send_reply,
)
from 官方文档.thinking_in_langgraph.components.state import EmailAgentState

# 创建 graph
workflow = StateGraph(EmailAgentState)

# 添加节点
workflow.add_node("read_email", read_email)
workflow.add_node("classify_intent", classify_intent)

# 为可能出现暂时性故障的节点添加重试策略
workflow.add_node(
    "search_documentation",
    search_documentation,
    retry_policy=RetryPolicy(max_attempts=3),
)

workflow.add_node("bug_tracking", bug_tracking)
workflow.add_node("draft_response", draft_response)
workflow.add_node("human_review", human_review)
workflow.add_node("send_reply", send_reply)

# 添加边
# classify_intent、search_documentation、bug_tracking、draft_response、human_review
# 这些节点通过 Command 返回值自行路由，无需手动加边
workflow.add_edge(START, "read_email")
workflow.add_edge("read_email", "classify_intent")
workflow.add_edge("send_reply", END)

# LangGraph API 会自动处理持久化（interrupt 等），无需自定义 checkpointer
app = workflow.compile()
