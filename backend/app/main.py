import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import router
from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.services.system_settings import load_overrides
from app.jobs.download_runner import recover_interrupted
from app.jobs.storage_runner import recover_interrupted as recover_storage_interrupted
from app.jobs.spider_runner import recover_interrupted_pool_scans

logger = logging.getLogger(__name__)

app = FastAPI(title="software_spider Admin", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.api_cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def load_saved_settings() -> None:
    try:
        with SessionLocal() as db:
            load_overrides(db)
        recover_interrupted()
        recover_storage_interrupted()
        recover_interrupted_pool_scans()
    except SQLAlchemyError:
        logger.warning("Could not load saved settings; using .env defaults", exc_info=True)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.status_code, "message": exc.detail}})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": 422, "message": exc.errors()}})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        return {"status": "degraded", "database": "disconnected"}


app.include_router(router)
