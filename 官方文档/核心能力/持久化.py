"""
LangGraph 持久化 (Persistence) — 完整教程
==========================================

⭐️ 先看这张图，理解 LangGraph 的三层存储：

┌──────────────────────────────────────────────────────────────┐
│  第一层：Checkpointer（图执行状态）— LangGraph 自动管           │
│  │  每个 super-step 自动保存快照                               │
│  │  用于：中断恢复 / 回放 / 容错                                │
│  │  生产用 PostgresSaver，开发用 InMemorySaver                  │
│  └─→ 你不直接操作它，编译时传入就行                             │
│                                                               │
│  第二层：Store（跨 thread 记忆）— 你决定用不用                   │
│  │  跨 thread 共享的用户偏好、知识                              │
│  │  80% 场景够用：PostgresStore + pgvector 语义搜索            │
│  │  20% 场景自己建表：记忆系统是产品核心时                       │
│  └─→ 通过 runtime.store 或 config 在节点内操作                 │
│                                                               │
│  第三层：业务数据（对话记录等）— 必须自己存                      │
│     每轮对话都要 INSERT 到 conversations 表                     │
│     用于：分析 / 合规 / 训练 / 审计                             │
│     Checkpointer 和 Store 都不替你做这件事                     │
└──────────────────────────────────────────────────────────────┘

参考文档：
  - https://docs.langchain.com/oss/python/langgraph/persistence
  - https://docs.langchain.com/oss/python/langgraph/add-memory

──────────────────────────────────────────────────────────────────
⭐️ 企业实战优先级图例（每个小节标题都标了等级）：

  ⭐️⭐️⭐️ 企业核心：几乎每个有状态的 Agent 项目都要用，必须吃透
  ⭐️⭐️   企业常用：重要认知或选型决策，要懂但不一定天天写
  ⭐️     了解即可：企业里几乎用不到（多为 demo / 调试 / 被自建方案替代）

各小节速查：
  01 Checkpoint 基础 ............ ⭐️⭐️⭐️  有状态图的地基
  02 State 操作 ................. ⭐️⭐️    get/update 常用；replay/查找 了解
  03 短期记忆（多轮 + 消息管理） ... ⭐️⭐️⭐️  对话类产品命脉
  04 Store 基础（InMemoryStore） .. ⭐️      仅 demo，生产不用内存 Store
  05 Graph + Store ............... ⭐️⭐️    跨 thread 记忆的概念要懂
  06 语义搜索（内存向量） .......... ⭐️      生产走专用向量库，这里只是体验
  07 PostgreSQL 实战 ............. ⭐️⭐️⭐️  生产 checkpointer + 对话落库
  08 PostgresStore vs 自建表 ..... ⭐️⭐️    长期记忆选型，决策认知
  09 Durability + Checkpointer 选型 ⭐️⭐️   上线前要做的两个选择
──────────────────────────────────────────────────────────────────
"""

import os
import uuid
from operator import add
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph, MessagesState
from langgraph.store.memory import InMemoryStore
from typing_extensions import TypedDict, Annotated

# 加载 .env（千问 API Key、PostgreSQL 连接串等）
# ⭐️ .env 在项目根目录，统一管理所有配置
load_dotenv(Path(__file__).parent.parent.parent / ".env")


# ═════════════════════════════════════════════
# 01. Checkpoint 基础          【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

class State(TypedDict):
    foo: str
    bar: Annotated[list[str], add]  # ⭐️ reducer：新值追加而非覆盖


def node_a(state: State):
    return {"foo": "a", "bar": ["a"]}


def node_b(state: State):
    return {"foo": "b", "bar": ["b"]}


