# database.py
import os
from databases import Database
from sqlalchemy import create_engine, MetaData

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://uber:eats@postgres:5432/uber_eats_db"
)

database = Database(DATABASE_URL)

SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")
engine = create_engine(SYNC_DATABASE_URL)

# Single shared metadata
metadata = MetaData()

def init_db():
    metadata.create_all(engine)
