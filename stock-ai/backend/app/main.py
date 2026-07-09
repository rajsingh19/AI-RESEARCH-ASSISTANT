from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router
from app.auth.router import router as auth_router
from app.config import SettingsError
from app.config import get_settings
from app.database.database import Base
from app.database.database import engine
from app.seed import seed_database
from app.utils.exceptions import AppError
from app.utils.logging import configure_logging
from app.models.conversation import Conversation, Message
from app.models.user import User  # noqa: F401 — ensures User table is created

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    refresher_task = None
    try:
        Base.metadata.create_all(bind=engine)
        seed_database()
        
        # Start background news refresher (Feature 6)
        from app.services.news_refresher import NewsRefresher
        from app.services.news.news_service import NewsServiceFactory
        
        news_svc = NewsServiceFactory.create_news_service(settings)
        if news_svc:
            refresher = NewsRefresher(settings, news_svc)
            import asyncio
            refresher_task = asyncio.create_task(refresher.start_loop())
            logger.info("Background news refresher task started.")
            
        logger.info("Application startup completed.")
        yield
    except SettingsError:
        logger.exception("Application configuration is invalid.")
        raise
    finally:
        if refresher_task:
            refresher_task.cancel()
            try:
                import asyncio
                await refresher_task
            except asyncio.CancelledError:
                pass
        logger.info("Application shutdown completed.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
    description=(
        "AI-powered Stock Market Assistant backed by FastAPI, SQLite, SQLAlchemy, "
        "and Gemini. Financial values are always retrieved from SQLite."
    ),
)

app.include_router(router)
app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ai-research-assistant-two-phi.vercel.app", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.error_code},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "code": "validation_error"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error.", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred.",
            "code": "internal_server_error",
        },
    )


@app.get("/")
def home() -> dict[str, str]:
    return {"message": "Stock AI Backend Running"}
