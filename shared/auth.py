import uuid
import os
from fastapi import Request
from jose import jwt, JWTError

JWT_SECRET = os.getenv("JWT_SECRET", "demo_secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

async def get_optional_user(request: Request):
    auth = request.headers.get("Authorization")
    trace_id = str(uuid.uuid4())

    if not auth or not auth.lower().startswith("bearer "):
        return {"id": None, "role": None, "trace_id": trace_id}

    token = auth.split(" ", 1)[1].strip()

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "id": payload.get("sub"),
            "role": payload.get("role"),
            "trace_id": trace_id
        }
    except JWTError:
        return {"id": None, "role": None, "trace_id": trace_id}
