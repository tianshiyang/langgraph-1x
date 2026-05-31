import operator
from typing import Literal

from IPython.display import Image, display
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage, HumanMessage
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from typing_extensions import TypedDict, Annotated
from langchain_core.tools import tool

from llms import glm_model


@tool
def multiply(a: int, b: int) -> int:
    """计算两个数的乘积

    Args:
        a: 第一个数字
        b: 第二个数字

    Returns:
        返回两个数的乘积
    """
    return a * b


@tool
def add(a: int, b: int) -> int:
    """
    计算量数之和
    Args:
        a: 第一个数字
        b: 第二个数字

    Returns:
        返回两个数相加的和
    """
    return a + b


@tool
def divide(a: int, b: int) -> float:
    """
    两数相除
    Args:
        a: 第一个数字
        b: 第二个数字

    Returns:
        返回两个数相除后的结果
    """
    return a / b


# 定义工具
tools = [multiply, add, divide]

tools_by_name = {tool.name: tool for tool in tools}

model_with_tools = glm_model.bind_tools(tools)


# 定义状态
class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int


# 定义模型节点
def llm_call(state: MessagesState):
    """LLM决定是否调用工具"""
    return {
        "messages": [
            model_with_tools.invoke(
                [
                    SystemMessage(
                        content="您是一位有用的助手，负责对一组输入执行算术运算。"
                    )
                ]
                + state["messages"]
            ),
        ],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# 定义工具节点
def tool_node(state: MessagesState):
    """执行工具调用"""
    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result}


# 定义判断是否结束的逻辑
# 根据 LLM 是否进行工具调用路由到工具节点或结束的条件边缘函数
def should_continue(state: MessagesState) -> Literal["tool_node", END]:
    """根据 LLM 是否进行了工具调用来决定是否继续循环或停止"""
    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return "tool_node"
    return END


# 构建工作流
agent_builder = StateGraph(MessagesState)

# 添加节点
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("tool_node", tool_node)

# 添加边来连接节点
agent_builder.add_edge(START, "llm_call")
agent_builder.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
agent_builder.add_edge("tool_node", "llm_call")

# 完成agent
agent = agent_builder.compile()

if __name__ == "__main__":
    display(Image(agent.get_graph(xray=True).draw_mermaid_png()))

    messages = agent.invoke({"messages": [HumanMessage(content="Add 3 and 4.")]})
    for m in messages["messages"]:
        m.pretty_print()
