#!/usr/bin/env python3
"""Generate docs/openapi.json (OpenAPI 3.1) and docs/postman_collection.json from the real FastAPI app.

    python scripts/generate_openapi.py            # write both files
    python scripts/generate_openapi.py --check    # fail if the committed files are out of date

The routes, parameters and schemas come from FastAPI itself (backend/app/api/routes.py + backend/app/schemas.py).
This script only adds what FastAPI cannot see from the type hints, all of it taken from the code:
  * the real error body {detail, code} (app/main.py replaces FastAPI's default 422 body) and the codes each route returns
    (app/api/core.py, app/services/ads.py),
  * binary responses (uploaded files, the MP4 with HTTP Range support, 206 / 416),
  * the allowed upload kinds, tags, clean operation ids and request examples.
No settings values are written into the files: the app is built with built-in defaults and no .env file.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DOCS = ROOT / "docs"
OPENAPI_PATH = DOCS / "openapi.json"
POSTMAN_PATH = DOCS / "postman_collection.json"

ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}

# Error codes per route, exactly as raised in app/api/core.py, app/services/ads.py and app/main.py.
ERRORS: dict[tuple[str, str], dict[str, str]] = {
    ("post", "/api/scrape"): {
        "422": "`invalid_request` (body failed validation).",
        "429": "`rate_limited` (too many requests from this client per minute).",
    },
    ("get", "/api/jobs/{job_id}"): {"404": "`job_not_found` (unknown or expired scan)."},
    ("post", "/api/uploads"): {
        "400": "`bad_kind`, `no_files`, `too_many_files`, `bad_image` or `bad_video` (the file failed validation).",
        "413": "`file_too_large` (MAX_UPLOAD_BYTES for images, MAX_VIDEO_UPLOAD_BYTES for videos).",
        "422": "`invalid_request` (missing multipart fields).",
        "429": "`rate_limited`.",
    },
    ("get", "/api/assets/{asset_id}"): {"404": "`asset_not_found`."},
    ("post", "/api/generate-ad"): {
        "404": "`job_not_found` (the scan in `job_id` does not exist or expired).",
        "409": "`scan_not_ready` (the scan has no first result yet).",
        "422": (
            "`invalid_request` (contradictory or invalid fields), `business_name_required`, `ai_video_unavailable` "
            "(AI modes without a configured video provider), `no_images`, `unknown_image`, `asset_not_found`, "
            "`bad_media` or `invalid_creative`."
        ),
        "429": "`rate_limited` or `daily_limit` (MAX_ADS_PER_DAY reached).",
    },
    ("get", "/api/ads/{ad_id}"): {"404": "`ad_not_found`."},
    ("post", "/api/ads/{ad_id}/cancel"): {"404": "`ad_not_found`.", "409": "`ad_finished` (already completed or failed)."},
    ("get", "/api/ads/{ad_id}/video"): {
        "404": "`ad_not_found`, or `no_video` (the ad failed).",
        "409": "`video_not_ready` (the ad is still being made).",
        "422": "`invalid_request` (bad query parameter).",
    },
}
TAGS = {
    "/api/scrape": "Website scan", "/api/jobs/{job_id}": "Website scan",
    "/api/uploads": "Uploads", "/api/assets/{asset_id}": "Uploads",
    "/api/generate-ad": "Ads", "/api/ads/{ad_id}": "Ads", "/api/ads/{ad_id}/cancel": "Ads", "/api/ads/{ad_id}/video": "Ads",
    "/api/config": "Configuration", "/health": "Health", "/ready": "Health",
}
TAG_DESCRIPTIONS = {
    "Website scan": "Start a background scan of a business website and poll its progress and result.",
    "Uploads": "Upload a logo, photos or videos (validated on the server) and fetch them by id.",
    "Ads": "Create ONE video ad in the background, poll it, cancel it and download the finished MP4.",
    "Configuration": "Options and limits of this deployment, so clients never hard-code them.",
    "Health": "Liveness and readiness probes (outside the /api prefix).",
}

EXAMPLES = {
    ("post", "/api/scrape"): {"scan": {"summary": "Scan a website", "value": {"url": "https://www.example.com", "refresh": False}}},
    ("post", "/api/generate-ad"): {
        "website": {
            "summary": "Auto ad from a scan: original website images (no AI video)",
            "value": {
                "job_id": "0123456789abcdef0123456789abcdef",
                "options": {"platform": "taxi_screen", "duration_seconds": 10, "style": "cinematic_premium", "add_overlays": True},
                "creative": {"creation_mode": "auto", "creative_mode": "website", "use_website_images": True,
                             "include_qr": True, "qr_url": "https://www.example.com/order"},
                "wait_for_prompt": False,
            },
        },
        "ai": {
            "summary": "Auto ad with AI-generated footage (needs a configured video provider)",
            "value": {
                "job_id": "0123456789abcdef0123456789abcdef",
                "business": {"cta": "Order now"},
                "options": {"goal": "awareness", "platform": "instagram_reel", "duration_seconds": 10},
                "creative": {"creation_mode": "auto", "creative_mode": "ai", "use_ai_video": True},
                "wait_for_prompt": False,
            },
        },
        "manual": {
            "summary": "Manual ad from uploaded media (FFmpeg only, no scan, no AI)",
            "value": {
                "business": {"name": "Night Owl Cafe", "offer": "2 for 1 coffee", "cta": "Scan to order"},
                "options": {"platform": "taxi_screen", "duration_seconds": 5},
                "creative": {"creation_mode": "manual", "use_uploaded_media": True,
                             "media_asset_ids": ["0123456789abcdef0123456789abcdef"],
                             "include_qr": True, "qr_url": "https://www.example.com/menu"},
            },
        },
    },
}


def build_app():
    """The real FastAPI app, built with default settings only (no .env, no keys)."""
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("APP_ENV", "development")
    from app.config import Settings  # noqa: E402
    from app.main import VERSION, create_app  # noqa: E402

    return create_app(Settings()), VERSION


def build_openapi() -> dict:
    """OpenAPI 3.1 for every route of the app, with the additions described in the module docstring."""
    app, version = build_app()
    spec = copy.deepcopy(app.openapi())
    # operation id = the Python function behind the route (e.g. get_job), not FastAPI's long generated name
    from app.api.routes import root_router, router  # noqa: E402  (the two routers the app includes)

    names = {
        (method.lower(), route.path): route.name
        for source in (router, root_router) for route in source.routes for method in getattr(route, "methods", None) or ()
    }
    spec["openapi"] = "3.1.0"
    spec["info"] = {
        "title": "Site2Ad (Adsify) API",
        "version": version,
        "summary": "Turn a business website, or your own media, into a short video ad.",
        "description": (
            "Scan a website, upload media, create ONE video ad in the background and download the MP4.\n\n"
            "**Long-running work is asynchronous.** `POST /api/scrape` and `POST /api/generate-ad` answer `202 Accepted` "
            "at once; poll `GET /api/jobs/{job_id}` and `GET /api/ads/{ad_id}` until the job is final.\n\n"
            "**Authentication:** none. The API has no login; protect a public deployment with your own gateway "
            "(see docs/API.md). Requests that cost money are limited per client (`RATE_LIMIT_PER_MINUTE`) and per day "
            "(`MAX_ADS_PER_DAY`).\n\n"
            "**Errors** always use the body `{\"detail\": \"plain-language message\", \"code\": \"machine_code\"}`."
        ),
    }
    spec["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development backend"},
        {"url": "{baseUrl}", "description": "Your deployment", "variables": {"baseUrl": {"default": "https://api.example.com"}}},
    ]
    spec["security"] = []
    spec["tags"] = [{"name": name, "description": text} for name, text in TAG_DESCRIPTIONS.items()]
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})

    for path, item in spec["paths"].items():
        for method, operation in item.items():
            operation["tags"] = [TAGS.get(path, "Other")]
            operation["operationId"] = names.get((method, path), operation.get("operationId", ""))
            responses = operation.setdefault("responses", {})
            # FastAPI documents its own 422 body; this app returns ErrorResponse instead (app/main.py).
            if "422" in responses:
                responses["422"] = {"description": "Validation error", "content": {"application/json": {"schema": ERROR_REF}}}
            for status, text in ERRORS.get((method, path), {}).items():
                responses[status] = {"description": text, "content": {"application/json": {"schema": ERROR_REF}}}
            for status in [s for s in list(responses) if s in {"400", "404", "409", "413", "422", "429"} and (method, path) in ERRORS]:
                if status not in ERRORS[(method, path)]:
                    responses.pop(status)  # FastAPI's shared ERRORS list: keep only codes this route really returns
            if path.startswith("/api/"):
                responses.setdefault("500", {"description": "`internal_error` (unexpected server error; details are logged, never returned).",
                                             "content": {"application/json": {"schema": ERROR_REF}}})
            if (method, path) in EXAMPLES:
                operation["requestBody"]["content"]["application/json"]["examples"] = EXAMPLES[(method, path)]

    _fix_uploads(spec, schemas)
    _fix_binary(spec)
    for unused in ("HTTPValidationError", "ValidationError"):
        if unused in schemas and unused not in json.dumps(spec["paths"]):
            schemas.pop(unused)
    return spec


def _fix_uploads(spec: dict, schemas: dict) -> None:
    """Document the multipart form: kind (logo | photo | video, checked in app/api/core.py) and the files field."""
    operation = spec["paths"]["/api/uploads"]["post"]
    ref = operation["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"].split("/")[-1]
    form = schemas[ref]
    form["properties"]["kind"].update({
        "enum": ["logo", "photo", "video"],
        "description": "logo: one image (PNG kept). photo: JPG/PNG/WebP, re-encoded. video: MP4/MOV/WebM, checked with ffprobe.",
    })
    form["properties"]["files"]["description"] = "One or more files (one for a logo). Limits come from GET /api/config."
    operation["description"] = (
        "Multipart upload. Images are decoded and re-encoded (EXIF and hidden data removed); videos are identified from "
        "their bytes and checked with ffprobe (H.264, H.265, VP8, VP9, AV1; length and size limits). All files of one "
        "request are stored or none (all or nothing)."
    )


def _fix_binary(spec: dict) -> None:
    """Binary responses for /api/assets/{id} and the MP4 with Range support."""
    binary = {"type": "string", "contentMediaType": "application/octet-stream"}
    asset = spec["paths"]["/api/assets/{asset_id}"]["get"]
    asset["responses"]["200"] = {
        "description": "The stored file. The media type comes from the stored file, never from the uploader.",
        "content": {kind: {"schema": binary} for kind in ("image/png", "image/jpeg", "video/mp4", "video/quicktime", "video/webm")},
    }
    video = spec["paths"]["/api/ads/{ad_id}/video"]["get"]
    video.setdefault("parameters", []).append({
        "name": "Range", "in": "header", "required": False,
        "description": "Optional byte range, e.g. `bytes=0-1048575` (players use it to seek).",
        "schema": {"type": "string"},
    })
    mp4 = {"video/mp4": {"schema": binary}}
    video["responses"]["200"] = {
        "description": "The whole MP4. With `download=true` it is sent as an attachment.",
        "headers": {"Accept-Ranges": {"schema": {"type": "string", "const": "bytes"}},
                    "Content-Disposition": {"description": "Only with download=true.", "schema": {"type": "string"}}},
        "content": mp4,
    }
    video["responses"]["206"] = {
        "description": "The requested byte range of the MP4.",
        "headers": {"Content-Range": {"schema": {"type": "string"}, "description": "e.g. `bytes 0-1048575/5242880`"}},
        "content": mp4,
    }
    video["responses"]["416"] = {
        "description": "The Range header cannot be satisfied (no body).",
        "headers": {"Content-Range": {"schema": {"type": "string"}, "description": "e.g. `bytes */5242880`"}},
    }


# --------------------------------------------------------------------------- Postman collection (v2.1)


def build_postman(spec: dict) -> dict:
    """A Postman v2.1 collection with one request per operation, grouped by tag, using a {{baseUrl}} variable."""
    folders: dict[str, list] = {name: [] for name in TAG_DESCRIPTIONS}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            folders.setdefault(operation["tags"][0], []).append(_postman_request(path, method, operation))
    return {
        "info": {
            "name": spec["info"]["title"],
            "description": spec["info"]["description"],
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000", "type": "string"},
            {"key": "job_id", "value": "", "type": "string"},
            {"key": "ad_id", "value": "", "type": "string"},
            {"key": "asset_id", "value": "", "type": "string"},
        ],
        "item": [
            {"name": name, "description": TAG_DESCRIPTIONS.get(name, ""), "item": requests}
            for name, requests in folders.items() if requests
        ],
    }


def _postman_request(path: str, method: str, operation: dict) -> dict:
    """One Postman request for one operation."""
    raw_path = path.replace("{", "{{").replace("}", "}}")
    query = [{"key": p["name"], "value": "false", "disabled": True, "description": p.get("description", "")}
             for p in operation.get("parameters", []) if p.get("in") == "query"]
    request: dict = {
        "method": method.upper(),
        "header": [{"key": "Accept", "value": "application/json"}],
        "url": {
            "raw": "{{baseUrl}}" + raw_path,
            "host": ["{{baseUrl}}"],
            "path": [part for part in raw_path.strip("/").split("/")],
            **({"query": query} if query else {}),
        },
        "description": operation.get("description") or operation.get("summary", ""),
    }
    content = operation.get("requestBody", {}).get("content", {})
    if "application/json" in content:
        examples = content["application/json"].get("examples") or {}
        first = next(iter(examples.values()), {}).get("value", {})
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {"mode": "raw", "raw": json.dumps(first, indent=2), "options": {"raw": {"language": "json"}}}
    elif "multipart/form-data" in content:
        request["body"] = {"mode": "formdata", "formdata": [
            {"key": "kind", "value": "photo", "type": "text", "description": "logo | photo | video"},
            {"key": "files", "type": "file", "src": [], "description": "Choose one or more files"},
        ]}
    return {"name": operation.get("summary") or operation["operationId"], "request": request}


def render(data: dict) -> str:
    """Stable JSON text."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    """Write (or check) both files."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when docs/ is out of date instead of writing")
    args = parser.parse_args()
    spec = build_openapi()
    outputs = {OPENAPI_PATH: render(spec), POSTMAN_PATH: render(build_postman(spec))}
    if args.check:
        stale = [str(p.relative_to(ROOT)) for p, text in outputs.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        if stale:
            print("Out of date:", ", ".join(stale), "- run: python scripts/generate_openapi.py")
            return 1
        print("docs/openapi.json and docs/postman_collection.json are up to date.")
        return 0
    DOCS.mkdir(exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print("wrote", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
