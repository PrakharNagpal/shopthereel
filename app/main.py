import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import settings
from app.meta.webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs can carry secrets


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = None
    if settings.front_door == "telegram":
        from app.telegram.poll import run

        task = asyncio.create_task(run())
    yield
    if task:
        task.cancel()


app = FastAPI(title="ShopTheReel", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "front_door": settings.front_door}


@app.get("/done", response_class=HTMLResponse)
async def done() -> str:
    return "<h3>Payment step finished. Go back to the chat.</h3>"
