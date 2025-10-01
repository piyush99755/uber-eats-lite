from sqlalchemy import Table, Column, String
from database import metadata

users = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("email", String, nullable=False, unique=True),
)
