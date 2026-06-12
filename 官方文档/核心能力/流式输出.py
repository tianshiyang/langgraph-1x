"""
LangGraph 流式输出 (Streaming) — 完整教程
==============================================

⭐️ 一句话理解流式：别等整张图跑完才一次性吐结果，而是「边跑边推」——
   节点产出一点、就推给前端一点。聊天界面里「文字一个一个蹦出来」、
   长任务里「正在检索…正在生成…」的进度条，全靠它。

⭐️ 先理解「非流式 vs 流式」的差别（这是你之前没学明白的根）：

   非流式 graph.invoke()：
     用户提问 ──────────[ 整张图闷头跑完 ]──────────► 一次性返回完整结果
                          （用户盯着空白屏幕等 5 秒，体验差）

   流式 graph.stream()：
     用户提问 ─► [节点A] ─► [节点B LLM] ─► [节点C] ─► END
                   │           │ │ │          │
                   ▼           ▼ ▼ ▼          ▼
                 事件        token逐个吐     事件
                   └──────────实时推给前端──────────►
                          （第 0.3 秒就开始有字出来，体验好）

⭐️ 核心只有一个 API + 一个参数：
       graph.stream(input, stream_mode="...")        # 同步
       graph.astream(input, stream_mode="...")       # 异步
   关键全在 stream_mode 上——它决定「你想要流出来的是什么东西」。

┌──────────────────────────────────────────────────────────────────┐
│  stream_mode 五选一（最常用前四个），决定 yield 出来的数据形态：    │
│                                                                    │
│   "messages"  ► LLM 的 token，逐块吐  → 聊天打字机效果 ⭐️最常用     │
│                 yield (AIMessageChunk, metadata) 二元组            │
│                                                                    │
│   "updates"   ► 每个节点「改了哪些字段」→ 进度/调试 ⭐️最常用        │
│                 yield {节点名: {改动的字段}}                        │
│                                                                    │
│   "values"    ► 每步之后「完整状态快照」→ 看全貌                    │
│                 yield 整个 state dict                              │
│                                                                    │
│   "custom"    ► 你自己用 get_stream_writer() 推的任意数据 → 进度条  │
│                 yield 你写进去的那个对象（dict/str 都行）           │
│                                                                    │
│   另有三个偏底层的（了解即可，见第 07 节）：                        │
│   "checkpoints" ► 每存一次检查点 → 配持久化做时间旅行/分支          │
│   "tasks"       ► Pregel 任务的创建/完成事件 → 排查调度             │
│   "debug"       ► 最啰嗦的底层调试信息 → 扒执行细节才开             │
└──────────────────────────────────────────────────────────────────┘

⭐️ 一个最容易踩的认知坑（实测确认，务必记住）：
   stream_mode="messages" 时，哪怕你节点内部写的是 model.invoke()（不是 stream），
   LangGraph 也会自动「劫持」底层 LLM 的 token 流，照样一个个吐给你。
   ——所以你**不需要**在节点里手动处理流式，只管在外层 stream() 时选对 mode。

参考文档（本教程基于官方 streaming 页——经典、稳定、生产主力的那套 API）：
  - https://docs.langchain.com/oss/python/langgraph/streaming
  （本项目 langgraph==1.2.4 / langchain==1.3.6，下列 API 全部可用并已实测）

──────────────────────────────────────────────────────────────────
⭐️ 一句话说清「为什么只学这一套」：

  graph.stream(input, stream_mode=...)  ——本教程全程用它。
     稳定、生产主力、官方示例最全（tags 过滤 / 禁流式 / checkpoints/tasks 都有）。

  官方还有另一页 event-streaming，讲的是 graph.stream_events(version="v3") 新写法，
  但它目前还是 **experimental(Beta)**。等它转正再说，**本教程不碰**——
  你现在要会、能上线的就是上面这一套 stream_mode。
──────────────────────────────────────────────────────────────────
⭐️ 企业实战优先级图例（每个小节标题都标了等级）：

  ⭐️⭐️⭐️ 企业核心：几乎每个带界面的 Agent 都要用，必须吃透
  ⭐️⭐️   企业常用：重要认知或选型，要懂但不一定天天写
  ⭐️     了解即可：特定场景/调试，先知道有这回事

各小节速查：
  01 messages 逐 token 输出 ......... ⭐️⭐️⭐️  聊天打字机，前端体验命脉
  02 updates 看节点进展（差量）...... ⭐️⭐️⭐️  「正在执行第几步」+ 调试
  03 values 完整状态快照 ............ ⭐️⭐️    要拿每步的全量 state 时
  04 custom 自定义进度事件 .......... ⭐️⭐️⭐️  长任务「检索中/生成中」进度条
  05 多模式组合 stream_mode=[...] ... ⭐️⭐️⭐️  进度 + token 同时要，实战标配
  06 控制哪些 token 流出去 .......... ⭐️⭐️⭐️  node过滤/tags过滤/禁流式，多LLM必用
  07 异步 + 子图 + 其它 stream_mode . ⭐️      astream/subgraphs/checkpoints/tasks/debug
  08 实战：流式 RAG 知识库问答助手 ... ⭐️⭐️⭐️  embedding 检索 + LLM 流式 + 进度
  09 学习路线
──────────────────────────────────────────────────────────────────
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

# 复用项目统一封装的模型（GLM）与向量模型（阿里 DashScope）。
# 01~07 演示都需要真实 LLM；08 实战还会用到 embeddings 做检索。
from provider import glm_model
from provider.embedding import embeddings

load_dotenv(Path(__file__).parent.parent.parent / ".env")


# 一个贯穿前几节的最小图：输入问题 → LLM 节点回答。
# 节点内部故意用 invoke（不是 stream），用来证明 messages 模式会自动捕获 token。
class QAState(TypedDict):
    question: str
    answer: str


def _answer_node(state: QAState) -> QAState:
    resp = glm_model.invoke([
        SystemMessage("你是简洁的助手，用一两句话回答。"),
        HumanMessage(state["question"]),
    ])
    return {"answer": resp.content}


def _build_qa_graph():
    builder = StateGraph(QAState)
    builder.add_node("answer", _answer_node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile()


# ═════════════════════════════════════════════
# 01. messages 逐 token 输出       【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_messages():
    """
    ⭐️ 这是流式里最常用的能力：把 LLM 的回答一个 token 一个 token 地吐出来，
       做成聊天界面那种「打字机」效果。

    ── stream_mode="messages" 到底 yield 什么？──
    每次 yield 一个 **二元组 (chunk, metadata)**：
      chunk    : AIMessageChunk，本次新增的那一小段内容，取 chunk.content
      metadata : dict，附带信息，最有用的是 metadata["langgraph_node"]
                 （这段 token 是哪个节点产生的——多 LLM 节点时用来区分，见第 06 节）

    ⭐️ 打字机效果的写法就这一句：print(content, end="", flush=True)
       end="" 不换行，flush=True 立刻刷到屏幕，token 才会一个个冒出来。

    ⚠️ 注意：不同模型「一块」的粒度不同。有的逐字（'北'、'京'），
       GLM 这种可能一次给一小段（'中国的'、'首都是北京。'）——都正常，
       前端照样是「分块到达」的流式体验。
    """
    print("\n=== 01. messages 逐 token 输出 ===")
    graph = _build_qa_graph()

    print("   AI: ", end="", flush=True)
    for chunk, metadata in graph.stream(
        {"question": "用一句话介绍杭州。", "answer": ""},
        stream_mode="messages",
    ):
        # chunk 是 AIMessageChunk；content 可能为 '' (首尾空块)，照打不影响
        print(chunk.content, end="", flush=True)
    print()  # 收尾换行


# ═════════════════════════════════════════════
# 02. updates 看节点进展（差量）    【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_updates():
    """
    ⭐️ 场景：你想知道「图现在跑到第几步了、哪个节点刚改了什么」——
       做「正在分析…正在查询…」这种步骤级进度，或排查流程走向，用 updates。

    ── stream_mode="updates" yield 什么？──
    每个节点跑完，yield 一个 dict：{节点名: {该节点这次更新的字段}}
      —— 注意是「差量」：只含这个节点 return 的那几个字段，不是全量 state。

    ⭐️ 对比记忆：
       updates = 「谁改了、改了啥」（差量，轻量，适合进度/调试）
       values  = 「改完之后，整个 state 长啥样」（全量，见第 03 节）
    """
    print("\n=== 02. updates 看节点进展 ===")

    # 用一个两节点的图，能更清楚看到「逐节点」吐 update
    class S(TypedDict):
        question: str
        topic: str
        answer: str

    def classify(state: S) -> S:
        return {"topic": "地理"}

    def answer(state: S) -> S:
        resp = glm_model.invoke([HumanMessage(state["question"])])
        return {"answer": resp.content}

    graph = (
        StateGraph(S)
        .add_node("classify", classify)
        .add_node("answer", answer)
        .add_edge(START, "classify")
        .add_edge("classify", "answer")
        .add_edge("answer", END)
        .compile()
    )

    for update in graph.stream(
        {"question": "珠穆朗玛峰有多高？", "topic": "", "answer": ""},
        stream_mode="updates",
    ):
        # update 形如 {"classify": {"topic": "地理"}}
        for node_name, changed in update.items():
            preview = {k: (v[:20] + "…" if isinstance(v, str) and len(v) > 20 else v)
                       for k, v in changed.items()}
            print(f"   ✓ 节点[{node_name}] 更新了: {preview}")


# ═════════════════════════════════════════════
# 03. values 完整状态快照          【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

def demo_values():
    """
    ⭐️ 场景：你不关心「谁改的」，只想要每一步之后「完整的 state 全貌」——
       比如想实时把整个状态渲染到调试面板，用 values。

    ── stream_mode="values" yield 什么？──
    每一步之后，yield **整个 state dict**（全量，不是差量）。
    最后一次 yield 的就是最终完整结果（等价于 invoke 的返回值）。

    ⭐️ 实用技巧：想拿「最终结果」时，可以遍历到最后留下最后一个；
       但其实直接 graph.invoke() 更省事。values 的价值在「过程中的每一帧」。
    """
    print("\n=== 03. values 完整状态快照 ===")
    graph = _build_qa_graph()

    last = None
    for snapshot in graph.stream(
        {"question": "Python 之父是谁？", "answer": ""},
        stream_mode="values",
    ):
        # snapshot 是完整 state：第1帧 answer 还为空，最后一帧 answer 已填好
        ans = snapshot.get("answer", "")
        print(f"   快照: question={snapshot['question']!r}, answer={ans[:30]!r}")
        last = snapshot
    print(f"   → 最终 answer: {last['answer']}")


# ═════════════════════════════════════════════
# 04. custom 自定义进度事件         【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_custom():
    """
    ⭐️ 场景：一个节点内部要做好几件耗时的事（查库 → 调外部 API → 整理），
       你想在过程中主动推「正在查询知识库… 找到 3 条… 正在汇总…」给前端。
       messages/updates 都做不到「节点执行中途」推消息，这时用 custom。

    ── 两步走 ──
       1) 节点内部拿到 writer：  writer = get_stream_writer()
          （导入：from langgraph.config import get_stream_writer）
       2) 想推什么就 writer(任意对象)，dict / str 都行，推几次都行。
       外层用 stream_mode="custom" 接收，yield 出来的就是你写进去的那个对象。

    ⭐️ 企业里常把 custom 事件设计成结构化 dict，方便前端按类型渲染：
         writer({"type": "progress", "stage": "检索", "percent": 30})
         writer({"type": "log", "msg": "命中缓存"})

    ⭐️ 不止节点——**工具(@tool)函数内部一样能 get_stream_writer()**。
       做 Agent 时，工具里推「Retrieved 30/100 records」这类进度，是最常见的用法。
    """
    print("\n=== 04. custom 自定义进度事件 ===")

    class S(TypedDict):
        result: str

    def heavy_task(state: S) -> S:
        writer = get_stream_writer()  # ⭐️ 在节点内部取 writer
        writer({"type": "progress", "stage": "连接数据库", "percent": 10})
        # ……（这里假装在干活）……
        writer({"type": "progress", "stage": "查询记录", "percent": 50})
        writer({"type": "log", "msg": "命中 3 条记录"})
        writer({"type": "progress", "stage": "汇总结果", "percent": 90})
        return {"result": "完成"}

    graph = (
        StateGraph(S)
        .add_node("heavy_task", heavy_task)
        .add_edge(START, "heavy_task")
        .add_edge("heavy_task", END)
        .compile()
    )

    for event in graph.stream({"result": ""}, stream_mode="custom"):
        # event 就是 writer(...) 里那个对象
        if event.get("type") == "progress":
            print(f"   [{event['percent']:>3}%] {event['stage']}")
        else:
            print(f"   · {event['msg']}")


# ═════════════════════════════════════════════
# 05. 多模式组合 stream_mode=[...]   【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_combined():
    """
    ⭐️ 这是最贴近实战的用法：真实聊天产品里，你**同时**想要——
         · custom   ：先显示「正在检索…」之类的进度
         · messages ：再逐 token 流式打印 AI 回答
         · updates  ：（可选）后台记录每个节点的执行，用于日志/调试
       一次 stream() 全要到，不用跑三遍。

    ── 写法：stream_mode 传一个 list ──
       此时每次 yield 变成 **二元组 (mode, chunk)**，
       mode 是字符串（"custom"/"messages"/"updates"），chunk 是该模式对应的数据。
       不同模式的事件会按**真实到达顺序交错**吐出来（先进度、再 token、最后 update）。
    """
    print("\n=== 05. 多模式组合（进度 + token + 节点日志）===")

    class S(TypedDict):
        question: str
        answer: str

    def reply(state: S) -> S:
        writer = get_stream_writer()
        writer({"stage": "思考中"})
        resp = glm_model.invoke([
            SystemMessage("用一句话回答。"),
            HumanMessage(state["question"]),
        ])
        writer({"stage": "回答完毕"})
        return {"answer": resp.content}

    graph = (
        StateGraph(S)
        .add_node("reply", reply)
        .add_edge(START, "reply")
        .add_edge("reply", END)
        .compile()
    )

    for mode, chunk in graph.stream(
        {"question": "世界上最大的海洋是哪个？", "answer": ""},
        stream_mode=["custom", "messages", "updates"],  # ⭐️ 传 list
    ):
        if mode == "custom":
            print(f"\n   〔进度〕{chunk['stage']}")
        elif mode == "messages":
            print(chunk[0].content, end="", flush=True)  # 逐 token 打字机
        elif mode == "updates":
            print(f"\n   〔日志〕节点更新: {list(chunk.keys())}")


# ═════════════════════════════════════════════
# 06. 控制哪些 token 流出去          【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_message_metadata():
    """
    ⭐️ 真实产品里，一张图常有**多个 LLM 节点**（先分类、再总结、最后润色回答），
       但你只想把「最终回答」逐 token 流给用户，中间产物不能刷屏。
       LangGraph 给了你三招来控制「哪些 token 流出去」：

    ┌──────────────┬────────────────────────────────────────────────────┐
    │ 手段          │ 适用 & 怎么做                                          │
    ├──────────────┼────────────────────────────────────────────────────┤
    │ ① 按节点过滤   │ 最常用。看 metadata["langgraph_node"]，只放行某个节点 │
    │ ② 按 tags 过滤 │ 更细。给模型 .with_config(tags=["xx"])，看 metadata   │
    │              │   ["tags"] 过滤——同一节点里多次调模型也能分别识别     │
    │ ③ 彻底不流式   │ 某个模型构造时设 streaming=False，它的输出就不再逐 token│
    │              │   （整块一次性给）。适合"内部步骤根本不需要流"          │
    └──────────────┴────────────────────────────────────────────────────┘

    ── metadata 里常用的键（实测）──
       langgraph_node  : 产生这段 token 的节点名（① 用它）
       tags            : 你给模型绑的标签列表（② 用它）
       ls_model_name / ls_provider 等: 模型信息

    ⚠️ 关于 nostream：官方还有个给模型打 tag "langsmith:nostream" 来禁流式的写法，
       但**是否生效取决于具体模型集成**（实测在 GLM/OpenAI 兼容端点上未必生效）。
       想稳妥地"不流式"，优先用 ③ streaming=False，而不是赌 nostream。

    下面这张图：summarize（内部步骤，不流）→ translate（最终回答，要流）。
    我们用 ① 按节点过滤，只打印 translate 的 token。
    （② tags 过滤的写法见函数末尾的 _demo_tag_filter 注释演示。）
    """
    print("\n=== 06. 控制哪些 token 流出去（按节点过滤）===")

    class S(TypedDict):
        text: str
        summary: str
        translation: str

    def summarize(state: S) -> S:
        resp = glm_model.invoke([
            SystemMessage("用一句话概括用户给的文本。"),
            HumanMessage(state["text"]),
        ])
        return {"summary": resp.content}

    def translate(state: S) -> S:
        resp = glm_model.invoke([
            SystemMessage("把这句话翻译成英文，只输出英文。"),
            HumanMessage(state["summary"]),
        ])
        return {"translation": resp.content}

    graph = (
        StateGraph(S)
        .add_node("summarize", summarize)
        .add_node("translate", translate)
        .add_edge(START, "summarize")
        .add_edge("summarize", "translate")
        .add_edge("translate", END)
        .compile()
    )

    print("   ① 按节点过滤——只显示 translate 节点：\n   EN: ", end="", flush=True)
    for chunk, metadata in graph.stream(
        {"text": "LangGraph 是一个用于构建有状态、多步骤 AI 应用的框架。",
         "summary": "", "translation": ""},
        stream_mode="messages",
    ):
        if metadata.get("langgraph_node") == "translate":  # ⭐️ 关键过滤
            print(chunk.content, end="", flush=True)
    print()

    # —— ② 按 tags 过滤：给模型绑标签，再用 metadata["tags"] 识别 ——
    print("   ② 按 tags 过滤——只显示绑了 'final' 标签的模型输出：\n   AI: ",
          end="", flush=True)

    final_model = glm_model.with_config(tags=["final"])  # ⭐️ 给这次调用打标签

    def answer(state: S) -> S:
        resp = final_model.invoke([
            SystemMessage("用一句话回答。"),
            HumanMessage(state["text"]),
        ])
        return {"translation": resp.content}

    g2 = (
        StateGraph(S)
        .add_node("answer", answer)
        .add_edge(START, "answer")
        .add_edge("answer", END)
        .compile()
    )
    for chunk, metadata in g2.stream(
        {"text": "请用一句话介绍上海。", "summary": "", "translation": ""},
        stream_mode="messages",
    ):
        if "final" in (metadata.get("tags") or []):  # ⭐️ 按 tags 过滤
            print(chunk.content, end="", flush=True)
    print()

    # —— ③ 彻底不流式：streaming=False（说明，不单独跑，省一次 LLM 调用）——
    print("   ③ 某模型构造时设 streaming=False，则其输出整块返回、不逐 token。")


# ═════════════════════════════════════════════
# 07. 异步 + 子图 + 其它 stream_mode  【⭐️ 了解即可】
# ═════════════════════════════════════════════

def demo_async_and_subgraph():
    """
    ⭐️ 三个进阶但不常单独写的点，一次性建立认知：

    ① 异步流式 astream：Web 服务（FastAPI 等）里几乎都用异步。写法和同步几乎一样，
       只是 for → async for、stream → astream、节点内 invoke → ainvoke。
         async for chunk, meta in graph.astream(inp, stream_mode="messages"):
             ...
       （还有个 StreamWriter 类型注解的异步写法：async def node(state, writer: StreamWriter)，
        效果同 get_stream_writer()，二选一即可。）

    ② 子图流式 subgraphs=True：当某个节点本身是一张子图（多智能体常见），
       默认外层 stream 只把子图当「一个黑盒节点」，看不到内部 token。
       传 subgraphs=True 后，yield 变成 (namespace, mode, chunk) 三元组，
       namespace 是一个元组，标明这段事件来自哪个子图层级（空元组=主图）。

    ③ 还有三个「偏底层」的 stream_mode，知道有就行（实测）：
       "checkpoints" ► 每存一次检查点吐一个事件 → 配合持久化做时间旅行/分支时用
                       （没配 checkpointer 时不产生事件）
       "tasks"       ► 每个 Pregel 任务的「创建/完成」事件 → 排查调度、看任务流
       "debug"       ► 最啰嗦的底层调试信息 → 真要扒执行细节时才开
       这三个都能和前面的模式一起放进 stream_mode=[...] 组合使用。

    下面演示异步 messages（子图/这三个底层模式仅在 docstring 说明，避免示例过长）。
    """
    print("\n=== 07. 异步 astream（子图/底层模式见 docstring）===")
    graph = _build_qa_graph()

    async def run():
        print("   AI: ", end="", flush=True)
        async for chunk, meta in graph.astream(
            {"question": "一句话解释什么是 async。", "answer": ""},
            stream_mode="messages",
        ):
            print(chunk.content, end="", flush=True)
        print()

    asyncio.run(run())
    print("   ── 其它要点 ──")
    print("   · 子图：stream 传 subgraphs=True → (namespace, mode, chunk) 三元组")
    print("   · 底层模式：checkpoints / tasks / debug，排查与时间旅行时用")


# ═════════════════════════════════════════════
# 08. 实战：流式 RAG 知识库问答助手   【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════
#
# 业务目标：一个客服知识库问答机器人。用户问一句话，系统要：
#   ① retrieve 节点：用 embeddings 把问题向量化，和知识库每条 FAQ 算余弦相似度，
#                    取最相关的 top-2 作为上下文。过程中用 custom 推「检索进度」。
#   ② generate 节点：把命中的 FAQ 当上下文喂给 LLM，**流式**生成最终回答。
#
# 这就是企业里 RAG 聊天产品最典型的流式骨架：
#   - 用 custom 模式做「🔍 正在检索知识库…命中 N 条…✍️ 正在生成」这类阶段提示；
#   - 用 messages 模式把 LLM 回答逐 token 打字机式吐给用户；
#   - 两者用 stream_mode=["custom","messages"] 一次拿到，按真实顺序交错渲染。
#
# embedding 在这里的作用：把「文本」变成「向量」，相似的文本向量也相近，
#   于是「问题向量」和「FAQ 向量」的余弦相似度，就能衡量「这条 FAQ 有多对题」。
# ═════════════════════════════════════════════

# —— 一个迷你知识库（真实项目里这些会存进向量数据库，如 pgvector）——
KNOWLEDGE_BASE = [
    "退货政策：商品签收后 7 天内可无理由退货，需保持包装完好。",
    "配送时效：现货商品 48 小时内发出，偏远地区可能延迟 1-2 天。",
    "发票申请：支持电子发票，可在「我的订单」页面自助申请开具。",
    "会员权益：黄金会员享受免运费、专属客服和生日礼券。",
    "支付方式：支持微信、支付宝、银行卡及货到付款。",
]


def _cosine(a: list[float], b: list[float]) -> float:
    """纯 Python 算余弦相似度，避免引入 numpy 依赖。值越接近 1 越相似。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-10)


