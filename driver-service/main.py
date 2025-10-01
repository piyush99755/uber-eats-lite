from fastapi import FastAPI

app = FastAPI(title="Driver Service")

@app.get("/drivers")
def get_drivers():
    return {"drivers": []}

@app.get("/health")
def health():
    return {"status": "driver-service healthy"}
