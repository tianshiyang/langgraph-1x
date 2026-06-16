"""
LangGraph 人机交互 (Human-in-the-loop / Interrupts) — 完整教程
================================================================

⭐️ 一句话理解：在图「跑到一半」的任意位置，主动按下暂停键，把当前情况
   抛给人类，等人点了「同意 / 改一下 / 重填」之后，再从暂停的地方继续跑。

⭐️ 这就是 Agent 时代最关键的一块拼图——LLM 不可全信，凡是「会花钱、会删库、
   会对外发消息、会签合同」的动作，上线前几乎都要卡一道人工闸门。
   interrupt() 就是这道闸门的官方实现。

⭐️ 它和「持久化」是连体婴：interrupt 暂停时，靠 checkpointer 把状态存盘；
   人类几小时后回来点同意，靠同一个 thread_id 把状态捞回来接着跑。
   ——所以：没配 checkpointer，interrupt 直接报错。先吃透「持久化.py」再看这篇。

──────────────────────────────────────────────────────────────────
⭐️ 先建立最重要的心智模型（理解了这张图，80% 的坑都不会踩）：

   第一次执行                          人类回来后 resume
   ┌─────────────┐                    ┌─────────────────────┐
   │ graph.stream│                    │ graph.stream(        │
   │  (输入, cfg)│                    │   Command(resume=X), │
   └──────┬──────┘                    │   cfg)  ← 同一thread │
          │                           └──────────┬──────────┘
          ▼                                      ▼
   ...跑到某节点...                        ⚠️ 整个节点【从头重跑】！
          │                              （不是从 interrupt 那行继续）
     interrupt(问题)                            │
          │                              ...又跑到 interrupt(问题)...
          │ 抛 GraphInterrupt 异常               │
          │ 状态存盘、暂停                  这一次 interrupt() 不再抛异常，
          ▼                              而是【直接返回 X】，节点继续往下跑
   返回给你:                                     │
   {'__interrupt__':                             ▼
     (Interrupt(value=问题, id=...),)}      节点正常 return，图继续

⭐️ 全篇你只需要记住三件事：
   1) 在节点里写 answer = interrupt(要问人类的东西)
   2) 第一次跑到这里 → 图暂停，把「要问人类的东西」吐给你
   3) 用 Command(resume=人类的答案) 再 stream 一次 → 节点【从头重跑】，
      这次 interrupt() 返回「人类的答案」，图继续

⭐️ 第 3 步的「从头重跑」是头号大坑（第 09 节专门讲）：
   interrupt() 上面的代码会再执行一遍。所以「扣款 / 写库 / 发消息」这类
   副作用，绝对不能放在 interrupt() 上面，否则会执行两次。

参考文档（本教程严格对照官网，并基于本机已装版本逐条实测）：
  - https://docs.langchain.com/oss/python/langgraph/interrupts
  （本项目 langgraph==1.2.4 / langchain==1.3.6 / Python 3.13，下列 API 全部实测可跑）

──────────────────────────────────────────────────────────────────
⭐️ 企业实战优先级图例（每个小节标题都标了等级）：

  ⭐️⭐️⭐️ 企业核心：做带审批/审核的 Agent 必用，必须吃透
  ⭐️⭐️   企业常用：重要认知或某类场景要用，要懂
  ⭐️     了解即可：偏调试 / 边角场景

各小节速查：
  01 interrupt + Command(resume) 基础 .. ⭐️⭐️⭐️  整篇地基，必须先跑通
  02 模式一：审批 / 拒绝 ................. ⭐️⭐️⭐️  最高频企业场景
  03 模式二：审查并编辑内容 .............. ⭐️⭐️⭐️  LLM 产出物的人工把关
  04 模式三：审查工具调用 (把闸门放进工具) . ⭐️⭐️⭐️  Agent 时代核心姿势
  05 模式四：校验输入（重问循环） ......... ⭐️⭐️    表单/参数收集
  06 多轮收集（一个节点问多个问题） ....... ⭐️⭐️    工单/资料收集
  07 并行分支同时 interrupt（按 id 恢复） .. ⭐️      多人会签等高级场景
  08 怎么查「当前卡在哪、在等什么」........ ⭐️⭐️    前端/运维必备
  09 头号大坑：节点从头重跑 + 副作用幂等 ... ⭐️⭐️⭐️  不懂必出生产事故
  10 其余四个坑（异常/顺序/序列化/子图） ... ⭐️⭐️    踩一次记一辈子
  11 静态断点 interrupt_before/after ..... ⭐️       仅调试，生产基本不用
──────────────────────────────────────────────────────────────────
"""