class RAGState(TypedDict):
    question: str          # 用户问题
    context: list[str]     # 检索命中的 FAQ
    answer: str            # 最终回答


# 知识库向量「预计算」缓存：真实项目里建库时算一次、存数据库；
# 这里用模块级缓存模拟，避免每次问答都重新 embed 整个知识库。
_kb_vectors_cache: list[list[float]] = []


def _retrieve(state: RAGState) -> RAGState:
    """① 检索：问题向量 vs 知识库向量，取 top-2。过程用 custom 推进度。"""
    writer = get_stream_writer()
    writer({"stage": "🔍 正在检索知识库…"})

    # 知识库向量只算一次，之后命中缓存
    global _kb_vectors_cache
    if not _kb_vectors_cache:
        _kb_vectors_cache = embeddings.embed_documents(KNOWLEDGE_BASE)

    # 问题向量化
    q_vec = embeddings.embed_query(state["question"])

    # 算相似度并排序，取 top-2
    scored = sorted(
        zip(KNOWLEDGE_BASE, _kb_vectors_cache),
        key=lambda pair: _cosine(q_vec, pair[1]),
        reverse=True,
    )
    top = [doc for doc, _ in scored[:2]]

    writer({"stage": f"📚 命中 {len(top)} 条相关知识，✍️ 正在生成回答…"})
    return {"context": top}


