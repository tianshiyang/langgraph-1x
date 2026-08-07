"""
LangGraph Agent 循环 (Agent Loop) — 企业生产版完整教程
========================================================

⭐️ 一句话：Agent 循环就是「模型想 → 调工具 → 看结果 → 再想 → ……直到不用工具为止」
   这个反复的过程。它是【所有 Agent 的心脏】。你在「快速开始」里手写的那个
   llm_call ↔ tool_node 来回跳的图，本质就是 Agent 循环。本篇把它彻底讲透，
   再用 langchain V1 的现成封装 create_agent 一行拿到生产级循环。

⭐️ 把这张「循环」图刻进脑子（全篇地基）：
   ┌───────────────────────────────────────────────────────────┐
   │                                                            │
   │   用户提问                                                  │
   │      │                                                     │
   │      ▼                                                     │
   │   ┌─────────┐  发起 tool_calls   ┌──────────┐              │
   │   │  模型   │ ─────────────────▶ │  执行工具 │              │
   │   │ (思考)  │ ◀───────────────── │ (查库等) │              │
   │   └─────────┘   工具结果喂回去     └──────────┘              │
   │      │                                                     │
   │      │ 模型这次【不再发 tool_calls】＝想清楚了              │
   │      ▼                                                     │
   │   最终回答 → 结束                                           │
   └───────────────────────────────────────────────────────────┘

⭐️ 全篇最重要的两个认知：
   1) 「循环靠什么停」：模型这一轮回复里【没有 tool_calls】就停。不是你写死几次，
      是模型自己判断「我够了，可以回答了」。所以必须有「兜底上限」防它停不下来（第08节）。
   2) 「工具就是 Agent 的手脚」：模型只会说话，真正去查订单/查库存/写工单的是工具。
      工具底层就是普通函数（这里直接连真实 Postgres，见 provider/ecommerce.py）。

──────────────────────────────────────────────────────────────────
⭐️ 全篇 API 速记（本机 langgraph==1.2.4 / langchain==1.3.6，全部实测可跑）：

   现成封装（生产首选）：
     from langchain.agents import create_agent     # ⭐️ V1 正确入口
     agent = create_agent(model=glm_model, tools=[...], system_prompt="...")
     agent.invoke({"messages": [("user", "...")]})         # 跑完整循环
     agent.stream({...}, stream_mode="updates")            # 看每一步

   注意：from langgraph.prebuilt import create_react_agent 是【旧名】，
        V1.0 起已废弃（会有 Deprecation 警告），新代码一律用 create_agent。

   防失控：     agent.invoke(input, {"recursion_limit": N})  # 超了抛 GraphRecursionError
   结构化输出： create_agent(..., response_format=PydanticModel)
              → out["structured_response"] 是结构化对象
   手写循环：   model.bind_tools([...]) + while 循环 + ToolMessage（第02节，看清本质）

──────────────────────────────────────────────────────────────────
⭐️ 重要程度图例（最多 5 颗 ⭐️，按「企业实战 + 学习性价比」综合打分）：
  ⭐️⭐️⭐️⭐️⭐️ 必懂：核心认知 / 几乎天天用
  ⭐️⭐️⭐️⭐️   重点：生产高频刚需，要会写
  ⭐️⭐️⭐️     常用：会遇到，要能看懂会改
  ⭐️⭐️       了解：知道有这回事即可
  ⭐️         边角：特定场景再深入

各小节速查（直接运行会从上到下依次演示，会真连 Postgres、真调 GLM）：
  01 心智模型：循环是什么、靠什么停 ........ ⭐️⭐️⭐️⭐️⭐️  全篇地基
  02 手写最小循环（看清本质，不靠框架）.... ⭐️⭐️⭐️⭐️    理解原理必看
  03 create_agent：一行拿到生产级循环 ..... ⭐️⭐️⭐️⭐️⭐️  生产首选写法
  04 看清循环的每一步（stream updates）.... ⭐️⭐️⭐️⭐️    调试/可观测刚需
  05 工具 = 接真实业务库 .................. ⭐️⭐️⭐️⭐️⭐️  Agent 落地核心
  06 多步推理：一题串起多次工具调用 ........ ⭐️⭐️⭐️⭐️    循环的威力所在
  07 自我纠错：工具报错后自己改正 .......... ⭐️⭐️⭐️⭐️    循环的鲁棒性
  08 防失控：recursion_limit（必设）....... ⭐️⭐️⭐️⭐️⭐️  生产安全线
  09 结构化输出 response_format ........... ⭐️⭐️⭐️      对接下游系统
  10 生产建议 + 手写 vs create_agent ...... ⭐️⭐️⭐️⭐️    选型与认知收口
──────────────────────────────────────────────────────────────────
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# ⭐️ 直接 `python 官方文档/agent循环/agent循环.py` 运行时，把项目根加入 sys.path，
#    才能 import 到本项目的 provider（glm_model / 电商业务库）。
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from langchain.agents import create_agent
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from provider import glm_model  # 本项目封装的智谱 GLM
from provider import ecommerce  # 电商业务库（真实 Postgres）


def banner(title: str):
    print("\n" + "═" * 64)
    print("▶", title)
    print("═" * 64)


# ═════════════════════════════════════════════════════════════
# 工具定义：Agent 的「手脚」。底层直接调 provider/ecommerce.py 查真实 Postgres。
# ⭐️ 三要素决定模型用不用得对：① 函数名 ② docstring（功能说明）③ 参数类型注解。
#    模型只看这三样来决定「该不该调、调哪个、传什么参数」。写清楚 docstring 至关重要。
# ═════════════════════════════════════════════════════════════

@tool
def query_order(order_id: str) -> str:
    """根据订单号查询订单详情（含状态、金额、商品、下单时间）。
    当用户问「我的订单怎么样了/什么状态/买了什么」时使用。"""
    o = ecommerce.get_order(order_id)
    return str(o) if o else f"未找到订单 {order_id}，请用户核对订单号是否正确。"


@tool
def query_logistics(order_id: str) -> str:
    """根据订单号查询物流轨迹（承运商、运单号、最新位置）。
    当用户问「我的快递到哪了/物流/什么时候到」时使用。"""
    lg = ecommerce.get_logistics(order_id)
    return str(lg) if lg else f"订单 {order_id} 暂无物流信息（可能还未发货）。"


@tool
def search_product(keyword: str) -> str:
    """按关键词搜索商品（返回名称、SKU、价格、库存）。
    当用户问「有没有XX卖/XX多少钱/XX还有货吗」时使用。"""
    items = ecommerce.search_products(keyword)
    return str(items) if items else f"没有搜到包含「{keyword}」的商品。"


@tool
def check_stock(sku: str) -> str:
    """根据商品 SKU 查询库存数量。当需要确认某个具体商品是否有货时使用。"""
    p = ecommerce.get_product(sku)
    if not p:
        return f"未找到商品 {sku}。"
    return f"{p['name']}（{sku}）当前库存 {p['stock']} 件，单价 {p['price']} 元。"


ALL_TOOLS = [query_order, query_logistics, search_product, check_stock]


# ═════════════════════════════════════════════════════════════
# 01. 心智模型：循环是什么、靠什么停          【⭐️⭐️⭐️⭐️⭐️ 全篇地基】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 别把 Agent 想得太玄。它就是一个 while 循环：
#      while 模型还想调工具:
#          调模型 → 拿到它要调的工具 → 执行工具 → 把结果塞回对话 → 再调模型
#      模型这一轮不调工具了 → 跳出循环 → 它的话就是最终答案
# ⭐️ 关键：「停」是模型自己决定的（它觉得信息够了就直接回答，不再发 tool_calls）。
#    这带来一个风险：万一它一直要调工具停不下来？→ 所以生产必须设上限（第08节）。
# 本节是地图，不跑代码。第02节用最朴素的 while 把这个循环亲手写出来给你看。


# ═════════════════════════════════════════════════════════════
# 02. 手写最小循环（看清本质，不靠框架）        【⭐️⭐️⭐️⭐️ 理解原理必看】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 不用任何 Agent 框架，纯手写。看完这段，你就彻底懂了「框架到底替你干了啥」。
#    步骤：bind_tools 让模型知道有哪些工具 → 循环里反复 invoke → 有 tool_calls 就执行
#    并把 ToolMessage 塞回 messages → 没有 tool_calls 就 break。

def demo_handwritten_loop():
    model_with_tools = glm_model.bind_tools(ALL_TOOLS)        # ⭐️ 把工具「告诉」模型
    tools_by_name = {t.name: t for t in ALL_TOOLS}            # 名字 → 工具，方便查表执行

    messages = [
        SystemMessage("你是电商客服，必须先用工具查到真实数据再回答，不要编造。"),
        HumanMessage("订单 SO20250601001 现在到哪了？"),
    ]

    for step in range(1, 6):                                  # ⭐️ range(1,6) 就是「兜底上限」=最多 5 圈
        ai = model_with_tools.invoke(messages)                # 调模型：让它思考这一步
        messages.append(ai)

        if not ai.tool_calls:                                 # ⭐️ 模型不调工具了 → 循环结束
            print(f"第{step}圈：模型给出最终答案 → {ai.content[:60].strip()}…")
            break

        # 模型要调工具：可能一次调多个，逐个执行，结果用 ToolMessage 塞回去
        for tc in ai.tool_calls:
            print(f"第{step}圈：模型决定调用工具 {tc['name']}({tc['args']})")
            observation = tools_by_name[tc["name"]].invoke(tc["args"])
            messages.append(ToolMessage(observation, tool_call_id=tc["id"]))
    print("⭐️ 看到没——框架(create_agent)替你做的，就是上面这个 while 循环。")


# ═════════════════════════════════════════════════════════════
# 03. create_agent：一行拿到生产级循环         【⭐️⭐️⭐️⭐️⭐️ 生产首选】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 第02节那段 while，生产里没人手写——langchain V1 的 create_agent 一行就给你
#    一个【编译好的循环图】，自带：并行工具调用、消息管理、错误处理、可挂 checkpointer。
# ⭐️ 三个核心参数：model（哪个模型）、tools（手脚）、system_prompt（人设/规则）。
# ⭐️ 输入输出和你熟悉的图一样：invoke({"messages":[...]})，结果在 out["messages"][-1]。

def build_cs_agent():
    """构建一个电商客服 Agent（后面好几节都复用它）。"""
    return create_agent(
        model=glm_model,
        tools=ALL_TOOLS,
        system_prompt=(
            "你是「静界数码」的电商客服。"
            "回答订单、物流、商品库存问题前，必须先调用对应工具查到真实数据，严禁编造。"
            "查不到就如实告知并请用户核对信息。回答简洁、口语化。"
        ),
    )


def demo_create_agent():
    agent = build_cs_agent()
    out = agent.invoke({"messages": [("user", "订单 SO20250601001 现在什么状态？")]})
    print("最终回答：", out["messages"][-1].content.strip()[:80])
    print(f"⭐️ 整段对话共 {len(out['messages'])} 条消息"
          "（用户→AI要调工具→工具结果→AI最终回答），循环全在 invoke 内部跑完了。")


# ═════════════════════════════════════════════════════════════
# 04. 看清循环的每一步（stream updates）        【⭐️⭐️⭐️⭐️ 可观测刚需】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ invoke 是「跑完给结果」，看不到中间过程。生产里排查「Agent 为啥这么答」，
#    要用 stream(stream_mode="updates")：每个节点跑完 yield 一次，
#    key="model" 是模型思考的那步，key="tools" 是执行工具的那步。
#    （create_agent 里模型节点就叫 "model"，工具节点叫 "tools"，可用 agent.get_graph() 看。）
# ⭐️ 这就是把第02节 print 的「第几圈调了啥」用框架的方式看出来。

def demo_stream_steps():
    agent = build_cs_agent()
    print("一步一步看 Agent 循环（updates 流）：")
    for chunk in agent.stream(
        {"messages": [("user", "SO20250601001 这个订单的快递到哪了？")]},
        stream_mode="updates",
    ):
        for node_name, payload in chunk.items():
            last = payload["messages"][-1]
            if node_name == "model" and last.tool_calls:
                calls = [tc["name"] for tc in last.tool_calls]
                print(f"  🧠 [模型] 决定调用工具：{calls}")
            elif node_name == "model":
                print(f"  ✅ [模型] 给出最终答案：{last.content[:50].strip()}…")
            elif node_name == "tools":
                print(f"  🔧 [工具] 返回：{str(last.content)[:50]}…")


# ═════════════════════════════════════════════════════════════
# 05. 工具 = 接真实业务库                       【⭐️⭐️⭐️⭐️⭐️ 落地核心】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 给同一个 Agent 配【多个】工具（订单/物流/商品/库存），它会【自己挑】该用哪个。
#    挑的依据就是每个工具的 docstring。这就是真实客服 Agent 的样子。
# ⭐️ 下面问三个不同领域的问题，观察它分别选了不同的工具。

def demo_tools_real_db():
    agent = build_cs_agent()
    for q in [
        "你们还有降噪耳机卖吗？多少钱？",     # → search_product
        "SKU-EARBUDS-02 还有货吗？",          # → check_stock（这个是缺货品）
    ]:
        out = agent.invoke({"messages": [("user", q)]})
        print(f"问：{q}")
        print(f"答：{out['messages'][-1].content.strip()[:90]}\n")


# ═════════════════════════════════════════════════════════════
# 06. 多步推理：一题串起多次工具调用            【⭐️⭐️⭐️⭐️ 循环的威力】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 循环真正的威力：一个问题需要【连环查】时，Agent 会自动多跑几圈。
#    例：「我那单耳机想再买一个，还有货吗」——
#       第1圈：查订单 SO20250601001 → 拿到 sku=SKU-EARBUDS-01
#       第2圈：用这个 sku 查库存
#       第3圈：综合两步结果回答
#    你不用写任何 if/else 编排，循环 + 工具的 docstring 让它自己串起来。

def demo_multi_step():
    agent = build_cs_agent()
    out = agent.invoke({
        "messages": [("user",
            "我之前下的订单 SO20250601001 买的那款耳机，我想再下一单，现在还有货吗？")]
    })
    # 数一下它调了几次工具，证明是「多步」
    tool_steps = sum(
        1 for m in out["messages"]
        if getattr(m, "tool_calls", None)
    )
    print(f"⭐️ 这一题 Agent 触发了 {tool_steps} 轮工具调用（先查订单拿SKU，再查库存）")
    print("最终回答：", out["messages"][-1].content.strip()[:100])


# ═════════════════════════════════════════════════════════════
# 07. 自我纠错：工具报错后自己改正              【⭐️⭐️⭐️⭐️ 循环的鲁棒性】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 循环让 Agent 有了「试错」能力：工具返回「没找到」时，结果会喂回模型，
#    模型下一圈能据此改正（换个查法 / 向用户追问），而不是直接崩。
# ⭐️ 这里故意给一个【不存在的订单号】，看 Agent 如何处理「查不到」。
#    工具返回的是「未找到，请核对」——模型会把这个信息转达给用户，而不是瞎编状态。

def demo_self_correct():
    agent = build_cs_agent()
    out = agent.invoke({"messages": [("user", "查一下我的订单 SO99999999 到哪了")]})
    print("（订单号不存在时）Agent 回答：")
    print("  ", out["messages"][-1].content.strip()[:100])
    print("⭐️ 注意它没有编造状态，而是如实说查不到——因为工具把『未找到』喂回了循环。")


# ═════════════════════════════════════════════════════════════
# 08. 防失控：recursion_limit（必设）           【⭐️⭐️⭐️⭐️⭐️ 生产安全线】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 既然「停」由模型决定，万一它陷入「反复调工具」停不下来，会烧光 token / 卡死。
#    LangGraph 给每条执行设了 recursion_limit（默认 25）：超过这么多「步」还没结束就
#    抛 GraphRecursionError。这是生产【必须显式设、并 try 住】的安全线。
# ⭐️ 注意单位是「图的超步数」，不完全等于「工具调用次数」（agent节点、tools节点各算一步）。
#    这里给一个需要多步的任务，把上限压到很低，故意触发异常给你看。

def demo_recursion_limit():
    agent = build_cs_agent()
    hard_question = ("把订单 SO20250601001、SO20250528002、SO20250610003 "
                     "三个的状态和物流都查出来逐一对比")
    try:
        agent.invoke({"messages": [("user", hard_question)]}, {"recursion_limit": 3})
        print("（本次未触发上限）")
    except GraphRecursionError as e:
        print("✅ 成功触发安全线 GraphRecursionError：")
        print("  ", str(e)[:90])
        print("⭐️ 生产做法：设一个合理上限（如 25~50），用 try 兜住，"
              "超限就转人工或给降级回复，绝不让它无限跑。")


# ═════════════════════════════════════════════════════════════
# 09. 结构化输出 response_format               【⭐️⭐️⭐️ 对接下游系统】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 前面 Agent 都吐「一段自然语言」。但很多时候下游是【程序】不是人：要把
#    Agent 的结论塞进工单系统、数据库、前端卡片——这就需要【结构化输出】。
# ⭐️ 做法：定义一个 Pydantic 模型描述你要的字段，传 response_format=该模型。
#    循环正常跑（照样查库），收尾时模型按这个 schema 输出，结果在 out["structured_response"]。

class OrderTriage(BaseModel):
    """对用户订单咨询的结构化研判结果（给工单系统用）。"""
    order_id: str = Field(description="用户咨询的订单号")
    order_status: str = Field(description="订单当前状态")
    intent: str = Field(description="用户意图，如 查物流/退货/咨询")
    need_human: bool = Field(description="是否需要转人工处理")


def demo_structured_output():
    agent = create_agent(
        model=glm_model,
        tools=ALL_TOOLS,
        system_prompt="你是电商客服，先查工具拿到真实数据，再按要求输出研判结果。",
        response_format=OrderTriage,          # ⭐️ 关键：声明结构化输出 schema
    )
    out = agent.invoke({
        "messages": [("user", "我订单 SO20250601001 的耳机有杂音，想退货")]
    })
    result: OrderTriage = out["structured_response"]   # ⭐️ 结构化结果在这里
    print("结构化研判结果（可直接落库/进工单系统）：")
    print(f"   订单号   : {result.order_id}")
    print(f"   订单状态 : {result.order_status}")
    print(f"   用户意图 : {result.intent}")
    print(f"   需转人工 : {result.need_human}")


# ═════════════════════════════════════════════════════════════
# 10. 生产建议 + 手写 vs create_agent          【⭐️⭐️⭐️⭐️ 认知收口】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 手写循环（第02节） vs create_agent（第03节）对比：
#    ┌──────────────┬───────────────────────┬──────────────────────────┐
#    │              │ 手写 while 循环        │ create_agent              │
#    ├──────────────┼───────────────────────┼──────────────────────────┤
#    │ 价值         │ 看清原理、完全可控      │ 生产首选，省掉一堆样板     │
#    │ 并行工具调用  │ 要自己写               │ 内置                      │
#    │ 错误/重试     │ 要自己 try            │ 可配（配合容错那篇）       │
#    │ 持久化/记忆   │ 要自己接 checkpointer │ checkpointer=… 一参搞定    │
#    │ 中断/人工介入 │ 要自己实现            │ interrupt_before/after    │
#    │ 何时用        │ 学习 / 特殊定制流程    │ 99% 的业务 Agent          │
#    └──────────────┴───────────────────────┴──────────────────────────┘
#
# ⭐️ 生产落地清单：
#    1) 一律用 create_agent（create_react_agent 是旧名，已废弃）。
#    2) recursion_limit 必设 + try GraphRecursionError 兜底（第08节）。
#    3) 工具的 docstring 写清楚——模型挑工具全靠它，这比调 prompt 还重要。
#    4) 要记住多轮对话 → create_agent(..., checkpointer=PostgresSaver)（见「记忆.py」）。
#    5) 要对接下游程序 → response_format 结构化输出（第09节）。
#    6) 单个 Agent 工具太多/职责太杂时 → 拆成多个 Agent 协作（见「多智能体.py」）。

def demo_production_note():
    print("Agent 循环生产清单：")
    print("  1) 用 create_agent（不要再用废弃的 create_react_agent）")
    print("  2) recursion_limit 必设 + try GraphRecursionError")
    print("  3) 工具 docstring 写清楚（模型挑工具的唯一依据）")
    print("  4) 多轮记忆 → 挂 checkpointer；下游对接 → response_format")
    print("  5) 职责太杂 → 拆多 Agent（见 多智能体.py）")


# ⭐️ 模块级图：供 langgraph.json 注册，可在 langgraph dev / studio 里打开调试。
#    （平台自带持久化，这里不挂 checkpointer。）
agent = build_cs_agent()


# ═════════════════════════════════════════════════════════════
# 主入口：从上到下依次演示（会真连 Postgres、真调 GLM）
#
# 运行前确保业务库已就绪（幂等，可先单独跑一次）：
#   python provider/ecommerce.py
# 然后：
#   python 官方文档/agent循环/agent循环.py
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ecommerce.seed_all()  # ⭐️ 确保业务库有数据（幂等）

    banner("02 手写最小循环（看清『模型↔工具』反复的本质）")
    demo_handwritten_loop()

    banner("03 create_agent：一行拿到生产级循环")
    demo_create_agent()

    banner("04 看清循环的每一步（stream_mode='updates'）")
    demo_stream_steps()

    banner("05 工具 = 接真实业务库（Agent 自己挑用哪个工具）")
    demo_tools_real_db()

    banner("06 多步推理（一题自动串起多次工具调用）")
    demo_multi_step()

    banner("07 自我纠错（工具返回『查不到』后，Agent 如实转达不编造）")
    demo_self_correct()

    banner("08 防失控 recursion_limit（故意触发 GraphRecursionError）")
    demo_recursion_limit()

    banner("09 结构化输出 response_format（吐出可落库的结构化结果）")
    demo_structured_output()

    banner("10 生产建议 + 手写 vs create_agent")
    demo_production_note()
