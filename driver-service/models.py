# models.py
import uuid
from sqlalchemy import Table, Column, String, DateTime, Float, Text, MetaData, JSON
from datetime import datetime

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
    Column("order_id", String, nullable=False),
    Column("driver_id", String, nullable=False),
    Column("driver_name", String, nullable=True),
    Column("user_id", String, nullable=True),
    Column("user_name", String, nullable=True),
    Column("items", JSON, nullable=True),
    Column("total", Float, nullable=True),
    Column("status", String, default="assigned"),
    Column("assigned_at", DateTime, default=datetime.utcnow),
    Column("delivered_at", DateTime, nullable=True),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.utcnow)
)

driver_orders_history = Table(
    "driver_orders_history",
    metadata,
    Column("id", String, primary_key=True),
    Column("order_id", String, nullable=False),
    Column("driver_id", String, nullable=False),
    Column("driver_name", String, nullable=True),
    Column("user_id", String, nullable=True),
    Column("user_name", String, nullable=True),
    Column("items", JSON, nullable=True),
    Column("total", Float, nullable=True),
    Column("status", String, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.utcnow)
)

