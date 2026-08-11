"""在线打分：给已经产生的 trace 挂上质量分数（Score）。

三类分数，覆盖真实业务里最常见的打分来源：
  - rule_score        : 规则/启发式分（是否带来源引用、长度是否正常），无需人也无需大模型；
  - simulate_user_feedback: 模拟前端👍/👎异步回传的用户满意度；
  - judge_relevance   : LLM-as-judge，用模型给「回答与问题的相关性」打 0-1 分。
分数通过 trace_id 关联到对应对话，UI 的 Scores 里可按维度聚合、按分数筛 trace。
"""

from __future__ import annotations

import re

import _setup  # noqa: F401  # 副作用：准备 sys.path 与 .env

from langchain_core.messages import HumanMessage, SystemMessage

from client import langfuse

from provider import glm_model

# 判定回答是否带来源引用的标记
_CITATION_MARK = "[来源"
# LLM 裁判输出里提取 0-1 分数的正则
_SCORE_RE = re.compile(r"0(?:\.\d+)?|1(?:\.0+)?")


# 规则分：回答是否带来源引用（BOOLEAN）+ 长度是否落在合理区间（NUMERIC）
def rule_score(trace_id: str, answer: str) -> None:
    has_citation = _CITATION_MARK in (answer or "")
    langfuse.create_score(
        name="has_citation",
        value=has_citation,
        data_type="BOOLEAN",
        trace_id=trace_id,
        comment="回答包含来源引用" if has_citation else "缺少来源引用",
    )
    # 长度合规：10~500 字之间记 1 分，过短/过长记 0 分
    length_ok = 10 <= len(answer or "") <= 500
    langfuse.create_score(
        name="length_ok",
        value=1.0 if length_ok else 0.0,
        data_type="NUMERIC",
        trace_id=trace_id,
        comment=f"回答长度 {len(answer or '')} 字",
    )


# 模拟用户反馈：前端👍/👎异步回传的满意度（BOOLEAN）
def simulate_user_feedback(trace_id: str, thumbs_up: bool) -> None:
    langfuse.create_score(
        name="user_feedback",
        value=thumbs_up,
        data_type="BOOLEAN",
        trace_id=trace_id,
        comment="用户👍" if thumbs_up else "用户👎",
    )


# LLM 裁判：让模型给回答与问题的相关性打 0-1 分（NUMERIC）
def judge_relevance(trace_id: str, question: str, answer: str) -> float:
    judge_messages = [
        SystemMessage(
            "你是回答质量评审。只输出一个 0 到 1 之间的小数，表示【回答】对【问题】的相关与有用程度，"
            "0 表示完全不相关，1 表示高度相关且有用。不要输出任何其他文字。"
        ),
        HumanMessage(f"【问题】{question}\n【回答】{answer}"),
    ]
    raw = glm_model.invoke(judge_messages).content
    match = _SCORE_RE.search(raw or "")
    score = float(match.group()) if match else 0.0
    langfuse.create_score(
        name="relevance",
        value=score,
        data_type="NUMERIC",
        trace_id=trace_id,
        comment=f"LLM 裁判原始输出：{(raw or '').strip()[:50]}",
    )
    return score
