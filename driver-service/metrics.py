from prometheus_client import Counter, Gauge

DRIVER_EVENTS_PROCESSED = Counter(
    "driver_events_processed_total",
    "Total driver-related events processed",
    ["event_type"]
)

ACTIVE_DRIVERS = Gauge(
    "active_drivers_total",
    "Current number of active drivers"
)