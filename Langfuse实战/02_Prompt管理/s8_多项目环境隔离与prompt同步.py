"""
场景 8 · 多项目环境隔离与 Prompt 跨项目同步（官方「方案 2」）
============================================================
背景：Langfuse 官方给出两种环境隔离方案——
  · 方案 1「内置 environments」：同一项目里用 LANGFUSE_TRACING_ENVIRONMENT 给
    trace/observation 打环境标签。缺点：不隔离 prompt，测试改的 prompt 生产立刻共用；
    且无访问隔离，谁都能看所有环境数据。
  · 方案 2「每个环境一个独立项目」：dev / staging / production 各是一个 Langfuse 项目，
    各自独立的成员、API key、prompt。优点：权限 + prompt 双隔离；
    代价：prompt 不自动同步，要用 API 或 GitHub 集成手动「从 staging 项目推到 production 项目」。

本脚本演示方案 2 的核心动作：**用 Prompt API 把一个 prompt 从 staging 项目晋升到 production 项目**。

关键点（与单项目 label 灰度的区别）：
  - 单项目 label 灰度（s5）：一个项目内，靠挪 production 标签指针切版本。
  - 多项目隔离（本脚本）：跨两个项目搬运 prompt 内容，两个项目各有各的 key 和 production 标签。

凭证（占位符，自行在 .env 填两套 project key；两个项目通常在同一台实例上）：
    LANGFUSE_STAGING_PUBLIC_KEY=pk-lf-...   # staging 项目
    LANGFUSE_STAGING_SECRET_KEY=sk-lf-...
    LANGFUSE_PROD_PUBLIC_KEY=pk-lf-...      # production 项目
    LANGFUSE_PROD_SECRET_KEY=sk-lf-...
    LANGFUSE_BASE_URL=https://...           # 共用的实例地址（沿用现有变量）

运行：
    python "Langfuse实战/02_Prompt管理/s8_多项目环境隔离与prompt同步.py"
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import _bootstrap  # noqa: F401  仅为副作用：加 sys.path + 加载 .env
from langfuse import Langfuse
from langfuse.model import ChatPromptClient

PROMPT_NAME = "tutorial-周报助手-多项目"


# 用一对 project key 显式构造某个环境的独立客户端；缺 key 时返回 None
def build_client(
    env_name: str, public_key: str | None, secret_key: str | None
) -> Langfuse | None:
    if not public_key or not secret_key:
        return None
    # 注意：不能用 get_client()（它是按默认环境变量的单例，扛不了多项目）；
    # 多项目必须用构造函数显式传 key。host 沿用共用实例地址。
    return Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=os.getenv("LANGFUSE_BASE_URL"),
    )


# 在 staging 项目里播种一个 prompt；已存在则跳过（保证可重复运行不狂造版本）
def seed_staging_prompt(staging: Langfuse) -> None:
    try:
        staging.get_prompt(PROMPT_NAME, label="production")
        print(f"[staging] Prompt「{PROMPT_NAME}」已存在，跳过播种。")
        return
    except Exception:
        pass  # 不存在 → 创建

    staging.create_prompt(
        name=PROMPT_NAME,
        prompt=(
            "你是资深 HR 助理。请把下面的工作流水整理成周报，要求：\n"
            "1) 不超过 3 条；2) 每条以动词开头；3) 每条不超过 20 字。\n\n"
            "工作流水：\n{{content}}"
        ),
        labels=["production"],  # 在 staging 项目内，这份就是 staging 的「线上」版本
        type="text",
        tags=["周报", "教程"],
        commit_message="staging 初版：严格格式约束",
    )
    print(f"[staging] 已播种 Prompt「{PROMPT_NAME}」。")


# 把源项目某个 label 的 prompt 内容，原样晋升到目标项目并打上目标 label
def promote_prompt(
    source: Langfuse,
    target: Langfuse,
    name: str,
    source_label: str,
    target_label: str,
) -> None:
    src_prompt = source.get_prompt(name, label=source_label)
    prompt_type = "chat" if isinstance(src_prompt, ChatPromptClient) else "text"

    # 幂等：目标项目已有同名 prompt 且内容一致，则说明已晋升过，跳过（避免重复造版本）
    try:
        existing = target.get_prompt(name, label=target_label)
        if existing.prompt == src_prompt.prompt:
            print(
                f"[production] 内容与 staging v{src_prompt.version} 一致，已是最新，跳过晋升。"
            )
            return
    except Exception:
        pass  # 目标项目还没有 → 下面首次创建

    target.create_prompt(
        name=src_prompt.name,
        prompt=src_prompt.prompt,  # text: 字符串；chat: 消息列表，均可原样回写
        type=prompt_type,
        labels=[target_label],
        tags=src_prompt.tags,
        config=src_prompt.config,
        commit_message=f"从 staging v{src_prompt.version} 晋升：{src_prompt.commit_message or ''}",
    )
    print(
        f"[production] 已从 staging v{src_prompt.version} 晋升 → 打上 label={target_label}。"
    )


# 缺少任一环境的 key 时，打印配置指引并退出
def require_clients(staging: Langfuse | None, production: Langfuse | None) -> None:
    if staging and production:
        return
    missing = []
    if not staging:
        missing.append("LANGFUSE_STAGING_PUBLIC_KEY / LANGFUSE_STAGING_SECRET_KEY")
    if not production:
        missing.append("LANGFUSE_PROD_PUBLIC_KEY / LANGFUSE_PROD_SECRET_KEY")
    raise SystemExit(
        "方案 2 需要两套独立项目的 key，请在 .env 补齐后重试。缺少：\n  - "
        + "\n  - ".join(missing)
        + "\n\n提示：在 Langfuse 建两个项目（如 my-app-staging / my-app-prod），\n"
        "各自 Settings → API Keys 拿到 pk/sk 填入上面变量；两个项目共用 LANGFUSE_BASE_URL。"
    )


if __name__ == "__main__":
    staging = build_client(
        "staging",
        os.getenv("LANGFUSE_STAGING_PUBLIC_KEY"),
        os.getenv("LANGFUSE_STAGING_SECRET_KEY"),
    )
    production = build_client(
        "production",
        os.getenv("LANGFUSE_PROD_PUBLIC_KEY"),
        os.getenv("LANGFUSE_PROD_SECRET_KEY"),
    )
    require_clients(staging, production)

    # 两个项目的鉴权各自校验（各用各的 key）
    if not staging.auth_check() or not production.auth_check():
        raise SystemExit(
            "鉴权失败：请检查两套 project key 与 LANGFUSE_BASE_URL 是否匹配。"
        )

    # 1) 在 staging 项目迭代 prompt（这里用播种代替「运营在 UI 改」）
    seed_staging_prompt(staging)

    # 2) 验证通过后，把 staging 的 production 版晋升到 production 项目
    promote_prompt(
        source=staging,
        target=production,
        name=PROMPT_NAME,
        source_label="production",  # 取 staging 项目内的线上版
        target_label="production",  # 打到 production 项目的线上标签
    )

    # 3) production 项目的线上代码，永远只按 label 拉取（跨项目内容已就位）
    prod_prompt = production.get_prompt(PROMPT_NAME, label="production")
    print(
        f"\n[production] 线上现使用 v{prod_prompt.version}，模板变量：{prod_prompt.variables}"
    )
    print(
        "实际会发给模型的 prompt：\n",
        prod_prompt.compile(content="周一修 bug；周三写检索；周五对齐需求。"),
    )

    staging.flush()
    production.flush()
    print(
        "\n方案 2 心智小结：\n"
        "  · 隔离靠『项目』：staging / production 各一个 Langfuse 项目，key、成员、prompt 全独立。\n"
        "  · 晋升靠『API/GitHub』：本脚本用 Prompt API 把内容从 staging 项目搬到 production 项目。\n"
        "  · 线上切版本仍靠 label：production 项目内部，依旧用 production 标签指针做灰度/回滚（见 s5）。\n"
        "  · label ≠ 环境：label 是『项目内的版本指针』，环境隔离是『项目级别』的事，两者正交。"
    )
