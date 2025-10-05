import sqlite3
from database import DB_FILE, engine, metadata
from models import notifications
from sqlalchemy import Table, Column, String

# --- Step 1: Ensure notifications table exists ---
metadata.create_all(engine)
print("Table 'notifications' ensured.")

# --- Step 2: Add 'order_id' column if missing ---
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(notifications);")
columns = [col[1] for col in cursor.fetchall()]

if "order_id" not in columns:
    cursor.execute("ALTER TABLE notifications ADD COLUMN order_id TEXT;")
    print("Column 'order_id' added successfully!")
else:
    print("Column 'order_id' already exists.")

conn.commit()
conn.close()
print("Database setup complete!")
