from database import database
from models import drivers
from sqlalchemy import select
from events import publish_event
import uuid


async def choose_available_driver():
    """
    Picks the next available driver using FIFO.
    Returns a dictionary with driver fields.
    """
    query = (
        select(drivers)
        .where(drivers.c.status == "available")
        .order_by(drivers.c.id.asc())
    )

    available = await database.fetch_all(query)

    if not available:
        print("[Driver Assignment] ❌ No available drivers found.")
        return None

    # Pick the first available driver
    driver_record = available[0]

    # Convert Record → dict safely
    driver = {
        "id": driver_record["id"],
        "name": driver_record["name"],
        "vehicle": driver_record["vehicle"],
        "license_number": driver_record["license_number"],
        "status": driver_record["status"]
    }

    print(f"[Driver Assignment] Eligible driver selected → {driver['id']}")
    return driver




async def notify_driver_pending(order_id: str):
    await publish_event(
        "driver.pending",
        data={
            "event_id": str(uuid.uuid4()),  
            "order_id": order_id,
            "reason": "no drivers available"
        }
    )

async def notify_driver_failed(order_id: str):
    await publish_event(
        "driver.failed",
        data={
            "event_id": str(uuid.uuid4()), 
            "order_id": order_id,
            "reason": "driver assignment failed after retries"
        }
    )