"""离线回归：把典型客服 case 攒成数据集，改 Prompt/模型后在同一数据集上跑实验并排对比。

这就是大模型应用的「回归测试」：改动上线前先在这里跑，效果掉了就别发。
本脚本用「同一套 RAG 流程 + 两套不同人设」跑两次实验，在 UI 里并排看谁更好。
对齐 03 章 s10 的真实 API 写法（task / evaluator / run_experiment 签名）。

运行：
    python "Langfuse实战/00_真实业务场景/langfuse/evaluate.py"
"""

from __future__ import annotations

import _setup  # noqa: F401  # 副作用：准备 sys.path 与 .env

from langchain_core.messages import BaseMessage
from langfuse import Evaluation

import rag_service
from client import langfuse
from prompts import build_messages

from provider import glm_model

DATASET_NAME = "support-回归集"

# 数据集用例：input=用户问题，expected_output=回答里应命中的关键词
SEED_ITEMS = [
    {"input": "签收后几天内可以无理由退货？", "expected_output": "7"},
    {"input": "现货一般多久发货？", "expected_output": "48"},
    {"input": "电子发票什么时候能开？", "expected_output": "24"},
    {"input": "铂金会员有什么额外权益？", "expected_output": "免运费"},
    {"input": "人工客服的电话是多少？", "expected_output": "400-800-0000"},
    {"input": "支持哪些支付方式？", "expected_output": "花呗"},
]

# 两套待对比的客服人设
PERSONA_STRICT = (
    "你是「优选商城」客服，只依据检索到的知识库资料回答，"
    "回答末尾必须用「[来源: 标题]」标注来源，资料没有就说转人工，不要编造。"
)
PERSONA_FREE = "你是热情的购物助手，尽量详细地帮用户解答，可以适当发挥。"


# 首次运行播种数据集（已存在则跳过）
def seed_dataset_once() -> None:
    try:
        ds = langfuse.get_dataset(DATASET_NAME)
        if ds.items:
            print(f"数据集「{DATASET_NAME}」已存在（{len(ds.items)} 条），跳过播种。")
            return
    except Exception:
        langfuse.create_dataset(name=DATASET_NAME, description="教程用：客服 RAG 回归集")

    for it in SEED_ITEMS:
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=it["input"],
            expected_output=it["expected_output"],
        )
    print(f"已播种数据集「{DATASET_NAME}」共 {len(SEED_ITEMS)} 条用例。")


# 任务工厂：用指定人设生成 task（走真实 RAG 流程：检索 → 拼消息 → 调模型）
def make_task(system_prompt: str):
    # 对单条用例执行：检索知识库并用指定人设生成回答
    def task(*, item, **kwargs) -> str:
        docs = rag_service.retrieve(item.input)
        history: list[BaseMessage] = []
        messages = build_messages(item.input, docs, history, system_prompt=system_prompt)
        return glm_model.invoke(messages).content

    return task


# 评估器：期望关键词是否命中（命中=1，否则=0）
def answer_hits_expected(*, input, output, expected_output, metadata, **kwargs) -> Evaluation:
    # 统一转成字符串再比对：Langfuse 会把「纯数字字符串」存成 JSON 数字，取回来是 int
    expected = str(expected_output) if expected_output is not None else ""
    answer = str(output) if output is not None else ""
    hit = bool(expected) and expected.lower() in answer.lower()
    return Evaluation(
        name="hit",
        value=1.0 if hit else 0.0,
        comment="命中期望关键词" if hit else f"未命中：期望含『{expected}』",
    )


# 评估器：回答是否带来源引用（考察「严谨引用」人设的效果差异）
def has_citation(*, input, output, expected_output, metadata, **kwargs) -> Evaluation:
    cited = "[来源" in (str(output) if output is not None else "")
    return Evaluation(name="has_citation", value=1.0 if cited else 0.0)


# 运行级评估器：整个数据集的平均命中率（作为回归门禁总分）
def avg_correctness(*, item_results, **kwargs) -> Evaluation:
    vals = [e.value for r in item_results for e in r.evaluations if e.name == "hit"]
    avg = sum(vals) / len(vals) if vals else 0.0
    return Evaluation(name="avg_correctness", value=avg)


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    seed_dataset_once()
    dataset = langfuse.get_dataset(DATASET_NAME)

    evaluators = [answer_hits_expected, has_citation]
    run_evaluators = [avg_correctness]

    # 实验 A：严谨引用人设
    result_a = dataset.run_experiment(
        name="严谨引用人设",
        description="只依据资料回答且必须标注来源",
        task=make_task(PERSONA_STRICT),
        evaluators=evaluators,
        run_evaluators=run_evaluators,
    )
    print("\n===== 实验 A（严谨引用人设）=====")
    print(result_a.format())

    # 实验 B：自由发挥人设
    result_b = dataset.run_experiment(
        name="自由发挥人设",
        description="允许适当发挥、不强制引用",
        task=make_task(PERSONA_FREE),
        evaluators=evaluators,
        run_evaluators=run_evaluators,
    )
    print("\n===== 实验 B（自由发挥人设）=====")
    print(result_b.format())

    langfuse.flush()
    print(
        f"\n去 UI：Datasets → {DATASET_NAME} → Runs，"
        "勾选『严谨引用人设』和『自由发挥人设』两个 run 即可并排对比命中率/引用率。"
    )
