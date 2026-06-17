"""
LangGraph 记忆 (Memory) — 企业生产版完整教程
================================================

⭐️ 本篇与上一版的区别：全部按【真实企业环境】写，不再用 InMemory*：
   · 短期记忆 → PostgresSaver（落库，服务重启/多实例都还在）
   · 长期记忆 → PostgresStore + pgvector（落库 + 语义检索，用真实 embedding）
   · 摘要     → langmem 的 SummarizationNode（业界现成方案，配真实 glm_model）
   本文件依赖本项目的 provider（glm_model / embeddings）与 .env 里的 DB_URI，
   运行前需要一个可连的 PostgreSQL（建议 pgvector 镜像），见文件末「如何起库」。

⭐️ 先把这张「两层」对照表刻进脑子（全篇最重要的认知）：
   ┌──────────┬──────────────────────────┬──────────────────────────┐
   │          │ 短期记忆 = checkpointer   │ 长期记忆 = store          │
   ├──────────┼──────────────────────────┼──────────────────────────┤
   │ 存什么    │ 这次会话的完整 state      │ 跨会话的长期事实           │
   │          │ （messages、变量…）       │ （爱好/地址/历史结论）     │
   │ 隔离维度  │ thread_id（一次会话）     │ namespace（如 user_id）    │
   │ 生命周期  │ 一条会话                 │ 永久，换 thread 仍在       │
   │ 生产实现  │ PostgresSaver            │ PostgresStore(+pgvector)  │
   │ 怎么挂    │ compile(checkpointer=)   │ compile(store=)           │
   │ 是否必用  │ 几乎必用（地基）          │ 看情况，常被自建方案替代   │
   └──────────┴──────────────────────────┴──────────────────────────┘

⭐️ 直接回答你最关心的「生产到底用不用自带 store」：
   - checkpointer(短期)：【一定用】，只是用 PostgresSaver 落库。这是地基。
   - 消息管理(trim/摘要)：【一定要会】，长对话省 token、稳上下文的刚需。
   - store(长期)：【看情况，常自建】。它本质是 put/search 的 KV+向量封装，
     原型/中小项目直接用 PostgresStore 很香；但已有成熟业务库/向量体系的团队，
     往往不被 runtime.store 这套约定绑住，自己存更灵活。详见第 10 节决策表。

──────────────────────────────────────────────────────────────────
⭐️ 全篇 API 速记（本机 langgraph==1.2.4 / langchain==1.3.6 / langmem==0.0.30
   / pgvector / DashScope text-embedding-v3(1024 维)，全部实测可跑）：

   短期：with PostgresSaver.from_conn_string(DB_URI) as cp: cp.setup()
        graph.compile(checkpointer=cp) + {"configurable":{"thread_id": x}}
   裁剪：trim_messages(msgs, max_tokens=, token_counter=count_tokens_approximately, ...)
   删除：RemoveMessage(id=某条id)  /  RemoveMessage(id=REMOVE_ALL_MESSAGES) 清空
   摘要：SummarizationNode(model=glm_model, token_counter=..., max_tokens=, ...)  # langmem
   长期：with PostgresStore.from_conn_string(DB_URI, index={"embed":embeddings,"dims":1024}) as st:
        st.setup(); st.put(ns,key,value) / st.get / st.search(ns, query=, limit=)
   节点取 store：def node(state, runtime: Runtime[Ctx]): runtime.store / runtime.context.user_id
   生产：首次 .setup() 建表/迁移；pgvector 需 CREATE EXTENSION vector

──────────────────────────────────────────────────────────────────
⭐️ 重要程度图例（最多 5 颗 ⭐️，按「企业实战 + 学习性价比」综合打分）：
  ⭐️⭐️⭐️⭐️⭐️ 必懂：核心认知 / 几乎天天用，不会就写不对
  ⭐️⭐️⭐️⭐️   重点：生产高频刚需，要会写
  ⭐️⭐️⭐️     常用：会遇到，要能看懂会改
  ⭐️⭐️       了解：知道有这回事、看懂别人代码即可
  ⭐️         边角：特定场景再深入

各小节速查（直接运行会从上到下依次演示）：
  01 两层记忆心智模型（短期 vs 长期）........ ⭐️⭐️⭐️⭐️⭐️  全篇地基认知
  02 短期记忆 = PostgresSaver（跨多轮+跨重启）⭐️⭐️⭐️⭐️⭐️  生产地基（配真实 glm_model）
  03 消息管理①：Trim 裁剪（控上下文/省钱）.. ⭐️⭐️⭐️⭐️    长对话刚需
  04 消息管理②：Delete 删除消息 ............ ⭐️⭐️⭐️      精修历史
  05 消息管理③：Summarize 摘要(langmem).... ⭐️⭐️⭐️⭐️    长对话主力方案
  06 长期记忆 = PostgresStore：put/get/search ⭐️⭐️       理解概念即可
  07 在节点里访问 store（Runtime）.......... ⭐️⭐️        理解写法即可
  08 namespace 命名空间（隔离）............. ⭐️⭐️        会用就行
  09 语义检索 semantic search（pgvector）... ⭐️⭐️⭐️      真实可跑，按意思召回
  10 生产落地 + 「该不该用自带 store」决策 .. ⭐️⭐️⭐️⭐️    做技术选型必看
──────────────────────────────────────────────────────────────────
"""

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ⭐️ 直接 `python 官方文档/核心能力/记忆.py` 运行时，把项目根加入 sys.path，
#    这样才能 import 到本项目的 provider（glm_model / embeddings）。
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from langchain_core.messages import (  # noqa: E402
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_core.messages.utils import (  # noqa: E402
    count_tokens_approximately,
    trim_messages,
)
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402
from langgraph.constants import END, START  # noqa: E402
from langgraph.graph import StateGraph  # noqa: E402
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages  # noqa: E402
from langgraph.runtime import Runtime  # noqa: E402
from langgraph.store.postgres import PostgresStore  # noqa: E402
from langmem.short_term import SummarizationNode  # noqa: E402
from typing_extensions import Annotated, Any, TypedDict  # noqa: E402

from provider import glm_model  # noqa: E402  本项目封装的智谱 GLM
from provider.embedding import embeddings  # noqa: E402  本项目封装的 DashScope 向量模型

DB_URI = os.environ["DB_URI"]  # 形如 postgresql://user:pwd@localhost:5432/langgraph
EMBED_DIMS = 1024  # ⭐️ text-embedding-v3 的维度；换模型记得改这里


def banner(title: str):
    print("\n" + "═" * 60)
    print("▶", title)
    print("═" * 60)


def ensure_pgvector():
    """⭐️ 语义检索依赖 pgvector 扩展；生产里通常放在迁移脚本里执行一次。"""
    import psycopg

    with psycopg.connect(DB_URI) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


# ═════════════════════════════════════════════════════════════
# 01. 两层记忆心智模型                          【⭐️⭐️⭐️⭐️⭐️ 全篇地基】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 别被「记忆」这个词骗了。LangGraph 里有两个独立的东西：
#    短期记忆 = checkpointer：「这一次聊天聊到哪了」——存当前 thread 的完整 state，
#               换 thread_id（开新会话）就看不到上一条会话。生产用 PostgresSaver。
#    长期记忆 = store：「关于这个【用户】我永远要记得的事」——按 user_id 等 namespace
#               存跨会话事实，换 thread 仍在。生产用 PostgresStore(+pgvector)。
# ⭐️ 类比：短期=这通电话的通话记录（挂了就翻篇）；长期=通讯录里「他爱喝美式、住杭州」。
# 本节是地图，不跑代码。下面用真实 Postgres 分别演示这两层。


# ═════════════════════════════════════════════════════════════
# 02. 短期记忆 = PostgresSaver                  【⭐️⭐️⭐️⭐️⭐️ 生产地基】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 生产里短期记忆就是「把图状态落到 Postgres」。和开发版唯一的差别：
#    InMemorySaver  →  PostgresSaver.from_conn_string(DB_URI)，并首次 .setup() 建表。
# ⭐️ 价值：服务重启、横向扩多个实例，同一个 thread_id 的对话历史都还在（内存版做不到）。
# ⭐️ 这里用【真实 glm_model】当回复节点：先告诉它名字，再问它名字——
#    它能答对，靠的就是 checkpointer 把上一轮的消息存下来又喂了回去。

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]  # ⭐️ add_messages：新消息追加 + 按 id 去重


