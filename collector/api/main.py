from fastapi import FastAPI

app = FastAPI(title="The Collector", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
