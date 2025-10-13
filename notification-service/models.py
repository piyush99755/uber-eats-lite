from sqlalchemy import Table, Column, String
from database import metadata  # Use the same metadata as database.py

notifications = Table(
    "notifications",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("order_id", String, nullable=True), 
    Column("title", String, nullable=False),
    Column("message", String, nullable=False)
)
