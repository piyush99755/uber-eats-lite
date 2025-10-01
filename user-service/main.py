from fastapi import FastAPI

app = FastAPI(title="User Service")

@app.get("/users")
def get_users():
    return {"users": []}

@app.get("/health")
def health():
    return {"status": "user-service healthy"}
