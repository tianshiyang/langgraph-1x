"""
LangGraph 异常处理机制 — 完整示例
=================================

LangGraph 为节点执行提供了三层异常防护机制，可以在 add_node() 中独立或组合配置：
  1. timeout       — 超时保护：节点超过时限自动中断
  2. retry_policy  — 自动重试：失败后按指数退避策略重试
  3. error_handler — 兜底降级：重试耗尽后执行自定义逻辑优雅处理

此外还展示了 cache_policy 节点缓存（与异常处理独立，但经常配合使用）。

执行顺序：
  节点出错 → timeout 触发 → retry_policy 重试 → 重试耗尽 → error_handler 兜底
  如果 error_handler 也未配置或失败 → 异常冒泡到调用方的 try/except
"""

import asyncio

from langgraph.cache.memory import InMemoryCache
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy, Command, CachePolicy
from typing_extensions import TypedDict

from langgraph.errors import NodeTimeoutError, NodeError
from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    value: str


async def call_model(state: State, runtime: Runtime) -> State:
    """
    模拟一个耗时的异步节点。

    通过 runtime.execution_info.node_attempt 可以获取当前是第几次执行（含重试），
    这对调试重试逻辑非常有用。

    参数:
        state: 当前图状态
        runtime: LangGraph 运行时，提供执行上下文信息
            - runtime.execution_info.node_attempt: 当前执行尝试次数（从 1 开始）
    """
    print(f"执行了: {runtime.execution_info.node_attempt}次")
    await asyncio.sleep(2)  # 模拟耗时操作，实际要 2 秒
    return {"value": "done"}


def payment_error_handler(state: State, error: NodeError) -> Command:
    """
    节点错误处理器（error_handler）。

    当节点的重试策略耗尽后，如果配置了 error_handler，LangGraph 会调用它来做优雅降级。

    参数:
        state:  当前图状态（与普通节点相同）
        error:  NodeError 对象，包含两个属性：
            - error.node:  出错的节点名称（str）
            - error.error: 原始异常对象（BaseException）

    返回值:
        Command 对象，可以控制图的后续行为：
            - update: 更新状态字段（和普通节点的 return 一样）
            - goto:   指定下一步跳转到哪个节点（覆盖默认的边路由）
            - resume: 恢复被中断的执行
            - graph:  跨子图导航（Command.PARENT 表示回到父图）

    示例 — 根据 error 类型做不同处理：
        if isinstance(error.error, NodeTimeoutError):
            return Command(update={"value": "超时了"}, goto="fallback")
        elif isinstance(error.error, ConnectionError):
            return Command(update={"value": "网络错误"}, goto="retry_later")
    """
    print("错误了")
    return Command(
        update={"value": f"错误了：{error.error}"},
    )


