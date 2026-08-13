"""
场景 9 · LLM-as-a-Judge 自动评估
============================================================
目标：用「裁判模型」自动给回答打分（相关性/是否幻觉/是否有害等），
     无需人工，适合生产大流量的持续质量抽检。

Langfuse 提供两种做法：
  A) UI 托管的 LLM-as-a-Judge（推荐生产用）：在 UI 配置 evaluator，
     自动对线上新 trace 打分，无需写代码。步骤见本阶段 README。
  B) 代码自建裁判（本脚本演示）：自己调一个模型当裁判，把结果 create_score 回填。
     好处是完全可控、可离线跑、可接入任意自定义评估维度。

本脚本用 GLM 同时扮演「答题者」和「裁判」，演示 B 方案的完整闭环。

运行：
    python "Langfuse实战/03_评估/s9_llm_as_a_judge.py"
"""

import json
import pathlib
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import observe
from langfuse.langchain import CallbackHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 项目根：使绝对导入 Langfuse实战.* 生效
from Langfuse实战._bootstrap import glm_model, langfuse

langfuse_handler = CallbackHandler()

# 裁判提示词：要求只输出 JSON，便于解析
JUDGE_SYSTEM = (
    "你是严格的答案质量评审。针对『问题』和『回答』，从相关性与准确性打分。"
    '只输出 JSON，格式：{"score": 0~1 的小数, "reason": "简短中文理由"}。'
)


# 答题者：正常回答问题（产生被评估的 trace）
@observe(name="answer")
def answer_question(question: str) -> tuple[str, str | None]:
    resp = glm_model.invoke(
        [HumanMessage(question)], config={"callbacks": [langfuse_handler]}
    )
    return resp.content, langfuse.get_current_trace_id()


# 裁判：给 (问题, 回答) 打分，返回 (分数, 理由)
def judge(question: str, answer: str) -> tuple[float, str]:
    resp = glm_model.invoke(
        [
            SystemMessage(JUDGE_SYSTEM),
            HumanMessage(f"问题：{question}\n\n回答：{answer}"),
        ]
    )
    raw = resp.content.strip()
    # 容错解析：去掉可能的 ```json 包裹
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()
    try:
        data = json.loads(raw)
        return float(data["score"]), str(data.get("reason", ""))
    except Exception:
        # 解析失败时给个保守分，避免整条流程中断
        return 0.0, f"裁判输出无法解析：{raw[:50]}"


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    question = "LangGraph 里的 checkpointer 有什么作用？"

    # 1) 答题，拿到 trace_id
    answer, trace_id = answer_question(question)
    print("回答：", answer)

    # 2) 裁判打分
    score, reason = judge(question, answer)
    print(f"裁判评分：{score}  理由：{reason}")

    # 3) 把裁判分数回填到被评估的 trace（NUMERIC）
    langfuse.create_score(
        trace_id=trace_id,
        name="llm_judge_relevance",
        value=score,
        data_type="NUMERIC",
        comment=reason,
    )

    langfuse.flush()
    print(
        f"\n已把裁判分数写回 trace {trace_id}。\n"
        "生产环境建议用 UI 托管的 LLM-as-a-Judge 自动评所有线上 trace（见 README）。"
    )
