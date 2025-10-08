from databases import Database
from sqlalchemy import create_engine, MetaData

DATABASE_URL = "sqlite:///./driver_service.db"

# Async database connection
database = Database(DATABASE_URL)

# SQLAlchemy engine (used for table creation)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Metadata object to hold table definitions
metadata = MetaData()
