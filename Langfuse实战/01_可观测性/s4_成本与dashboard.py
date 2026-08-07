"""
场景 4 · 成本、延迟与 Dashboard
============================================================
目标：批量产生一些真实调用，让 Langfuse 自动按 token 聚合出
     「成本 / 延迟 / 调用量」看板，学会看 Dashboard。

说明：
  - Langfuse 会根据 generation 上的 model 名 + usage_details（token 数）
    自动套用「模型定价表」算出成本。
  - 若你的模型（如 glm-4）在 Langfuse 没有内置定价，成本会显示为 0，
    需要去 UI: Settings → Models 自建一条 Model Definition（见本阶段 README）。

运行（会连续调用模型十几次，注意 token 消耗）：
    python "Langfuse实战/01_可观测性/s4_成本与dashboard.py"
运行后去 UI 的 Dashboards / Tracing 观察成本与延迟曲线。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _bootstrap import glm_model, langfuse  # noqa: E402

from langchain_core.messages import HumanMessage  # noqa: E402
from langfuse import observe, propagate_attributes  # noqa: E402
from langfuse.langchain import CallbackHandler  # noqa: E402

langfuse_handler = CallbackHandler()

# 一批不同长度的问题，用来制造有差异的 token / 延迟
QUESTIONS = [
    "用一句话解释什么是大模型。",
    "解释一下 RAG 的工作流程，分点说明。",
    "写一首关于秋天的五言绝句。",
    "把 '知识就是力量' 翻译成英文和日文。",
    "列举 3 个 Python 常用的 Web 框架并各写一句简介。",
]


# 处理一个问题（每次调用是一条 trace）
@observe(name="qa")
def ask(question: str) -> str:
    response = glm_model.invoke(
        [HumanMessage(question)], config={"callbacks": [langfuse_handler]}
    )
    return response.content


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    # 循环两轮，制造足够的样本量，便于看板出曲线
    for round_no in range(2):
        for i, q in enumerate(QUESTIONS):
            with propagate_attributes(
                tags=["cost-demo"], metadata={"round": round_no, "idx": i}
            ):
                answer = ask(q)
                print(f"[第{round_no}轮·{i}] {q}\n  → {answer[:40]}...\n")

    langfuse.flush()
    print("已上报共 10 条 trace（tag=cost-demo）。去 UI 查看：")
    print("  - Dashboards：Total cost / Traces / Latency 曲线")
    print("  - 若成本为 0：Settings → Models 给 glm-4 配置定价（见 README）")
