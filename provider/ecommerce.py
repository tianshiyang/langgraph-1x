"""
电商客服中台 — 共享业务数据层（SQLAlchemy 2.0 ORM + 真实 Postgres/Neon）
========================================================================

⭐️ 这是「agent循环」和「多智能体」两篇教程共用的【业务数据库】。
   它和 LangGraph 的 checkpointer/store 没关系——那是「Agent 自己的记忆」，
   这里是「公司本来就有的业务库」（订单、物流、商品、售后工单……）。
   Agent 的工具(tool) 最终就是来查这些表，这才是真实企业里 Agent 干的事。

⭐️ 本文件用 SQLAlchemy 2.0 ORM（企业标准），不再手写原生 SQL：
   · 表 = Python 类（DeclarativeBase + Mapped），改字段就改类；
   · 增删改查走 Session + select()，有类型提示、不易拼错。
   · 注意边界：ORM 只管【你自己的业务表】；LangGraph 的 PostgresSaver
     仍走它自己的原生 psycopg，两套并存，互不干扰，这是正常的。

⭐️ 表清单（都加 cs_ 前缀＝customer-service，避免和 langgraph 的 checkpoint 表混）：
   cs_users      用户/会员
   cs_products   商品（含库存）
   cs_orders     订单
   cs_logistics  物流轨迹
   cs_tickets    售后工单（退货/换货/维修/咨询）

⭐️ 用法：
   建表 + 灌数据（幂等，可反复跑）：  python provider/ecommerce.py
   在教程里直接 import 查询函数：     from provider.ecommerce import get_order, ...

⭐️ 对外暴露的函数（get_order / create_ticket 等）返回的仍是【纯 dict / list[dict] / None】，
   方便 @tool 直接用、也方便 str() 成自然语言喂回模型——内部换成 ORM 不影响调用方。
"""

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import ForeignKey, Numeric, create_engine, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ──────────────────────────────────────────────────────────────
# 引擎（Engine）：SQLAlchemy 连接数据库的总入口，整个进程一个就够。
# ⭐️ 把 .env 里的 postgresql:// 改成 postgresql+psycopg://，告诉 SQLAlchemy
#    底层用 psycopg(v3) 这个驱动。URL 里的 sslmode / channel_binding 会原样传给 psycopg。
# ⭐️ pool_pre_ping=True：Neon 这类 serverless 库会回收空闲连接，开启后每次取连接先 ping 一下，
#    自动剔除已失效的连接，避免偶发的 "connection closed" 报错。生产连云库建议都开。
# ──────────────────────────────────────────────────────────────
_DB_URL = os.environ["DB_URI"].replace("postgresql://", "postgresql+psycopg://", 1)
engine = create_engine(_DB_URL, pool_pre_ping=True)


# ═════════════════════════════════════════════════════════════
# 一、表模型（ORM Models）—— 每个类对应一张表
# ⭐️ SQLAlchemy 2.0 现代写法：继承 DeclarativeBase，字段用 Mapped[类型] + mapped_column()。
#    Mapped[str] 表示「这列是字符串、非空」；Mapped[str | None] 表示可空。
# ═════════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    """所有表模型的基类。Base.metadata 里登记了全部表，建表/删表用它。"""


class User(Base):
    __tablename__ = "cs_users"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    phone: Mapped[str | None]
    level: Mapped[str | None]          # 会员等级：普通/黄金/白金会员
    city: Mapped[str | None]


class Product(Base):
    __tablename__ = "cs_products"
    sku: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str | None]
    # ⭐️ 金额用 Numeric(10,2) 精确小数（钱别用 float 存）；读出来是 Decimal，
    #    对外返回前用 _row() 统一转成 float，方便 JSON 序列化 / 喂给模型。
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    stock: Mapped[int | None]
    spec: Mapped[str | None]


class Order(Base):
    __tablename__ = "cs_orders"
    order_id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("cs_users.user_id"))
    sku: Mapped[str | None] = mapped_column(ForeignKey("cs_products.sku"))
    qty: Mapped[int | None]
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # 实付金额
    status: Mapped[str | None]        # 已付款/已发货/已签收/已取消
    created_at: Mapped[datetime | None]


class Logistics(Base):
    __tablename__ = "cs_logistics"
    order_id: Mapped[str] = mapped_column(ForeignKey("cs_orders.order_id"), primary_key=True)
    carrier: Mapped[str | None]       # 承运快递公司
    tracking_no: Mapped[str | None]   # 运单号
    status: Mapped[str | None]        # 揽收/运输中/派送中/已签收
    last_location: Mapped[str | None]
    updated_at: Mapped[datetime | None]


