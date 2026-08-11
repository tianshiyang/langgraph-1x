"""PII 脱敏：作为 Langfuse 客户端的 `mask` 钩子，在数据上报前同步打码。

签名严格对齐 `langfuse.types.MaskFunction`：仅接收关键字参数 `data`，返回替换后的值。
需自行递归处理 str / dict / list 等嵌套结构；返回值会替代原始数据，必须可 JSON 序列化。
"""

from __future__ import annotations

import re
from typing import Any

# 常见 PII 正则（按需扩展）
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")  # 中国大陆手机号
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dХxX](?!\d)")  # 18 位身份证号
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")  # 邮箱
_BANK_CARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")  # 银行卡号（16-19 位）


# 对单个字符串做脱敏替换（顺序：身份证/银行卡先于手机号，避免长号段被截断误伤）
def _mask_text(text: str) -> str:
    text = _EMAIL_RE.sub("<EMAIL>", text)
    text = _ID_CARD_RE.sub("<ID>", text)
    text = _BANK_CARD_RE.sub("<CARD>", text)
    text = _PHONE_RE.sub("<PHONE>", text)
    return text


# 递归脱敏：处理字符串、字典、列表/元组，其余类型原样返回
def mask_pii(*, data: Any, **kwargs: Any) -> Any:
    if isinstance(data, str):
        return _mask_text(data)
    if isinstance(data, dict):
        return {key: mask_pii(data=value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask_pii(data=item) for item in data]
    return data
