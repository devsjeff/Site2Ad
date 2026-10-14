#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING server (standard library only).

    python scripts/smoke_test.py                              # server at http://127.0.0.1:8000
    python scripts/smoke_test.py --base http://localhost:8000 --url https://example.com --name "Example Co"

It checks /health, /ready, /api/config, scans a website, creates ONE ad, polls it, and downloads the video.
In demo mode (VIDEO_PROVIDER=mock) this costs nothing. With a real provider it spends video credits.
Exit code 0 = every step worked.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

OK, BAD = "\033[32mok\033[0m", "\033[31mFAIL\033[0m"


def call(base: str, method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, dict | bytes, dict]:
    """One HTTP call. Returns (status, parsed JSON or raw bytes, headers)."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status, headers = response.read(), response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw, status, headers = exc.read(), exc.code, dict(exc.headers)
    try:
        return status, json.loads(raw), headers
    except ValueError:
        return status, raw, headers


def step(label: str, passed: bool, detail: str = "") -> None:
    """Print one result line and stop at the first failure."""
    print(f"  [{OK if passed else BAD}] {label}{(' - ' + detail) if detail else ''}")
    if not passed:
        sys.exit(1)


def poll(base: str, path: str, done, seconds: float, label: str) -> dict:
    """Poll `path` until done(payload) is true or time runs out."""
    deadline = time.monotonic() + seconds
    last: dict = {}
    while time.monotonic() < deadline:
        status, payload, _ = call(base, "GET", path)
        if status != 200 or not isinstance(payload, dict):
            step(f"{label}: poll", False, f"HTTP {status}")
        last = payload  # type: ignore[assignment]
        if done(last):
            return last
        time.sleep(1.5)
    step(f"{label}: finished in time", False, f"last status {last.get('status')} stage {last.get('stage')} {last.get('progress')}%")
    return last


def main() -> int:
    """Run the whole smoke test."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="backend address")
    parser.add_argument("--url", default="https://example.com", help="website to scan")
    parser.add_argument("--name", default="Smoke Test Bakery", help="business name used if the scan finds none")
    parser.add_argument("--seconds", type=int, default=5, help="video length")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    print(f"Smoke test against {base}")

    status, payload, _ = call(base, "GET", "/health")
    step("GET /health", status == 200 and isinstance(payload, dict) and payload.get("status") == "ok")
    status, payload, _ = call(base, "GET", "/ready")
    step("GET /ready", status in (200, 503) and isinstance(payload, dict), f"status={payload.get('status') if isinstance(payload, dict) else '?'}")
    if isinstance(payload, dict) and payload.get("problems"):
        for problem in payload["problems"]:
            print(f"        note: {problem}")
    status, config, _ = call(base, "GET", "/api/config")
    step("GET /api/config", status == 200 and isinstance(config, dict) and "platforms" in config, f"video_provider={config.get('video_provider')}")  # type: ignore[union-attr]
    if not config.get("demo_mode"):  # type: ignore[union-attr]
        print("        WARNING: demo mode is off, this run will spend video credits.")

    status, job, _ = call(base, "POST", "/api/scrape", {"url": args.url})
    step("POST /api/scrape", status == 202 and isinstance(job, dict) and "job_id" in job, f"job {job.get('job_id', '')[:8]}")  # type: ignore[union-attr]
    job = poll(base, f"/api/jobs/{job['job_id']}", lambda j: j.get("stage") == "ad_ready" or j.get("is_final"), 90, "scan")  # type: ignore[index]
    step("scan reached a usable state", job.get("status") in {"ok", "partial", "running", "blocked"}, f"status={job.get('status')} - {job.get('message')}")

    usable = job.get("status") in {"ok", "partial"} or (job.get("result") or {}).get("status") in {"ok", "partial"}
    body: dict = {"business": {"name": args.name}, "options": {"duration_seconds": args.seconds}, "wait_for_prompt": False}
    if usable:
        body["job_id"] = job["job_id"]
    status, ad, _ = call(base, "POST", "/api/generate-ad", body)
    step("POST /api/generate-ad", status == 202 and isinstance(ad, dict) and "ad_id" in ad, f"ad {ad.get('ad_id', '')[:8] if isinstance(ad, dict) else ad}")
    ad_id = ad["ad_id"]  # type: ignore[index]

    ad = poll(base, f"/api/ads/{ad_id}", lambda a: a.get("status") in {"completed", "completed_with_fallback", "failed"}, 600, "ad")
    step("ad completed", ad.get("status") in {"completed", "completed_with_fallback"}, f"status={ad.get('status')} provider={ad.get('provider')} error={ad.get('error')}")
    prompt = ad.get("prompt") or {}
    step("exactly one prompt with a negative section", bool(prompt.get("positive_prompt")) and bool(prompt.get("negative_prompt")), f"{prompt.get('shot_count')} shots, builder={prompt.get('builder')}")
    for warning in ad.get("warnings", []):
        print(f"        note: {warning}")

    status, video, headers = call(base, "GET", ad["video_url"], timeout=120)
    step("download video", status == 200 and isinstance(video, bytes) and len(video) > 1000 and b"ftyp" in video[:64], f"{len(video) // 1024} KB, {headers.get('Content-Type')}")  # type: ignore[arg-type]
    request = urllib.request.Request(base + ad["video_url"], headers={"Range": "bytes=0-99"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            step("video Range request (seeking)", response.status == 206 and len(response.read()) == 100)
    except urllib.error.HTTPError as exc:
        step("video Range request (seeking)", False, f"HTTP {exc.code}")

    print("All steps passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
