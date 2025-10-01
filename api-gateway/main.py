from fastapi import FastAPI

app = FastAPI(title="API Gateway")

@app.get("/")
def root():
    return {"message": "Welcome to API Gateway"}

@app.get("/health")
def health():
    return {"status": "api-gateway healthy"}
