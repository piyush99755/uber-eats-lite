# database.py
import os
from databases import Database
from sqlalchemy import create_engine
from models import metadata  # ✅ Import shared metadata

# Database URL (from environment or fallback)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://uber:eats@postgres:5432/uber_eats_db"
)

# Async database connection
database = Database(DATABASE_URL)

# Sync engine for schema creation
SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(SYNC_DATABASE_URL)

def init_db():
    """Create all tables if they don't exist."""
    metadata.create_all(engine)
    print("[DB] ✅ Tables ensured (payments).")
