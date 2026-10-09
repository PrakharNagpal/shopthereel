import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.meta.webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ShopTheReel")
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/done", response_class=HTMLResponse)
async def done() -> str:
    return "<h3>Payment step finished. Go back to Instagram.</h3>"