def llm_reply(state: ChatState):
    # ⭐️ 真实企业写法：把累计的 messages 直接交给模型，历史由 checkpointer 提供
    resp = glm_model.invoke(state["messages"])
    return {"messages": [resp]}


def demo_short_term():
    """⭐️ 同一 thread 连聊两轮，第二轮模型能记得第一轮说的名字。"""
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()  # ⭐️ 首次建表（幂等，可重复调）

        b = StateGraph(ChatState)
        b.add_node("reply", llm_reply)
        b.add_edge(START, "reply")
        b.add_edge("reply", END)
        graph = b.compile(checkpointer=checkpointer)

        cfg = {"configurable": {"thread_id": f"demo-{uuid.uuid4()}"}}
        graph.invoke(
            {"messages": [HumanMessage("你好，我叫小田，请记住我的名字。")]}, cfg
        )
        out = graph.invoke({"messages": [HumanMessage("我刚才说我叫什么名字？")]}, cfg)

        print("模型回答：", out["messages"][-1].content.strip()[:60])
        print("这条 thread 已落库的消息条数：", len(graph.get_state(cfg).values["messages"]))
        print("⭐️ 重点：把进程杀掉重启，只要 thread_id 不变，上面的历史依然能查到。")


# ═════════════════════════════════════════════════════════════
# 03. 消息管理①：Trim 裁剪                       【⭐️⭐️⭐️⭐️ 长对话刚需】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 痛点：对话越聊越长，messages 全塞给模型 → 超上下文窗口 / 又慢又贵。
# ⭐️ trim_messages：调模型【之前】按 token 预算裁掉一部分，只留最相关的。
#    它是「读时裁剪」——只影响这次喂给模型的内容，不动你 Postgres 里存的历史
#    （要真删历史看第 04 节）。最常用、最安全。
# ⭐️ 关键参数：max_tokens 预算 / token_counter 用官方 count_tokens_approximately /
#    strategy="last" 保留最近 / start_on="human" 裁完从 Human 开始（符合对话格式）。

