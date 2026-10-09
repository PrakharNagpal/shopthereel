import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import settings
from app.meta.webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs can carry secrets


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = None
    if settings.front_door == "telegram":
        from app.telegram.poll import run

        task = asyncio.create_task(run())
    from app.dm.instagram import restore
    restore()
    yield
    if task:
        task.cancel()


app = FastAPI(title="ShopTheReel", lifespan=lifespan)
app.include_router(webhook_router)

from app.web.routes import router as web_router
app.include_router(web_router)
from app.meta.commerce import router as commerce_router
app.include_router(commerce_router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "front_door": settings.front_door}


@app.get("/done", response_class=HTMLResponse)
async def done() -> str:
    return "<h3>Payment step finished. Go back to the chat.</h3>"

from fastapi import Request
from fastapi.responses import JSONResponse
from app.reap.client import ReapError
import httpx

@app.exception_handler(ReapError)
async def reap_error(request: Request, exc: ReapError):
    from app.purchase.service import friendly_error
    return JSONResponse({'detail':friendly_error(exc),'code':exc.code}, status_code=502)

@app.exception_handler(httpx.RequestError)
async def network_error(request: Request, exc: httpx.RequestError):
    return JSONResponse({'detail':'The store service timed out. Try again in a moment.'}, status_code=502)
