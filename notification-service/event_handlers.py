# event_handlers.py

# Mapping of event types to frontend-friendly messages
EVENT_MESSAGES = {
    "user.created": lambda payload: f"New user registered: {payload['name']} ({payload['email']})",
    "driver.created": lambda payload: f"New driver joined: {payload['name']} ({payload['vehicle']})",
    "order.created": lambda payload: f"Order placed by {payload['user_id']} with total ${payload['total']}",
    "payment.processed": lambda payload: f"Payment completed for order {payload['order_id']} amount ${payload['amount']}",
    "payment.failed": lambda payload: f"Payment failed for order {payload.get('order_id', 'unknown')}: {payload['error']}",
    "delivery.assigned": lambda payload: f"Driver {payload['driver_id']} assigned to order {payload['order_id']}",
}

def format_event(event_type: str, payload: dict) -> str:
    """Return a frontend-friendly message for a given event type."""
    if event_type in EVENT_MESSAGES:
        try:
            return EVENT_MESSAGES[event_type](payload)
        except Exception as e:
            return f"[Error formatting event {event_type}] {e}"
    return f"[Unknown event] {event_type} → {payload}"
