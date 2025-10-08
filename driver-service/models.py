# models.py
from sqlalchemy import Table, Column, String
from database import metadata

drivers = Table(
    "drivers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("vehicle", String, nullable=False),
    Column("license_number", String, nullable=False),
    Column("status", String, nullable=False)
)
