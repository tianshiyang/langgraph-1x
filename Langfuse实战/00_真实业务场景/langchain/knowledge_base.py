"""mock 企业知识库 + 模拟向量检索。

真实项目里这一层通常是「向量库（如 pgvector/Milvus）+ embedding 模型」。
这里为了让 demo 零外部依赖、可离线复现，用「关键词重叠打分」模拟召回：
文档带一组关键词，命中越多分越高；命中为 0 时回退到字符重叠，保证总能给出弱相关结果。
接口形态（search → 带 score 的文档列表）与真实向量检索保持一致，
上层 rag_service 感知不到底层是 mock 还是真向量库。
"""

from __future__ import annotations

from typing import TypedDict


# 单篇知识库文档
class KBDoc(TypedDict):
    id: str  # 文档唯一 ID
    title: str  # 文档标题（会作为回答里的引用来源）
    text: str  # 文档正文
    keywords: list[str]  # 用于模拟召回的关键词


# 检索命中结果 = 文档 + 本次相关度打分
class RetrievedDoc(TypedDict):
    id: str  # 文档 ID
    title: str  # 文档标题
    text: str  # 文档正文
    score: float  # 相关度打分（越大越相关）


# 企业客服知识库（电商场景）：退货 / 配送 / 发票 / 会员 / 售后 / 支付
KNOWLEDGE_BASE: list[KBDoc] = [
    {
        "id": "kb-return",
        "title": "退货与退款政策",
        "text": (
            "自签收之日起 7 天内，商品完好、不影响二次销售的，可申请无理由退货。"
            "生鲜、定制、贴身衣物等特殊商品不支持无理由退货。"
            "退款在仓库验收合格后 1-3 个工作日原路退回，到账时间以银行为准。"
        ),
        "keywords": ["退货", "退款", "无理由", "7天", "七天", "退", "验收", "到账"],
    },
    {
        "id": "kb-shipping",
        "title": "发货与配送时效",
        "text": (
            "现货商品在付款后 48 小时内发货，预售商品以商品页标注的发货时间为准。"
            "默认合作快递为顺丰/中通，偏远地区时效顺延 1-2 天。"
            "下单后可在「我的订单-物流详情」查看实时轨迹。"
        ),
        "keywords": ["发货", "配送", "快递", "物流", "多久", "时效", "到货", "几天", "顺丰", "预售", "预定"],
    },
    {
        "id": "kb-invoice",
        "title": "发票开具说明",
        "text": (
            "支持开具电子普通发票和增值税专用发票。"
            "电子发票在确认收货后 24 小时内开具，可在「我的-发票管理」下载。"
            "专票需提供公司名称、税号、开户行及账号，审核通过后 3 个工作日内开具。"
        ),
        "keywords": ["发票", "开票", "电子发票", "专票", "普票", "税号", "增值税"],
    },
    {
        "id": "kb-membership",
        "title": "会员等级与权益",
        "text": (
            "会员分为普通、黄金、铂金三级，按近 12 个月累计消费自动升级。"
            "黄金会员享 95 折与专属客服，铂金会员额外享 9 折、免运费和优先发货。"
            "会员权益不可折现，等级每月 1 号根据消费额刷新。"
        ),
        "keywords": ["会员", "等级", "权益", "折扣", "黄金", "铂金", "升级", "积分"],
    },
    {
        "id": "kb-aftersale",
        "title": "售后与人工联系方式",
        "text": (
            "商品质量问题在保修期内可申请换货或维修，需提供订单号与问题照片。"
            "人工客服在线时间为每天 9:00-21:00，可在 App 内「联系客服」转接人工，"
            "或拨打客服热线 400-800-0000。"
        ),
        "keywords": ["售后", "人工", "客服", "换货", "维修", "保修", "投诉", "电话", "热线"],
    },
    {
        "id": "kb-payment",
        "title": "支付方式说明",
        "text": (
            "支持微信、支付宝、银行卡及花呗分期。"
            "单笔订单满 1000 元可选择 3/6/12 期分期，手续费以结算页展示为准。"
            "支付遇到扣款未到账，通常 2 小时内自动回退，如未回退请联系人工客服。"
        ),
        "keywords": ["支付", "付款", "微信", "支付宝", "银行卡", "分期", "花呗", "扣款"],
    },
]


# 关键词命中分：查询里出现一个文档关键词计 1 分
def _keyword_score(query: str, doc: KBDoc) -> float:
    return sum(1.0 for kw in doc["keywords"] if kw in query)


# 字符重叠兜底分：仅在全库都没有关键词命中时使用，避免完全空手
def _char_overlap_score(query: str, doc: KBDoc) -> float:
    chars = set(query)
    return sum(1 for kw in doc["keywords"] for ch in set(kw) if ch in chars) * 0.01


# 模拟向量检索：优先返回关键词命中的文档；全库零命中时才用字符重叠兜底
def search(query: str, top_k: int = 3) -> list[RetrievedDoc]:
    scored = [(doc, _keyword_score(query, doc)) for doc in KNOWLEDGE_BASE]
    hits = [pair for pair in scored if pair[1] > 0]
    if not hits:
        hits = [
            (doc, _char_overlap_score(query, doc))
            for doc in KNOWLEDGE_BASE
        ]
        hits = [pair for pair in hits if pair[1] > 0]
    hits.sort(key=lambda pair: pair[1], reverse=True)
    top = hits[:top_k]
    return [
        {"id": doc["id"], "title": doc["title"], "text": doc["text"], "score": round(score, 3)}
        for doc, score in top
    ]