class Ticket(Base):
    __tablename__ = "cs_tickets"
    ticket_id: Mapped[str] = mapped_column(primary_key=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("cs_orders.order_id"))
    type: Mapped[str | None]          # 退货/换货/维修/咨询
    reason: Mapped[str | None]
    status: Mapped[str | None]        # 待处理/处理中/已解决
    created_at: Mapped[datetime | None]


# ──────────────────────────────────────────────────────────────
# 小工具：把 ORM 对象转成纯 dict（对外统一返回 dict，不泄露 ORM 对象）。
# ⭐️ Decimal → float，方便序列化；datetime 原样保留（和旧版行为一致）。
# ──────────────────────────────────────────────────────────────
def _row(obj) -> dict | None:
    if obj is None:
        return None
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        out[col.name] = float(v) if isinstance(v, Decimal) else v
    return out


# ═════════════════════════════════════════════════════════════
# 二、建表 + 灌真实数据（幂等）
# ═════════════════════════════════════════════════════════════
#
# ⭐️ Base.metadata.create_all(engine)：按模型建表，表已存在就跳过（幂等，不会报错）。
# ⭐️ 灌数据用「主键不存在才插」(session.get 查一下)，等价于原来的 ON CONFLICT DO NOTHING，
#    ID 都是稳定可读的（订单 SO2025...、用户 U001、商品 SKU-...），反复跑不会重复造数据。

_SEED_USERS = [
    User(user_id="U001", name="张伟", phone="13800000001", level="黄金会员", city="杭州"),
    User(user_id="U002", name="李娜", phone="13900000002", level="普通会员", city="上海"),
    User(user_id="U003", name="王芳", phone="13700000003", level="白金会员", city="北京"),
]

_SEED_PRODUCTS = [
    Product(sku="SKU-EARBUDS-01", name="静界 Pro 无线降噪耳机", category="数码配件",
            price=Decimal("899.00"), stock=120, spec="夜空黑 / 主动降噪 / 续航30h"),
    Product(sku="SKU-EARBUDS-02", name="静界 Air 半入耳耳机", category="数码配件",
            price=Decimal("399.00"), stock=0, spec="云白 / 半入耳 / 缺货中"),
    Product(sku="SKU-WATCH-01", name="律动 GT 智能手表", category="数码配件",
            price=Decimal("1299.00"), stock=35, spec="曜石黑 / 血氧监测 / 14天续航"),
    Product(sku="SKU-CHARGER-01", name="闪充 65W 氮化镓充电器", category="数码配件",
            price=Decimal("159.00"), stock=500, spec="三口快充 / 适配笔记本"),
    Product(sku="SKU-BOTTLE-01", name="轻随 保温杯 500ml", category="居家",
            price=Decimal("89.00"), stock=240, spec="钛灰 / 24h 保温"),
    Product(sku="SKU-LAMP-01", name="暖光 护眼台灯", category="居家",
            price=Decimal("229.00"), stock=12, spec="国AA级 / 无频闪 / 三档色温"),
]

_SEED_ORDERS = [
    Order(order_id="SO20250601001", user_id="U001", sku="SKU-EARBUDS-01", qty=1,
          amount=Decimal("899.00"), status="已发货", created_at=datetime(2025, 6, 1, 10, 23)),
    Order(order_id="SO20250528002", user_id="U001", sku="SKU-WATCH-01", qty=1,
          amount=Decimal("1299.00"), status="已签收", created_at=datetime(2025, 5, 28, 14, 5)),
    Order(order_id="SO20250610003", user_id="U002", sku="SKU-CHARGER-01", qty=2,
          amount=Decimal("318.00"), status="已付款", created_at=datetime(2025, 6, 10, 9, 41)),
    Order(order_id="SO20250605004", user_id="U003", sku="SKU-LAMP-01", qty=1,
          amount=Decimal("229.00"), status="已发货", created_at=datetime(2025, 6, 5, 19, 30)),
    Order(order_id="SO20250612005", user_id="U002", sku="SKU-BOTTLE-01", qty=3,
          amount=Decimal("267.00"), status="已取消", created_at=datetime(2025, 6, 12, 8, 12)),
]

_SEED_LOGISTICS = [
    Logistics(order_id="SO20250601001", carrier="顺丰速运", tracking_no="SF1234567890",
              status="运输中", last_location="杭州转运中心 已发出", updated_at=datetime(2025, 6, 2, 6, 10)),
    Logistics(order_id="SO20250528002", carrier="顺丰速运", tracking_no="SF0987654321",
              status="已签收", last_location="本人已签收", updated_at=datetime(2025, 5, 30, 11, 20)),
    Logistics(order_id="SO20250605004", carrier="中通快递", tracking_no="ZT5555666677",
              status="派送中", last_location="北京朝阳区派送点 派送中", updated_at=datetime(2025, 6, 7, 8, 45)),
]

