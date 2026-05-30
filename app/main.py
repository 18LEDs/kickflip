import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers.grants import router as grants_router
from app.scheduler import scheduler, start_expiry_sweep
from app.tasks import recover_on_startup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()
    start_expiry_sweep()
    await recover_on_startup()
    log.info("Kickflip started")
    yield
    scheduler.shutdown(wait=False)
    log.info("Kickflip stopped")


app = FastAPI(title="Kickflip — Debug Log Enabler", lifespan=lifespan)
app.include_router(grants_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")