def demo_trim():
    history = [
        SystemMessage("你是一个客服助手。"),
        HumanMessage("我上周买的耳机有杂音" * 3),
        AIMessage("方便提供订单号吗？" * 3),
        HumanMessage("订单号 88888" * 3),
        AIMessage("已查到，正在为你处理" * 3),
        HumanMessage("那我现在最关心的是能不能换货？"),
    ]
    kept = trim_messages(
        history,
        max_tokens=40,                       # ⭐️ 预算很小，强制裁剪给你看效果
        token_counter=count_tokens_approximately,
        strategy="last",                     # 保留最近
        start_on="human",                    # 裁完从 Human 开始
        allow_partial=False,                 # 不切碎单条消息
    )
    print(f"原始 {len(history)} 条 → 裁剪后 {len(kept)} 条（只是【这次】喂给模型的变少）")
    for m in kept:
        print(f"   {type(m).__name__:<13} {m.content[:20]}…")
    print("⭐️ 真实用法：在调用 glm_model 前先 trim，再 glm_model.invoke(kept)。")


# ═════════════════════════════════════════════════════════════
# 04. 消息管理②：Delete 删除消息                 【⭐️⭐️⭐️ 精修历史】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 和 trim 的区别：trim 是「这次少喂点」，删除是「真的从 Postgres 存档里抹掉」。
# ⭐️ 做法：节点里返回 RemoveMessage(id=要删那条的id)。messages 用了 add_messages，
#    它认得 RemoveMessage —— 看到就按 id 删。清空整段用 RemoveMessage(id=REMOVE_ALL_MESSAGES)。
# ⭐️ 典型用法：每轮结束把历史修剪到「最近 N 条」，落库就不会无限膨胀。

class PruneState(TypedDict):
    messages: Annotated[list, add_messages]


def grow(state: PruneState):
    return {"messages": [AIMessage("（机器人）好的~")]}


def prune_to_last_2(state: PruneState):
    """⭐️ 只保留最近 2 条，其余真删掉。"""
    msgs = state["messages"]
    if len(msgs) > 2:
        return {"messages": [RemoveMessage(id=m.id) for m in msgs[:-2]]}
    return {}


def demo_delete():
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()
        b = StateGraph(PruneState)
        b.add_node("chat", grow)
        b.add_node("prune", prune_to_last_2)   # ⭐️ 回复完顺手修剪
        b.add_edge(START, "chat")
        b.add_edge("chat", "prune")
        b.add_edge("prune", END)
        graph = b.compile(checkpointer=checkpointer)

        cfg = {"configurable": {"thread_id": f"del-{uuid.uuid4()}"}}
        graph.invoke(
            {"messages": [HumanMessage("第1句"), HumanMessage("第2句"), HumanMessage("第3句")]},
            cfg,
        )
        kept = graph.get_state(cfg).values["messages"]
        print(f"3 条 + 机器人回复，prune 后 Postgres 里只剩 {len(kept)} 条：")
        for m in kept:
            print(f"   {type(m).__name__:<13} {m.content}")
        print("\n清空整段历史的写法： return {'messages': [RemoveMessage(id=REMOVE_ALL_MESSAGES)]}")


