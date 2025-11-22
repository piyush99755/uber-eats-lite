# database.py
import os
from databases import Database
from sqlalchemy import create_engine
from models import metadata

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://uber:eats@postgres:5432/uber_eats_db"
)

# Async DB for actual queries
database = Database(DATABASE_URL)

# Sync engine for create_tables.py
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(SYNC_DATABASE_URL)
