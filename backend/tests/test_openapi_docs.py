"""docs/openapi.json and docs/postman_collection.json must match the code (scripts/generate_openapi.py --check)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_openapi.py"


def load_generator():
    """Import scripts/generate_openapi.py as a module."""
    spec = importlib.util.spec_from_file_location("generate_openapi", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_api_docs_match_the_code():
    """A route or schema change without regenerating docs/ fails here."""
    if not SCRIPT.is_file():  # running from a backend-only copy
        return
    generator = load_generator()
    spec = generator.build_openapi()
    assert generator.OPENAPI_PATH.read_text(encoding="utf-8") == generator.render(spec), "run: python scripts/generate_openapi.py"
    assert generator.POSTMAN_PATH.read_text(encoding="utf-8") == generator.render(generator.build_postman(spec))


def test_spec_documents_every_route_and_the_real_error_body():
    """Every route is present, errors use {detail, code}, and no secret-looking value is in the files."""
    if not SCRIPT.is_file():
        return
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    operations = {(method, path) for path, item in spec["paths"].items() for method in item}
    assert operations == {
        ("post", "/api/scrape"), ("get", "/api/jobs/{job_id}"), ("post", "/api/uploads"), ("get", "/api/assets/{asset_id}"),
        ("post", "/api/generate-ad"), ("get", "/api/ads/{ad_id}"), ("post", "/api/ads/{ad_id}/cancel"),
        ("get", "/api/ads/{ad_id}/video"), ("get", "/api/config"), ("get", "/health"), ("get", "/ready"),
        ("post", "/api/studio/jobs"), ("get", "/api/studio/jobs/{job_id}"), ("put", "/api/studio/jobs/{job_id}/assumptions"),
        ("post", "/api/studio/jobs/{job_id}/continue"), ("post", "/api/studio/jobs/{job_id}/cancel"), ("get", "/api/studio/jobs/{job_id}/video"),
        ("get", "/api/studio/jobs/{job_id}/screenshots/{file}"),
    }
    assert spec["openapi"].startswith("3.1") and spec["security"] == []
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    assert spec["paths"]["/api/generate-ad"]["post"]["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    text = (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8") + (ROOT / "docs" / "postman_collection.json").read_text(encoding="utf-8")
    for secret in ("mhk_live_", "sk-or-", "VIDEO_MODEL_API_KEY=", "AI_PROMPT_API_KEY="):
        assert secret not in text
