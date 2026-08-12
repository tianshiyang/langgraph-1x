"""
场景 10 · Dataset 数据集 + Experiment 实验对比
============================================================
目标：把典型 case 攒成可复用的「测试集」，改 Prompt/模型后在同一数据集上跑实验，
     并排对比新旧效果。这就是大模型应用的「回归测试」。

关键 API：
  - langfuse.create_dataset(name=...)                              建数据集
  - langfuse.create_dataset_item(dataset_name=, input=, expected_output=)  加用例
  - dataset = langfuse.get_dataset(name)                           取数据集
  - dataset.run_experiment(name=, task=, evaluators=, run_evaluators=)  跑实验
  - task(*, item, **kwargs)                    对每条用例执行任务，返回输出
  - evaluator(*, input, output, expected_output, metadata, **kwargs) -> Evaluation  打分

本脚本跑两次实验（两套不同 system prompt），在 UI 里可并排对比谁更好。

运行：
    python "Langfuse实战/03_评估/s10_dataset与experiment.py"
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import Evaluation

from Langfuse实战._bootstrap import glm_model, langfuse

DATASET_NAME = "tutorial-常识问答"

# 数据集用例：input=问题，expected_output=期望答案里应包含的关键词
SEED_ITEMS = [
    {"input": "中国的首都是哪座城市？", "expected_output": "北京"},
    {"input": "水的化学分子式是什么？", "expected_output": "H2O"},
    {"input": "一年有多少个月？", "expected_output": "12"},
    {"input": "太阳系中最大的行星是哪颗？", "expected_output": "木星"},
    {"input": "光在真空中的速度约为每秒多少万公里？", "expected_output": "30"},
]


# 首次运行播种数据集（已存在则跳过）
def seed_dataset_once() -> None:
    try:
        ds = langfuse.get_dataset(DATASET_NAME)
        if ds.items:
            print(f"数据集「{DATASET_NAME}」已存在（{len(ds.items)} 条），跳过播种。")
            return
    except Exception:
        langfuse.create_dataset(name=DATASET_NAME, description="教程用：常识问答回归集")

    for it in SEED_ITEMS:
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            input=it["input"],
            expected_output=it["expected_output"],
        )
    print(f"已播种数据集「{DATASET_NAME}」共 {len(SEED_ITEMS)} 条用例。")


# 任务工厂：用不同 system prompt 生成不同的 task（用于对比两套策略）
def make_task(system_prompt: str):
    # 对单条用例执行：把 system + 问题发给模型，返回回答
    def task(*, item, **kwargs) -> str:
        messages = [SystemMessage(system_prompt), HumanMessage(item.input)]
        return glm_model.invoke(messages).content

    return task


# 评估器：期望关键词是否出现在回答里（命中=1，否则=0）
def correctness(*, input, output, expected_output, metadata, **kwargs) -> Evaluation:
    hit = expected_output and (expected_output.lower() in (output or "").lower())
    return Evaluation(
        name="correctness",
        value=1.0 if hit else 0.0,
        comment="命中期望关键词" if hit else f"未命中：期望含『{expected_output}』",
    )


# 评估器：回答是否足够简洁（<=50 字得 1 分）
def conciseness(*, input, output, expected_output, metadata, **kwargs) -> Evaluation:
    concise = len(output or "") <= 50
    return Evaluation(name="conciseness", value=1.0 if concise else 0.0)


# 运行级评估器：整个数据集的平均正确率
def avg_correctness(*, item_results, **kwargs) -> Evaluation:
    vals = [
        e.value for r in item_results for e in r.evaluations if e.name == "correctness"
    ]
    avg = sum(vals) / len(vals) if vals else 0.0
    return Evaluation(name="avg_correctness", value=avg)


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    seed_dataset_once()
    dataset = langfuse.get_dataset(DATASET_NAME)

    evaluators = [correctness, conciseness]
    run_evaluators = [avg_correctness]

    # 实验 A：要求「只答关键词，不要解释」——预期更简洁、更容易命中
    result_a = dataset.run_experiment(
        name="简洁策略",
        description="system 要求只答核心答案",
        task=make_task("你是常识问答助手，只回答最核心的答案，不要任何解释。"),
        evaluators=evaluators,
        run_evaluators=run_evaluators,
    )
    print("\n===== 实验 A（简洁策略）=====")
    print(result_a.format())

    # 实验 B：允许展开解释——对比简洁度会不会下降
    result_b = dataset.run_experiment(
        name="详细策略",
        description="system 允许展开解释",
        task=make_task("你是博学的老师，回答问题时请展开详细解释。"),
        evaluators=evaluators,
        run_evaluators=run_evaluators,
    )
    print("\n===== 实验 B（详细策略）=====")
    print(result_b.format())

    langfuse.flush()
    print(
        "\n去 UI：Datasets → tutorial-常识问答 → Runs，"
        "勾选『简洁策略』和『详细策略』两个 run 即可并排对比正确率/简洁度。"
    )
