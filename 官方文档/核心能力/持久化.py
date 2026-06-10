"""
LangGraph 持久化 (Persistence) — 完整示例与详解
================================================

⭐️ 核心概念：
  - Checkpointer（检查点保存器）：每个 super-step（超步）自动保存图状态的快照
  - Thread（线程）：通过 thread_id 标识，是 checkpoint 的一级分组键
  - Super-step（超步）：图的一次"滴答"，同一超步内的节点并行执行
  - Store（存储）：跨 thread 共享数据的长期记忆

⭐️ 持久化的四大用途：
  1. Human-in-the-loop：检查、中断、审批图的执行步骤
  2. Memory（记忆）：同一 thread 内的多轮对话上下文保持
  3. Time travel（时间旅行）：回放、回溯、分叉历史状态
  4. Fault tolerance（容错）：节点失败后从最后成功的超步恢复

参考文档：
  - https://docs.langchain.com/oss/python/langgraph/persistence
  - https://docs.langchain.com/oss/python/langgraph/add-memory
"""

import uuid
from dataclasses import dataclass
from operator import add

from langchain_core.messages import RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import START, END
from langgraph.graph import StateGraph, MessagesState
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.store.memory import InMemoryStore
from typing_extensions import TypedDict, Annotated


# ═════════════════════════════════════════════
# 一、状态定义
# ═════════════════════════════════════════════

class State(TypedDict):
    """简单状态：foo 覆盖写入，bar 通过 reducer 累加"""
    foo: str
    bar: Annotated[list[str], add]  # ⭐️ reducer：新值追加而非覆盖


def node_a(state: State):
    return {"foo": "a", "bar": ["a"]}


def node_b(state: State):
    return {"foo": "b", "bar": ["b"]}


# ═════════════════════════════════════════════
# 二、构建图 + 基本 Checkpoint 机制
# ═════════════════════════════════════════════

workflow = StateGraph(State)
workflow.add_node(node_a)
workflow.add_node(node_b)
workflow.add_edge(START, "node_a")
workflow.add_edge("node_a", "node_b")
workflow.add_edge("node_b", END)

# ⭐️ 编译时传入 checkpointer 即可启用持久化
checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)


def demo_basic_checkpoint():
    """
    ⭐️ 执行图时必须指定 thread_id

    一次 START -> node_a -> node_b -> END 的执行产生 4 个 checkpoint：
      1. 空 checkpoint（next = __start__，step = -1）
      2. 用户输入后（next = node_a，step = 0）
      3. node_a 执行后（next = node_b，step = 1） — bar=['a']（reducer 累加）
      4. node_b 执行后（next = ()，step = 2）     — bar=['a','b']

    ⭐️ Pending writes 机制：
      同一超步内如果节点 A 成功但节点 B 失败，A 的输出已经持久化。
      恢复时不会重跑 A，只重跑 B。
    """
    config: RunnableConfig = {"configurable": {"thread_id": "1"}}

    result = graph.invoke({"foo": "", "bar": []}, config=config)
    print("=== 基本执行结果 ===")
    print(f"最终状态: {result}")
    # {'foo': 'b', 'bar': ['a', 'b']}

    # ⭐️ 获取最新状态快照
    snapshot = graph.get_state(config)
    print(f"values: {snapshot.values}")
    print(f"next:   {snapshot.next}")    # () 表示图执行完毕
    print(f"step:   {snapshot.metadata.get('step')}")


# ═════════════════════════════════════════════
# 三、获取状态 & 状态历史
# ═════════════════════════════════════════════