# ═════════════════════════════════════════════════════════════
# 05. 消息管理③：Summarize 摘要（langmem）       【⭐️⭐️⭐️⭐️ 长对话主力】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 比「直接删」更聪明：删会丢信息；摘要是把【老消息压缩成一段摘要】保留要点，
#    再删掉原始老消息。既省 token 又不丢上下文，是长对话生产里最常用的方案。
# ⭐️ 企业不必自己造轮子：langmem 提供现成的 SummarizationNode，把它当一个普通节点
#    放在「调用模型之前」，它会自动维护一段滚动摘要(running_summary)并压缩历史。
# ⭐️ 关键点：
#    - state 要有一个 context: dict 字段，langmem 用它存滚动摘要
#    - 节点输出到 output_messages_key（这里叫 summarized_messages），后续节点用它喂模型
#    - max_tokens_before_summary：超过这个量才触发摘要；max_summary_tokens：摘要本身上限

class SummaryState(TypedDict):
    messages: Annotated[list, add_messages]
    context: dict[str, Any]            # ⭐️ langmem 存 running_summary 的地方


class LLMInput(TypedDict):
    summarized_messages: list          # ⭐️ 摘要节点压缩后的消息，喂给模型用这个


def build_summary_graph(checkpointer):
    summarization = SummarizationNode(
        token_counter=count_tokens_approximately,
        model=glm_model,                       # ⭐️ 用真实模型来写摘要
        max_tokens=256,                        # 压缩后目标上限
        max_tokens_before_summary=200,         # 超过才触发摘要
        max_summary_tokens=128,
        output_messages_key="summarized_messages",
    )

    def call_model(state: LLMInput):
        # ⭐️ 用被压缩过的 summarized_messages 调模型，而不是原始全量 messages
        resp = glm_model.invoke(state["summarized_messages"])
        return {"messages": [resp]}

    b = StateGraph(SummaryState)
    b.add_node("summarize", summarization)
    b.add_node("call", call_model)
    b.add_edge(START, "summarize")
    b.add_edge("summarize", "call")
    b.add_edge("call", END)
    return b.compile(checkpointer=checkpointer)


def demo_summarize():
    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()
        graph = build_summary_graph(checkpointer)

        # 造一段「很长」的历史，触发摘要
        long_history = []
        for i in range(8):
            long_history.append(HumanMessage(f"第{i}个问题：请帮我看看订单和物流情况。" * 3))
            long_history.append(AIMessage(f"第{i}个回复：已为你查询，请稍候。" * 3))

        cfg = {"configurable": {"thread_id": f"sum-{uuid.uuid4()}"}}
        graph.invoke({"messages": long_history, "context": {}}, cfg)

        rs = graph.get_state(cfg).values.get("context", {}).get("running_summary")
        if rs:
            print("langmem 生成的滚动摘要（节选）：")
            print("   " + rs.summary.strip().replace("\n", " ")[:80] + "…")
        print("⭐️ 之后每轮，长历史都会被这段摘要 + 最近几条替代再喂模型，token 大幅下降。")


# ═════════════════════════════════════════════════════════════
# 06. 长期记忆 = PostgresStore：put/get/search   【⭐️⭐️ 理解概念即可】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ store 是跨会话的存储，最核心三个动作（先脱离图，单独认识它）：
#    store.put(namespace, key, value)            存一条（value 是 dict）
#    store.get(namespace, key)                   按 key 取一条
#    store.search(namespace, query=, limit=)     搜（不给 query 就列全部）
# ⭐️ 生产用 PostgresStore.from_conn_string(DB_URI)，首次 .setup() 建表。
#    namespace 是元组，最常见 (user_id, "memories")。
# ⭐️ 这部分是「了解」级：知道它能干嘛、能看懂别人代码即可（是否真用见第 10 节）。

def demo_store_basics():
    with PostgresStore.from_conn_string(DB_URI) as store:
        store.setup()
        ns = (f"user-{uuid.uuid4()}", "memories")   # 用随机 user 避免和历史数据混

        store.put(ns, "m1", {"text": "喜欢喝美式咖啡"})
        store.put(ns, "m2", {"text": "住在杭州"})

        print("get 单条：", store.get(ns, "m1").value)
        print("search 全部：", [i.value for i in store.search(ns)])