import uuid
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

# 加载根目录 .env（GLM / 千问 Key、PostgreSQL 连接串等，与其他教程统一）
load_dotenv(Path(__file__).parent.parent.parent / ".env")


# ═════════════════════════════════════════════════════════════
# 01. interrupt + Command(resume) 基础      【⭐️⭐️⭐️ 整篇地基】
# ═════════════════════════════════════════════════════════════

class BasicState(TypedDict):
    foo: str
    human_value: Optional[str]  # 这个字段将由人类通过 interrupt 填进来


def basic_node(state: BasicState):
    # ⭐️ interrupt(value)：value 会被原样吐给「调用图的那一方」（你/前端）
    #    第一次执行：抛 GraphInterrupt，图暂停。
    #    resume 后重跑到这里：interrupt() 直接返回 Command(resume=...) 里的值。
    answer = interrupt("请问你的年龄是多少？")
    print(f"  [节点内] 收到人类输入: {answer}")
    return {"human_value": answer}


def demo_basic():
    """
    ⭐️ 跑通这一个例子，整篇就懂一大半了。盯住三处输出：
       1) 第一次 stream → 吐出 {'__interrupt__': (Interrupt(value='...', id='...'),)}
          注意：节点里的 print 还【没打印】，因为根本没跑到那行就暂停了。
       2) Command(resume=...) 再 stream → 节点【从头重跑】，
          这次 interrupt() 返回了 18，节点 print 出来，正常 return。

    ⭐️ 三个硬性前提（缺一报错）：
       - compile 时必须传 checkpointer（interrupt 靠它存盘）
       - 执行时必须带 thread_id（resume 靠它找回同一份状态）
       - 恢复用的输入必须是 Command(resume=...)，不能再传原始输入
    """
    builder = StateGraph(BasicState)
    builder.add_node("basic_node", basic_node)
    builder.add_edge(START, "basic_node")
    builder.add_edge("basic_node", END)

    # ⭐️ 开发用 InMemorySaver；生产换 PostgresSaver（见「持久化.py」第 07 节）
    graph = builder.compile(checkpointer=InMemorySaver())

    # ⭐️ thread_id 是这次会话的唯一标识，resume 时必须用同一个
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("=== 01. 基础：第一次执行（会暂停）===")
    for chunk in graph.stream({"foo": "abc"}, config):
        print(" ", chunk)
        # 这里会看到: {'__interrupt__': (Interrupt(value='请问你的年龄是多少？', id='...'),)}

    print("--- 模拟人类回来了，回答 18，resume ---")
    # ⭐️ 关键：用 Command(resume=值) 恢复。值就是 interrupt() 的返回值。
    for chunk in graph.stream(Command(resume=18), config):
        print(" ", chunk)
        # {'basic_node': {'human_value': 18}}


# ═════════════════════════════════════════════════════════════
# 02. 模式一：审批 / 拒绝 (approve / reject)   【⭐️⭐️⭐️ 最高频】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：退款审批、大额转账、删除生产数据、给客户群发邮件……
#   LLM/流程跑到「危险动作」前停下，把动作详情抛给人，
#   人点「同意」就执行，点「拒绝」就走另一条路。
#
# ⭐️ 关键技巧：节点返回 Command(goto=...)，用人类的答案决定走哪个分支。
#    这就是 interrupt 和「条件路由」结合的经典姿势。

class RefundState(TypedDict):
    order_id: str
    amount: float
    result: str