builder = StateGraph(State)
builder.add_node(
    "model",
    call_model,
    # ==================== 第 1 层：timeout（超时保护）====================
    #
    # timeout 控制节点执行的时间上限，支持三种配置形式：
    #
    #   timeout=1.0
    #       → 等价于 TimeoutPolicy(run_timeout=1.0)
    #       → 节点整体运行超过 1 秒就触发 NodeTimeoutError
    #
    #   timeout=timedelta(seconds=5)
    #       → 同上，用 timedelta 对象
    #
    #   timeout=TimeoutPolicy(run_timeout=10.0, idle_timeout=5.0)
    #       → run_timeout:  从节点开始执行算起的总时间上限
    #       → idle_timeout: 节点在这段时间内没有任何"活动"就超时
    #                        （活动 = 写状态、流式输出、回调事件、调度子任务）
    #
    # ⚠️ timeout 仅支持 async 节点，同步节点编译时会抛出 ValueError
    #
    # 底层原理：asyncio 看门狗任务与节点执行赛跑
    #   - run 看门狗：await asyncio.sleep(run_timeout) 后触发
    #   - idle 看门狗：循环检测 last_progress_time，超时触发
    #   - 哪个先触发就抛 NodeTimeoutError(node, elapsed, kind, ...)
    #
    # NodeTimeoutError 故意不继承 TimeoutError/OSError，
    # 这样默认 retry_on 策略会认为它是"可重试的"异常
    timeout=1.0,

    # ==================== 第 2 层：retry_policy（自动重试）====================
    #
    # RetryPolicy 参数详解：
    #
    #   initial_interval=0.5    首次重试等待时间（秒）
    #   backoff_factor=2.0      每次等待时间乘以这个系数（指数退避）
    #   max_interval=128.0      单次最长等待时间（秒）
    #   max_attempts=3          最多尝试次数（含首次执行）
    #   jitter=True             加入随机抖动，防止多个实例同时重试（重试风暴）
    #   retry_on=...            控制哪些异常触发重试
    #
    # 退避时间线示例（默认参数）：
    #   第 1 次: 原始执行
    #   第 2 次: 等 0.5s 后重试      (0.5 × 2^0)
    #   第 3 次: 等 1.0s 后重试      (0.5 × 2^1)  ← 达到 max_attempts=3，停止
    #
    # retry_on 支持三种形式：
    #   retry_on=ConnectionError                           # 单个异常类型
    #   retry_on=[ConnectionError, NodeTimeoutError]       # 异常类型列表
    #   retry_on=lambda exc: hasattr(exc, 'status_code')   # 自定义判断函数
    #       and exc.status_code >= 500
    #
    # 默认策略（default_retry_on）：
    #   ✗ 不重试: ValueError, TypeError, SyntaxError, RuntimeError, OSError 等编程错误
    #   ✓ 重试:   其他所有异常（网络错误、API 5xx、NodeTimeoutError 等）
    #
    # 多策略组合（按顺序匹配第一个适用的）：
    #   retry_policy=[
    #       RetryPolicy(max_attempts=3, retry_on=ConnectionError),
    #       RetryPolicy(max_attempts=5, retry_on=NodeTimeoutError),
    #   ]
    retry_policy=RetryPolicy(),

    # ==================== 第 3 层：error_handler（兜底降级）====================
    #
    # 当重试耗尽后，如果配置了 error_handler，LangGraph 会：
    #   1. 自动创建隐藏节点 "__error_handler__{节点名}"
    #   2. 将 NodeError(node=节点名, error=原始异常) 注入到处理器的 config 中
    #   3. 调用处理器，用返回的 Command 更新状态并继续图执行
    #
    # ⚠️ 注意：error_handler 成功处理后，异常被"吞掉"，
    #          外层 try/except NodeTimeoutError 不会触发
    #          只有 error_handler 也不存在或也失败时，异常才冒泡
    error_handler=payment_error_handler,

    # ==================== 额外：cache_policy（节点缓存）====================
    #
    # CachePolicy(ttl=120) 表示节点结果缓存 120 秒
    # 在 ttl 时间内，相同的输入会直接返回缓存结果，不再执行节点
    # 需要在 compile() 时传入 cache=InMemoryCache() 才会生效
    #
    # CachePolicy 参数：
    #   ttl:           缓存存活时间（秒）
    #   key_func:      自定义缓存键生成函数（默认基于输入状态 hash）
    cache_policy=CachePolicy(ttl=120),
)
builder.add_edge(START, "model")
builder.add_edge("model", END)

# compile 时传入 cache 才能让 cache_policy 生效
graph = builder.compile(cache=InMemoryCache())

# ==================== 异常冒泡到调用方 ====================
#
# 本例的执行流程：
#   1. call_model 开始 → asyncio.sleep(2)
#   2. 1 秒后 timeout 触发 → NodeTimeoutError
#   3. RetryPolicy 判断 NodeTimeoutError 可重试 → 等 0.5s 后重试
#   4. 第 2 次执行 → 又超时 → 等 1.0s 后重试
#   5. 第 3 次执行 → 又超时 → 达到 max_attempts=3，停止重试
#   6. error_handler 生效 → payment_error_handler 被调用
#      → 返回 Command(update={"value": "错误了：..."})
#   7. 状态更新，图继续执行到 END
#   8. error_handler 成功处理了异常 → 外层 except 不会触发
#
# 如果没有配置 error_handler，异常会冒泡到这里被 try/except 捕获：
try:
    asyncio.run(graph.ainvoke({"value": "start"}))
except NodeTimeoutError:
    print("Node timed out")
