from database import database
from models import drivers
from sqlalchemy import select

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