def approve_refund(state: RefundState) -> Command[Literal["do_refund", "reject_refund"]]:
    # ⭐️ value 用 dict，把人类做决定所需的信息一次性给全（前端好渲染审批卡片）
    decision = interrupt({
        "type": "refund_approval",
        "question": "是否批准这笔退款？",
        "order_id": state["order_id"],
        "amount": state["amount"],
    })
    # decision 是人类传回来的值（这里约定传 True/False）
    if decision is True:
        return Command(goto="do_refund")
    return Command(goto="reject_refund")


def do_refund(state: RefundState):
    # ⭐️ 真正的扣款/退款放在这个【独立节点】里——这样它永远在 interrupt 之后，
    #    绝不会因为「节点从头重跑」而执行两遍（第 09 节细讲）。
    print(f"  [执行] 已退款 ¥{state['amount']} 给订单 {state['order_id']}")
    return {"result": f"refunded:{state['amount']}"}


def reject_refund(state: RefundState):
    print(f"  [执行] 退款被拒绝，订单 {state['order_id']}")
    return {"result": "rejected"}


def build_refund_graph():
    builder = StateGraph(RefundState)
    builder.add_node("approve_refund", approve_refund)
    builder.add_node("do_refund", do_refund)
    builder.add_node("reject_refund", reject_refund)
    builder.add_edge(START, "approve_refund")
    builder.add_edge("do_refund", END)
    builder.add_edge("reject_refund", END)
    return builder.compile(checkpointer=InMemorySaver())


def demo_approve_reject():
    """⭐️ 演示同一套图，分别走「同意」和「拒绝」两条路。"""
    graph = build_refund_graph()

    print("=== 02. 审批通过 ===")
    cfg_a: RunnableConfig = {"configurable": {"thread_id": "refund-approve"}}
    for chunk in graph.stream({"order_id": "A001", "amount": 99.0}, cfg_a):
        print(" ", chunk)  # 暂停，吐出审批卡片
    # ⭐️ 同意：resume=True
    for chunk in graph.stream(Command(resume=True), cfg_a):
        print(" ", chunk)

    print("=== 02. 审批拒绝 ===")
    cfg_r: RunnableConfig = {"configurable": {"thread_id": "refund-reject"}}
    for _ in graph.stream({"order_id": "A002", "amount": 8888.0}, cfg_r):
        pass
    # ⭐️ 拒绝：resume=False
    for chunk in graph.stream(Command(resume=False), cfg_r):
        print(" ", chunk)


# ═════════════════════════════════════════════════════════════
# 03. 模式二：审查并编辑内容 (review & edit)   【⭐️⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：LLM 生成了营销文案 / 合同条款 / 周报 / 客服回复草稿，
#   不直接发出去，先给人看，人可以「原样通过」或「改两句再通过」，
#   把人改后的版本写回 state，再继续。
#
# ⭐️ 和模式一的区别：模式一 resume 一个布尔决定走向；
#    这里 resume 一个【人类编辑后的内容】，直接覆盖原内容。

class DraftState(TypedDict):
    topic: str
    draft: str        # LLM 生成的草稿
    final: str        # 人工定稿


def generate_draft(state: DraftState):
    # 真实项目这里会调 glm_model 生成。为保证 demo 离线可跑，这里写死。
    # 想接真模型：from provider import glm_model; draft = glm_model.invoke(...).content
    draft = f"【关于「{state['topic']}」的推广文案】立即下单享 5 折，错过等一年！"
    return {"draft": draft}


def human_review_draft(state: DraftState):
    # ⭐️ 把 LLM 草稿抛给人，请人 review。人 resume 回来的就是定稿内容。
    edited = interrupt({
        "type": "review_draft",
        "instruction": "请审阅这段文案，可直接修改后提交",
        "draft": state["draft"],
    })
    # ⭐️ 人改完的内容写回 state（若人原样通过，edited 就等于原 draft）
    return {"final": edited}


def publish(state: DraftState):
    print(f"  [发布] {state['final']}")
    return {}