def _generate(state: RAGState) -> RAGState:
    """② 生成：把命中的 FAQ 当上下文，让 LLM 基于它流式回答。"""
    context_text = "\n".join(f"- {c}" for c in state["context"])
    resp = glm_model.invoke([
        SystemMessage(
            "你是电商客服。只依据下面提供的【知识库】回答用户问题，"
            "用简洁口语化的一两句话；若知识库没有相关信息就说不清楚。\n"
            f"【知识库】\n{context_text}"
        ),
        HumanMessage(state["question"]),
    ])
    return {"answer": resp.content}


def _build_rag_graph():
    return (
        StateGraph(RAGState)
        .add_node("retrieve", _retrieve)
        .add_node("generate", _generate)
        .add_edge(START, "retrieve")
        .add_edge("retrieve", "generate")
        .add_edge("generate", END)
        .compile()
    )


def demo_rag_streaming():
    """
    ⭐️ 跑一个完整的流式 RAG 问答，体会真实聊天产品的输出节奏：
       先看到检索阶段的进度提示（custom），紧接着回答逐 token 蹦出来（messages）。
    """
    print("\n=== 08. 实战：流式 RAG 知识库问答助手 ===")
    graph = _build_rag_graph()

    question = "我买的东西不想要了，能退吗？"
    print(f"   用户：{question}\n")

    answered_prefix = False
    for mode, chunk in graph.stream(
        {"question": question, "context": [], "answer": ""},
        stream_mode=["custom", "messages"],   # ⭐️ 进度 + token 一起要
    ):
        if mode == "custom":
            print(f"   {chunk['stage']}")
        elif mode == "messages":
            # 只流 generate 节点的 token（这里只有它调 LLM，过滤可省，演示规范写法）
            msg, meta = chunk
            if meta.get("langgraph_node") == "generate":
                if not answered_prefix:
                    print("\n   客服：", end="", flush=True)
                    answered_prefix = True
                print(msg.content, end="", flush=True)
    print("\n")


