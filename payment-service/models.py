# models.py
from sqlalchemy import Table, Column, String, Float, MetaData, UniqueConstraint
from database import metadata   

payments = Table(
    "payments",
    metadata,
    Column("id", String, primary_key=True),
    Column("order_id", String, nullable=False, unique=True),
    Column("amount", Float, nullable=False),
    Column("status", String, nullable=False),
    Column("user_id",String, nullable=True),

    UniqueConstraint("order_id", name="uix_order_id")
)
