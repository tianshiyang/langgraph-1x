"""编排入口：跑一段完整的多轮客服对话，并附上全套 Langfuse 观测与在线打分。

一次运行会产生：
  - 1 个 Session（多轮对话聚合）；
  - 每轮 1 个 trace：root=support-turn(chain) → 子节点 retriever + generation(带真实 token/cost)；
  - 每轮的规则分，末轮额外的用户反馈分与 LLM 相关性分；
  - PII 脱敏：含手机号的那轮，在 UI 里显示为 <PHONE>。

运行：
    python "Langfuse实战/00_真实业务场景/langfuse/run.py"
"""

from __future__ import annotations

import uuid

import _setup  # noqa: F401  # 副作用：准备 sys.path 与 .env

import feedback
from client import langfuse
from hosted_prompts import seed_support_prompt
from instrumented import InstrumentedSupportSession

# 模拟一位客户连问 4 轮（含追问 + 一轮带手机号，用于演示脱敏）
CONVERSATION = [
    "你们家发货一般要多久啊？",
    "那预售的商品呢？",  # 追问：承接上一轮「发货时效」
    "我买的东西想退，签收 7 天内还能退吗？",
    "退货有问题的话打我手机 13812345678 联系我，怎么转人工客服？",  # 含 PII
]


# 跑一轮完整会话：多轮对话 + 每轮规则分 + 末轮用户反馈/相关性分
def main() -> None:
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    seed_support_prompt()  # 幂等播种线上人设

    user_id = "user-1001"
    session_id = f"support-{uuid.uuid4().hex[:8]}"
    session = InstrumentedSupportSession(user_id=user_id, session_id=session_id)
    print(f"会话开始：user_id={user_id} session_id={session_id}\n")

    last_turn = None
    for i, question in enumerate(CONVERSATION, start=1):
        turn = session.ask(question)
        sources = "、".join(doc["title"] for doc in turn["docs"]) or "（无）"
        print(f"【第 {i} 轮】用户：{question}")
        print(f"命中知识库：{sources}")
        print(f"客服：{turn['answer']}\n")

        # 每轮挂规则分
        if turn["trace_id"]:
            feedback.rule_score(turn["trace_id"], turn["answer"])
        last_turn = turn

    # 末轮模拟用户👍 + LLM 相关性打分
    if last_turn and last_turn["trace_id"]:
        feedback.simulate_user_feedback(last_turn["trace_id"], thumbs_up=True)
        score = feedback.judge_relevance(
            last_turn["trace_id"], CONVERSATION[-1], last_turn["answer"]
        )
        print(f"末轮 LLM 相关性评分：{score}")

    langfuse.flush()
    print(
        "\n完成。去 Langfuse UI 查看：\n"
        f"  - Sessions → {session_id}：4 轮对话聚合在一个会话里；\n"
        "  - Tracing：每轮 trace 为 support-turn，下挂 knowledge-retrieval(retriever) 与 generation；\n"
        "  - Scores：has_citation / length_ok / user_feedback / relevance；\n"
        "  - 含手机号那轮的输入在 UI 中显示为 <PHONE>（PII 脱敏生效）；\n"
        "  - generation 上有真实 token 用量；成本若为 0，见 README『成本显示为 0』一节配置模型单价。"
    )


if __name__ == "__main__":
    main()