def demo_review_edit():
    """⭐️ LLM 生成草稿 → 人工润色 → 发布。"""
    builder = StateGraph(DraftState)
    builder.add_node("generate_draft", generate_draft)
    builder.add_node("human_review_draft", human_review_draft)
    builder.add_node("publish", publish)
    builder.add_edge(START, "generate_draft")
    builder.add_edge("generate_draft", "human_review_draft")
    builder.add_edge("human_review_draft", "publish")
    builder.add_edge("publish", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "draft-1"}}
    print("=== 03. 审查并编辑 ===")
    for chunk in graph.stream({"topic": "夏季大促"}, cfg):
        print(" ", chunk)  # 会先打印 generate_draft 的产出，再暂停在 review

    # ⭐️ 人觉得太浮夸，改得克制一点，再提交
    edited_text = "【夏季大促】精选好物 5 折起，欢迎选购。"
    for chunk in graph.stream(Command(resume=edited_text), cfg):
        print(" ", chunk)


# ═════════════════════════════════════════════════════════════
# 04. 模式三：审查工具调用 (interrupt 放进工具里)  【⭐️⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# 这是 Agent 时代最该掌握的姿势。
#
# ⭐️ 核心思想：interrupt() 不一定写在「图节点」里，它可以直接写在【工具函数】里。
#    这样，无论哪张图、哪个 Agent 用了这个 send_email 工具，
#    「发邮件前必须人工批」这条规则都自动带着走——闸门跟着工具走，而不是跟着图走。
#
# 企业场景：Agent 自主决定要「发邮件 / 下单 / 调用付费 API / 改数据库」，
#   在工具真正动手前停下，把「准备调用的参数」抛给人，
#   人可以「批准」「带修改地批准」或「取消」。

def send_email_tool(to: str, subject: str, body: str) -> str:
    """
    一个「带人工审批闸门」的发邮件工具（这里用普通函数演示其内部逻辑；
    真实项目中给它套上 @tool 装饰、交给 create_react_agent 即可，闸门照样生效）。

    ⭐️ 重点看 interrupt 的 value 和 resume 的结构：
       - value：把「即将发送的邮件」全文抛给人审
       - resume：人传回 {"action": "approve"/"edit"/"reject", 可带修改后的字段}
    """
    response = interrupt({
        "type": "tool_review",
        "action": "send_email",
        "message": "Agent 准备发送这封邮件，请审批",
        "to": to,
        "subject": subject,
        "body": body,
    })

    action = response.get("action")
    if action == "reject":
        return "用户取消了发送"

    # ⭐️ approve / edit：允许人在审批时顺手改字段（没改的就用原值兜底）
    final_to = response.get("to", to)
    final_subject = response.get("subject", subject)
    final_body = response.get("body", body)
    print(f"  [发送] To={final_to} | 主题={final_subject} | 正文={final_body}")
    return f"邮件已发送给 {final_to}"


class EmailState(TypedDict):
    to: str
    subject: str
    body: str
    log: str


def agent_send_email(state: EmailState):
    """模拟 Agent 决定调用上面的工具。"""
    result = send_email_tool(state["to"], state["subject"], state["body"])
    return {"log": result}


def demo_review_tool_call():
    """⭐️ 工具内部的闸门：批准时还能顺手改主题。"""
    builder = StateGraph(EmailState)
    builder.add_node("agent_send_email", agent_send_email)
    builder.add_edge(START, "agent_send_email")
    builder.add_edge("agent_send_email", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "email-1"}}
    print("=== 04. 审查工具调用 ===")
    init = {"to": "client@corp.com", "subject": "报价", "body": "详见附件", "log": ""}
    for chunk in graph.stream(init, cfg):
        print(" ", chunk)  # 暂停，吐出待审邮件

    # ⭐️ 人：批准，但把主题改得更正式
    resume_value = {"action": "edit", "subject": "【正式报价单】贵司项目合作"}
    for chunk in graph.stream(Command(resume=resume_value), cfg):
        print(" ", chunk)


# ═════════════════════════════════════════════════════════════
# 05. 模式四：校验输入（重问循环）           【⭐️⭐️ 表单/参数】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：收集用户填的金额 / 年龄 / 手机号，格式不对就「在节点内反复重问」，
#   直到合法才放行。
#
# ⭐️ 关键：interrupt() 可以放在 while 循环里。校验不通过就再 interrupt 一次，
#    把「为什么错、请重填」作为新的提示抛给人。
#    ——这一切都在【同一个节点、同一次任务】里完成，无需多个节点。