def demo_state_history():
    """
    ⭐️ StateSnapshot 关键字段：

    | 字段           | 类型                  | 说明                                      |
    |---------------|----------------------|-------------------------------------------|
    | values        | dict                 | 当前 checkpoint 的状态值                    |
    | next          | tuple[str, ...]      | 下一步要执行的节点，() 表示完成               |
    | config        | dict                 | 含 thread_id, checkpoint_ns, checkpoint_id  |
    | metadata      | dict                 | source ('input'/'loop'/'update'), writes, step |
    | created_at    | str                  | ISO 8601 时间戳                             |
    | parent_config | dict or None         | 上一个 checkpoint 的配置，None = 第一个       |
    | tasks         | tuple[PregelTask]    | 待执行任务，含 id, name, error, interrupts   |
    """
    config: RunnableConfig = {"configurable": {"thread_id": "2"}}
    graph.invoke({"foo": "", "bar": []}, config=config)

    print("\n=== 状态历史（最新在前）===")
    for snapshot in graph.get_state_history(config):
        step = snapshot.metadata.get("step", "?")
        source = snapshot.metadata.get("source", "?")
        print(f"  step={step:>2}, source={source:<7}, next={str(snapshot.next):<12}, "
              f"values={snapshot.values}")

    # ⭐️ 获取指定 checkpoint_id 的快照
    history = list(graph.get_state_history(config))
    if len(history) > 1:
        specific_id = history[1].config["configurable"]["checkpoint_id"]
        old_snapshot = graph.get_state(
            {"configurable": {"thread_id": "2", "checkpoint_id": specific_id}}
        )
        print(f"\n指定 checkpoint_id 快照: step={old_snapshot.metadata.get('step')}")


# ═════════════════════════════════════════════
# 四、修改状态（Time Travel — Fork）
# ═════════════════════════════════════════════

def demo_update_state():
    """
    ⭐️ update_state() 创建新 checkpoint 来修改状态，不修改原始 checkpoint

    - 值会经过 reducer 处理（有 reducer 的 key 是累加，不是覆盖）
    - 可选 as_node 参数：假装更新来自某个节点，影响恢复后执行路径
    """
    config: RunnableConfig = {"configurable": {"thread_id": "3"}}
    graph.invoke({"foo": "", "bar": []}, config=config)

    # 修改状态（产生新 checkpoint，metadata.source = 'update'）
    graph.update_state(config, {"foo": "updated!", "bar": ["extra"]})

    state = graph.get_state(config)
    print("\n=== update_state 后 ===")
    print(f"values: {state.values}")
    # foo='updated!', bar=['a','b','extra']（reducer 累加了）
    print(f"source: {state.metadata.get('source')}")
    # 'update'


# ═════════════════════════════════════════════
# 五、回放（Replay）
# ═════════════════════════════════════════════

def demo_replay():
    """
    ⭐️ 传入历史 checkpoint_id 即可从该点重放

    - checkpoint 之前的节点：不重跑（结果已保存）
    - checkpoint 之后的节点：重新执行（包括 LLM 调用、中断等）
    """
    config: RunnableConfig = {"configurable": {"thread_id": "4"}}
    graph.invoke({"foo": "", "bar": []}, config=config)

    history = list(graph.get_state_history(config))

    # 找到 node_a 刚执行完的 checkpoint（next 中包含 node_b）
    before_node_b = next((s for s in history if s.next == ("node_b",)), None)
    if before_node_b:
        cp_id = before_node_b.config["configurable"]["checkpoint_id"]
        print(f"\n=== 从 checkpoint {cp_id[:8]}... 回放 ===")

        replay_config = {
            "configurable": {"thread_id": "4", "checkpoint_id": cp_id}
        }
        result = graph.invoke(None, replay_config)
        print(f"回放结果: {result}")


# ═════════════════════════════════════════════
# 六、短期记忆（同一 Thread 内多轮对话）
# ═════════════════════════════════════════════

