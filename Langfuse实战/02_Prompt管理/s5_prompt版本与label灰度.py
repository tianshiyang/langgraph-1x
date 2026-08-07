"""
场景 5 · Prompt 版本管理与 Label 灰度发布
============================================================
目标：把 Prompt 从「写死在代码里的字符串」升级成「有版本、能灰度、能回滚」的配置。
     核心思想：代码只按 label（如 production）拉取，改 Prompt / 切版本都在 UI 完成，
     代码不用改、不用发版。

关键 API：
  - langfuse.create_prompt(name, prompt, labels=[...], type="text")  创建/新增版本
  - langfuse.get_prompt(name, label="production")                    按标签拉取
  - prompt.compile(**vars)                                           填充 {{变量}}

运行：
    python "Langfuse实战/02_Prompt管理/s5_prompt版本与label灰度.py"
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from _bootstrap import glm_model, langfuse  # noqa: E402

from langchain_core.messages import HumanMessage  # noqa: E402

PROMPT_NAME = "tutorial-周报助手"


# 首次运行时播种两个版本；已存在则跳过（保证脚本可重复运行不狂造版本）
def seed_prompts_once() -> None:
    try:
        langfuse.get_prompt(PROMPT_NAME, label="production")
        print(f"Prompt「{PROMPT_NAME}」已存在，跳过播种。")
        return
    except Exception:
        pass  # 不存在 → 下面创建

    # v1：简单版，直接设为 production（线上默认用它）
    langfuse.create_prompt(
        name=PROMPT_NAME,
        prompt="把下面的工作流水整理成周报：\n{{content}}",
        labels=["production"],  # production 标签 = 线上默认版本
        type="text",
        commit_message="v1 初版：最简单的整理",
    )
    # v2：更严格的格式版，先只挂 staging（灰度中，线上还不用）
    langfuse.create_prompt(
        name=PROMPT_NAME,
        prompt=(
            "你是资深 HR 助理。请把下面的工作流水整理成周报，要求：\n"
            "1) 不超过 3 条；2) 每条以动词开头；3) 每条不超过 20 字。\n\n"
            "工作流水：\n{{content}}"
        ),
        labels=["staging"],  # staging 标签 = 灰度环境版本
        type="text",
        commit_message="v2 更严格的格式约束",
    )
    print(f"已播种 Prompt「{PROMPT_NAME}」：v1(production) / v2(staging)")


# 用指定 label 的 prompt 生成周报
def make_report(content: str, label: str) -> str:
    prompt = langfuse.get_prompt(PROMPT_NAME, label=label)
    print(f"\n>>> 使用 label={label} 的第 {prompt.version} 版")
    compiled = prompt.compile(content=content)  # 填充 {{content}}
    print("实际发给模型的 prompt：\n", compiled)
    response = glm_model.invoke([HumanMessage(compiled)])
    return response.content


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    seed_prompts_once()

    raw = "周一修了登录 bug；周三写了检索模块；周五和产品对齐了需求。"

    # 线上默认（production → v1）
    print("\n【production 版结果】\n", make_report(raw, "production"))
    # 灰度版（staging → v2），对比效果差异
    print("\n【staging 版结果】\n", make_report(raw, "staging"))

    langfuse.flush()
    print(
        "\n动手体验灰度切换：\n"
        "  1) 去 UI → Prompts → tutorial-周报助手\n"
        "  2) 把 production 标签从 v1 挪到 v2（点版本右侧 → Set label）\n"
        "  3) 不改任何代码，重跑本脚本，production 版结果会变成 v2 的严格格式\n"
        "  4) 出问题时把 production 标签挪回 v1，即完成『一键回滚』"
    )
