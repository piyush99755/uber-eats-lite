from sqlalchemy import Table, Column, String, Float, JSON, DateTime
from database import metadata, engine
from datetime import datetime

# ------------------------
# Orders table
# ------------------------
orders = Table(
    "orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("items", String, nullable=False),
    Column("total", Float, nullable=False),
    Column("status", String, default="pending"),
    Column("driver_id", String, nullable=True)
)

# ------------------------
# Event Logs table
# ------------------------
event_logs = Table(
    "event_logs",
    metadata,
    Column("id", String, primary_key=True),
    Column("event_type", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("source", String, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow)
)

processed_events = Table(
    "processed_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("event_type", String, nullable=False),
    Column("source_service", String, nullable=False),
    Column("processed_at", DateTime, default=datetime.utcnow)
)
# ------------------------
# Create tables
# ------------------------
metadata.create_all(engine)