def demo_checkpoint():
    """
    ⭐️ 编译时传入 checkpointer，图就会在每个 super-step 自动保存状态快照。

    ⭐️ 执行时必须指定 thread_id：
        config = {"configurable": {"thread_id": "1"}}

    ⭐️ Super-step（超步）：图的一次"滴答"。
        START -> node_a -> node_b -> END 有 3 个超步，产生 4 个 checkpoint：
          step=-1: 空 checkpoint（等待输入）
          step=0:  输入写入后（next = node_a）
          step=1:  node_a 执行后（next = node_b），bar=['a']（reducer 累加）
          step=2:  node_b 执行后（next = ()），bar=['a','b']

    ⭐️ Pending writes：
        同一超步内节点 A 成功但节点 B 失败时，A 的输出已持久化。
        恢复时不重跑 A，只重跑 B。
    """
    workflow = StateGraph(State)
    workflow.add_node(node_a)
    workflow.add_node(node_b)
    workflow.add_edge(START, "node_a")
    workflow.add_edge("node_a", "node_b")
    workflow.add_edge("node_b", END)

    # ⭐️ 编译时传入 checkpointer → 持久化启用
    checkpointer = InMemorySaver()
    graph = workflow.compile(checkpointer=checkpointer)

    config: RunnableConfig = {"configurable": {"thread_id": "1"}}

    # 执行图
    result = graph.invoke({"foo": "", "bar": []}, config=config)
    print("=== 01. Checkpoint 基础 ===")
    print(f"最终状态: {result}")
    # {'foo': 'b', 'bar': ['a', 'b']}

    # ⭐️ get_state() 获取最新快照
    snapshot = graph.get_state(config)
    print(f"values: {snapshot.values}")
    print(f"next:   {snapshot.next}")      # () = 执行完毕
    print(f"step:   {snapshot.metadata.get('step')}")

    return graph


# ═════════════════════════════════════════════
# 02. State 操作（查看 / 历史 / 修改 / 回放）  【⭐️⭐️ 企业常用】
#     2a 查看 / 2b 修改 = ⭐️⭐️常用（调试、人工干预）
#     2c 回放 / 2d 查找 = ⭐️了解（多为调试场景，生产很少主动调）
# ═════════════════════════════════════════════

def demo_state_ops(graph):
    """
    ⭐️ StateSnapshot 关键字段：

    | 字段           | 说明                                          |
    |---------------|-----------------------------------------------|
    | values        | 当前 checkpoint 的状态值                        |
    | next          | 下一步要执行的节点元组，() 表示完成                |
    | config        | 含 thread_id, checkpoint_ns, checkpoint_id      |
    | metadata      | source ('input'/'loop'/'update'), writes, step  |
    | parent_config | 上一个 checkpoint 的配置，None = 第一个           |
    | tasks         | 待执行任务，含 id, name, error, interrupts       |
    """

    # ── 2a. 查看状态历史 ──
    config: RunnableConfig = {"configurable": {"thread_id": "2"}}
    graph.invoke({"foo": "", "bar": []}, config=config)

    print("\n=== 02a. 状态历史（最新在前）===")
    for snapshot in graph.get_state_history(config):
        step = snapshot.metadata.get("step", "?")
        source = snapshot.metadata.get("source", "?")
        print(f"  step={step:>2}, source={source:<7}, "
              f"next={str(snapshot.next):<12}, values={snapshot.values}")

    # ── 2b. 修改状态（创建新 checkpoint，不改原始）──
    config3: RunnableConfig = {"configurable": {"thread_id": "3"}}
    graph.invoke({"foo": "", "bar": []}, config=config3)

    # ⭐️ update_state 产生新 checkpoint，metadata.source = 'update'
    # 有 reducer 的 key 会累加而不是覆盖
    graph.update_state(config3, {"foo": "updated!", "bar": ["extra"]})

    state = graph.get_state(config3)
    print("\n=== 02b. update_state 后 ===")
    print(f"values: {state.values}")
    # foo='updated!', bar=['a','b','extra']（reducer 累加了 extra）
    print(f"source: {state.metadata.get('source')}")  # 'update'

    # ── 2c. 回放（Replay）──
    config4: RunnableConfig = {"configurable": {"thread_id": "4"}}
    graph.invoke({"foo": "", "bar": []}, config=config4)

    history = list(graph.get_state_history(config4))
    # 找到 node_a 刚执行完的 checkpoint
    before_b = next((s for s in history if s.next == ("node_b",)), None)
    if before_b:
        cp_id = before_b.config["configurable"]["checkpoint_id"]
        print(f"\n=== 02c. 从 checkpoint {cp_id[:8]}... 回放 ===")
        # ⭐️ 回放（Replay）原理：config 里同时给 thread_id + checkpoint_id，
        #    图就从该 checkpoint 加载状态，并从它之后继续执行：
        #      - checkpoint_id 之前的节点：不重跑，直接复用已保存的输出
        #      - checkpoint_id 之后的节点：重新执行
        #    input 传 None 表示不提供新输入，纯按已保存状态续跑。
        replay_config: RunnableConfig = {
            "configurable": {"thread_id": "4", "checkpoint_id": cp_id}
        }
        # ⚠️ 易错点：invoke() 没有 replay_config 这个参数！
        #    回放就是把带 checkpoint_id 的 config 当成普通 config 传进去。
        #    ✅ graph.invoke(None, replay_config)                # 位置参数 = config
        #    ✅ graph.invoke(None, config=replay_config)         # 关键字写 config=
        #    ❌ graph.invoke(None, replay_config=replay_config)  # 没这个参数，
        #       会被 **kwargs 吞掉，真正的 config 仍是 None，于是报错：
        #       ValueError: Checkpointer requires one or more of the following
        #       'configurable' keys: thread_id, checkpoint_ns, checkpoint_id
        result = graph.invoke(None, config=replay_config)
        print(f"回放结果: {result}")

    # ── 2d. 查找特定 checkpoint ──
    print("\n=== 02d. 查找 Checkpoint ===")
    # 按 next 查找
    before_b = next((s for s in history if s.next == ("node_b",)), None)
    print(f"node_b 执行前: {before_b.values if before_b else '未找到'}")

    # 按 step 查找
    step_2 = next((s for s in history if s.metadata.get("step") == 2), None)
    print(f"step=2:       {step_2.values if step_2 else '未找到'}")

    # 找 update_state 创建的
    forks = [s for s in history if s.metadata.get("source") == "update"]
    print(f"update 创建的: {len(forks)} 个")


