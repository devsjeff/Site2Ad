"""FastAPI application factory. Run with:  uvicorn app.main:app --host 0.0.0.0 --port 8000"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.core import Api, ApiError
from .api.routes import root_router, router
from .config import Settings, redact
from .context import AppContext

VERSION = "1.0.0"
logger = logging.getLogger("adsify")


def configure_logging(level: str) -> None:
    """One simple log format for the whole app."""
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def error_body(detail: str, code: str) -> dict:
    """The one error shape every non-2xx response uses (matches schemas.ErrorResponse)."""
    return {"detail": detail, "code": code}


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Build the app: CORS from CORS_ORIGINS, one /api router, uniform JSON errors, services created at startup."""
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    problems = settings.validate()
    if problems:
        raise RuntimeError("Invalid configuration:\n - " + "\n - ".join(problems))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Create the services on startup and close them on shutdown."""
        logger.info("starting Adsify %s with %s", VERSION, redact(settings))
        ctx = await AppContext.create(settings)
        app.state.ctx = ctx
        app.state.api = Api(ctx)
        try:
            yield
        finally:
            await ctx.close()

    production = settings.env == "production"
    app = FastAPI(
        title="Adsify API", version=VERSION, lifespan=lifespan,
        description="Website to video ad: scan a website, write ONE prompt, create ONE video.",
        docs_url=None if production else "/docs", redoc_url=None, openapi_url=None if production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"], expose_headers=["Content-Range", "Accept-Ranges"],
    )

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        """Known errors: status, message and code from the Api layer."""
        return JSONResponse(error_body(exc.message, exc.code), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Bad request bodies: one readable sentence instead of Pydantic's nested list."""
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part not in {"body", "query", "path"})
        message = first.get("msg", "Invalid request.")
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
        return JSONResponse(error_body(f"{where}: {message}" if where else message, "invalid_request"), status_code=422)

    @app.exception_handler(Exception)
    async def on_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Anything else: log it, show a generic message (no stack traces to users)."""
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(error_body("Something went wrong on our side. Please try again.", "internal_error"), status_code=500)

    app.include_router(router)
    app.include_router(root_router)
    return app


app = create_app()
