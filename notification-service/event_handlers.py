# event_handlers.py

EVENT_MESSAGES = {
    "user.created": lambda payload: f"New user registered: {payload['name']} ({payload['email']})",
    "user.deleted": lambda payload: f"🧹 User deleted: {payload['id']}",

    "driver.created": lambda payload: f"New driver joined: {payload['name']} ({payload['vehicle']})",
    "driver.deleted": lambda payload: f"🧹 Driver deleted: {payload['id']}",

    "order.created": lambda payload: f"Order placed by {payload['user_id']} with total ${payload['total']}",
    "order.deleted": lambda payload: f"🧹 Order deleted: {payload['id']}",

    "payment.processed": lambda payload: f"Payment completed for order {payload['order_id']} amount ${payload['amount']}",
    "payment.failed": lambda payload: f"Payment failed for order {payload.get('order_id', 'unknown')}: {payload['error']}",

    "delivery.assigned": lambda payload: f"Driver {payload['driver_id']} assigned to order {payload['order_id']}",
}

def format_event(event_type: str, payload: dict, trace_id: str | None = None) -> str:
    """Return a frontend-friendly message for a given event type. Optional trace_id for logs."""
    prefix = f"[trace:{trace_id}] " if trace_id else ""
    if event_type in EVENT_MESSAGES:
        try:
            return prefix + EVENT_MESSAGES[event_type](payload)
        except Exception as e:
            return prefix + f"[Error formatting event {event_type}] {e}"
    return prefix + f"[Unknown event] {event_type} → {payload}"