def demo_short_term_memory():
    """
    ⭐️ 同一 thread_id 的多次 invoke 自动携带之前的全部消息

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
    print("\n=== 短期记忆 ===")
    print(f"第一轮消息数: {len(r1['messages'])}")  # 2

    r2 = chat_graph.invoke(
        {"messages": [{"role": "user", "content": "我叫什么？"}]}, config
    )
    print(f"第二轮消息数: {len(r2['messages'])}")  # 4（含前两轮全部消息）


# ═════════════════════════════════════════════
# 七、消息管理（裁剪 / 删除 / 摘要）
# ═════════════════════════════════════════════

def demo_manage_messages():
    """
    ⭐️ 长对话会撑爆 LLM 上下文窗口，必须管理消息历史

    三种策略：
      1. 裁剪（Trim）：按 token 数截断，保留最近的消息
      2. 删除（Delete）：用 RemoveMessage 删除指定消息
      3. 摘要（Summarize）：用 LLM 总结早期消息，替换为摘要
    """

    # --- 方式1：删除指定消息 ---
    def delete_old_messages(state: MessagesState):
        messages = state["messages"]
        if len(messages) > 3:
            # ⭐️ RemoveMessage 通过消息 id 删除（需要 add_messages reducer）
            return {"messages": [RemoveMessage(id=m.id) for m in messages[:-3]]}
        return {}

    # --- 方式1b：删除全部消息 ---
    def delete_all_messages(state: MessagesState):
        # ⭐️ REMOVE_ALL_MESSAGES 是一个特殊常量，一键清空
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)]}

    print("\n=== 消息管理 ===")
    print("策略1 - 删除: RemoveMessage(id=msg.id) 删除指定消息")
    print("策略1b- 清空: RemoveMessage(id=REMOVE_ALL_MESSAGES) 清空全部")
    print("策略2 - 裁剪: 用 trim_messages() 按 token 数保留最近消息")
    print("策略3 - 摘要: 用 SummarizationNode 自动总结早期消息")

    # ⚠️ 删除消息时注意：
    #   - 有些 LLM 要求消息历史以 user 消息开头
    #   - assistant 消息如果带 tool_calls，后面必须紧跟对应的 tool 消息


# ═════════════════════════════════════════════
# 八、长期记忆（Store — 跨 Thread 共享数据）
# ═════════════════════════════════════════════

def demo_store_basic():
    """
    ⭐️ Checkpointer 只能保存 thread 内的状态
    ⭐️ Store 可以跨 thread 共享数据（如用户偏好、全局知识）

    Store 和 Checkpointer 的分工：
      - Checkpointer → thread 内的状态持久化（短期记忆）
      - Store        → 跨 thread 的数据共享（长期记忆）
    """
    store = InMemoryStore()

    # ── Namespace（命名空间）──
    # ⭐️ Store 用 tuple 作为命名空间，组织数据
    # 可以是任意长度，不限于用户维度
    user_id = "user-001"
    namespace = (user_id, "memories")  # ("user-001", "memories")

    # ── 写入 ──
    # put(namespace, key, value)
    # key 是这条记忆的唯一标识，value 是内容字典
    memory_id = str(uuid.uuid4())
    store.put(namespace, memory_id, {"food": "火锅", "level": "超爱"})

    # ── 读取 ──
    # search() 返回 Item 列表，每个 Item 有 value/key/namespace/created_at/updated_at
    memories = store.search(namespace)
    item = memories[-1]
    print("\n=== Store 基本用法 ===")
    print(f"value:     {item.value}")       # {'food': '火锅', 'level': '超爱'}
    print(f"key:       {item.key}")         # uuid
    print(f"namespace: {item.namespace}")   # ['user-001', 'memories']

    return store


def demo_store_namespace():
    """
    ⭐️ Namespace 三个关键行为：

    1. 前缀匹配：search(("alice",)) 会返回 ("alice","memories") 下的内容
    2. limit 静默截断：超出 limit 的结果不会报错，直接丢弃
    3. 排序因后端而异：
       - InMemoryStore  → 插入顺序（最新在最后）
       - PostgresStore   → updated_at 降序（最新在最前）
    """
    store = InMemoryStore()

    # 写入不同 namespace
    store.put(("alice", "memories"), "1", {"text": "喜欢披萨"})
    store.put(("alice", "memories"), "2", {"text": "喜欢编程"})
    store.put(("alice", "preferences"), "3", {"text": "深色模式"})

    # ⭐️ 前缀匹配：("alice",) 会匹配所有以 alice 开头的 namespace
    all_alice = store.search(("alice",))
    print("\n=== Namespace 前缀匹配 ===")
    print(f'("alice",) 匹配到 {len(all_alice)} 条')
    for item in all_alice:
        print(f"  namespace={item.namespace}, value={item.value}")

    # 精确匹配：只取 ("alice", "memories")
    only_memories = store.search(("alice", "memories"))
    print(f'("alice","memories") 精确匹配到 {len(only_memories)} 条')

    # ── 分页 ──
    # 用 limit + offset 翻页
    page = store.search(("alice", "memories"), limit=1, offset=0)
    print(f"分页 limit=1 offset=0: {[i.value for i in page]}")

    # ── 列举所有 namespace ──
    # list_namespaces() 查看当前有哪些 namespace
    namespaces = store.list_namespaces(prefix=("alice",), max_depth=2)
    print(f"alice 下的 namespace: {namespaces}")


# ═════════════════════════════════════════════
# 九、Store 语义搜索
# ═════════════════════════════════════════════

def demo_store_semantic_search():
    """
    ⭐️ 记忆多了以后，精确匹配不够用，需要按"意思"搜索

    启用方式：创建 Store 时传入 index 配置（embedding 模型 + 维度 + 字段）

    注意：语义搜索需要 embedding 模型，这里展示配置方式。
    实际运行需要安装 langchain-openai 并配置 OPENAI_API_KEY。
    """
    print("\n=== Store 语义搜索 ===")

    # ⭐️ 配置语义搜索的 Store
    semantic_store_config = """
    from langchain.embeddings import init_embeddings
    from langgraph.store.memory import InMemoryStore

    store = InMemoryStore(
        index={
            "embed": init_embeddings("openai:text-embedding-3-small"),
            "dims": 1536,
            "fields": ["$",]           # "$" 表示嵌入整个 value
        }
    )
    """
    print(f"配置方式:\n{semantic_store_config}")

    # 写入后用自然语言搜索
    usage_code = """
    store.put(("user_1", "memories"), "1", {"text": "我喜欢吃火锅"})
    store.put(("user_1", "memories"), "2", {"text": "我是个程序员"})

    # ⭐️ 用 query 参数做语义搜索
    results = store.search(
        ("user_1", "memories"),
        query="用户饿了想吃什么",  # 自然语言查询
        limit=3                     # 返回最相关的前 3 条
    )
    """
    print(f"使用方式:\n{usage_code}")

    # ⭐️ 控制嵌入粒度
    print("\n嵌入粒度控制:")
    print('  fields=["$"]                  → 嵌入整个 value')
    print('  fields=["text"]               → 只嵌入 text 字段')
    print('  store.put(..., index=False)   → 不嵌入（仍可按 namespace 检索）')
    print('  store.put(..., index=["text"])→ 只嵌入指定字段')


# ═════════════════════════════════════════════
# 十、在 Graph 中同时使用 Checkpointer + Store
# ═════════════════════════════════════════════

def demo_graph_with_store():
    """
    ⭐️ Checkpointer + Store 联合使用是生产环境标配

    编译时同时传入两者，节点通过 Runtime 对象访问 Store。
    """
    @dataclass
    class Context:
        user_id: str

    # 代码模板（展示结构，不含实际 LLM 调用）
    template = '''
    from dataclasses import dataclass
    from langgraph.runtime import Runtime
    from langgraph.graph import StateGraph, MessagesState, START

    @dataclass
    class Context:
        user_id: str

    async def chat_node(state: MessagesState, runtime: Runtime[Context]):
        user_id = runtime.context.user_id
        namespace = (user_id, "memories")

        # ⭐️ 读取记忆（语义搜索）
        memories = await runtime.store.asearch(
            namespace,
            query=state["messages"][-1].content,
            limit=3
        )
        info = "\\n".join(d.value.get("text", "") for d in memories)

        # ... 用 memories 构建 prompt，调用 LLM ...

        # ⭐️ 写入新记忆
        await runtime.store.aput(
            namespace,
            str(uuid.uuid4()),
            {"text": "用户喜欢深色模式"}
        )
        return {"messages": [response]}

    store = InMemoryStore()
    checkpointer = InMemorySaver()

    builder = StateGraph(MessagesState, context_schema=Context)
    builder.add_node(chat_node)
    builder.add_edge(START, "chat_node")
    graph = builder.compile(checkpointer=checkpointer, store=store)

    # ⭐️ 调用时传 context（含 user_id）+ config（含 thread_id）
    # thread_id 控制对话隔离，user_id 控制记忆共享
    graph.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        {"configurable": {"thread_id": "1"}},
        context=Context(user_id="1"),
    )
    '''
    print("\n=== Graph 中使用 Store 模板 ===")
    print(template)


# ═════════════════════════════════════════════
# 十一、生产级记忆架构：自己管记忆
# ═════════════════════════════════════════════

def demo_production_memory():
    """
    ⭐️ 生产环境核心原则：Checkpointer 管图状态，记忆自己管

    LangGraph Store 的能力上限太低：
      - 只有 put / search / list_namespaces
      - 没有遗忘、衰减、去重、合并
      - 没有多维度筛选（标签、时间、来源、优先级）
      - 绑死在 LangGraph，换框架记忆全丢

    ⭐️ 生产级做法：节点内直连自己的数据库，完全绕过 Store

    分工：
      Checkpointer → 图执行状态（哪个节点、中断点、恢复点）
      自定义存储    → 长期记忆（用户偏好、知识、历史行为）
    """

    # ── 1. 数据库表设计（PostgreSQL 示例）──
    schema_sql = """
    -- ⭐️ 自己的 memories 表，完全可控
    CREATE TABLE memories (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     VARCHAR(64) NOT NULL,
        content     TEXT NOT NULL,            -- 记忆内容
        category    VARCHAR(32),              -- 分类：preference / fact / event
        priority    VARCHAR(16) DEFAULT 'normal',  -- core / normal / temp
        source_thread_id VARCHAR(64),         -- 来自哪次对话（溯源）
        embedding   VECTOR(1536),             -- 向量（配合 pgvector 做语义搜索）
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        accessed_at TIMESTAMPTZ DEFAULT NOW(), -- 最后访问时间（用于衰减）
        access_count INT DEFAULT 0            -- 访问次数（热度）
    );

    -- 按用户 + 优先级 + 时间 组合查询
    CREATE INDEX idx_memories_user_priority
        ON memories (user_id, priority, created_at DESC);

    -- 向量相似度搜索（pgvector）
    CREATE INDEX idx_memories_embedding
        ON memories USING ivfflat (embedding vector_cosine_ops);
    """
    print("\n=== 生产级记忆架构 ===")
    print("数据库表设计:")
    print(schema_sql)

    # ── 2. 记忆生命周期管理 ──
    lifecycle = """
    ⭐️ 记忆不是存了就完了，需要完整的生命周期：

    1. 提取（Extract）：  从对话中提取值得记住的信息
    2. 去重（Dedup）：    和已有记忆比较，重复的合并/更新
    3. 存储（Store）：    写入数据库 + 生成 embedding
    4. 检索（Retrieve）： 按语义 + 优先级 + 时间组合查询
    5. 衰减（Decay）：    临时记忆超期自动降级或删除
    6. 合并（Consolidate）：多条碎片记忆合并为一条完整记忆
    """
    print(lifecycle)

    # ── 3. 生产级节点实现模板 ──
    node_template = '''
    import asyncpg
    from langgraph.graph import StateGraph, MessagesState, START
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async def chat_with_memory(state: MessagesState, config):
        """生产级记忆节点：直连数据库，不走 LangGraph Store"""
        user_id = config["configurable"]["user_id"]
        pool = config["__db_pool__"]  # 应用启动时创建的连接池

        # ── 检索：组合查询（语义 + 优先级 + 时间衰减）──
        memories = await pool.fetch("""
            SELECT content, priority, category,
                   (access_count * 1.0 /
                       GREATEST(1, EXTRACT(DAY FROM NOW() - accessed_at))
                   ) AS relevance_score
            FROM memories
            WHERE user_id = $1
              AND (priority = 'core'
                   OR accessed_at > NOW() - INTERVAL '30 days')
            ORDER BY relevance_score DESC
            LIMIT 10
        """, user_id)

        # ── 用检索到的记忆构建 prompt ──
        memory_text = "\\n".join(f"- [{m['priority']}] {m['content']}" for m in memories)
        system_msg = f"以下是关于用户的已知信息:\\n{memory_text}"

        response = await model.ainvoke(
            [{"role": "system", "content": system_msg}, *state["messages"]]
        )

        # ── 提取新记忆（可交给 LLM 判断哪些值得记住）──
        new_memory = await extract_memory(state["messages"][-1].content, response)
        if new_memory:
            await pool.execute("""
                INSERT INTO memories (user_id, content, category, priority,
                                      source_thread_id, embedding)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT ON CONSTRAINT memories_user_content_unique
                DO UPDATE SET
                    content = EXCLUDED.content,
                    priority = EXCLUDED.priority,
                    accessed_at = NOW(),
                    access_count = memories.access_count + 1
            """, user_id, new_memory["content"], new_memory["category"],
                 new_memory["priority"],
                 config["configurable"]["thread_id"],
                 new_memory["embedding"])

        return {"messages": [response]}

    # ── 编译：只用 checkpointer，不传 store ──
    checkpointer = AsyncPostgresSaver.from_conn_string(DB_URI)
    graph = builder.compile(checkpointer=checkpointer)
    #                         ↑ 没有 store=    记忆自己管
    '''
    print("生产级节点实现:")
    print(node_template)

    # ── 4. LangGraph Store vs 自己管 对比 ──
    comparison = """
    ┌────────────────┬──────────────────────┬──────────────────────┐
    │                │  LangGraph Store     │  自己管（生产推荐）     │
    ├────────────────┼──────────────────────┼──────────────────────┤
    │ 图执行状态      │  不归 Store 管        │  Checkpointer 管      │
    │ 存储结构        │  固定：namespace+dict │  自定义表结构          │
    │ 查询能力        │  语义搜索 or 列举     │  SQL + 向量任意组合    │
    │ 遗忘/衰减       │  ❌ 没有              │  ✅ 自己写             │
    │ 去重/合并       │  ❌ 没有              │  ✅ UPSERT / LLM 合并  │
    │ 溯源            │  ❌ 没有              │  ✅ source_thread_id   │
    │ 优先级          │  ❌ 扁平              │  ✅ priority 字段      │
    │ 框架耦合        │  绑死 LangGraph       │  独立，换框架不影响     │
    │ 迁移成本        │  高（数据格式固定）    │  低（标准数据库）       │
    └────────────────┴──────────────────────┴──────────────────────┘
    """
    print(comparison)

    # ── 5. 衰减策略示例 ──
    decay_code = '''
    # ⭐️ 记忆衰减：定期清理，防止记忆无限膨胀
    async def decay_memories(pool):
        """每天跑一次的定时任务"""

        # 临时记忆超过 7 天未访问 → 删除
        await pool.execute("""
            DELETE FROM memories
            WHERE priority = 'temp'
              AND accessed_at < NOW() - INTERVAL '7 days'
        """)

        # 普通记忆超过 30 天未访问 → 降级为 temp（下次再清）
        await pool.execute("""
            UPDATE memories
            SET priority = 'temp'
            WHERE priority = 'normal'
              AND accessed_at < NOW() - INTERVAL '30 days'
        """)

        # 核心记忆永不清除（除非手动删）
    '''
    print("记忆衰减策略:")
    print(decay_code)

    # ── 6. 记忆合并示例 ──
    merge_code = '''
    # ⭐️ 多条碎片记忆合并为一条（减少冗余，提高检索精度）
    async def consolidate_memories(pool, user_id):
        """将同一 category 下的碎片记忆合并"""

        fragments = await pool.fetch("""
            SELECT id, content
            FROM memories
            WHERE user_id = $1 AND category = 'preference'
            ORDER BY created_at
        """, user_id)

        if len(fragments) < 2:
            return  # 不足 2 条无需合并

        # 用 LLM 合并
        merged = await model.ainvoke([{
            "role": "user",
            "content": f"将这些关于用户偏好的碎片合并为一条完整记忆:\\n"
                       + "\\n".join(f["content"] for f in fragments)
        }])

        # 删除旧碎片，插入合并后的记忆
        async with pool.transaction():
            await pool.execute(
                "DELETE FROM memories WHERE id = ANY($1)",
                [f["id"] for f in fragments]
            )
            await pool.execute("""
                INSERT INTO memories (user_id, content, category, priority)
                VALUES ($1, $2, 'preference', 'core')
            """, user_id, merged.content)
    '''
    print("记忆合并策略:")
    print(merge_code)


# ═════════════════════════════════════════════
# 十二、Durability 模式（持久化级别）
# ═════════════════════════════════════════════

def demo_durability_modes():
    """
    ⭐️ 三种持久化级别（从低到高）：

    | 模式    | 行为                              | 适用场景          |
    |--------|----------------------------------|------------------|
    | exit   | 图退出时才保存，中间不保存          | 长时间运行的图      |
    | async  | 异步保存，下一步执行的同时写入       | 推荐的平衡点 ⭐️    |
    | sync   | 同步保存，写完 checkpoint 再执行下一步 | 最高安全，最慢     |

    用法：graph.stream({...}, durability="sync")
    """
    print("\n=== Durability 模式 ===")
    print('  "exit"  — 仅图退出时保存，性能最佳但中间状态不保存')
    print('  "async" — 异步保存，性能和安全的平衡（推荐）')
    print('  "sync"  — 同步保存，每步都确保写入，最安全但最慢')


# ═════════════════════════════════════════════
# 十三、Checkpointer 实现选择
# ═════════════════════════════════════════════

def demo_checkpointer_options():
    """
    ⭐️ 不同场景选不同 checkpointer：

    | 实现                               | 适用场景   | 安装包                          |
    |-----------------------------------|-----------|-------------------------------|
    | InMemorySaver                     | 开发/调试  | langgraph（内置）                |
    | SqliteSaver / AsyncSqliteSaver    | 本地实验   | langgraph-checkpoint-sqlite    |
    | PostgresSaver / AsyncPostgresSaver| 生产环境   | langgraph-checkpoint-postgres  |
    | CosmosDBSaver                     | Azure 生产 | langchain-azure-cosmosdb       |

    ⭐️ Checkpointer 接口核心方法：
      .put          — 存储 checkpoint
      .put_writes   — 存储超步内的中间写入（pending writes）
      .get_tuple    — 获取 checkpoint（用于 get_state）
      .list         — 列出 checkpoint（用于 get_state_history）

    异步版本：.aput / .aput_writes / .aget_tuple / .alist
    """
    print("\n=== Checkpointer 选择 ===")
    print("  开发调试: InMemorySaver（内置）")
    print("  本地实验: SqliteSaver")
    print("  生产环境: PostgresSaver ⭐️")


# ═════════════════════════════════════════════
# 十四、实用技巧：查找特定 Checkpoint
# ═════════════════════════════════════════════

def demo_find_checkpoint():
    """在历史中按条件查找 checkpoint"""
    config: RunnableConfig = {"configurable": {"thread_id": "5"}}
    graph.invoke({"foo": "", "bar": []}, config=config)

    history = list(graph.get_state_history(config))
    print("\n=== 查找 Checkpoint ===")

    # 找 node_b 执行前的 checkpoint
    before_b = next((s for s in history if s.next == ("node_b",)), None)
    print(f"node_b 执行前: {before_b.values if before_b else '未找到'}")

    # 按 step 编号查找
    step_2 = next((s for s in history if s.metadata.get("step") == 2), None)
    print(f"step=2:       {step_2.values if step_2 else '未找到'}")

    # 找 update_state 创建的 checkpoint
    forks = [s for s in history if s.metadata.get("source") == "update"]
    print(f"update_state 创建的 checkpoint 数: {len(forks)}")

    # 找发生中断的 checkpoint
    interrupted = next(
        (s for s in history if s.tasks and any(t.interrupts for t in s.tasks)),
        None
    )
    print(f"发生中断的 checkpoint: {'有' if interrupted else '无'}")

    # ⭐️ 删除 thread 的所有 checkpoint
    # checkpointer.delete_thread("5")


# ═════════════════════════════════════════════
# 主入口
# ═════════════════════════════════════════════

if __name__ == "__main__":
    demo_basic_checkpoint()
    demo_state_history()
    demo_update_state()
    demo_replay()
    demo_short_term_memory()
    demo_manage_messages()
    demo_store_basic()
    demo_store_namespace()
    demo_store_semantic_search()
    demo_graph_with_store()
    demo_production_memory()
    demo_durability_modes()
    demo_checkpointer_options()
    demo_find_checkpoint()
