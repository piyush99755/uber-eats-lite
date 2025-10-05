import os
from databases import Database
from sqlalchemy import create_engine, MetaData

# --- Absolute path to database file to avoid path issues on Windows ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db")
DATABASE_URL = f"sqlite:///{DB_FILE}"

# --- SQLAlchemy engine and metadata ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()

# --- Databases connection ---
database = Database(DATABASE_URL)

