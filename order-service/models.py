from sqlalchemy import Table, Column, String, Float
from database import metadata, engine

orders = Table(
    "orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("items", String, nullable=False),
    Column("total", Float, nullable=False),
    Column("status", String, default="pending")
)

# Create tables
metadata.create_all(engine)
