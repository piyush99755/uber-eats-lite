from fastapi import FastAPI

app = FastAPI(title="Order Service")

@app.get("/orders")
def get_orders():
    return {"orders": []}

@app.get("/health")
def health():
    return {"status": "order-service healthy"}
