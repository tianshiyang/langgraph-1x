"""
LangGraph 容错 (Fault Tolerance) — 完整教程
==============================================

⭐️ 一句话理解容错：节点是会失败的（LLM 限流、网络抖动、外部 API 挂了），
   LangGraph 提供三件套，让"单个节点失败"不至于让"整条流程崩掉"。

⭐️ 先看这张图，理解一次节点执行的"生死流程"：

┌────────────────────────────────────────────────────────────────┐
│  节点开始执行                                                     │
│     │                                                            │
│     ├─ 成功 ───────────────────────────────────► 图继续往下走     │
│     │                                                            │
│     └─ 抛异常                                                     │
│           │                                                      │
│           ▼                                                      │
│     ① RetryPolicy（重试）：这个错该不该重试？还有次数吗？           │
│           │  能重试 → 等一会儿(退避) → 再跑一次（回到顶部）         │
│           │  不能重试 / 次数用尽                                   │
│           ▼                                                      │
│     ② error_handler（兜底）：配了处理器吗？                        │
│           │  配了 → 跑兜底逻辑（补偿 / 降级 / 改道）→ 图继续        │
│           │  没配                                                 │
│           ▼                                                      │
│     ③ 异常向上抛出 → 整条流程失败（但 checkpoint 已存，可恢复）     │
└────────────────────────────────────────────────────────────────┘

   另外还有 ④ Timeout（超时）：节点跑太久 → 抛 NodeTimeoutError，
   这个超时异常会被当成"普通异常"，照样走上面 ①②③ 的流程。

⭐️ 三件套（可自由组合）：
   1. RetryPolicy   —— 失败了自动重试（应对"瞬时故障"）
   2. TimeoutPolicy —— 跑太久就掐掉（应对"卡死/吊死"，仅异步节点）
   3. error_handler —— 重试也救不回来时的"最后兜底"（补偿/降级/改道）

参考文档：
  - https://docs.langchain.com/oss/python/langgraph/fault-tolerance
  （以上 API 需要 langgraph>=1.2；本项目已是 1.2.4，全部可用）

──────────────────────────────────────────────────────────────────
⭐️ 企业实战优先级图例（每个小节标题都标了等级）：

  ⭐️⭐️⭐️ 企业核心：几乎每个生产 Agent 都要配，必须吃透
  ⭐️⭐️   企业常用：重要认知或选型，要懂但不一定天天写
  ⭐️     了解即可：特定场景/调试才用，先知道有这回事

各小节速查：
  01 RetryPolicy 基础 ............... ⭐️⭐️⭐️  重试瞬时故障，生产命脉
  02 retry_on 自定义 ............... ⭐️⭐️    控制"哪些错才重试"
  03 execution_info 重试感知降级 .... ⭐️⭐️    末次尝试改走 fallback
  04 TimeoutPolicy 超时 ............ ⭐️⭐️    防 LLM/外部调用卡死（异步专属）
  05 error_handler 兜底/补偿 ........ ⭐️⭐️⭐️  重试耗尽后的优雅降级
  06 set_node_defaults 统一默认 ..... ⭐️⭐️    大图统一配置，去重
  07 优雅停机 graceful shutdown ..... ⭐️      k8s/SIGTERM 滚动发布才用
  08 其他认知（一次性扫盲） .......... ⭐️      子图/interrupt/functional 等
  09 实战：高可用 AI 客服工单流水线 ... ⭐️⭐️⭐️  把三件套全用上
  10 学习路线
──────────────────────────────────────────────────────────────────
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.constants import START, END
from langgraph.errors import NodeError
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy, TimeoutPolicy, default_retry_on
from typing_extensions import TypedDict

# 复用项目统一封装的模型（GLM）。只有第 09 节实战会真正调用它。
# 01~08 的 API 演示全是纯 Python 假函数，断网也能跑，方便你反复练。
from provider import glm_model

load_dotenv(Path(__file__).parent.parent.parent / ".env")


# ═════════════════════════════════════════════
# 01. RetryPolicy 基础          【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

class State(TypedDict):
    result: str


# 用一个"前两次必失败、第三次成功"的假节点，模拟网络抖动
_attempts_01 = {"n": 0}


def call_api(state: State) -> State:
    _attempts_01["n"] += 1
    print(f"   [call_api] 第 {_attempts_01['n']} 次尝试")
    if _attempts_01["n"] < 3:
        # ConnectionError 属于"瞬时故障"，默认会被重试
        raise ConnectionError("网络抖动，连接失败")
    return {"result": f"第 {_attempts_01['n']} 次终于成功"}


def demo_retry_basic():
    """
    ⭐️ 这是整个容错里最常用的能力：节点失败了，自动再试几次。

    ── add_node 的 retry_policy 参数 ──
    在 add_node 时传 retry_policy=RetryPolicy(...)，这个节点就有了"重试能力"。

    ── RetryPolicy 各字段的实际含义（你不熟 API，逐个解释）──
    | 字段             | 默认值            | 大白话含义                                   |
    |-----------------|------------------|--------------------------------------------|
    | max_attempts    | 3                | 总共最多跑几次（含第一次）。=3 即"1 次 + 2 次重试" |
    | initial_interval| 0.5 秒           | 第一次重试前先等多久                           |
    | backoff_factor  | 2.0              | 每多重试一次，等待时间翻几倍（指数退避）          |
    | max_interval    | 128 秒           | 等待时间的天花板，再退避也不超过它               |
    | jitter          | True             | 给等待时间加随机抖动，避免大量请求同时重试（惊群） |
    | retry_on        | default_retry_on | 判断"哪些异常该重试"，见第 02 节                |

    ⭐️ 指数退避（backoff）举例（initial=0.5, factor=2）：
        第1次重试前等 0.5s → 第2次等 1s → 第3次等 2s → ...（+随机抖动）
        为什么？外部系统正过载时，越急着重试越雪上加霜；越往后等越久才合理。

    ⭐️ default_retry_on（默认重试策略）很聪明，它默认重试大部分异常，
       但**不重试**这些"代码 bug 类"异常（重试也没用，错的是你代码）：
         ValueError, TypeError, KeyError(LookupError), ArithmeticError,
         ImportError, NameError, SyntaxError, RuntimeError, OSError ...
       对 requests / httpx，只重试 5xx（服务端错），不重试 4xx（你请求错）。
    """
    print("\n=== 01. RetryPolicy 基础 ===")
    _attempts_01["n"] = 0

    builder = StateGraph(State)
    builder.add_node(
        "call_api",
        call_api,
        # ⭐️ 核心就这一行：最多 3 次，重试间隔很短只是为了演示快点
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.05),
    )
    builder.add_edge(START, "call_api")
    builder.add_edge("call_api", END)
    graph = builder.compile()

    result = graph.invoke({"result": ""})
    print(f"   最终结果: {result}")
    # 第 1、2 次失败被吞掉并自动重试，第 3 次成功


# ═════════════════════════════════════════════
# 02. retry_on 自定义          【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

class RateLimitError(Exception):
    """模拟 LLM 厂商的限流错误（429）——这种值得重试"""


class InvalidPromptError(Exception):
    """模拟"提示词非法"——这种重试一百次也没用，应当立刻放弃"""


def demo_retry_on():
    """
    ⭐️ retry_on 回答一个问题：到底哪些异常该重试？

    三种写法（从简单到灵活）：
      1) 传单个异常类：     retry_on=ConnectionError
      2) 传异常类元组：     retry_on=(ConnectionError, TimeoutError)
      3) 传一个函数(回调)：  retry_on=my_func  —— 最灵活，按异常内容判断

    ⭐️ 企业里最实用的是第 3 种：在默认策略基础上"挖掉"几个不该重试的错。
       下面这个 custom_retry_on：限流(429)要重试，提示词非法直接放弃，
       其余的交还给 default_retry_on 决定（不要自己从零重写默认逻辑）。
    """
    print("\n=== 02. retry_on 自定义 ===")

    def custom_retry_on(exc: BaseException) -> bool:
        if isinstance(exc, InvalidPromptError):
            return False                  # 明确：这种不重试
        if isinstance(exc, RateLimitError):
            return True                   # 明确：这种一定重试
        return default_retry_on(exc)      # 其余：沿用官方默认判断

    # 用一个"被限流两次后成功"的节点演示
    calls = {"n": 0}

    def call_llm(state: State) -> State:
        calls["n"] += 1
        print(f"   [call_llm] 第 {calls['n']} 次尝试")
        if calls["n"] < 3:
            raise RateLimitError("429 Too Many Requests")
        return {"result": "限流缓解后成功拿到回复"}

    graph = (
        StateGraph(State)
        .add_node(
            "call_llm",
            call_llm,
            retry_policy=RetryPolicy(
                max_attempts=4,
                initial_interval=0.05,
                retry_on=custom_retry_on,   # ⭐️ 用我们的自定义判断
            ),
        )
        .add_edge(START, "call_llm")
        .add_edge("call_llm", END)
        .compile()
    )
    print(f"   最终结果: {graph.invoke({'result': ''})}")


# ═════════════════════════════════════════════
# 03. execution_info 重试感知降级   【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

def demo_execution_info():
    """
    ⭐️ 场景：前几次重试还想调"主用方案"，但如果一直失败、到了最后一次尝试，
       就别再硬刚了，改走"备用/降级方案"，保证至少有个结果。

    ── 怎么知道"现在是第几次尝试"？──
    给节点函数加第二个参数 runtime: Runtime，读 runtime.execution_info。

    ── execution_info 各字段含义 ──
    | 字段                     | 含义                                     |
    |-------------------------|------------------------------------------|
    | node_attempt            | 当前是第几次尝试（从 1 开始）⭐️ 最常用      |
    | node_first_attempt_time | 第一次尝试的 Unix 时间戳                    |
    | thread_id               | 当前线程 ID（用了 checkpointer 才有）       |
    | run_id / checkpoint_id  | 本次运行 / 检查点 ID（排查问题时定位用）     |
    | task_id                 | 当前任务 ID                               |

    ⭐️ 小知识：哪怕你没配 retry_policy，execution_info 也存在，
       此时 node_attempt 恒为 1。所以这段代码加不加重试都不会报错。
    """
    print("\n=== 03. execution_info 重试感知降级 ===")
    calls = {"n": 0}

    def call_with_fallback(state: State, runtime: Runtime) -> State:
        attempt = runtime.execution_info.node_attempt
        calls["n"] += 1

        # ⭐️ 到了最后一次尝试（第 3 次），不再调主方案，直接降级
        if attempt >= 3:
            print(f"   第 {attempt} 次：主方案屡败，改走降级方案")
            return {"result": "【降级】返回缓存/默认答复"}

        print(f"   第 {attempt} 次：尝试主方案……失败")
        raise ConnectionError("主用 API 不可用")

    graph = (
        StateGraph(State)
        .add_node(
            "call_with_fallback",
            call_with_fallback,
            retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.05),
        )
        .add_edge(START, "call_with_fallback")
        .add_edge("call_with_fallback", END)
        .compile()
    )
    print(f"   最终结果: {graph.invoke({'result': ''})}")


# ═════════════════════════════════════════════
# 04. TimeoutPolicy 超时          【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

def demo_timeout():
    """
    ⭐️ 场景：LLM/外部接口偶尔会"吊死"（连接不断但永远不返回），
       不设超时的话整条流程会一直挂着。超时就是给节点装个"闹钟"。

    ⚠️ 两条重要限制（务必记住）：
       1) **超时仅对异步节点(async def)生效**。同步节点配 timeout 会在
          compile() 时直接报错。阻塞型 I/O 请用 asyncio.to_thread 包起来。
       2) 因为是异步节点，整张图要用 await graph.ainvoke(...) 来跑。

    ── timeout 参数可以传三种东西 ──
       timeout=60                         # 直接给秒数：整体最多 60 秒
       timeout=timedelta(minutes=2)       # 给 timedelta 也行
       timeout=TimeoutPolicy(...)         # 最细粒度，见下

    ── TimeoutPolicy 两种超时（含义不同，别搞混）──
    | 字段        | 含义                                                  |
    |------------|-------------------------------------------------------|
    | run_timeout| "总时长"上限：这次尝试从头到尾最多跑多久，不会重置 ⭐️常用 |
    | idle_timeout| "空闲"上限：多久没有任何进展(没吐 token/没写状态)就掐    |
    | refresh_on | idle 的进展判定方式，默认 "auto"（自动识别多种信号）     |

    ⭐️ 一句话区分：
       run_timeout  管"跑得太久"（哪怕一直在干活，超过总时长也掐）；
       idle_timeout 管"卡住没动静"（在干活就不掐，纯粹卡死才掐）。
       LLM 流式输出场景常用 idle_timeout：只要还在吐字就不算超时。

    ⭐️ 超时发生时：抛 NodeTimeoutError → 该次尝试的写入被清空 →
       交给 RetryPolicy 决定要不要再来一次（每次重试都是一个全新的超时时钟）。

    NodeTimeoutError 自带上下文：node(哪个节点)、elapsed(跑了多少秒)、
       kind("run"还是"idle")、run_timeout/idle_timeout(当时的配置)。
    """
    print("\n=== 04. TimeoutPolicy 超时 ===")

    async def slow_node(state: State) -> State:
        await asyncio.sleep(5)            # 模拟一个会跑 5 秒的慢操作
        return {"result": "正常完成"}

    # 兜底处理器：超时后别让流程崩，给个降级结果（顺带读出超时类型）
    def on_timeout(state: State, error: NodeError) -> Command:
        kind = getattr(error.error, "kind", "?")
        elapsed = getattr(error.error, "elapsed", -1)
        print(f"   超时被兜住：kind={kind}, elapsed≈{elapsed:.2f}s")
        return {"result": f"【超时降级】{type(error.error).__name__}"}

    graph = (
        StateGraph(State)
        .add_node(
            "slow_node",
            slow_node,
            timeout=TimeoutPolicy(run_timeout=0.3),  # 0.3 秒就掐，必然超时
            error_handler=on_timeout,                # 第 05 节细讲
        )
        .add_edge(START, "slow_node")
        .add_edge("slow_node", END)
        .compile()
    )

    # ⭐️ 异步节点必须用 ainvoke
    result = asyncio.run(graph.ainvoke({"result": ""}))
    print(f"   最终结果: {result}")


# ═════════════════════════════════════════════
# 05. error_handler 兜底/补偿     【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════

def demo_error_handler():
    """
    ⭐️ 重试是"再试试看能不能成"；error_handler 是"试到底也不行，那怎么收场"。
       两者是接力关系：retry_policy 先重试，重试耗尽（或不可重试）才轮到它。
       （没配 retry_policy 时，一抛异常就直接进 error_handler。）

    ── error_handler 的函数签名 ──
       第二个参数标注成 error: NodeError，就能拿到失败上下文：
         error.node  —— 哪个节点失败了（字符串）
         error.error —— 具体的异常对象（BaseException）
       这个参数是可选的，你也可以写 def handler(state) 或加 runtime/config。

    ── 返回值：返回 Command 可以"改道" ──
       Command(update={...}, goto="某节点") 既更新状态、又跳到指定节点。
       这是实现"补偿事务(saga)"的关键：付款失败 → 跳到"释放库存"做回滚。

    ⭐️ 经典场景：电商下单的补偿。
       reserve(锁库存) → charge(扣款，失败) → 兜底：标记需补偿 → finalize 收尾。
    """
    print("\n=== 05. error_handler 兜底/补偿 ===")

    class OrderState(TypedDict):
        status: str

    def reserve_inventory(s: OrderState) -> OrderState:
        print("   锁定库存：成功")
        return {"status": "库存已锁定"}

    def charge_payment(s: OrderState) -> OrderState:
        print("   发起扣款：失败（支付网关超时）")
        raise RuntimeError("payment gateway timeout")

    # ⭐️ 兜底：扣款最终失败 → 做补偿（这里只是打标，真实场景会去释放库存）→ 改道 finalize
    def payment_error_handler(s: OrderState, error: NodeError) -> Command:
        print(f"   兜底触发：节点[{error.node}] 失败原因={error.error}")
        return Command(
            update={"status": f"已补偿(回滚库存)；原因: {error.error}"},
            goto="finalize",
        )

    def finalize(s: OrderState) -> OrderState:
        print(f"   收尾：当前状态 = {s['status']}")
        return s

    graph = (
        StateGraph(OrderState)
        .add_node("reserve_inventory", reserve_inventory)
        .add_node(
            "charge_payment",
            charge_payment,
            # 假设这是个"网络类才重试"的扣款；这里抛的是 RuntimeError(不在重试名单)，
            # 所以一次都不重试，直接进 error_handler。改成 ConnectionError 就会先重试。
            retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.05,
                                     retry_on=ConnectionError),
            error_handler=payment_error_handler,
        )
        .add_node("finalize", finalize)
        .add_edge(START, "reserve_inventory")
        .add_edge("reserve_inventory", "charge_payment")
        .add_edge("finalize", END)
        .compile()
    )
    print(f"   最终结果: {graph.invoke({'status': ''})}")
    # 注意：扣款失败没有让整条流程崩，而是被补偿后正常收尾


# ═════════════════════════════════════════════
# 06. set_node_defaults 统一默认   【⭐️⭐️ 企业常用】
# ═════════════════════════════════════════════

def demo_node_defaults():
    """
    ⭐️ 痛点：一张图十几个节点，难道每个 add_node 都重复写一遍 retry_policy？
       set_node_defaults 让你"定一次默认，全图通用"。

    ── 用法 ──
       StateGraph(State).set_node_defaults(
           retry_policy=...,  timeout=...,  error_handler=...,  cache_policy=...
       )

    ── 覆盖规则（很直觉）──
       某个节点 add_node 时自己传了参数 → 用它自己的（覆盖默认）；
       没传 → 用全局默认。默认在 compile() 时才结算，所以
       set_node_defaults 写在 add_node 前面或后面都行。

    ⭐️ 一个细节认知（不用背，知道有这回事）：
       默认值对"普通节点"和"error_handler 节点"的适用范围不同——
         retry_policy / timeout：两者都适用（兜底逻辑卡死/抖动也该被治）
         error_handler / cache_policy：只给普通节点，不会套到兜底节点自己身上
         （否则兜底节点自己失败又触发自己，会绕进死循环）
       另外：默认值**不会**传进子图(subgraph)。
    """
    print("\n=== 06. set_node_defaults 统一默认 ===")

    class S(TypedDict):
        log: str

    def default_handler(s: S, error: NodeError) -> S:
        return {"log": f"统一兜底：{error.node} -> {error.error}"}

    def step_a(s: S) -> S:
        raise ValueError("a 节点炸了")     # ValueError 默认不重试，直接进兜底

    def step_b(s: S) -> S:                 # b 自带兜底，覆盖全局默认
        raise ValueError("b 节点炸了")

    def step_b_handler(s: S, error: NodeError) -> S:
        return {"log": f"B 专属兜底：{error.error}"}

    graph = (
        StateGraph(S)
        # ⭐️ 全图默认：最多 2 次重试 + 统一兜底
        .set_node_defaults(
            retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.05),
            error_handler=default_handler,
        )
        .add_node("step_a", step_a)                              # 用全局默认兜底
        .add_node("step_b", step_b, error_handler=step_b_handler)  # 用自己的兜底
        .add_edge(START, "step_a")
        .add_edge("step_a", "step_b")
        .add_edge("step_b", END)
        .compile()
    )
    print(f"   最终结果: {graph.invoke({'log': ''})}")


# ═════════════════════════════════════════════
# 07. 优雅停机 graceful shutdown   【⭐️ 了解即可】
# ═════════════════════════════════════════════

def demo_graceful_shutdown():
    """
    ⭐️ 什么时候用：k8s 滚动发布 / 收到 SIGTERM 时，想"跑完当前这一步就停"，
       并存一个可恢复的 checkpoint，而不是硬杀进程导致状态丢一半。
       —— 没做 k8s 发布的同学，知道有这回事即可，先不用深究。

    ── 核心 API（仅 langgraph>=1.2）──
       from langgraph.runtime import RunControl
       from langgraph.errors import GraphDrained

       control = RunControl()
       # 在 SIGTERM 信号里调用：control.request_drain("sigterm")
       try:
           result = graph.invoke(inputs, config, control=control)
       except GraphDrained as e:
           print("已优雅排空:", e.reason)   # 还有后续 super-step 没跑完时抛这个

       # 恢复：用同一个 thread_id 再 invoke 一次（传 None 表示从断点续）
       result = graph.invoke(None, config)

    ⭐️ 行为要点：
       - 正在跑的节点会"跑完当前这一步"才停（不会从中间硬切）；
       - 自然在同一拍跑完 → 正常返回；还有步骤没跑 → 抛 GraphDrained；
       - request_drain() 不会强杀 asyncio 任务/线程。要硬上限，得另配超时。

    ── 节点内部还能感知排空请求 ──
       async def my_node(state, runtime: Runtime):
           if runtime.drain_requested:
               return {"status": "skipped", "reason": runtime.drain_reason}
           ...

    （这里只讲概念，不跑演示——它依赖 checkpointer + 信号，单测意义不大。）
    """
    print("\n=== 07. 优雅停机（仅概念，见 docstring）===")
    print("   k8s/SIGTERM 滚动发布场景：RunControl + GraphDrained，知道即可")


# ═════════════════════════════════════════════
# 08. 其他认知（一次性扫盲）        【⭐️ 了解即可】
# ═════════════════════════════════════════════

def demo_misc():
    """
    ⭐️ 这些不常单独写，但要知道"它们是怎么和容错交互的"：

    1) Functional API（@task / @entrypoint）同样支持 timeout / retry_policy：
         @task(timeout=TimeoutPolicy(idle_timeout=30),
               retry_policy=RetryPolicy(max_attempts=3))
         async def call_api(url): ...
       行为和 add_node 一致。

    2) interrupt()（人机协作的"暂停"）**不走**重试/兜底：
       它是正常的流程暂停信号(GraphBubbleUp)，不是"错误"，别指望 error_handler 接它。

    3) 子图(subgraph)抛异常：会冒泡到"调用子图的那个父节点"。
       父节点若配了 error_handler，就能在 error.error 里拿到子图的异常。

    4) 失败可恢复(resume-safe)：失败的"出处"会被记进 checkpoint。
       进程在"节点已失败、兜底还没跑完"时挂掉，重启从 checkpoint 恢复后，
       兜底处理器仍能拿到同样的 NodeError 上下文。（配了 checkpointer 才有）

    5) idle_timeout 的"心跳"：长循环里没有自动进展信号时，可以
       runtime.heartbeat() 手动报"我还活着"；配合 refresh_on="heartbeat"
       让心跳成为唯一的刷新信号。属于很细的长任务调优，先了解。

    6) 动态超时：用 Send 扇出时，可对单个 Send 传 timeout= 覆盖目标节点的默认超时。

    7) 平台/语言限制：超时与 error_handler 目前是 **Python 专属**；
       重试策略 Python/TS 都有；超时只支持异步节点。
    """
    print("\n=== 08. 其他认知 ===")
    print("   functional API / interrupt 不走兜底 / 子图冒泡 / resume-safe / 心跳")


# ═════════════════════════════════════════════
# 09. 实战：高可用 AI 客服工单流水线  【⭐️⭐️⭐️ 企业核心】
# ═════════════════════════════════════════════
#
# 业务目标：用户提交一条客服工单文本，系统要：
#   ① 用 LLM 给工单分类（咨询/投诉/退款/其他）—— 体现"重试 + 末次降级"
#   ② 同步到外部 CRM 系统（这步最不稳，常抖动）—— 体现"自定义重试 + 兜底补偿"
#   ③ 用 LLM 起草一条回复给用户              —— 体现"超时 + 重试"
#   ④ 收尾汇总
#
# 容错设计（这就是企业里真正在做的事）：
#   - 用 set_node_defaults 给所有 LLM 节点统一配 重试 + 超时，少写重复代码；
#   - classify 用 execution_info 做"末次降级"：LLM 一直失败就退回规则分类，绝不空手；
#   - sync_crm 是非 LLM 的外部调用，自定义 retry_on，最终失败则兜底为"转人工"，
#     而不是让整条工单流程崩掉；
#   - 全程异步(async)，因为要用 timeout（超时仅异步生效）。
# ═════════════════════════════════════════════

class TicketState(TypedDict):
    ticket: str        # 原始工单文本
    category: str      # 分类结果
    crm_status: str    # CRM 同步状态
    reply: str         # 给用户的回复
    log: list[str]     # 全流程日志


# —— 模拟外部 CRM：前两次抖动，第三次成功（用随机让它更真实一点）——
_crm_attempts = {"n": 0}


class CRMTransientError(Exception):
    """CRM 瞬时不可用——值得重试"""


async def classify_ticket(state: TicketState, runtime: Runtime) -> TicketState:
    """① 分类：LLM 为主，末次尝试降级为规则分类（保证一定有结果）。"""
    attempt = runtime.execution_info.node_attempt
    log = state["log"] + [f"classify 第 {attempt} 次尝试"]

    # ⭐️ 末次尝试还在重试圈里挣扎 → 直接降级，不再赌 LLM
    if attempt >= 3:
        text = state["ticket"]
        rule = "投诉" if any(k in text for k in ("差评", "投诉", "太差", "垃圾")) else "咨询"
        log.append(f"  → LLM 屡败，规则降级分类为：{rule}")
        return {"category": rule, "log": log}

    # 主方案：调 LLM 分类
    msgs = [
        SystemMessage("你是客服分类器。只输出一个词：咨询/投诉/退款/其他。"),
        HumanMessage(state["ticket"]),
    ]
    resp = await glm_model.ainvoke(msgs)
    category = resp.content.strip()[:4]
    log.append(f"  → LLM 分类为：{category}")
    return {"category": category, "log": log}


async def sync_crm(state: TicketState) -> TicketState:
    """② 同步 CRM：最不稳的一步。自定义重试；最终失败则兜底转人工。"""
    _crm_attempts["n"] += 1
    log = state["log"] + [f"sync_crm 第 {_crm_attempts['n']} 次尝试"]
    # 前两次模拟抖动
    if _crm_attempts["n"] < 3:
        raise CRMTransientError("CRM 503 暂时不可用")
    log.append("  → CRM 同步成功")
    return {"crm_status": "已同步", "log": log}


def crm_error_handler(state: TicketState, error: NodeError) -> Command:
    """②的兜底：CRM 实在同步不上，不让整单失败，降级为"转人工"。"""
    log = state["log"] + [f"  → CRM 兜底：{error.error}，转人工处理"]
    return Command(
        update={"crm_status": "同步失败-已转人工", "log": log},
        goto="draft_reply",   # 改道：跳过失败点，继续走起草回复
    )


async def draft_reply(state: TicketState) -> TicketState:
    """③ 起草回复：LLM 生成，受统一的超时 + 重试保护。"""
    log = state["log"] + ["draft_reply 调 LLM 起草回复"]
    msgs = [
        SystemMessage("你是客服助手，用一句话礼貌回复用户，并体现已受理。"),
        HumanMessage(f"工单类别：{state['category']}；CRM 状态：{state['crm_status']}；"
                     f"用户原话：{state['ticket']}"),
    ]
    resp = await glm_model.ainvoke(msgs)
    return {"reply": resp.content.strip(), "log": log}


def finalize(state: TicketState) -> TicketState:
    """④ 收尾。"""
    return {"log": state["log"] + ["finalize 完成"]}


def build_ticket_graph():
    """组装工单流水线，并统一配置容错策略。"""
    builder = StateGraph(TicketState)

    # ⭐️ 统一默认：所有节点最多重试 3 次。
    #    注意：timeout 不放进默认！因为 timeout 仅支持异步节点，而兜底处理器
    #    crm_error_handler / 收尾 finalize 是同步函数，给它们套 timeout 会在
    #    compile() 时直接报错。所以超时只逐个加在真正异步的 LLM/外部调用节点上。
    builder.set_node_defaults(
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.2),
    )

    builder.add_node(
        "classify_ticket",
        classify_ticket,
        timeout=TimeoutPolicy(run_timeout=30),   # LLM 调用，防卡死
    )
    builder.add_node(
        "sync_crm",
        sync_crm,
        # ⭐️ 覆盖默认重试：CRM 只在"瞬时错误"时重试；兜底转人工
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.2,
                                 retry_on=CRMTransientError),
        timeout=TimeoutPolicy(run_timeout=30),
        error_handler=crm_error_handler,
    )
    builder.add_node(
        "draft_reply",
        draft_reply,
        timeout=TimeoutPolicy(run_timeout=30),   # LLM 调用，防卡死
    )
    builder.add_node("finalize", finalize)        # 同步收尾，不配 timeout

    builder.add_edge(START, "classify_ticket")
    builder.add_edge("classify_ticket", "sync_crm")
    builder.add_edge("sync_crm", "draft_reply")
    builder.add_edge("draft_reply", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def demo_ticket_pipeline():
    """
    ⭐️ 跑两条工单，观察容错如何兜住失败：
       本例里 CRM 前两次必抖动 → 自动重试到第 3 次成功；
       若把 sync_crm 改成永远失败，则会走 crm_error_handler 转人工，流程照样跑完。
    """
    print("\n=== 09. 实战：高可用 AI 客服工单流水线 ===")
    _crm_attempts["n"] = 0
    graph = build_ticket_graph()

    out = asyncio.run(graph.ainvoke({
        "ticket": "你们的售后太差了，我要投诉！",
        "category": "", "crm_status": "", "reply": "", "log": [],
    }))

    print("   ── 全流程日志 ──")
    for line in out["log"]:
        print("   " + line)
    print(f"\n   分类结果: {out['category']}")
    print(f"   CRM状态:  {out['crm_status']}")
    print(f"   回复用户: {out['reply']}")


# ═════════════════════════════════════════════
# 10. 学习路线
# ═════════════════════════════════════════════

def practice_guide():
    """
    ⭐️ 按"企业实战优先级"排（不是按章节顺序）：

    ⭐️⭐️⭐️ 企业核心（必吃透，几乎每个生产 Agent 都用）：
       - 01 RetryPolicy：retry_policy + max_attempts/退避——应对 LLM 限流、网络抖动
       - 05 error_handler：重试救不回来时的兜底/补偿/改道(Command)——别让单点失败炸全流程
       - 09 实战流水线：把"重试 + 末次降级 + 超时 + 兜底补偿"在一张图里串起来

    ⭐️⭐️ 企业常用（要懂，偏认知/选型，不一定天天手写）：
       - 02 retry_on：精确控制"哪些错才重试"（限流要重试，参数错别重试）
       - 03 execution_info：靠 node_attempt 做"末次降级"，保证有兜底结果
       - 04 TimeoutPolicy：run_timeout vs idle_timeout，记住"仅异步节点"
       - 06 set_node_defaults：大图统一配置去重；记住默认不进子图

    ⭐️ 了解即可（特定场景/调试才用）：
       - 07 优雅停机：k8s 滚动发布 / SIGTERM 才用
       - 08 其他认知：functional API、interrupt 不走兜底、子图冒泡、resume-safe、心跳

    ⭐️ 和"持久化"的联动（容错的底座）：
       重试时"已成功节点不会重跑"、失败可恢复(resume-safe)，靠的都是 checkpointer。
       生产上请务必配 PostgresSaver——详见同目录《持久化.py》第 07/09 节。
    """
    print("\n=== 10. 学习路线（按企业优先级）===")
    print("⭐️⭐️⭐️ 核心: 01 RetryPolicy -> 05 error_handler -> 09 实战流水线")
    print("⭐️⭐️   常用: 02 retry_on -> 03 execution_info -> 04 超时 -> 06 统一默认")
    print("⭐️     了解: 07 优雅停机 -> 08 其他认知（容错底座是 checkpointer）")


# ═════════════════════════════════════════════
# 主入口
# ═════════════════════════════════════════════

if __name__ == "__main__":
    # —— 纯 Python，断网可跑（练 API）——
    demo_retry_basic()        # 01 ⭐️⭐️⭐️
    demo_retry_on()           # 02 ⭐️⭐️
    demo_execution_info()     # 03 ⭐️⭐️
    demo_timeout()            # 04 ⭐️⭐️
    demo_error_handler()      # 05 ⭐️⭐️⭐️
    demo_node_defaults()      # 06 ⭐️⭐️
    demo_graceful_shutdown()  # 07 ⭐️（仅概念）
    demo_misc()               # 08 ⭐️（仅概念）

    # —— 需要 GLM API Key + 网络（真正调用 LLM）——
    demo_ticket_pipeline()    # 09 ⭐️⭐️⭐️

    practice_guide()          # 10