# models.py
from sqlalchemy import Table, Column, String,DateTime
from database import metadata
from datetime import datetime


drivers = Table(
    "drivers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("vehicle", String, nullable=False),
    Column("license_number", String, nullable=False),
    Column("status", String, nullable=False)
)

processed_events = Table(
    "processed_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("event_type", String, nullable=False),
    Column("source_service", String, nullable=False),
    Column("processed_at", DateTime, default=datetime.utcnow)
)
