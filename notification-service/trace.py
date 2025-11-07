# trace.py
import uuid

def get_or_create_trace_id(existing_trace_id=None):
    """Return existing trace_id or generate a new one."""
    if existing_trace_id:
        return existing_trace_id
    return str(uuid.uuid4())
