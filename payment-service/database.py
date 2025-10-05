from databases import Database
from sqlalchemy import create_engine
from models import payments  # import the table so its metadata is registered

DATABASE_URL = "sqlite:///./payment_service.db"
database = Database(DATABASE_URL)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# Export metadata from models for table creation
metadata = payments.metadata