# ═════════════════════════════════════════════
# 03. 短期记忆（同一 Thread 多轮对话 + 消息管理）  【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_short_term_memory():
    """
    ⭐️ 同一 thread_id 的多次 invoke 自动携带之前的全部消息。
    Checkpointer 在每个 super-step 保存完整消息历史，
    下次 invoke 时自动加载，实现"记忆"效果。
    """
    def echo_node(state: MessagesState):
        last_msg = state["messages"][-1].content
        return {"messages": [{"role": "assistant", "content": f"收到: {last_msg}"}]}

    builder = StateGraph(MessagesState)
    builder.add_node(echo_node)
    builder.add_edge(START, "echo_node")
    builder.add_edge("echo_node", END)

    chat_graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "chat-1"}}

    r1 = chat_graph.invoke(
        {"messages": [{"role": "user", "content": "你好，我是小明"}]}, config
    )
    print("\n=== 03a. 短期记忆 ===")
    print(f"第一轮消息数: {len(r1['messages'])}")  # 2

    r2 = chat_graph.invoke(
        {"messages": [{"role": "user", "content": "我叫什么？"}]}, config
    )
    print(f"第二轮消息数: {len(r2['messages'])}")  # 4（含前两轮全部消息）

    # ── 03b. 消息管理 ──
    # ⭐️ 长对话会撑爆 LLM 上下文窗口，必须管理消息历史

    # 策略1：删除指定消息（保留最近 3 条）
    # ⭐️ RemoveMessage 通过消息 id 删除，需要 add_messages reducer
    print("\n=== 03b. 消息管理 ===")
    print("删除指定: RemoveMessage(id=msg.id) 删除指定消息")
    print("清空全部: RemoveMessage(id=REMOVE_ALL_MESSAGES) 一键清空")
    print("裁剪:     trim_messages(state['messages'], max_tokens=128)")
    print("摘要:     SummarizationNode 自动总结早期消息")

    # ⚠️ 删除消息时注意：
    #   - 有些 LLM 要求消息历史以 user 消息开头
    #   - assistant 消息如果带 tool_calls，后面必须紧跟对应的 tool 消息


# ═════════════════════════════════════════════
# 04. Store 基础（跨 Thread 共享数据）  【⭐️ 了解即可】
#     InMemoryStore 仅用于 demo/测试，企业生产几乎不用内存 Store。
#     概念（namespace/put/search）要懂，API 细节不必死记。
# ═════════════════════════════════════════════

