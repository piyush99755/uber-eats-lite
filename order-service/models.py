from sqlalchemy import Table, Column, String, MetaData

metadata = MetaData()

orders = Table(
    "orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String),
    Column("items", String),  # could be JSON/string
    Column("status", String)
)
