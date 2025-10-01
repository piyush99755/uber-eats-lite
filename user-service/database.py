# database.py
from sqlalchemy import create_engine, MetaData
from databases import Database

DATABASE_URL = "sqlite:///./user_service.db"

# Async database
database = Database(DATABASE_URL)

# SQLAlchemy engine and metadata
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()
