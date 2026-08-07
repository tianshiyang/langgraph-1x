"""
场景 12 · CI/CD 回归门禁 + PII 脱敏
============================================================
把前面所有能力串成「工程闭环」，演示两个企业刚需：

【A. PII 脱敏】
  合规要求 trace 里不能落敏感信息（手机号/身份证）。
  用 Langfuse(mask=fn)：在数据上报前同步脱敏，UI 里看到的是打码后的内容。
  关键：mask 函数签名固定为  def mask(*, data, **kwargs) -> Any

【B. CI 回归门禁】
  把场景 10 的数据集实验塞进 CI：跑完算平均分，低于阈值就 exit(1) 卡住部署。
  这样每次改 Prompt/模型走 PR 时，效果回退会被自动拦下。

前置：需要先跑过 场景10 播种数据集 tutorial-常识问答。

运行（正常应通过；把阈值调高可看到门禁拦截）：
    python "Langfuse实战/04_企业集成/s12_ci门禁与pii脱敏.py"
    echo "退出码 = $?"   # 0=通过, 1=回归拦截
"""

import pathlib
import re
import sys
from typing import Any

# 只做 sys.path + dotenv，不复用 _bootstrap 的单例（本场景要自建带 mask 的 client）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
import dotenv  # noqa: E402

dotenv.load_dotenv(_ROOT / ".env")

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langfuse import Evaluation, Langfuse, observe  # noqa: E402

from provider import glm_model  # noqa: E402

# ============================================================
# A. PII 脱敏
# ============================================================
PHONE_RE = re.compile(r"1\d{10}")  # 简化版手机号：1 开头 11 位
ID_RE = re.compile(r"\d{17}[\dxX]")  # 简化版身份证：18 位


# 递归地对字符串做正则打码（dict/list 也能处理）
def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = PHONE_RE.sub("<PHONE>", value)
        value = ID_RE.sub("<ID>", value)
        return value
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


# Langfuse 上报前调用的脱敏钩子（签名固定：关键字参数 data）
def pii_mask(*, data: Any, **kwargs: Any) -> Any:
    return _redact(data)


# ★ 自建带 mask 的客户端（本进程第一个 client，确保 mask 生效）
langfuse = Langfuse(mask=pii_mask)


# 产生一条含敏感信息的 trace，验证会被脱敏
@observe(name="pii-demo")
def handle_with_pii(user_text: str) -> str:
    resp = glm_model.invoke([HumanMessage(user_text)])
    # 手工把「原始含敏感信息」写进 span 的 input/output，观察是否被打码
    langfuse.update_current_span(input=user_text, output=resp.content)
    return resp.content


def run_pii_demo() -> None:
    text = "我的手机号是 13800138000，身份证 11010119900307561X，帮我查订单。"
    print("原始输入（含敏感信息）：", text)
    handle_with_pii(text)
    langfuse.flush()
    print("已上报。去 UI 查看该 trace：手机号/身份证应显示为 <PHONE> / <ID>。\n")


# ============================================================
# B. CI 回归门禁
# ============================================================
DATASET_NAME = "tutorial-常识问答"  # 复用场景 10 播种的数据集
PASS_THRESHOLD = 0.6  # 平均正确率低于此值 → 判定回归，卡部署


# 任务：回答数据集里的问题
def task(*, item, **kwargs) -> str:
    messages = [
        SystemMessage("你是常识问答助手，只回答最核心的答案，不要解释。"),
        HumanMessage(item.input),
    ]
    return glm_model.invoke(messages).content


# 单条评估器：期望关键词是否命中
def correctness(*, input, output, expected_output, metadata, **kwargs) -> Evaluation:
    hit = expected_output and (expected_output.lower() in (output or "").lower())
    return Evaluation(name="correctness", value=1.0 if hit else 0.0)


# 运行级评估器：平均正确率
def avg_correctness(*, item_results, **kwargs) -> Evaluation:
    vals = [
        e.value for r in item_results for e in r.evaluations if e.name == "correctness"
    ]
    return Evaluation(name="avg_correctness", value=(sum(vals) / len(vals)) if vals else 0.0)


# 跑实验并根据阈值决定 CI 是否通过；返回进程退出码
def run_ci_gate() -> int:
    try:
        dataset = langfuse.get_dataset(DATASET_NAME)
    except Exception:
        print(f"未找到数据集「{DATASET_NAME}」，请先运行 场景10 播种。")
        return 1

    result = dataset.run_experiment(
        name="CI回归检查",
        task=task,
        evaluators=[correctness],
        run_evaluators=[avg_correctness],
    )
    print(result.format())

    # 从运行级评估结果里取平均正确率
    score = next(
        (e.value for e in result.run_evaluations if e.name == "avg_correctness"), 0.0
    )
    print(f"\n平均正确率 = {score:.2f}，阈值 = {PASS_THRESHOLD}")
    if score < PASS_THRESHOLD:
        print("❌ 效果回退，CI 拦截本次部署（exit 1）")
        return 1
    print("✅ 达标，允许部署（exit 0）")
    return 0


if __name__ == "__main__":
    if not langfuse.auth_check():
        raise SystemExit("Langfuse 鉴权失败，请检查 .env 中的 key 与 BASE_URL")

    print("===== A. PII 脱敏 =====")
    run_pii_demo()

    print("===== B. CI 回归门禁 =====")
    exit_code = run_ci_gate()

    langfuse.flush()
    sys.exit(exit_code)
