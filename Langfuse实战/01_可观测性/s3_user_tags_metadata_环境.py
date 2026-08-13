"""
场景 3 · User / Tags / Metadata / 环境隔离
============================================================
目标：给 trace 打上业务维度标签，让后续能按维度筛选、聚合、隔离。
  - user_id     ：按用户/租户统计用量与成本
  - tags        ：按业务线/功能筛选（如 weekly-report、rag、agent）
  - metadata    ：挂任意自定义业务字段（如部门、来源渠道）
  - environment ：区分 dev / staging / prod，看板互不污染

关键点：
  - user_id / session_id / tags / metadata 用 propagate_attributes 设置
  - environment 用环境变量 LANGFUSE_TRACING_ENVIRONMENT 设置（需在建 client 前）

运行：
    python "Langfuse实战/01_可观测性/s3_user_tags_metadata_环境.py"
运行后在 UI Tracing 页面用 tags / user / environment 做筛选。
"""

import os
import pathlib
import sys

from langchain_core.messages import HumanMessage
from langfuse import observe, propagate_attributes
from langfuse.langchain import CallbackHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # 项目根：使绝对导入 Langfuse实战.* 生效
from Langfuse实战._bootstrap import glm_model, langfuse

# environment 必须在 get_client() 之前设置好，这里演示用代码兜底（正式建议写进 .env）
os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "development")


langfuse_handler = CallbackHandler()


# 生成一段周报总结（业务函数）
@observe(name="weekly-report")
def generate_weekly_report(raw_text: str) -> str:
    prompt = f"把下面的工作流水整理成 3 条周报要点：\n{raw_text}"
    response = glm_model.invoke(
        [HumanMessage(prompt)], config={"callbacks": [langfuse_handler]}
    )
    # 也可以在 trace 内补充 metadata / tags（作用于当前 span）
    langfuse.update_current_span(metadata={"raw_char_count": len(raw_text)})
    return response.content


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    raw = "周一修了登录 bug；周三写了检索模块；周五和产品对齐了需求。"

    # propagate_attributes 一次性把用户、标签、业务元数据打到整条 trace
    with propagate_attributes(
        user_id="user-xiaotian",  # 按用户统计
        tags=["weekly-report", "rag"],  # 按业务线筛选
        metadata={"department": "研发部", "channel": "内部工具"},  # 自定义业务字段
    ):
        result = generate_weekly_report(raw)
        print("周报：\n", result)

    langfuse.flush()
    print("\n已上报（environment=development）。在 UI 里可按以下维度筛选：")
    print("  - Tags: weekly-report / rag")
    print("  - User: user-xiaotian")
    print("  - Environment: development（右上角环境切换）")
