from database import database
from models import drivers
from sqlalchemy import select
from events import publish_event
import uuid


async def choose_available_driver():
    """
    Picks the next available driver using FIFO.
    (First driver who became available is used first.)

    Later you can upgrade this to:
    - least busy algorithm
    - closest driver by distance
    - load-balanced driver selection
    """
    query = (
        select(drivers)
        .where(drivers.c.status == "available")
        .order_by(drivers.c.id.asc())   # deterministic order
    )

    available = await database.fetch_all(query)

    if not available:
        print("[Driver Assignment] ❌ No available drivers found.")
        return None

    # Always pick the first driver → predictable & fair
    driver = available[0]

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