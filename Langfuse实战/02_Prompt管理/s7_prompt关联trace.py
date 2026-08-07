"""
场景 7 · Prompt 与 Trace 关联 + Playground 调试
============================================================
目标：调用模型时，把「用了哪个 Prompt 的哪一版」关联到 trace。
     这样在 UI 里就能「按 Prompt 版本」分析效果（延迟/成本/评分），
     从而用数据决定某个新版本要不要全量上线。

关键 API：
  - 手工 generation：start_as_current_observation(as_type="generation", prompt=<PromptClient>)
  - 或在上下文里：langfuse.update_current_generation(prompt=<PromptClient>)
  （LangChain 场景的关联写法见本阶段 README）

运行：
    python "Langfuse实战/02_Prompt管理/s7_prompt关联trace.py"
运行后去 UI：该 generation 会显示关联的 Prompt 版本；点进 Playground 可继续调。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _bootstrap import glm_model, langfuse  # noqa: E402

from langchain_core.messages import HumanMessage  # noqa: E402
from langfuse import observe  # noqa: E402

PROMPT_NAME = "tutorial-周报助手"  # 复用场景 5 播种的 prompt


# 生成周报，并把所用 Prompt 版本关联到本次 generation
@observe(name="weekly-report-with-prompt")
def make_report_linked(content: str) -> tuple[str, str | None]:
    # 1) 拉取线上 Prompt
    prompt = langfuse.get_prompt(PROMPT_NAME, label="production")
    compiled = prompt.compile(content=content)

    # 2) 把模型调用记录为 generation，并通过 prompt= 建立关联
    with langfuse.start_as_current_observation(
        as_type="generation",
        name="glm-answer",
        model="glm-4",
        input=compiled,
        prompt=prompt,  # ★ 关键：关联 Prompt 版本
    ) as generation:
        response = glm_model.invoke([HumanMessage(compiled)])
        usage = response.usage_metadata or {}
        generation.update(
            output=response.content,
            usage_details={
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "total": usage.get("total_tokens", 0),
            },
        )
        answer = response.content

    trace_id = langfuse.get_current_trace_id()
    return answer, trace_id


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    raw = "周一修了登录 bug；周三写了检索模块；周五和产品对齐了需求。"
    answer, trace_id = make_report_linked(raw)
    print("周报：\n", answer)
    print("\ntrace_id =", trace_id)

    langfuse.flush()
    print(
        "\n去 UI 查看：\n"
        "  - 该 trace 的 glm-answer generation 上会显示关联的 Prompt 版本\n"
        "  - Prompts → tutorial-周报助手 → Metrics：能看到该版本的用量/延迟\n"
        "  - 任意 generation 右上角 → Open in Playground，可直接改 Prompt 试跑并另存新版本"
    )
