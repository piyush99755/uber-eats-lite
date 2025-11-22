# models.py
from sqlalchemy import Table, Column, String, DateTime, Float, Text, MetaData
from datetime import datetime

# Define metadata here
metadata = MetaData()

drivers = Table(
    "drivers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("vehicle", String, nullable=False),
    Column("license_number", String, nullable=False),
    Column("status", String, nullable=False),
)

processed_events = Table(
    "processed_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("event_type", String, nullable=False),
    Column("source_service", String, nullable=False),
    Column("processed_at", DateTime, default=datetime.utcnow),
)

delivery_history = Table(
    "delivery_history",
    metadata,
    Column("id", String, primary_key=True),
    Column("driver_id", String, index=True),
    Column("order_id", String, index=True),
    Column("items", Text),
    Column("total", Float),
    Column("delivered_at", DateTime, default=datetime.utcnow),
)