class AgeState(TypedDict):
    age: Optional[int]


def collect_valid_age(state: AgeState):
    prompt = "请输入你的年龄（正整数）"
    while True:
        value = interrupt(prompt)
        # ⭐️ 校验：必须是正整数
        if isinstance(value, int) and value > 0:
            return {"age": value}
        # 不合法 → 更新提示，循环回去再次 interrupt
        prompt = f"输入 {value!r} 不合法，请重新输入一个正整数"


def demo_validate_input():
    """⭐️ 演示：先填非法值被打回，再填合法值通过。"""
    builder = StateGraph(AgeState)
    builder.add_node("collect_valid_age", collect_valid_age)
    builder.add_edge(START, "collect_valid_age")
    builder.add_edge("collect_valid_age", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "age-1"}}
    print("=== 05. 校验输入 ===")
    for chunk in graph.stream({"age": None}, cfg):
        print(" ", chunk)  # 第一次提问

    # ⭐️ 人填了字符串 "三十"，非法 → 节点会再 interrupt 一次（重问）
    for chunk in graph.stream(Command(resume="三十"), cfg):
        print(" ", chunk)  # 又吐出一个 interrupt：提示不合法

    # ⭐️ 人改填 30，合法 → 通过
    for chunk in graph.stream(Command(resume=30), cfg):
        print(" ", chunk)  # {'collect_valid_age': {'age': 30}}


# ═════════════════════════════════════════════════════════════
# 06. 多轮收集（一个节点问多个问题）         【⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：客服建工单，需要依次问「姓名 → 手机 → 问题描述」。
#
# ⭐️ 一个节点里可以连写多个 interrupt()。LangGraph 靠【调用顺序】把
#    每次 resume 的值，对应到第几个 interrupt。
# ⭐️⭐️ 重要：因为「节点从头重跑」，第二次 resume 时，第一个 interrupt 不会再问，
#    而是直接返回上一次你给的答案（LangGraph 记住了）；只有还没答的那个会暂停。
# ⚠️ 正因如此，多个 interrupt 的【顺序必须稳定】，不能这次问 3 个、下次问 2 个
#    （第 10 节细讲）。

class TicketState(TypedDict):
    name: Optional[str]
    phone: Optional[str]
    desc: Optional[str]


def collect_ticket(state: TicketState):
    name = interrupt("请问您的称呼？")
    phone = interrupt("请问您的联系电话？")
    desc = interrupt("请描述您遇到的问题")
    return {"name": name, "phone": phone, "desc": desc}


def demo_multi_collect():
    """⭐️ 一个节点收三项，每次 resume 推进一项。"""
    builder = StateGraph(TicketState)
    builder.add_node("collect_ticket", collect_ticket)
    builder.add_edge(START, "collect_ticket")
    builder.add_edge("collect_ticket", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "ticket-1"}}
    print("=== 06. 多轮收集 ===")
    for chunk in graph.stream({}, cfg):
        print(" ", chunk)  # 问：称呼

    for chunk in graph.stream(Command(resume="张三"), cfg):
        print(" ", chunk)  # 问：电话（注意：没有再问称呼）

    for chunk in graph.stream(Command(resume="13800138000"), cfg):
        print(" ", chunk)  # 问：问题描述

    for chunk in graph.stream(Command(resume="登录不上后台"), cfg):
        print(" ", chunk)  # 三项收齐，return


# ═════════════════════════════════════════════════════════════
# 07. 并行分支同时 interrupt（按 id 恢复）    【⭐️ 高级】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：一份合同同时需要「法务」和「财务」会签，两条分支并行各自停下等人。
#
# ⭐️ 此时一次 stream 会吐出【多个】Interrupt（各有不同的 id）。
#    恢复时，Command(resume=...) 传一个 {interrupt_id: 答案} 的字典，
#    LangGraph 按 id 把每个答案派发给对应的分支。

from operator import add  # noqa: E402
from typing import Annotated  # noqa: E402


