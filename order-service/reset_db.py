from database import engine, metadata
import models

print("🔄 Dropping tables...")
metadata.drop_all(engine, tables=[models.orders, models.event_logs, models.processed_events])
print("✅ Tables dropped.")

print("🧱 Creating tables...")
metadata.create_all(engine)
print("✅ Tables recreated successfully!")