_SEED_TICKETS = [
    Ticket(ticket_id="T20250529001", order_id="SO20250528002", type="咨询",
           reason="询问手表表带能否更换尺寸", status="已解决", created_at=datetime(2025, 5, 29, 16, 0)),
]


def seed_all():
    """⭐️ 建表 + 灌入种子数据，幂等。教程运行前会自动调用，保证库里有数据。"""
    Base.metadata.create_all(engine)  # 建表（已存在则跳过）
    with Session(engine) as s:
        for model, rows in [
            (User, _SEED_USERS), (Product, _SEED_PRODUCTS), (Order, _SEED_ORDERS),
            (Logistics, _SEED_LOGISTICS), (Ticket, _SEED_TICKETS),
        ]:
            for row in rows:
                pk = getattr(row, list(model.__table__.primary_key.columns)[0].name)
                if s.get(model, pk) is None:        # ⭐️ 主键不存在才插（幂等）
                    s.merge(row)                    # merge：不存在则插入，已存在则更新
        s.commit()


# ═════════════════════════════════════════════════════════════
# 三、业务查询函数（DAO）—— 这些就是后面 Agent 工具(tool) 的底层实现
# ═════════════════════════════════════════════════════════════
#
# ⭐️ 统一套路：开一个 Session → 用 select()/session.get() 查 → _row() 转成 dict 返回。
#    Session 是「一次会话/工作单元」，with 退出自动关闭，最省心。
# ⭐️ 查不到时返回 None 或空列表，让上层（Agent）决定怎么向用户解释。


def get_user(user_id: str) -> dict | None:
    with Session(engine) as s:
        return _row(s.get(User, user_id))


def get_order(order_id: str) -> dict | None:
    """按订单号查订单主信息。"""
    with Session(engine) as s:
        return _row(s.get(Order, order_id))         # get：按主键查一条，最快


def list_orders_by_user(user_id: str) -> list[dict]:
    """查某用户的全部订单（按时间倒序）。"""
    with Session(engine) as s:
        stmt = (
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
        )
        return [_row(o) for o in s.scalars(stmt)]


def get_logistics(order_id: str) -> dict | None:
    """查订单物流轨迹。未发货的订单查不到物流（返回 None）。"""
    with Session(engine) as s:
        return _row(s.get(Logistics, order_id))


def search_products(keyword: str) -> list[dict]:
    """按关键词模糊搜商品（名称/品类），库存多的排前面。"""
    like = f"%{keyword}%"
    with Session(engine) as s:
        stmt = (
            select(Product)
            .where(or_(Product.name.ilike(like), Product.category.ilike(like)))
            .order_by(Product.stock.desc())
        )
        return [_row(p) for p in s.scalars(stmt)]


def get_product(sku: str) -> dict | None:
    """按 SKU 查单个商品（含库存）。"""
    with Session(engine) as s:
        return _row(s.get(Product, sku))


def create_ticket(order_id: str, type: str, reason: str) -> dict:
    """⭐️ 创建售后工单（这是一个【写操作】副作用！）。

    ticket_id 用「T + 订单号去掉SO + 序号」拼，保证可读且大概率唯一；
    真实系统会用雪花/序列。返回新建的工单 dict。
    """
    with Session(engine) as s:
        # 该订单已有几条工单 → 决定本次序号
        existing = s.scalars(select(Ticket).where(Ticket.order_id == order_id)).all()
        ticket_id = f"T{order_id[2:]}-{len(existing) + 1:02d}"
        ticket = Ticket(
            ticket_id=ticket_id, order_id=order_id, type=type, reason=reason,
            status="待处理", created_at=datetime.now(),
        )
        s.add(ticket)        # 加入会话
        s.commit()           # 提交 → 真正写库
        return _row(ticket)  # commit 后会话仍开着，读属性会自动刷新，安全


def list_tickets_by_order(order_id: str) -> list[dict]:
    """查某订单下的全部售后工单（按时间倒序）。"""
    with Session(engine) as s:
        stmt = (
            select(Ticket)
            .where(Ticket.order_id == order_id)
            .order_by(Ticket.created_at.desc())
        )
        return [_row(t) for t in s.scalars(stmt)]


# ═════════════════════════════════════════════════════════════
# 直接运行：建表 + 灌数据 + 打印一份概览，确认数据进库了
# ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    seed_all()
    print("✅ 电商业务库已就绪（SQLAlchemy 建表 + 灌真实数据，幂等）\n")
    with Session(engine) as s:
        from sqlalchemy import func
        for model in [User, Product, Order, Logistics, Ticket]:
            c = s.scalar(select(func.count()).select_from(model))
            print(f"  {model.__tablename__:<14} {c} 行")
    print("\n示例数据可在教程里直接引用：")
    print("  用户 U001 张伟 | 订单 SO20250601001(耳机·已发货) | 商品 SKU-EARBUDS-02(缺货)")
