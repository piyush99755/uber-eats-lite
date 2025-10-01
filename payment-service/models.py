from sqlalchemy import Table, Column, String, Float, MetaData

metadata = MetaData()

payments = Table(
    "payments",
    metadata,
    Column("id", String, primary_key=True),
    Column("order_id", String),
    Column("amount", Float),
    Column("status", String)
)