# ═════════════════════════════════════════════
# 09. 学习路线
# ═════════════════════════════════════════════

def practice_guide():
    """
    ⭐️ 本教程基于官方 streaming 页（经典 stream_mode API，生产主力）。
       按「企业实战优先级」排（不是按章节顺序）：

    ⭐️⭐️⭐️ 企业核心（必吃透，几乎每个带界面的 Agent 都用）：
       - 01 messages：逐 token 打字机，前端体验命脉；记住「节点内 invoke 也能流」
       - 02 updates ：节点级进度 +「图走到哪了」的调试视角
       - 04 custom  ：长任务里主动推「检索中/生成中/X%」进度，get_stream_writer()
       - 05 组合    ：stream_mode=[...] 一次拿到「进度 + token」，实战标配写法
       - 06 控制流出：node过滤 / tags过滤 / streaming=False——多 LLM 节点产品必用
       - 08 实战    ：把检索进度(custom) + 流式回答(messages) 串成 RAG 聊天骨架

    ⭐️⭐️ 企业常用（要懂，偏认知/技巧）：
       - 03 values：要每步「完整 state 全貌」时用；和 updates 的差量对比记忆

    ⭐️ 了解即可（特定场景）：
       - 07 异步 astream + 子图 subgraphs + checkpoints/tasks/debug 模式

    ⭐️ 关于官方另一页 event-streaming（v3 投影 API）：
       那是 stream_events(version="v3") 的新写法，目前还是 **experimental(Beta)**，
       本教程**不涉及**——生产一律用上面的经典 stream_mode，等它转正再说。

    ⭐️ 和「持久化 / 容错」的联动：
       - 流式 + 中断(interrupt)：人机协作时流会暂停，靠 checkpointer 存档、
         再用 Command(resume=...) 续跑（详见《持久化.py》《容错.py》）。
       - 一句话串起三件套：持久化让流程「可恢复」，容错让节点「不崩」，
         流式让用户「等得舒服」——共同支撑一个生产级 Agent。

    ══════════════════════════════════════════════════════════════
    ⭐️⭐️⭐️ 企业落地 TODO 清单（本教程刻意没写，留给「综合项目」阶段实战）

    本教程讲的是「流式的心智模型」——5 个 mode 怎么选、怎么过滤/组合/推进度。
    下面这些是「把流式接进真实系统的工程集成」，它们都**依附具体场景才有意义**，
    脱离项目单独写就是空中楼阁。做综合项目时，对照这份清单逐条落地即可：

    [ ] ① 接入 Web 服务（FastAPI + SSE）★最关键
          做法：async for 消费 graph.astream(...)，把每个 chunk 包成
                "data: {json}\\n\\n"，用 StreamingResponse(media_type=
                "text/event-stream") 返回，前端用 EventSource 逐字渲染。
          —— 流式的真正终点是浏览器逐字显示，这是落地第一难关。

    [ ] ② Agent 工具调用流式 + MessagesState ★主流形态
          做法：messages 的 AIMessageChunk 自带 .tool_call_chunks，
                可流式展示「正在调用 搜索 工具…」；状态用 add_messages 的
                MessagesState（或 create_react_agent），而非自定义 TypedDict。
          —— 企业里流式最常见的载体就是 Agent，这是 messages 的「另一半」。

    [ ] ③ 流式中途出错 & 用户取消
          做法：用 try/except 包住 stream 迭代，出错时向前端补发一个
                {"type":"error"} 事件；用户点「停止生成」/关页面 → 检测
                客户端断连或 asyncio.CancelledError，及时中断生成、释放资源。
          —— 生产健壮性，不补的话线上一定踩坑。

    [ ] ④ 流式下的 Token 用量统计
          做法：流式时 usage 在**最后一个** AIMessageChunk 的 usage_metadata 里
                （部分模型需开 stream_usage=True）；或用 UsageMetadataCallbackHandler
                （见 provider/llms.py 已有用法）。用于计费/成本监控。

    [ ] ⑤ 流式 + interrupt 人机协作
          做法：interrupt() 暂停 + checkpointer 存档 + Command(resume=...) 续跑。
          —— 横跨 流式/持久化/容错 三块，正是综合项目的压轴料。

    建议：做综合项目时，把「① SSE + ② Agent 工具流」作为主线先打通，
          再补 ③④ 健壮性，最后用 ⑤ 串起人机协作。
    ══════════════════════════════════════════════════════════════
    """
    print("\n=== 09. 学习路线（按企业优先级）===")
    print("⭐️⭐️⭐️ 核心: 01 messages -> 02 updates -> 04 custom -> 05 组合 -> 06 控制流出 -> 08 实战")
    print("⭐️⭐️   常用: 03 values（完整快照）")
    print("⭐️     了解: 07 异步/子图/底层模式")
    print("⭐️     联动: 流式 + interrupt/checkpointer（见 持久化.py / 容错.py）")
    print("\n⭐️ 企业落地 5 项（留给综合项目，见 docstring 清单）：")
    print("   ① FastAPI+SSE  ② Agent工具流+MessagesState  ③ 出错/取消")
    print("   ④ 用量统计  ⑤ 流式+interrupt 人机协作")


# ═════════════════════════════════════════════
# 主入口
# ═════════════════════════════════════════════

if __name__ == "__main__":
    # —— 以下全部需要 GLM API Key + 网络（真正调用 LLM）——
    demo_messages()             # 01 ⭐️⭐️⭐️
    demo_updates()              # 02 ⭐️⭐️⭐️
    demo_values()               # 03 ⭐️⭐️
    demo_custom()               # 04 ⭐️⭐️⭐️（纯 Python，不调 LLM，断网也能跑）
    demo_combined()             # 05 ⭐️⭐️⭐️
    demo_message_metadata()     # 06 ⭐️⭐️⭐️
    demo_async_and_subgraph()   # 07 ⭐️

    # —— 实战：额外需要 阿里 DashScope embedding Key ——
    demo_rag_streaming()        # 08 ⭐️⭐️⭐️

    practice_guide()            # 10
