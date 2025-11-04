# models.py
from sqlalchemy import Table, Column, String, Text, JSON, TIMESTAMP, func
from database import metadata  # same metadata instance used for all tables

# ---------------------------------------------------------------------------
# Notifications Table
# ---------------------------------------------------------------------------
notifications = Table(
    "notifications",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("order_id", String, nullable=True),
    Column("title", String, nullable=False),
    Column("message", String, nullable=False)
)

# ---------------------------------------------------------------------------
# Events Table  (for Event Dashboard)
# ---------------------------------------------------------------------------
events = Table(
    "events",
    metadata,
    Column("id", String, primary_key=True),
    Column("event_type", Text, nullable=False),
    Column("source_service", Text, nullable=False),
    Column("occurred_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("metadata", JSON, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
)
