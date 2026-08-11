"""可独立运行的多轮客服对话 demo（纯业务，不 import 任何 langfuse）。

证明：实现层能脱离可观测性独立运行。运行：
    python "Langfuse实战/00_真实业务场景/langchain/app.py"
"""

import pathlib
import sys

import dotenv

# 入口负责路径准备：加项目根（为了 provider）+ 本目录（为了裸导入 rag_service 等）
_THIS_DIR = pathlib.Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parents[2]
for _p in (str(_PROJECT_ROOT), str(_THIS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
dotenv.load_dotenv(_PROJECT_ROOT / ".env")  # 加载模型 API key 等环境变量

from rag_service import SupportSession  # noqa: E402

# 模拟一位客户连问 4 轮（第 2 轮是对第 1 轮的追问，考察多轮理解）
CONVERSATION = [
    "你们家发货一般要多久啊？",
    "那预售的商品呢？",  # 追问：承接上一轮的「发货时效」
    "我买的东西想退，签收 7 天内还能退吗？",
    "如果退货过程中有问题，怎么联系人工客服？",
]


# 跑一段多轮对话并打印回答与命中来源
def main() -> None:
    session = SupportSession()
    for i, question in enumerate(CONVERSATION, start=1):
        result = session.ask(question)
        sources = "、".join(doc["title"] for doc in result["docs"]) or "（无）"
        print(f"\n【第 {i} 轮】用户：{question}")
        print(f"命中知识库：{sources}")
        print(f"客服：{result['answer']}")


if __name__ == "__main__":
    main()
