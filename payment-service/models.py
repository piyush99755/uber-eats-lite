from sqlalchemy import Table, Column, String, Float, MetaData

metadata = MetaData()

payments = Table(
    "payments",
    metadata,
    Column("id", String, primary_key=True),
    Column("order_id", String, nullable=False),
    Column("amount", Float, nullable=False),
    Column("status", String, nullable=False)
)

