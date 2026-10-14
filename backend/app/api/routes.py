"""FastAPI routes. One router, one prefix (/api). Every route is a thin wrapper over api/core.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from ..schemas import (
    AdResponse, ConfigResponse, ErrorResponse, GenerateAdRequest, HealthResponse, JobResponse, ReadyResponse, ScrapeRequest,
    UploadResponse,
)
from .core import Api, UploadedFile
from .ranges import RangeNotSatisfiable, parse_range, read_slice

API_PREFIX = "/api"
router = APIRouter(prefix=API_PREFIX)
root_router = APIRouter()
ERRORS = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 413: {"model": ErrorResponse},
    422: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
}


def get_api(request: Request) -> Api:
    """Dependency: the Api object created at startup."""
    return request.app.state.api


def client_id(request: Request, api: Api) -> str:
    """Who is calling, for rate limiting: the socket address, or X-Forwarded-For when TRUST_PROXY_HEADERS is on."""
    if api.ctx.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/scrape", response_model=JobResponse, status_code=202, responses=ERRORS)
async def start_scrape(body: ScrapeRequest, request: Request, api: Api = Depends(get_api)) -> JobResponse:
    """Start scanning a website. Poll GET /api/jobs/{job_id} for progress."""
    return await api.start_scrape(body, client_id(request, api))


@router.get("/jobs/{job_id}", response_model=JobResponse, responses=ERRORS)
async def get_job(job_id: str, api: Api = Depends(get_api)) -> JobResponse:
    """Progress and result of a website scan."""
    return await api.get_job(job_id)


@router.post("/uploads", response_model=UploadResponse, status_code=201, responses=ERRORS)
async def upload_images(
    request: Request, kind: str = Form("photo"), files: list[UploadFile] = File(...), api: Api = Depends(get_api),
) -> UploadResponse:
    """Upload a logo, photos or videos (multipart form: kind=logo|photo|video, files=...)."""
    limit = api.upload_limit(kind)
    items = [UploadedFile(filename=f.filename or "", content=await f.read(limit + 1)) for f in files[: api.ctx.settings.max_upload_files + 1]]
    return await api.upload(items, kind, client_id(request, api))


@router.get("/assets/{asset_id}", responses=ERRORS)
async def get_asset(asset_id: str, api: Api = Depends(get_api)) -> FileResponse:
    """An uploaded image or video (for previews). The type comes from the stored file, never from the uploader."""
    path, media_type = await api.asset_file(asset_id)
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.post("/generate-ad", response_model=AdResponse, status_code=202, responses=ERRORS)
async def generate_ad(body: GenerateAdRequest, request: Request, api: Api = Depends(get_api)) -> AdResponse:
    """Create ONE ad (one prompt, one video). Poll GET /api/ads/{ad_id}."""
    return await api.create_ad(body, client_id(request, api))


@router.get("/ads/{ad_id}", response_model=AdResponse, responses=ERRORS)
async def get_ad(ad_id: str, api: Api = Depends(get_api)) -> AdResponse:
    """Progress, prompt and result of an ad."""
    return await api.get_ad(ad_id)


@router.post("/ads/{ad_id}/cancel", response_model=AdResponse, responses=ERRORS)
async def cancel_ad(ad_id: str, api: Api = Depends(get_api)) -> AdResponse:
    """Stop an ad that is still being made (it ends as failed with a 'cancelled' message)."""
    return await api.cancel_ad(ad_id)


@router.get("/ads/{ad_id}/video", responses=ERRORS)
async def get_ad_video(request: Request, ad_id: str, download: bool = Query(False), api: Api = Depends(get_api)) -> Response:
    """The finished MP4 (supports Range requests so players can seek)."""
    path = await api.ad_video(ad_id)
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="ad-{ad_id[:8]}.mp4"'
    try:
        span = parse_range(request.headers.get("range"), size)
    except RangeNotSatisfiable:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if span is None:
        return FileResponse(path, media_type="video/mp4", headers=headers)
    start, end = span
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(content=read_slice(path, start, end), status_code=206, media_type="video/mp4", headers=headers)


@router.get("/config", response_model=ConfigResponse)
async def get_config(api: Api = Depends(get_api)) -> ConfigResponse:
    """What this server can do (options, limits, demo mode)."""
    return api.config()


@root_router.get("/health", response_model=HealthResponse)
async def health(api: Api = Depends(get_api)) -> HealthResponse:
    """Liveness: the process is up."""
    return api.health()


@root_router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(api: Api = Depends(get_api)) -> Response:
    """Readiness: database, cache, browser and video provider status. Answers 503 when the database is down."""
    report = await api.ready()
    return JSONResponse(report.model_dump(mode="json"), status_code=200 if report.status == "ok" else 503)