def demo_store_basic():
    """
    ⭐️ Checkpointer 只能保存 thread 内的状态
    ⭐️ Store 可以跨 thread 共享数据（用户偏好、全局知识）

    分工：
      Checkpointer → thread 内状态（短期）
      Store        → 跨 thread 数据（长期）
    """
    store = InMemoryStore()

    # ── Namespace（命名空间）──
    # ⭐️ 用 tuple 组织数据，可以是任意长度
    user_id = "user-001"
    ns = (user_id, "memories")

    # ── 写入：put(namespace, key, value) ──
    store.put(ns, str(uuid.uuid4()), {"food": "火锅", "level": "超爱"})
    store.put(ns, str(uuid.uuid4()), {"food": "寿司", "level": "喜欢"})

    # ── 读取：search() 返回 Item 列表 ──
    # ⭐️ 每个 Item 有：value / key / namespace / created_at / updated_at
    items = store.search(ns)
    print("\n=== 04a. Store 基本用法 ===")
    for item in items:
        print(f"  value={item.value}, namespace={item.namespace}")

    # ── Namespace 前缀匹配 ──
    # ⭐️ search(("alice",)) 会匹配 ("alice","memories")、("alice","prefs") 等
    store.put(("alice", "memories"), "1", {"text": "喜欢披萨"})
    store.put(("alice", "memories"), "2", {"text": "喜欢编程"})
    store.put(("alice", "preferences"), "3", {"text": "深色模式"})

    all_alice = store.search(("alice",))            # 前缀匹配 → 3 条
    only_mem = store.search(("alice", "memories"))   # 精确匹配 → 2 条
    print("\n=== 04b. Namespace ===")
    print(f'("alice",) 前缀匹配: {len(all_alice)} 条')
    print(f'("alice","memories") 精确: {len(only_mem)} 条')

    # ── 分页 ──
    page = store.search(("alice", "memories"), limit=1, offset=0)
    print(f"分页 limit=1 offset=0: {[i.value for i in page]}")

    # ── 列举 namespace ──
    nss = store.list_namespaces(prefix=("alice",), max_depth=2)
    print(f"alice 下的 namespace: {nss}")

    # ⭐️ Namespace 三个注意点：
    # 1. 前缀匹配不是精确匹配，("alice",) 会命中所有 alice 开头的
    # 2. 超出 limit 的结果静默丢弃，不会报错
    # 3. 排序因后端而异：InMemoryStore 按插入顺序，PostgresStore 按 updated_at 降序

    return store


# ═════════════════════════════════════════════
# 05. Graph 中使用 Checkpointer + Store  【⭐️⭐️ 企业常用】
#     "跨 thread 长期记忆"这个概念企业一定会遇到；
#     但具体存储常用自建表替代（见 08），这里重在理解机制。
# ═════════════════════════════════════════════

def demo_graph_with_store():
    """
    ⭐️ 编译时同时传入 checkpointer 和 store。
    节点内通过 store 引用访问。

    这里演示一个完整可运行的例子（不需要 LLM）。
    """
    store = InMemoryStore()

    # ── 节点：读取记忆 + 写入新记忆 ──
    def chat_node(state: MessagesState, config: RunnableConfig):
        user_id = config["configurable"]["user_id"]
        ns = (user_id, "memories")

        # ⭐️ 读取记忆
        memories = store.search(ns)
        info = ", ".join(d.value.get("text", "") for d in memories)

        last_msg = state["messages"][-1].content
        if info:
            reply = f"[已记住: {info}] 你说: {last_msg}"
        else:
            reply = f"你说: {last_msg}"

        # ⭐️ 写入新记忆
        if "记住" in last_msg:
            store.put(ns, str(uuid.uuid4()), {"text": last_msg.replace("记住", "").strip()})

        return {"messages": [{"role": "assistant", "content": reply}]}

    builder = StateGraph(MessagesState)
    builder.add_node(chat_node)
    builder.add_edge(START, "chat_node")
    builder.add_edge("chat_node", END)

    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer, store=store)

    # ── 第一次对话：告诉 AI 记住一些东西 ──
    config1 = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    r1 = graph.invoke(
        {"messages": [{"role": "user", "content": "记住 我喜欢火锅"}]}, config1
    )
    print("\n=== 05. Graph 中使用 Store ===")
    print(f"第一轮: {r1['messages'][-1].content}")

    # ── 第二次对话：同一用户，不同 thread ──
    # ⭐️ thread_id 不同，但 user_id 相同 → 记忆跨 thread 共享
    config2 = {"configurable": {"thread_id": "t2", "user_id": "u1"}}
    r2 = graph.invoke(
        {"messages": [{"role": "user", "content": "我喜欢吃什么？"}]}, config2
    )
    print(f"第二轮（不同 thread）: {r2['messages'][-1].content}")
    # 记忆被带过来了！