# ═════════════════════════════════════════════════════════════
# 07. 在节点里访问 store（Runtime）              【⭐️⭐️ 理解写法即可】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 让 store 在图运行时用起来，两步：
#    1) compile(store=...) 把 store 挂到图上
#    2) 节点签名加第二个参数 runtime: Runtime[Ctx]，用 runtime.store 拿到它；
#       用 runtime.context.user_id 拿到「这次是哪个用户」（context 在 invoke 时传入）
# ⭐️ 这就是前面说的「侵入性」：节点要依赖 Runtime / context_schema 这套约定。
#    很多团队嫌它绑得太死，宁可在节点里直接调自家 DAO/DB —— 也是合理选择。

@dataclass
class Ctx:
    user_id: str                             # ⭐️ 运行时上下文：跨节点传当前用户


class MemState(TypedDict):
    note: str


def remember_node(state: MemState, runtime: Runtime[Ctx]):
    store = runtime.store                    # ⭐️ 从 runtime 拿到挂载的 store
    uid = runtime.context.user_id            # ⭐️ 拿到当前用户
    ns = (uid, "memories")
    store.put(ns, "pref", {"text": "这个用户偏好简洁回答"})
    return {"note": f"已为用户 {uid} 写入长期记忆，共 {len(store.search(ns))} 条"}


def demo_store_in_graph():
    with PostgresStore.from_conn_string(DB_URI) as store, \
            PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        store.setup()
        checkpointer.setup()

        b = StateGraph(MemState, context_schema=Ctx)   # ⭐️ 声明 context_schema
        b.add_node("remember", remember_node)
        b.add_edge(START, "remember")
        b.add_edge("remember", END)
        graph = b.compile(store=store, checkpointer=checkpointer)

        out = graph.invoke(
            {"note": ""},
            {"configurable": {"thread_id": f"t-{uuid.uuid4()}"}},
            context=Ctx(user_id=f"user-{uuid.uuid4()}"),  # ⭐️ invoke 时把当前用户传进去
        )
        print(out)


# ═════════════════════════════════════════════════════════════
# 08. namespace 命名空间                         【⭐️⭐️ 会用就行】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ namespace 是元组，靠它把记忆「分抽屉」，避免不同用户/用途串味：
#       (user_id, "memories")          某用户的通用记忆
#       (user_id, "preferences")       某用户的偏好
#       ("org_42", user_id, "notes")   组织 → 用户 → 笔记，多级也行
# ⭐️ search 只在【指定的那个抽屉】里搜，天然做到多租户/多用户隔离。

def demo_namespace():
    with PostgresStore.from_conn_string(DB_URI) as store:
        store.setup()
        ua = (f"A-{uuid.uuid4()}", "memories")
        ub = (f"B-{uuid.uuid4()}", "memories")
        store.put(ua, "k", {"text": "A 的事"})
        store.put(ub, "k", {"text": "B 的事"})
        print("只搜 A 的抽屉：", [i.value for i in store.search(ua)])
        print("只搜 B 的抽屉：", [i.value for i in store.search(ub)])
        print("⭐️ 同样 key='k' 互不干扰，因为命名空间不同 —— 这就是隔离。")


# ═════════════════════════════════════════════════════════════
# 09. 语义检索 semantic search（pgvector）       【⭐️⭐️⭐️ 真实可跑】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 前面 search 是「列出/精确」。语义检索按【意思】找：存了一堆记忆后，
#    问「晚饭吃点辣的吗」，能召回「喜欢吃川菜，越辣越好」这类语义相近条目。
# ⭐️ 开启方式：建 store 时给一个 index（embedding 模型 + 维度）。
#    本项目用 DashScope text-embedding-v3（1024 维），底层落到 Postgres 的 pgvector。
#       store = PostgresStore.from_conn_string(DB_URI,
#                   index={"embed": embeddings, "dims": 1024})
#    put 进去时自动算向量；search(ns, query=...) 时按相近度排序，附带 score。
# ⭐️ 何时用内置 / 何时上专用向量库：数据量不大、就想省事 → 内置足够；
#    大规模 / 复杂检索 → 多半交给专门向量库（Milvus/独立 pgvector 服务）。