class SignState(TypedDict):
    approvals: Annotated[list[str], add]  # reducer：两条分支的结果各自追加


def legal_sign(state: SignState):
    ans = interrupt({"role": "法务", "question": "法务是否会签？"})
    return {"approvals": [f"法务:{ans}"]}


def finance_sign(state: SignState):
    ans = interrupt({"role": "财务", "question": "财务是否会签？"})
    return {"approvals": [f"财务:{ans}"]}


def demo_parallel_interrupts():
    """⭐️ 两条分支并行 interrupt，一次性按 id 全部恢复。"""
    builder = StateGraph(SignState)
    builder.add_node("legal_sign", legal_sign)
    builder.add_node("finance_sign", finance_sign)
    # ⭐️ START 同时连到两个节点 → 并行执行
    builder.add_edge(START, "legal_sign")
    builder.add_edge(START, "finance_sign")
    builder.add_edge("legal_sign", END)
    builder.add_edge("finance_sign", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "sign-1"}}
    print("=== 07. 并行 interrupt ===")

    for chunk in graph.stream({"approvals": []}, cfg):
        print(" ", chunk)
    # ⚠️ 注意：并行的多个 interrupt 会分散在【不同的 stream 块】里，
    #    千万别用 interrupts = chunk["__interrupt__"] 去接（会被后一块覆盖，只剩一个）。
    # ⭐️ 最稳妥：暂停后用 get_state 把所有任务上挂起的 interrupt 一次性收齐。
    snapshot = graph.get_state(cfg)
    interrupts = [itr for task in snapshot.tasks for itr in task.interrupts]

    # ⭐️ 构造 {id: 答案} 字典，一次把两条分支都恢复
    answers = {item.id: "同意" for item in interrupts}
    for chunk in graph.stream(Command(resume=answers), cfg):
        print(" ", chunk)  # {'approvals': ['法务:同意', '财务:同意']} （顺序可能不同）


# ═════════════════════════════════════════════════════════════
# 08. 怎么查「当前卡在哪、在等什么」         【⭐️⭐️ 前端/运维必备】
# ═════════════════════════════════════════════════════════════
#
# 前端/后端需要知道：这个 thread 到底卡住了没？在问什么？好渲染审批界面。
#
# ⭐️ 两条路：
#   A) stream/invoke 的返回值里直接看 '__interrupt__' 键（上面一直在用）。
#   B) 任意时刻用 graph.get_state(config) 查状态快照：
#        - snapshot.next            → 接下来要跑的节点（非空说明还没结束）
#        - snapshot.interrupts      → 当前挂起的所有 Interrupt（1.x 提供）
#        - snapshot.tasks[i].interrupts → 每个待执行任务各自挂起的 interrupt
#      路 B 不需要重新 stream，特别适合「页面刷新后，重新拉取当前待办」。

def demo_inspect_state():
    """⭐️ 用 get_state 查看「卡在哪、在等什么」。"""
    builder = StateGraph(BasicState)
    builder.add_node("basic_node", basic_node)
    builder.add_edge(START, "basic_node")
    builder.add_edge("basic_node", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "inspect-1"}}
    print("=== 08. 查看挂起状态 ===")
    for _ in graph.stream({"foo": "x"}, cfg):
        pass  # 跑到暂停

    snapshot = graph.get_state(cfg)
    print("  接下来要跑的节点 next =", snapshot.next)            # ('basic_node',) 非空=没结束
    # ⭐️ 挂起的 interrupt（从 tasks 里取，最稳妥、跨版本通用）
    for task in snapshot.tasks:
        for itr in task.interrupts:
            print(f"  正在等待: id={itr.id} value={itr.value!r}")

    # 恢复，结束后 next 应为空
    for _ in graph.stream(Command(resume=20), cfg):
        pass
    print("  恢复后 next =", graph.get_state(cfg).next)  # () 空 = 跑完了


