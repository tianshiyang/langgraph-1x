"""
场景 11 · Annotation Queue 人工标注队列
============================================================
目标：把需要人工评审的 trace 推进一个「标注队列」，让标注同学在 UI 里
     统一评分/写备注，产出高质量评估数据（可反哺场景 10 的黄金数据集）。

企业实践流程：
  1) 评估负责人在 UI 建好 Score Config（打分维度）和 Annotation Queue
  2) 应用侧用 API 把「可疑/被踩/需复核」的 trace 自动推进队列（本脚本）
  3) 标注同学在 UI 的 Annotation 页面逐条打分、写备注

关键 API（走底层 REST：langfuse.api.annotation_queues）：
  - list_queues()                                   列出已有队列
  - create_queue_item(queue_id, object_id, object_type)  把 trace 加入队列

前置：请先在 UI 建一个 Annotation Queue（Settings/Annotation → 需先建 Score Config）。

运行：
    python "Langfuse实战/03_评估/s11_annotation_queue.py"
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from langchain_core.messages import HumanMessage
from langfuse import observe
from langfuse.api import AnnotationQueueObjectType
from langfuse.langchain import CallbackHandler

from Langfuse实战._bootstrap import glm_model, langfuse

langfuse_handler = CallbackHandler()


# 产生一条需要人工复核的 trace
@observe(name="need-review")
def make_trace(question: str) -> str | None:
    glm_model.invoke([HumanMessage(question)], config={"callbacks": [langfuse_handler]})
    return langfuse.get_current_trace_id()


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    trace_id = make_trace("请给出一个有争议、需要人工把关的回答：AI 会取代程序员吗？")
    langfuse.flush()  # 先确保 trace 已上报，队列项才好关联
    print("待复核 trace_id =", trace_id)

    # 1) 列出已有标注队列
    queues = langfuse.api.annotation_queues.list_queues()
    if not queues.data:
        print(
            "\n未发现任何标注队列。请先去 UI 建一个：\n"
            "  Settings → Score Configs 建打分维度（如 relevance）\n"
            "  再建 Annotation Queue 并勾选该维度\n"
            "然后重跑本脚本。"
        )
        raise SystemExit(0)

    # 2) 取第一个队列，把 trace 推进去
    queue = queues.data[0]
    print(f"使用队列：{queue.name}（id={queue.id}）")

    item = langfuse.api.annotation_queues.create_queue_item(
        queue_id=queue.id,
        object_id=trace_id,
        object_type=AnnotationQueueObjectType.TRACE,  # 也可用 "TRACE"
    )
    print(f"已加入队列，queue_item_id = {item.id}")
    print(
        "\n去 UI：Annotation → 选择该队列 → 开始逐条标注（打分/写备注）。\n"
        "标注产生的分数会挂到对应 trace，可导出用于构建黄金数据集。"
    )
