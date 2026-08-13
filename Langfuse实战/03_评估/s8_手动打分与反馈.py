"""
场景 8 · 手动打分与用户反馈（Scores）
============================================================
目标：给 trace 挂「分数」。分数是评估体系的原子——可以来自：
  - 线上真实用户的 👍/👎（前端回传）
  - 你自己回捞后的人工评分
  - 程序规则/裁判模型自动打分（见场景 9）

三种数据类型：
  - NUMERIC     数值型，如 0.87
  - CATEGORICAL 分类型，如 "好"/"中"/"差"（字符串）
  - BOOLEAN     布尔型，用 1.0 / 0.0 表示 是/否

关键 API：
  - 上下文内：langfuse.score_current_trace(name, value, data_type, comment)
  - 事后按 id：langfuse.create_score(trace_id=..., name=..., value=..., data_type=...)

运行：
    python "Langfuse实战/03_评估/s8_手动打分与反馈.py"
"""


import pathlib
import sys

from langchain_core.messages import HumanMessage
from langfuse import observe
from langfuse.langchain import CallbackHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 项目根：使绝对导入 Langfuse实战.* 生效
from Langfuse实战._bootstrap import glm_model, langfuse

langfuse_handler = CallbackHandler()


# 回答问题，并在链路内做一个「规则打分」
@observe(name="qa")
def ask(question: str) -> tuple[str, str | None]:
    response = glm_model.invoke(
        [HumanMessage(question)], config={"callbacks": [langfuse_handler]}
    )
    answer = response.content

    # 规则型自动打分：回答长度是否达标（演示 BOOLEAN 与上下文内打分）
    length_ok = 1.0 if len(answer) >= 20 else 0.0
    langfuse.score_current_trace(
        name="length_ok",
        value=length_ok,
        data_type="BOOLEAN",
        comment=f"回答长度={len(answer)}",
    )

    trace_id = langfuse.get_current_trace_id()
    return answer, trace_id


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    answer, trace_id = ask("用一句话解释什么是向量数据库。")
    print("回答：", answer)
    print("trace_id =", trace_id)

    # 模拟「前端用户点赞」——事后按 trace_id 追加打分（BOOLEAN）
    langfuse.create_score(
        trace_id=trace_id,
        name="user_feedback",
        value=1.0,  # 1=赞, 0=踩
        data_type="BOOLEAN",
        comment="用户点了赞",
    )

    # 模拟「人工质检」——追加一个分类分（CATEGORICAL，值必须是字符串）
    langfuse.create_score(
        trace_id=trace_id,
        name="quality",
        value="好",  # 好 / 中 / 差
        data_type="CATEGORICAL",
        comment="人工抽检：准确且简洁",
    )

    langfuse.flush()
    print(
        "\n已挂 3 个分数（length_ok / user_feedback / quality）。\n"
        "去 UI：\n"
        "  - 该 trace 详情页右侧 Scores 面板可见\n"
        "  - Scores 页面可按分数聚合、筛选『被踩』的回答集中改进"
    )