# ═════════════════════════════════════════════════════════════
# 09. 头号大坑：节点从头重跑 + 副作用幂等     【⭐️⭐️⭐️ 必懂】
# ═════════════════════════════════════════════════════════════
#
# ⭐️⭐️⭐️ 这是 interrupt 唯一一个「不懂就出生产事故」的点，务必刻进脑子：
#
#   resume 时，含 interrupt 的那个节点会【从函数第一行重新执行】，
#   不是从 interrupt 那一行继续。所以 interrupt() 上面的代码会跑两遍！
#
# ❌ 错误写法（扣款会执行两次！）：
#
#     def bad_node(state):
#         charge_credit_card(state["amount"])   # ← resume 后又跑一遍，扣两次钱！
#         ok = interrupt("确认支付？")
#         return {"ok": ok}
#
# ✅ 正确写法 1：把副作用放到 interrupt 之后
#
#     def ok_node(state):
#         ok = interrupt("确认支付？")
#         if ok:
#             charge_credit_card(state["amount"])  # 只在 resume 后跑一次
#         return {"ok": ok}
#
# ✅ 正确写法 2（推荐）：把副作用单独拆成 interrupt 之后的【独立节点】
#     ——就是第 02 节 do_refund 的做法。职责清晰，永不重复执行。
#
# ✅ 正确写法 3：副作用必须放前面时，做成【幂等】操作（如 upsert、带唯一键去重），
#     重跑也不会产生第二次实际效果。
#
# 下面用计数器直观演示「interrupt 上面的代码确实跑了两次」：

_side_effect_counter = {"count": 0}


class CounterState(TypedDict):
    done: bool


def node_with_side_effect(state: CounterState):
    # ⚠️ 故意放在 interrupt 前面，演示它会被执行两次
    _side_effect_counter["count"] += 1
    print(f"  [副作用] interrupt 之前的代码被执行了第 {_side_effect_counter['count']} 次")
    interrupt("随便确认一下")
    return {"done": True}


def demo_reexecution_pitfall():
    """⭐️ 实测：interrupt 上面的代码，第一次跑 + resume 重跑 = 共两次。"""
    _side_effect_counter["count"] = 0
    builder = StateGraph(CounterState)
    builder.add_node("node_with_side_effect", node_with_side_effect)
    builder.add_edge(START, "node_with_side_effect")
    builder.add_edge("node_with_side_effect", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "pitfall-1"}}
    print("=== 09. 节点从头重跑大坑 ===")
    for _ in graph.stream({"done": False}, cfg):
        pass  # 第 1 次执行副作用，然后暂停
    for _ in graph.stream(Command(resume=True), cfg):
        pass  # 从头重跑 → 第 2 次执行副作用！
    print(f"  → 结论：同一句副作用代码共执行了 {_side_effect_counter['count']} 次（这就是坑）")


# ═════════════════════════════════════════════════════════════
# 10. 其余四个坑（异常 / 顺序 / 序列化 / 子图） 【⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 坑 1：别用宽泛的 try/except 把 interrupt 吞掉
#    interrupt() 是靠【抛 GraphInterrupt 异常】来暂停的。
#    如果你在节点里写 try: ... except Exception: ...，会把这个信号也挡住，
#    图就暂停不了。
#    ❌  try: x = interrupt("..."); except Exception: x = None
#    ✅  interrupt 单独写，try/except 只包真正可能出错的业务代码，
#        且只 catch 具体异常（如 except NetworkError），别用裸 Exception。
#
# ⭐️ 坑 2：同一节点内多个 interrupt 的顺序/数量必须稳定
#    resume 的值是按「第几个 interrupt」对应的。若用 if 让 interrupt 时有时无、
#    或换顺序，重跑时对应关系就错乱了。
#    ❌  name = interrupt(...);  if cond: age = interrupt(...);  city = interrupt(...)
#    ✅  三个 interrupt 固定都在、固定顺序（见第 06 节）。
#        分支问答更稳的做法：拆成不同节点，用条件边路由。
#
# ⭐️ 坑 3：interrupt 的 value 必须可 JSON 序列化
#    它要存进 checkpointer、要传给前端。只能放 dict / list / str / 数字 / 布尔。
#    ❌  interrupt({"validator": some_function})   # 函数、类实例、DB连接都不行
#    ✅  interrupt({"question": "...", "fields": ["name", "email"]})
#
# ⭐️ 坑 4：子图里 interrupt，父节点也从头重跑
#    若父节点调用了子图、子图内部 interrupt，resume 时父节点【从头重跑】、
#    子图里 interrupt 之前的节点也会重跑。和第 09 节同源，副作用照样要小心。
#
# 下面只给「坑 1」配一个可运行的对照（其余三坑上面注释已说透）：

