"""
LangGraph 人机交互 (Human-in-the-loop / Interrupts) — 完整教程（input 交互版）
==============================================================================

⭐️ 一句话理解：在图「跑到一半」的任意位置，主动按下暂停键，把当前情况
   抛给人类，等人点了「同意 / 改一下 / 重填」之后，再从暂停的地方继续跑。

⭐️ 这就是 Agent 时代最关键的一块拼图——LLM 不可全信，凡是「会花钱、会删库、
   会对外发消息、会签合同」的动作，上线前几乎都要卡一道人工闸门。
   interrupt() 就是这道闸门的官方实现。

⭐️ 它和「持久化」是连体婴：interrupt 暂停时，靠 checkpointer 把状态存盘；
   人类几小时后回来点同意，靠同一个 thread_id 把状态捞回来接着跑。
   ——所以：没配 checkpointer，interrupt 直接报错。先吃透「持久化.py」再看这篇。

★★★ 本文件是【input 交互版·极简】★★★
   每个 demo 都用最朴素的 input() 在终端问你，你输入的字符串【原样】
   塞回 Command(resume=...)，不做任何转换/校验。直接 `python 人机交互.py`，
   选一个场景，按提示打字即可亲手体验「图暂停 → 你输入 → 图继续」。

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

⭐️ 还有个实测要点（在通用驱动器里专门标了）：
   节点 resume 后若【立刻又 interrupt】（如校验重问、多轮收集下一问），
   get_state().next 会变成空 ()，但其实还在等人。所以「是否还在等输入」
   要看 tasks[*].interrupts（pending），不能看 next，否则会误判图跑完了。

参考文档（本教程严格对照官网，并基于本机已装版本逐条实测）：
  - https://docs.langchain.com/oss/python/langgraph/interrupts
  （本项目 langgraph==1.2.4 / langchain==1.3.6 / Python 3.13，下列 API 全部实测可跑）

──────────────────────────────────────────────────────────────────
⭐️ 企业实战优先级图例（每个小节标题都标了等级）：

  ⭐️⭐️⭐️ 企业核心：做带审批/审核的 Agent 必用，必须吃透
  ⭐️⭐️   企业常用：重要认知或某类场景要用，要懂
  ⭐️     了解即可：偏调试 / 边角场景

各小节速查（运行后按编号选）：
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
from operator import add
from pathlib import Path
from typing import Annotated, Literal, Optional

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
# 00. 极简驱动器：把 input() 直接当 resume 值      【⭐️⭐️⭐️ 全篇复用】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 就这么点逻辑：跑图 → 卡住了就 input() 问你 → 你打的字【原样】resume → 循环。
#    不做任何转换/校验，你按提示的格式打字就行。
#
# ⭐️ 唯一一处「讲究」：判断「是否还在等人」要看 pending（挂起的 interrupt），
#    不能看 state.next——因为节点 resume 后立刻再 interrupt 时，next 会变空，
#    但其实还在等输入（实测坑，已在持久化层面验证）。


def run(graph, init, config: RunnableConfig):
    """跑图：每遇到一次 interrupt 就 input() 问你，输入原样 resume，直到跑完。"""
    data = init
    while True:
        # ① 跑图（首次喂初始输入，之后喂 Command(resume=...) 或 None）
        for chunk in graph.stream(data, config):
            if "__interrupt__" not in chunk:
                print("   ▷", chunk)

        # ② 看还有没有挂起的 interrupt（并行时可能不止一个）
        state = graph.get_state(config)
        pending = [itr for task in state.tasks for itr in task.interrupts]

        if pending:
            if len(pending) == 1:
                # 单个：input() 的字符串直接 resume
                data = Command(
                    resume=input(f"   ❓ {pending[0].value}\n   ✍️  你的输入 > ")
                )
            else:
                # 并行多个：逐个问，按 id 组字典一次性恢复
                data = Command(
                    resume={
                        itr.id: input(f"   ❓ {itr.value}\n   ✍️  你的输入 > ")
                        for itr in pending
                    }
                )
        elif state.next:
            # 没 interrupt 却还有节点要跑 → 静态断点(第11节)，传 None 继续
            input(f"   ⏸ 已在 {state.next} 之前暂停（静态断点），回车继续 > ")
            data = None
        else:
            print("   ✅ 图执行完毕，最终状态：", dict(state.values))
            return state.values


def new_config() -> RunnableConfig:
    """每个 demo 用一个全新的 thread_id。"""
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


# ═════════════════════════════════════════════════════════════
# 01. interrupt + Command(resume) 基础      【⭐️⭐️⭐️ 整篇地基】
# ═════════════════════════════════════════════════════════════


class BasicState(TypedDict):
    foo: str
    human_value: Optional[str]  # 这个字段将由人类通过 interrupt 填进来


def basic_node(state: BasicState):
    # ⭐️ interrupt(value)：value 原样吐给「调用图的那一方」（你/前端）。
    #    第一次执行：抛 GraphInterrupt，图暂停。
    #    resume 后重跑到这里：interrupt() 直接返回 Command(resume=...) 里的值。
    answer = interrupt("请问你的年龄是多少？")
    print(f"   [节点内] interrupt 返回了：{answer}")
    return {"human_value": answer}


def demo_basic():
    """⭐️ 最小闭环：图问年龄 → 你输入 → 写进 state。"""
    builder = StateGraph(BasicState)
    builder.add_node("basic_node", basic_node)
    builder.add_edge(START, "basic_node")
    builder.add_edge("basic_node", END)
    # ⭐️ 三个硬性前提：compile 传 checkpointer + 执行带 thread_id + 用 Command(resume) 恢复
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {"foo": "abc"}, new_config())


# ═════════════════════════════════════════════════════════════
# 02. 模式一：审批 / 拒绝 (approve / reject)   【⭐️⭐️⭐️ 最高频】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：退款审批、大额转账、删除生产数据、群发邮件……
# ⭐️ 关键技巧：节点返回 Command(goto=...)，用人类的答案决定走哪个分支。
# ⭐️ 极简约定：输入任意非空字符串(如 y)=批准；直接回车(空字符串)=拒绝。
#    （因为非空字符串为真、空字符串为假，if decision 天然就分流了，无需转换）


class RefundState(TypedDict):
    order_id: str
    amount: float
    result: str


def approve_refund(
    state: RefundState,
) -> Command[Literal["do_refund", "reject_refund"]]:
    decision = interrupt(
        {
            "question": "是否批准这笔退款？输 y 批准 / 直接回车拒绝",
            "order_id": state["order_id"],
            "amount": state["amount"],
        }
    )
    return Command(goto="do_refund" if decision else "reject_refund")


def do_refund(state: RefundState):
    # ⭐️ 真正的扣款放在 interrupt 之后的【独立节点】，绝不会因「从头重跑」执行两遍
    print(f"   [执行] 已退款 ¥{state['amount']} 给订单 {state['order_id']}")
    return {"result": f"refunded:{state['amount']}"}


def reject_refund(state: RefundState):
    print(f"   [执行] 退款被拒绝，订单 {state['order_id']}")
    return {"result": "rejected"}


def demo_approve_reject():
    """⭐️ 输 y 批准、回车拒绝。"""
    builder = StateGraph(RefundState)
    builder.add_node("approve_refund", approve_refund)
    builder.add_node("do_refund", do_refund)
    builder.add_node("reject_refund", reject_refund)
    builder.add_edge(START, "approve_refund")
    builder.add_edge("do_refund", END)
    builder.add_edge("reject_refund", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {"order_id": "A001", "amount": 8888.0, "result": ""}, new_config())


# ═════════════════════════════════════════════════════════════
# 03. 模式二：审查并编辑内容 (review & edit)   【⭐️⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：LLM 生成营销文案 / 合同条款 / 客服回复草稿，先给人看，
#   人可「原样通过」或「改两句再通过」，把人改后的版本写回 state，再继续。
# ⭐️ 和模式一的区别：这里 resume 的是【人编辑后的内容】，直接覆盖原内容。


class DraftState(TypedDict):
    topic: str
    draft: str
    final: str


def generate_draft(state: DraftState):
    # 真实项目这里调 glm_model 生成；为离线可跑写死。
    # 想接真模型：from provider import glm_model; draft = glm_model.invoke(...).content
    draft = f"【关于「{state['topic']}」的推广文案】立即下单享 5 折，错过等一年！"
    return {"draft": draft}


def human_review_draft(state: DraftState):
    # ⭐️ 把 LLM 草稿抛给人 review，人 resume 回来的就是定稿内容
    edited = interrupt(
        {
            "instruction": "请审阅并输入修改后的定稿（想原样通过就把它再打一遍）",
            "draft": state["draft"],
        }
    )
    return {"final": edited}


def publish(state: DraftState):
    print(f"   [发布] {state['final']}")
    return {}


def demo_review_edit():
    """⭐️ LLM 出草稿 → 你润色 → 发布。你输入的文字就是定稿。"""
    builder = StateGraph(DraftState)
    builder.add_node("generate_draft", generate_draft)
    builder.add_node("human_review_draft", human_review_draft)
    builder.add_node("publish", publish)
    builder.add_edge(START, "generate_draft")
    builder.add_edge("generate_draft", "human_review_draft")
    builder.add_edge("human_review_draft", "publish")
    builder.add_edge("publish", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {"topic": "夏季大促", "draft": "", "final": ""}, new_config())


# ═════════════════════════════════════════════════════════════
# 04. 模式三：审查工具调用 (interrupt 放进工具里)  【⭐️⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 核心思想：interrupt() 可以直接写在【工具函数】里，而不是图节点里。
#    这样「发邮件前必须人工批」这条规则跟着工具走——换哪张图都自动生效。
# ⭐️ 极简约定：输 n=取消发送；其余（含直接回车）=批准发送。


def send_email_tool(to: str, subject: str, body: str) -> str:
    """一个「带人工审批闸门」的发邮件工具（普通函数演示其内部逻辑）。"""
    decision = interrupt(
        {
            "action": "send_email",
            "message": "Agent 准备发送这封邮件。输 n 取消 / 其余批准发送",
            "to": to,
            "subject": subject,
            "body": body,
        }
    )
    if decision.strip().lower() == "n":
        return "用户取消了发送"
    print(f"   [发送] To={to} | 主题={subject} | 正文={body}")
    return f"邮件已发送给 {to}"


class EmailState(TypedDict):
    to: str
    subject: str
    body: str
    log: str


def agent_send_email(state: EmailState):
    result = send_email_tool(state["to"], state["subject"], state["body"])
    return {"log": result}


def demo_review_tool_call():
    """⭐️ 工具内部的闸门：输 n 取消、其余批准。"""
    builder = StateGraph(EmailState)
    builder.add_node("agent_send_email", agent_send_email)
    builder.add_edge(START, "agent_send_email")
    builder.add_edge("agent_send_email", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    init = {"to": "client@corp.com", "subject": "报价", "body": "详见附件", "log": ""}
    run(graph, init, new_config())


# ═════════════════════════════════════════════════════════════
# 05. 模式四：校验输入（重问循环）           【⭐️⭐️ 表单/参数】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：收集金额/年龄/手机号，格式不对就「在节点内反复重问」，直到合法。
# ⭐️ 关键：interrupt() 放在 while 循环里。校验不过就再 interrupt 一次。
# ⭐️ input() 给的是字符串，所以「转成数字 + 校验」放在【节点里】做（这也更贴近
#    真实：前端传来的本来就是字符串）。亲自试：先输「三十」被打回，再输 30 通过。


class AgeState(TypedDict):
    age: Optional[int]


def collect_valid_age(state: AgeState):
    prompt = "请输入你的年龄（正整数）"
    while True:
        value = interrupt(prompt)
        # ⭐️ 校验在节点内：能转成正整数才放行
        if value.strip().isdigit() and int(value) > 0:
            return {"age": int(value)}
        prompt = f"输入 {value!r} 不合法，请重新输入一个正整数"


def demo_validate_input():
    """⭐️ 先故意输非数字看它打回，再输正整数看它通过。"""
    builder = StateGraph(AgeState)
    builder.add_node("collect_valid_age", collect_valid_age)
    builder.add_edge(START, "collect_valid_age")
    builder.add_edge("collect_valid_age", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {"age": None}, new_config())


# ═════════════════════════════════════════════════════════════
# 06. 多轮收集（一个节点问多个问题）         【⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：客服建工单，依次问「姓名 → 电话 → 问题描述」。
# ⭐️ 一个节点连写多个 interrupt()，LangGraph 按【调用顺序】把每次 resume 对应上。
# ⭐️⭐️ 因「从头重跑」，第二次 resume 时第一个 interrupt 不再问（返回上次答案），
#    只有还没答的那个会暂停。所以多个 interrupt 顺序/数量必须稳定（第10节）。


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
    """⭐️ 一个节点收三项，你每输一项推进一步。"""
    builder = StateGraph(TicketState)
    builder.add_node("collect_ticket", collect_ticket)
    builder.add_edge(START, "collect_ticket")
    builder.add_edge("collect_ticket", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {}, new_config())


# ═════════════════════════════════════════════════════════════
# 07. 并行分支同时 interrupt（按 id 恢复）    【⭐️ 高级】
# ═════════════════════════════════════════════════════════════
#
# 企业场景：一份合同同时需要「法务」和「财务」会签，两条分支并行各自停下。
# ⭐️ 此时会同时挂起【多个】Interrupt（各有不同 id）。驱动器会逐个问你，
#    再用 Command(resume={id: 答案}) 一次性把两条分支都恢复。


class SignState(TypedDict):
    approvals: Annotated[list[str], add]  # reducer：两条分支结果各自追加


def legal_sign(state: SignState):
    ans = interrupt("法务是否会签？")
    return {"approvals": [f"法务:{ans}"]}


def finance_sign(state: SignState):
    ans = interrupt("财务是否会签？")
    return {"approvals": [f"财务:{ans}"]}


def demo_parallel_interrupts():
    """⭐️ 法务、财务两条分支并行，逐个问你后一次性恢复。"""
    builder = StateGraph(SignState)
    builder.add_node("legal_sign", legal_sign)
    builder.add_node("finance_sign", finance_sign)
    builder.add_edge(START, "legal_sign")  # ⭐️ START 同时连两个节点 → 并行
    builder.add_edge(START, "finance_sign")
    builder.add_edge("legal_sign", END)
    builder.add_edge("finance_sign", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {"approvals": []}, new_config())


# ═════════════════════════════════════════════════════════════
# 08. 怎么查「当前卡在哪、在等什么」         【⭐️⭐️ 前端/运维必备】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 不重新 stream，直接用 graph.get_state(config) 查：
#     - snapshot.next                 → 接下来要跑的节点
#     - snapshot.tasks[i].interrupts  → 每个任务挂起的 interrupt
#   适合「页面刷新后，重新拉取当前待办」。


def demo_inspect_state():
    """⭐️ 先暂停，显式打印 get_state 的字段，再让你输入恢复。"""
    builder = StateGraph(BasicState)
    builder.add_node("basic_node", basic_node)
    builder.add_edge(START, "basic_node")
    builder.add_edge("basic_node", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    config = new_config()
    for _ in graph.stream({"foo": "x"}, config):  # 先跑到暂停（不恢复）
        pass

    snapshot = graph.get_state(config)
    print("   接下来要跑的节点 next =", snapshot.next)
    for task in snapshot.tasks:
        for itr in task.interrupts:
            print(f"   正在等待: id={itr.id}  value={itr.value!r}")

    # 再用驱动器把它恢复（它已处于暂停，run 会直接读到挂起项并问你）
    run(graph, Command(resume="20"), config)


# ═════════════════════════════════════════════════════════════
# 09. 头号大坑：节点从头重跑 + 副作用幂等     【⭐️⭐️⭐️ 必懂】
# ═════════════════════════════════════════════════════════════
#
# ⭐️⭐️⭐️ resume 时，含 interrupt 的那个节点会【从函数第一行重新执行】，
#   不是从 interrupt 那行继续。所以 interrupt() 上面的代码会跑两遍！
#
# ❌ 错误：先 charge() 再 interrupt() → resume 后 charge 跑两次，扣两次钱
# ✅ 正确1：副作用放 interrupt 之后    ✅ 正确2：拆成独立节点(见第02节 do_refund)
# ✅ 正确3：副作用做成幂等(upsert/唯一键去重)
#
# 下面用计数器让你【亲眼看到】interrupt 上面的代码跑了两次：

_side_effect_counter = {"count": 0}


class CounterState(TypedDict):
    done: bool


def node_with_side_effect(state: CounterState):
    _side_effect_counter["count"] += 1  # ⚠️ 故意放 interrupt 前，演示它被执行两次
    print(
        f"   [副作用] interrupt 之前的代码被执行了第 {_side_effect_counter['count']} 次"
    )
    interrupt("随便确认一下（回车即可）")
    return {"done": True}


def demo_reexecution_pitfall():
    """⭐️ 随便输点东西恢复，看计数器从 1 变 2。"""
    _side_effect_counter["count"] = 0
    builder = StateGraph(CounterState)
    builder.add_node("node_with_side_effect", node_with_side_effect)
    builder.add_edge(START, "node_with_side_effect")
    builder.add_edge("node_with_side_effect", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {"done": False}, new_config())
    print(
        f"   → 结论：同一句副作用代码共执行了 {_side_effect_counter['count']} 次（这就是坑）"
    )


# ═════════════════════════════════════════════════════════════
# 10. 其余四个坑（异常 / 顺序 / 序列化 / 子图） 【⭐️⭐️】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 坑1：别用宽泛 try/except 吞掉 interrupt（它靠抛 GraphInterrupt 暂停）
#    ❌ try: x=interrupt(...) except Exception: ...   ✅ interrupt 单独写，只 catch 具体异常
# ⭐️ 坑2：同节点多个 interrupt 的顺序/数量必须稳定（resume 按第几个对应）
# ⭐️ 坑3：interrupt 的 value 必须可 JSON 序列化（要存盘+传前端；别放函数/连接/实例）
# ⭐️ 坑4：子图里 interrupt，父节点也从头重跑（和第09节同源，副作用要小心）
#
# 下面给「坑1」配可运行对照：interrupt 在 try 之外，照常能暂停/恢复。


class SafeState(TypedDict):
    name: Optional[str]
    extra: Optional[str]


def safe_node(state: SafeState):
    name = interrupt("请输入姓名")  # ✅ interrupt 独立成行，绝不放进 try
    try:
        extra = {"a": 1}["a"]  # ✅ try 只包真正可能抛错的业务
        extra = f"ok:{extra}"
    except KeyError:  # ✅ 只 catch 具体异常，不用裸 Exception
        extra = "fallback"
    return {"name": name, "extra": extra}


def demo_exception_pitfall():
    """⭐️ interrupt 在 try 之外，输入姓名即可正常恢复。"""
    builder = StateGraph(SafeState)
    builder.add_node("safe_node", safe_node)
    builder.add_edge(START, "safe_node")
    builder.add_edge("safe_node", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    run(graph, {}, new_config())


# ═════════════════════════════════════════════════════════════
# 11. 静态断点 interrupt_before / interrupt_after  【⭐️ 仅调试】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 和 interrupt() 不同的另一套：编译时指定「在某节点前/后自动暂停」，像断点，
#    主要用于【调试】。区别：不携带数据、恢复时传 None（不是 Command）。
#    驱动器已能识别它（没有 interrupt 数据但 next 非空 → 提示回车，传 None）。


class DbgState(TypedDict):
    x: int


def step_a(state: DbgState):
    print("   [step_a] 执行")
    return {"x": state["x"] + 1}


def step_b(state: DbgState):
    print("   [step_b] 执行")
    return {"x": state["x"] * 10}


def demo_static_breakpoint():
    """⭐️ 在 step_b 之前自动暂停，回车继续（传 None 恢复）。"""
    builder = StateGraph(DbgState)
    builder.add_node("step_a", step_a)
    builder.add_node("step_b", step_b)
    builder.add_edge(START, "step_a")
    builder.add_edge("step_a", "step_b")
    builder.add_edge("step_b", END)
    # ⭐️ 编译时声明断点：在 step_b 之前停
    graph = builder.compile(checkpointer=InMemorySaver(), interrupt_before=["step_b"])
    run(graph, {"x": 1}, new_config())


# ═════════════════════════════════════════════════════════════
# 主入口：菜单，选一个 demo 亲手交互体验
# ═════════════════════════════════════════════════════════════

DEMOS = {
    "1": ("基础 interrupt/resume（问年龄）", demo_basic),
    "2": ("审批/拒绝（退款，y 批准/回车拒绝）", demo_approve_reject),
    "3": ("审查并编辑（润色文案）", demo_review_edit),
    "4": ("审查工具调用（发邮件，n 取消/其余发送）", demo_review_tool_call),
    "5": ("校验输入（先输三十被打回，再输30）", demo_validate_input),
    "6": ("多轮收集（依次问姓名/电话/问题）", demo_multi_collect),
    "7": ("并行 interrupt（法务+财务会签）", demo_parallel_interrupts),
    "8": ("查看挂起状态 get_state", demo_inspect_state),
    "9": ("大坑：节点从头重跑（看计数器变2）", demo_reexecution_pitfall),
    "10": ("坑：别吞 interrupt 异常", demo_exception_pitfall),
    "11": ("静态断点（回车继续）", demo_static_breakpoint),
}


def main():
    while True:
        print("\n" + "=" * 60)
        print("LangGraph 人机交互 · 选一个 demo 亲手玩（输 q 退出）")
        print("=" * 60)
        for key, (title, _) in DEMOS.items():
            print(f"  {key:>2}. {title}")
        choice = input("\n请输入编号 > ").strip()

        if choice.lower() in {"q", "quit", "exit"}:
            print("再见 👋")
            break
        if choice not in DEMOS:
            print("⚠️ 没有这个编号，重选。")
            continue

        title, fn = DEMOS[choice]
        print(f"\n----- ▶ 开始：{title} -----")
        try:
            fn()
        except (KeyboardInterrupt, EOFError):
            print("\n（已中断本次 demo，回到菜单）")
        print("----- ◀ 本 demo 结束 -----")


if __name__ == "__main__":
    main()
