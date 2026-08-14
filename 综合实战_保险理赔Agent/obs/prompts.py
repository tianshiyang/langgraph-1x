"""Prompt 托管 prompts（Phase 11 / 埋点规范 §7 / Agent设计 §10）。

职责：把抽取/决策话术 prompt 推送到 Langfuse，业务侧拉取托管版本（带本地回退，保证 core 可独立跑）。

托管 prompt（埋点规范 §7）：
  - claim-extract          材料→结构化字段        temperature 0
  - claim-decision-letter  通过/拒赔话术          temperature 0.3
  - （可选）claim-preexisting 既往症判定

待实现：
  - push_prompts()                         # 首次把本地基线推到 Langfuse
  - get_prompt(name, label="production")   # 拉托管版本；失败回退本地 BASELINE
  - LOCAL_BASELINE: dict[str, str]         # 本地回退文案

要点：label 灰度 production/latest；运营 UI 改 production 指向版本，代码不动即换线上话术
  （自测：改拒赔话术后重跑 Case C，文书措辞变化）。
"""

import _setup  # noqa: F401

# TODO(Phase 11): 实现托管 + 本地回退 + label 灰度。
