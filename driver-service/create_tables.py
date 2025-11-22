# create_tables.py
from database import engine
from models import metadata

print("Creating tables in DB...")
metadata.create_all(engine)
print("Tables created successfully!")
