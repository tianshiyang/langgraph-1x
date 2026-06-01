from typing import Literal

from langgraph.types import Command

from .state import EmailAgentState


def search_documentation(state: EmailAgentState) -> Command[Literal["draft_response"]]:
    """在知识库中搜索相关信息"""

    # 根据分类构建搜索查询
    classification = state.get("classification", {})
    query = f"{classification.get('intent', '')} {classification.get('topic', '')}"

    try:
        # 实现搜索逻辑
        # 存储原始搜索结果，而非格式化的文本
        search_results = [
            "Reset password via Settings > Security > Change Password",
            "Password must be at least 12 characters",
            "Include uppercase, lowercase, numbers, and symbols",
            # "通过 设置 > 安全 > 修改密码 来重置密码"
            # "密码长度至少为 12 个字符"
            # "需包含大写字母、小写字母、数字和符号"
        ]
    except Exception as e:
        search_results = [f"搜索暂时不可用： {e}"]
    return Command(
        update={
            "search_results": search_results,
        },
        goto="draft_response",
    )


def bug_tracking(state: EmailAgentState) -> Command[Literal["draft_response"]]:
    """创建或更新bug跟踪工单"""
    ticket_id = "BUG—12345"
    return Command(
        update={
            "search_results": [f"bug工单{ticket_id}已创建"],
            "current_step": "bug_tracked",
        },
        goto="draft_response",
    )