class SafeState(TypedDict):
    name: Optional[str]
    extra: Optional[str]


def safe_node(state: SafeState):
    # ✅ interrupt 独立成行，绝不放进 try
    name = interrupt("请输入姓名")

    # ✅ try 只包真正可能抛错的业务，且应 catch 具体异常（这里演示用）
    try:
        extra = {"a": 1}["a"]  # 假装是一次可能 KeyError 的取值
        extra = f"ok:{extra}"
    except KeyError:
        extra = "fallback"

    return {"name": name, "extra": extra}


def demo_exception_pitfall():
    """⭐️ 演示：interrupt 在 try 之外，照常能暂停/恢复。"""
    builder = StateGraph(SafeState)
    builder.add_node("safe_node", safe_node)
    builder.add_edge(START, "safe_node")
    builder.add_edge("safe_node", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg: RunnableConfig = {"configurable": {"thread_id": "safe-1"}}
    print("=== 10. 别吞掉 interrupt 异常 ===")
    for chunk in graph.stream({}, cfg):
        print(" ", chunk)  # 能正常暂停
    for chunk in graph.stream(Command(resume="李四"), cfg):
        print(" ", chunk)  # 正常恢复


# ═════════════════════════════════════════════════════════════
# 11. 静态断点 interrupt_before / interrupt_after  【⭐️ 仅调试】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 这是和 interrupt() 不同的另一套机制：编译时（或运行时）指定
#    「在某个节点【前/后】自动暂停」，像断点一样，主要用于【调试】。
# ⭐️ 和 interrupt() 的根本区别：
#    - interrupt()：动态、写在业务逻辑里、能携带数据问人、是生产 HITL 主力。
#    - 静态断点：固定卡在某节点前后、不携带数据、恢复时传 None 即可、主要调试用。
# ⭐️ 恢复方式也不同：静态断点用 graph.stream(None, cfg)（传 None，不是 Command）。

class DbgState(TypedDict):
    x: int


def step_a(state: DbgState):
    print("  [step_a] 执行")
    return {"x": state["x"] + 1}


def step_b(state: DbgState):
    print("  [step_b] 执行")
    return {"x": state["x"] * 10}


def demo_static_breakpoint():
    """⭐️ 在 step_b 之前自动暂停（断点），传 None 继续。"""
    builder = StateGraph(DbgState)
    builder.add_node("step_a", step_a)
    builder.add_node("step_b", step_b)
    builder.add_edge(START, "step_a")
    builder.add_edge("step_a", "step_b")
    builder.add_edge("step_b", END)

    # ⭐️ 编译时声明断点：在 step_b 之前停
    graph = builder.compile(
        checkpointer=InMemorySaver(),
        interrupt_before=["step_b"],
    )

    cfg: RunnableConfig = {"configurable": {"thread_id": "dbg-1"}}
    print("=== 11. 静态断点 ===")
    for chunk in graph.stream({"x": 1}, cfg):
        print(" ", chunk)  # 跑完 step_a 就停（step_b 还没跑）
    print("  当前 next =", graph.get_state(cfg).next)  # ('step_b',)

    # ⭐️ 静态断点恢复：传 None（不是 Command(resume=...)）
    for chunk in graph.stream(None, cfg):
        print(" ", chunk)


# ═════════════════════════════════════════════════════════════
# 主入口：按顺序跑一遍所有 demo
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    demo_basic()
    print()
    demo_approve_reject()
    print()
    demo_review_edit()
    print()
    demo_review_tool_call()
    print()
    demo_validate_input()
    print()
    demo_multi_collect()
    print()
    demo_parallel_interrupts()
    print()
    demo_inspect_state()
    print()
    demo_reexecution_pitfall()
    print()
    demo_exception_pitfall()
    print()
    demo_static_breakpoint()
