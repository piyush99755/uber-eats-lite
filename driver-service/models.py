# models.py
import uuid
from sqlalchemy import Table, Column, String, DateTime, Float, Text, MetaData, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
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

driver_orders = Table(
    "driver_orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("driver_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    Column("delivered_at", DateTime, nullable=True),
)

driver_orders_history = Table(
    "driver_orders_history",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("order_id", String, nullable=False),
    Column("driver_id", UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
)