def demo_semantic_search():
    ensure_pgvector()  # ⭐️ 确保扩展存在（生产放迁移脚本）
    with PostgresStore.from_conn_string(
        DB_URI, index={"embed": embeddings, "dims": EMBED_DIMS}
    ) as store:
        store.setup()
        ns = (f"sem-{uuid.uuid4()}", "memories")
        store.put(ns, "a", {"text": "我喜欢吃川菜，越辣越好"})
        store.put(ns, "b", {"text": "我住在杭州西湖区"})
        store.put(ns, "c", {"text": "我对花生过敏"})

        hits = store.search(ns, query="晚饭推荐点辣的吗", limit=2)
        print("语义检索『晚饭推荐点辣的吗』Top2（带相近度）：")
        for h in hits:
            print(f"   score={h.score:.3f}  {h.value['text']}")
        print("⭐️ 注意：召回靠的是『意思相近』，query 里压根没出现『川菜/辣』也能命中。")


# ═════════════════════════════════════════════════════════════
# 10. 生产落地 + 「该不该用自带 store」决策      【⭐️⭐️⭐️⭐️ 选型必看】
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 开发 → 生产，记忆这块只改两件事：
#    1) 内存实现换数据库后端：
#         短期：InMemorySaver → PostgresSaver / RedisSaver / MongoDBSaver …
#         长期：InMemoryStore  → PostgresStore  / RedisStore …
#    2) 数据库后端【首次要建表/迁移】，启动时跑一次：
#         checkpointer.setup() / store.setup()（异步版加 await）
#       建议把 setup/migration 放到「部署步骤」或「服务启动时」执行一次；
#       语义检索还要 CREATE EXTENSION vector（pgvector）。
#    （子图无需单独配 checkpointer：父图编译时挂上会自动传给子图。）
#
# ⭐️ 回到你的核心疑问——决策表直接给结论：
#    ┌────────────────────┬──────────────────────────────────────────────┐
#    │ checkpointer(短期)  │ 【一定用】PostgresSaver。这是地基。            │
#    ├────────────────────┼──────────────────────────────────────────────┤
#    │ 消息管理 trim/摘要   │ 【一定要会】。trim + langmem 摘要是长对话刚需。 │
#    ├────────────────────┼──────────────────────────────────────────────┤
#    │ store(长期记忆)     │ 【看情况，常自建】：                            │
#    │                    │  · 原型/中小项目/想快 → 直接用 PostgresStore   │
#    │                    │  · 有成熟业务库或向量体系 → 多半自己存，         │
#    │                    │    不被 runtime.store 这套约定绑住，更灵活      │
#    └────────────────────┴──────────────────────────────────────────────┘
#
# ⭐️ 学习建议：劲花在「PostgresSaver + 消息管理(trim/langmem 摘要)」上
#    （⭐️⭐️⭐️⭐️~⭐️⭐️⭐️⭐️⭐️）；store 理解到「会写、看得懂、知道何时换自家方案」即可（⭐️⭐️）。

def demo_production_note():
    print("生产落地清单：")
    print("  1) InMemorySaver → PostgresSaver ；InMemoryStore → PostgresStore")
    print("  2) 启动时执行一次 checkpointer.setup() / store.setup() 建表迁移")
    print("  3) 语义检索需 CREATE EXTENSION vector（pgvector）")
    print("  4) store 是否自建：有成熟业务/向量库就自建，否则可直接用官方 PostgresStore")


# ═════════════════════════════════════════════════════════════
# 主入口：从上到下依次演示（会真连 Postgres、真调 glm_model / 向量模型）
#
# 如何起库（本机示例，pgvector 镜像，库名/账号需与 .env 的 DB_URI 一致）：
#   docker run -d --name lg-pg -p 5432:5432 \
#     -e POSTGRES_USER=langgraph -e POSTGRES_PASSWORD=langgraph123 \
#     -e POSTGRES_DB=langgraph pgvector/pgvector:pg16
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    banner("02 短期记忆 PostgresSaver（跨多轮、跨重启，配真实 glm_model）")
    demo_short_term()

    banner("03 Trim 裁剪（这次少喂点给模型）")
    demo_trim()

    banner("04 Delete 删除消息（真从 Postgres 抹掉）")
    demo_delete()

    banner("05 Summarize 摘要（langmem SummarizationNode + glm_model）")
    demo_summarize()

    banner("06 PostgresStore 基础 put/get/search")
    demo_store_basics()

    banner("07 在节点里用 store（Runtime / context）")
    demo_store_in_graph()

    banner("08 namespace 命名空间隔离")
    demo_namespace()

    banner("09 语义检索（pgvector + DashScope 向量，真实召回）")
    demo_semantic_search()

    banner("10 生产落地清单")
    demo_production_note()
