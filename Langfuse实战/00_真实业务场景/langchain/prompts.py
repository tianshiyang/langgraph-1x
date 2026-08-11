"""客服人设与消息拼装（本地基线版）。

这里定义业务默认的 system prompt 与「system + 检索资料 + 历史 + 当前问题」的消息拼装逻辑。
观测层 `langfuse/prompts.py` 会把同一份人设托管到 Langfuse，实现「运营在 UI 改 prompt 不动代码」；
但业务层始终保留这份本地基线，保证脱网/未接 Langfuse 时也能正常回答。
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from knowledge_base import RetrievedDoc

# 客服人设：要求严格基于检索资料回答，并在末尾标注来源
SUPPORT_SYSTEM_PROMPT = (
    "你是「优选商城」的在线客服助手，只依据下方【知识库资料】回答用户问题。\n"
    "要求：\n"
    "1. 回答简洁、口语化，先给结论再给必要细节；\n"
    "2. 必须在回答末尾用一行标注来源，格式为「[来源: 文档标题]」，可标注多个；\n"
    "3. 如果资料里没有相关信息，明确说明「这个我暂时没查到，建议为您转接人工客服」，不要编造；\n"
    "4. 结合上文对话理解用户的追问（如「它」「这个」指代前面提到的内容）。"
)


# 把检索到的文档拼成【知识库资料】文本块
def build_context(docs: list[RetrievedDoc]) -> str:
    if not docs:
        return "【知识库资料】（无匹配资料）"
    lines = ["【知识库资料】"]
    for doc in docs:
        lines.append(f"- {doc['title']}：{doc['text']}")
    return "\n".join(lines)


# 拼装本轮完整消息：system(人设+资料) + 历史对话 + 当前问题
# system_prompt 可覆盖默认人设（观测层会传入 Langfuse 托管的线上人设）
def build_messages(
    question: str,
    docs: list[RetrievedDoc],
    history: list[BaseMessage] | None = None,
    *,
    system_prompt: str | None = None,
) -> list[BaseMessage]:
    persona = system_prompt or SUPPORT_SYSTEM_PROMPT
    system_content = f"{persona}\n\n{build_context(docs)}"
    messages: list[BaseMessage] = [SystemMessage(system_content)]
    if history:
        messages.extend(history)
    messages.append(HumanMessage(question))
    return messages
