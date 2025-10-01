from fastapi import FastAPI

app = FastAPI(title="Notification Service")

@app.get("/notifications")
def get_notifications():
    return {"notifications": []}

@app.get("/health")
def health():
    return {"status": "notification-service healthy"}