# ═════════════════════════════════════════════
# 06. 语义搜索（千问 Embedding）  【⭐️ 了解即可】
#     "记忆要按语义检索"的思想很重要，但企业生产走专用向量库
#     （pgvector / Milvus / 等），不靠 InMemoryStore 的内置索引。
# ═════════════════════════════════════════════

def demo_semantic_search():
    """
    ⭐️ 记忆多了以后，精确匹配不够用，需要按"意思"搜索。

    启用方式：创建 Store 时传入 index 配置
      - embed:  embedding 模型
      - dims:   向量维度
      - fields: 要嵌入哪些字段（"$" = 整个 value）

    这里用千问的 text-embedding-v3 模型。
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("\n=== 06. 语义搜索 ===")
        print("跳过：未配置 DASHSCOPE_API_KEY")
        return

    from langchain_community.embeddings import DashScopeEmbeddings

    # ⭐️ 创建带语义搜索的 Store
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v3",
        dashscope_api_key=api_key,
    )

    store = InMemoryStore(
        index={
            "embed": embeddings,
            "dims": 1024,       # text-embedding-v3 输出维度
            "fields": ["$"],    # "$" = 嵌入整个 value
        }
    )

    # 写入一些记忆
    ns = ("user_1", "memories")
    store.put(ns, "1", {"text": "我喜欢吃火锅，尤其是麻辣锅底"})
    store.put(ns, "2", {"text": "我是个程序员，主要写 Python"})
    store.put(ns, "3", {"text": "周末喜欢爬山和打羽毛球"})

    # ⭐️ 语义搜索：用自然语言查询
    print("\n=== 06. 语义搜索 ===")
    results = store.search(ns, query="用户平时做什么运动", limit=2)
    print("查询: '用户平时做什么运动'")
    for r in results:
        print(f"  -> {r.value}")

    results2 = store.search(ns, query="吃饭相关", limit=2)
    print("查询: '吃饭相关'")
    for r in results2:
        print(f"  -> {r.value}")

    # ⭐️ 嵌入粒度控制：
    # fields=["$"]              → 嵌入整个 value
    # fields=["text"]           → 只嵌入 text 字段
    # store.put(..., index=False)   → 不嵌入（仍可按 namespace 检索）
    # store.put(..., index=["text"])→ 只嵌入指定字段


# ═════════════════════════════════════════════
# 07. 生产环境：PostgreSQL 实战  【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_postgres():
    """
    ⭐️ 生产环境推荐架构（PostgreSQL 一把梭）：

    PostgreSQL
    ├── checkpointer 表：PostgresSaver 自动创建（图执行状态）
    ├── store 表：PostgresStore 自动创建（长期记忆 + pgvector 语义搜索）
    └── conversations 表：你自己建（每轮对话一行）

    也就是：
      - Checkpointer → PostgresSaver（必须）
      - Store        → PostgresStore（80% 场景够用）或自己建表（20% 高级场景）
      - 对话记录      → conversations 表（必须自己存）
    """
    db_uri = os.getenv("DB_URI")
    if not db_uri:
        print("\n=== 07. PostgreSQL 实战 ===")
        print("跳过：未配置 DB_URI（需要 Docker 运行 PostgreSQL）")
        print("启动命令: docker run -d --name langgraph-postgres \\")
        print("  -e POSTGRES_USER=langgraph -e POSTGRES_PASSWORD=langgraph123 \\")
        print("  -e POSTGRES_DB=langgraph -p 5432:5432 pgvector/pgvector:pg16")
        return

    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    # ── 7a. Checkpointer：PostgresSaver ──
    # ⭐️ 首次使用要调 setup() 建表
    with PostgresSaver.from_conn_string(db_uri) as checkpointer:
        checkpointer.setup()

        # 用 PostgresSaver 编译图
        workflow = StateGraph(State)
        workflow.add_node(node_a)
        workflow.add_node(node_b)
        workflow.add_edge(START, "node_a")
        workflow.add_edge("node_a", "node_b")
        workflow.add_edge("node_b", END)
        pg_graph = workflow.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "pg-1"}}
        result = pg_graph.invoke({"foo": "", "bar": []}, config=config)

        print("\n=== 07a. PostgresSaver ===")
        print(f"执行结果: {result}")

        # ⭐️ get_state / get_state_history 和 InMemorySaver 完全一样
        snapshot = pg_graph.get_state(config)
        print(f"最新快照: values={snapshot.values}, next={snapshot.next}")

        # ⭐️ 数据持久化到磁盘了，重启不丢
        # PostgreSQL 里的 checkpoint 表由 PostgresSaver 自动管理

    # ── 7b. 对话记录：必须自己存 ──
    # ⭐️ Checkpointer 存的是图执行状态（序列化 blob），不适合业务查询。
    # 每轮对话你都要自己 INSERT 到 conversations 表。
    with psycopg.connect(db_uri) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id     VARCHAR(64) NOT NULL,
                thread_id   VARCHAR(64) NOT NULL,
                role        VARCHAR(16) NOT NULL,
                content     TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # 模拟写入一条对话记录
        conn.execute("""
            INSERT INTO conversations (user_id, thread_id, role, content)
            VALUES (%s, %s, %s, %s)
        """, ("user_1", "pg-1", "user", "你好"))

        conn.execute("""
            INSERT INTO conversations (user_id, thread_id, role, content)
            VALUES (%s, %s, %s, %s)
        """, ("user_1", "pg-1", "assistant", "你好！"))

        # ⭐️ 这就是 Checkpointer 做不到的业务查询
        rows = conn.execute(
            "SELECT role, content FROM conversations WHERE user_id = %s",
            ("user_1",)
        ).fetchall()

        print("\n=== 07b. 对话记录（自己存的）===")
        for row in rows:
            print(f"  [{row[0]}] {row[1]}")


# ═════════════════════════════════════════════
# 08. 生产环境：PostgresStore vs 自己建表  【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

def demo_production_memory():
    """
    ⭐️ 长期记忆的存储方案选择：

    ┌─────────────────┬──────────────────────┬───────────────────────┐
    │                 │  PostgresStore       │  自己建 memories 表     │
    │                 │  （推荐 80% 场景）    │  （推荐 20% 高级场景）   │
    ├─────────────────┼──────────────────────┼───────────────────────┤
    │ 表结构           │ LangGraph 自动建      │ 你自己设计              │
    │ API             │ runtime.store.put    │ 直连 pool.execute      │
    │                 │ runtime.store.search │ SQL + 向量任意组合      │
    │ 语义搜索         │ ✅ pgvector          │ ✅ pgvector            │
    │ 遗忘/衰减        │ ❌ 要写定时任务清表    │ ✅ priority + TTL      │
    │ 去重/合并         │ ❌ 自己逻辑           │ ✅ UPSERT              │
    │ 和业务数据 JOIN   │ ❌ 表结构不透明       │ ✅ 同库同表可直接 JOIN   │
    │ 框架耦合         │ 绑定 LangGraph       │ 独立，换框架不影响       │
    └─────────────────┴──────────────────────┴───────────────────────┘

    ⭐️ 什么时候必须自己建表？
      - 记忆要和业务数据关联查询（比如 JOIN users 表）
      - 需要优先级 / 衰减 / 合并等高级生命周期管理
      - 记忆系统是你产品的核心竞争力
      - 团队不想依赖 LangGraph 内部表结构
    """
    print("\n=== 08. 生产环境：记忆方案选择 ===")

    # ── 方案A：PostgresStore（大多数项目推荐）──
    print("方案A -- PostgresStore（推荐大多数项目）:")
    print("  编译时传 checkpointer + store")
    print("  store = PostgresStore.from_conn_string(DB_URI)")
    print("  store.setup()  # 首次建表")
    print("  graph = builder.compile(checkpointer=PostgresSaver(...), store=store)")
    print("  节点内: runtime.store.aput() / runtime.store.asearch()")
    print()

    # ── 方案B：自己建 memories 表 ──
    print("方案B -- 自己建表（记忆是产品核心时）:")
    print("  自己建 memories 表（含 priority/category/embedding/accessed_at）")
    print("  graph = builder.compile(checkpointer=checkpointer)  # 没有 store=")
    print("  节点内直连数据库：pool.fetch(SQL, user_id)")
    print()

    # ── 衰减策略 ──
    print("记忆衰减策略（定时任务）:")
    print("  temp   超过 7 天未访问 -> 删除")
    print("  normal 超过 30 天未访问 -> 降级为 temp")
    print("  core   永不清除")


# ═════════════════════════════════════════════
# 09. Durability 模式 + Checkpointer 选型  【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

def demo_misc():
    """
    ⭐️ Durability 模式（持久化级别）：

    | 模式   | 行为                               | 场景         |
    |-------|-----------------------------------|-------------|
    | exit  | 图退出时才保存                      | 长时间运行的图  |
    | async | 异步保存，下一步执行同时写入（推荐）  | 大多数场景 ⭐️ |
    | sync  | 同步保存，写完再执行下一步            | 最高安全，最慢 |

    用法：graph.stream({...}, durability="sync")

    ⭐️ Checkpointer 选型：

    | 实现                      | 场景    | 安装包                         |
    |--------------------------|--------|-------------------------------|
    | InMemorySaver            | 开发调试 | langgraph（内置）               |
    | SqliteSaver              | 本地实验 | langgraph-checkpoint-sqlite   |
    | PostgresSaver（推荐生产） | 生产    | langgraph-checkpoint-postgres |
    | CosmosDBSaver            | Azure   | langchain-azure-cosmosdb      |
    """
    print("\n=== 09. Durability + Checkpointer 选型 ===")
    print('  Durability: "exit"(快) < "async"(推荐) < "sync"(最安全)')
    print("  Checkpointer: InMemory(开发) -> Sqlite(实验) -> Postgres(生产)")


# ═════════════════════════════════════════════
# 10. 动手练习指南
# ═════════════════════════════════════════════

def practice_guide():
    """
    ⭐️ 按"企业实战优先级"排（不是按章节顺序）：

    ⭐️⭐️⭐️ 企业核心（必吃透，几乎每个项目都用）：
       - 01. Checkpoint 基础：super-step、reducer、自动快照——有状态图的地基
       - 03. 短期记忆：多轮对话消息累加 + trim/摘要管理——对话类产品命脉
       - 07. PostgreSQL 实战：PostgresSaver 做生产 checkpointer + 对话自己落库

    ⭐️⭐️ 企业常用（要懂，偏认知/选型，不一定天天手写）：
       - 02. State 操作：get_state/get_state_history（调试监控）、update_state（人工干预）
       - 05. Graph + Store：理解"跨 thread 长期记忆"机制
       - 08. 记忆方案选型：PostgresStore vs 自建表，知道什么时候该自建
       - 09. Durability + Checkpointer 选型：上线前的两个选择题

    ⭐️ 了解即可（企业几乎用不到，多为 demo / 调试 / 被自建替代）：
       - 02c/02d. 回放与查找 checkpoint：调试场景，生产很少主动调
       - 04. Store 基础（InMemoryStore）：仅 demo，生产不用内存 Store
       - 06. 语义搜索（内存向量）：生产走专用向量库，这里只为体验"按语义检索"
    """
    print("\n=== 10. 学习路线（按企业优先级）===")
    print("⭐️⭐️⭐️ 核心: 01 Checkpoint -> 03 短期记忆 -> 07 PostgreSQL")
    print("⭐️⭐️   常用: 02 State操作 -> 05 Graph+Store -> 08 记忆选型 -> 09 选型")
    print("⭐️     了解: 02c/d 回放查找 -> 04 内存Store -> 06 内存语义搜索")


# ═════════════════════════════════════════════
# 主入口
# ═════════════════════════════════════════════

if __name__ == "__main__":
    # 必练
    graph = demo_checkpoint()           # 01
    demo_state_ops(graph)               # 02
    demo_short_term_memory()            # 03

    # 建议练
    demo_store_basic()                  # 04
    demo_graph_with_store()             # 05
    demo_semantic_search()              # 06
    demo_postgres()                     # 07

    # 了解即可
    demo_production_memory()            # 08
    demo_misc()                         # 09
    practice_guide()                    # 10