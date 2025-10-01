from fastapi import FastAPI

app = FastAPI(title="Payment Service")

@app.get("/payments")
def get_payments():
    return {"payments": []}

@app.get("/health")
def health():
    return {"status": "payment-service healthy"}
