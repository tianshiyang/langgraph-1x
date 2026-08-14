"""PII 脱敏 mask（Phase 10 / NFR-2 / 埋点规范 §6）。

职责：提供符合 langfuse MaskFunction 签名的 mask 函数，client 级统一脱敏，业务不手动脱敏。

签名（对齐 langfuse.types.MaskFunction）：def mask_pii(*, data, **kwargs) -> Any

规则（复用你 00_真实业务场景/langfuse/pii.py 的正则集）：
  - 身份证 <ID> / 银行卡 <CARD> / 手机号 <PHONE> / 邮箱 <EMAIL>
  - 替换顺序：身份证、银行卡 先于 手机号（避免长号段被手机号正则误伤）。
  - 递归处理 dict/list（U-5d）；病历诊断可保留，姓名+证件组合、银行卡号必脱敏。

验收：U-5a~d；O-3（含身份证的抽取输入在 UI 显示 <ID>，无明文）。

待实现：def mask_pii(*, data, **kwargs)
"""

# TODO(Phase 10): 迁移/复用现有 pii 正则实现 mask_pii。
