"""Studio on the website: jobs and the /api/studio routes, with scripted stages (the real stages are tested in test_studio.py)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.studio.config import Run, StageError
from app.video.base import ffmpeg_path

from .conftest import make_settings
from .test_studio import BOARD_CAPTURE, NOTES, good_promo


def scripted_stages(fail_at: str = "", crash_at: str = "", slow: float = 0.0):
    """Stages that write the same files the real ones write, instantly."""

    def stage(name):
        def run_stage(run: Run, policy=None) -> str:
            if slow:
                time.sleep(slow)
            if name == fail_at:
                raise StageError("The page could not be captured: nothing to read.")
            if name == crash_at:
                raise RuntimeError("secret internal detail: /srv/app/studio/x.py line 9")
            if name == "capture":
                for shot in BOARD_CAPTURE["screenshots"]:
                    Image.new("RGB", (320, 200), (40, 90, 160)).save(run.shots_dir / f"{shot['id']}_{shot['kind']}.png")
                shots = [{**s, "file": f"{s['id']}_{s['kind']}.png"} for s in BOARD_CAPTURE["screenshots"]]
                Run.write_json(run.capture_json, {**BOARD_CAPTURE, "screenshots": shots})
            elif name == "notes":
                Run.write_json(run.product_json, {**NOTES, "what_it_is": "Silent cab screens.", "who_for": "Advertisers."})
            elif name == "brand":
                Run.write_json(run.brand_json, {
                    "colors": {"mode": "light", "primary": "#ff6600", "accent": "#ffb27a", "background_light": "#faf8f5", "background_dark": "#18181b", "ink": "#171717", "on_primary": "#ffffff"},
                    "fonts": {"heading": "Outfit", "body": "Inter"}, "shapes": {"summary": "pill buttons"}, "tone": "Direct", "photo_style": "Real photos"})
            elif name == "assumptions":
                Run.write_json(run.assumptions_json, {
                    "video_type": run.request()["video_type"], "audience": "Brand marketers", "key_message": "Reach riders in cabs", "tone": "Direct", "voice": "neerja",
                    "voice_reason": "warm", "music": "upbeat", "music_reason": "energy", "cta": {"text": "Launch", "target": "x.example"},
                    "must_include": [{"what": "the price", "claims": ["C2"]}], "must_avoid": ["other companies"]})
            elif name == "storyboard":
                board = {"video_type": "promo", "length": 20, "platform": "16:9", "adapted_beats": [], "shots": []}
                for index, item in enumerate(good_promo()["shots"], start=1):
                    shot = {**item, "n": index, "purpose": item["beat"], "seconds": 4.0}
                    shot["visual"] = {**shot["visual"], **({"id": "01"} if shot["visual"].get("type") == "screenshot" else {})}
                    board["shots"].append(shot)
                Run.write_json(run.storyboard_json, board)
            elif name == "build":
                subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2", "-pix_fmt", "yuv420p", str(run.final_mp4)], check=True)
            elif name == "check":
                Run.write_json(run.check_dir / "report.json", {"problems": [], "passed": True})
            return f"{name} done"

        return run_stage

    return {name: stage(name) for name in ("capture", "notes", "brand", "assumptions", "storyboard", "build", "check")}


@pytest.fixture
def client(tmp_path):
    """The real app with studio's stages scripted; local addresses allowed (the guard itself is tested below)."""
    settings = make_settings(tmp_path, ai_prompt_api_key="test-key", unsafe_allow_private_networks=True, rate_limit_per_minute=1000)
    with TestClient(create_app(settings)) as http:
        http.app.state.ctx.studio.stages = scripted_stages()
        yield http


def start(http, **extra):
    body = {"url": "http://127.0.0.1:9/", "video_type": "promo", "length": 20, "platform": "16:9", **extra}
    response = http.post("/api/studio/jobs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def wait_for(http, job_id, *statuses, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        job = http.get(f"/api/studio/jobs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job stayed {job['status']} at {job['stage']}")


def test_a_job_pauses_for_review_takes_corrections_and_makes_the_video(client):
    job_id = start(client)
    job = wait_for(client, job_id, "review")
    assert [s["status"] for s in job["stages"]] == ["done"] * 4 + ["pending"] * 3
    assert job["claims"][0]["id"] == "C1" and job["brand"]["primary"] == "#ff6600" and job["assumptions"]["voice"] == "neerja" and job["shots"] == []
    assert len(job["screenshots"]) == 2 and client.get(f"/api/studio/jobs/{job_id}/screenshots/{job['screenshots'][0]['file']}").headers["content-type"] == "image/png"

    bad = {**job["assumptions"], "voice": "robot"}
    assert client.put(f"/api/studio/jobs/{job_id}/assumptions", json=bad).status_code == 422
    unknown_claim = {**job["assumptions"], "must_include": [{"what": "x", "claims": ["C99"]}]}
    wrong = client.put(f"/api/studio/jobs/{job_id}/assumptions", json=unknown_claim)
    assert wrong.status_code == 422 and wrong.json()["code"] == "bad_assumptions" and "C99" in wrong.json()["detail"]
    good = {**job["assumptions"], "voice": "prabhat", "key_message": "Cab ads from ₹4,000 a month", "must_avoid": ["other companies", "  ", "unsourced numbers"]}
    saved = client.put(f"/api/studio/jobs/{job_id}/assumptions", json=good)
    assert saved.status_code == 200 and saved.json()["assumptions"]["voice"] == "prabhat" and saved.json()["assumptions"]["must_avoid"] == ["other companies", "unsourced numbers"]
    stored = json.loads(next((client.app.state.ctx.studio.root / job_id).glob("04_assumptions.json")).read_text(encoding="utf-8"))
    assert stored["voice"] == "prabhat" and stored["cta"]["text"] == "Launch"  # the file the storyboard reads has the correction

    assert client.post(f"/api/studio/jobs/{job_id}/continue").status_code == 202
    done = wait_for(client, job_id, "completed")
    assert done["progress"] == 100 and done["passed"] is True and len(done["shots"]) == 5 and done["video_url"] == f"/api/studio/jobs/{job_id}/video"
    assert done["shots"][0]["screenshot"] == "01" and "real screenshot" in done["shots"][0]["visual"]

    video = client.get(done["video_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and video.content[4:8] == b"ftyp"
    ranged = client.get(done["video_url"], headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100
    assert "attachment" in client.get(done["video_url"] + "?download=true").headers["content-disposition"]
    assert client.post(f"/api/studio/jobs/{job_id}/continue").status_code == 409  # already made
    assert client.put(f"/api/studio/jobs/{job_id}/assumptions", json=good).status_code == 409


def test_without_review_a_job_runs_straight_through(client):
    job_id = start(client, review=False)
    assert wait_for(client, job_id, "completed")["video_url"]


@pytest.mark.parametrize("bad_id", ["x", "../../etc/passwd", "0" * 32, "G" * 32])
def test_unknown_or_malformed_job_ids_are_404(client, bad_id):
    for method, path in (("get", ""), ("get", "/video"), ("post", "/cancel"), ("post", "/continue")):
        response = getattr(client, method)(f"/api/studio/jobs/{bad_id}{path}")
        assert response.status_code in (404, 422) and "detail" in response.json()


def test_screenshot_names_cannot_leave_the_job_folder(client):
    job_id = start(client)
    wait_for(client, job_id, "review")
    for name in ("..%2F..%2Fjob.json", "../job.json", "01_hero.png.exe", "job.json", "..%5Cjob.json"):
        assert client.get(f"/api/studio/jobs/{job_id}/screenshots/{name}").status_code in (404, 422)


def test_a_stage_that_cannot_continue_fails_the_job_with_its_message(client):
    client.app.state.ctx.studio.stages = scripted_stages(fail_at="notes")
    job = wait_for(client, start(client), "failed")
    assert "nothing to read" in job["error"] and [s["status"] for s in job["stages"]][:2] == ["done", "failed"] and job["video_url"] is None


def test_an_unexpected_crash_never_leaks_internals(client):
    client.app.state.ctx.studio.stages = scripted_stages(crash_at="brand")
    job = wait_for(client, start(client), "failed")
    assert "Finding your brand" in job["error"] and "secret" not in json.dumps(job) and "/srv/app" not in json.dumps(job)


def test_a_job_waiting_for_review_can_be_cancelled(client):
    job_id = start(client)
    wait_for(client, job_id, "review")
    assert client.post(f"/api/studio/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/studio/jobs/{job_id}/continue").status_code == 409
    assert client.post(f"/api/studio/jobs/{job_id}/cancel").status_code == 409


def test_a_running_job_stops_after_its_current_step(client):
    client.app.state.ctx.studio.stages = scripted_stages(slow=0.6)
    job_id = start(client, review=False)
    wait_for(client, job_id, "running")  # cancel while it is really working, not after a guessed pause
    assert client.post(f"/api/studio/jobs/{job_id}/cancel").status_code == 200
    job = wait_for(client, job_id, "cancelled")
    assert job["video_url"] is None and any(s["status"] == "pending" for s in job["stages"])


def test_a_job_interrupted_by_a_restart_is_reported_not_left_spinning(client):
    job_id = start(client)
    wait_for(client, job_id, "review")
    studio = client.app.state.ctx.studio
    state = json.loads((studio.root / job_id / "job.json").read_text(encoding="utf-8"))
    (studio.root / job_id / "job.json").write_text(json.dumps({**state, "status": "running"}), encoding="utf-8")
    job = client.get(f"/api/studio/jobs/{job_id}").json()
    assert job["status"] == "failed" and "restart" in job["error"]


def test_the_request_is_validated(client):
    for body in ({"url": "x"}, {"url": "https://a.example", "video_type": "podcast"}, {"url": "https://a.example", "length": 3}, {"url": "https://a.example", "platform": "4:3"},
                 {"url": "https://a.example", "video_type": "pitch", "length": 10}):
        assert client.post("/api/studio/jobs", json=body).status_code == 422, body
    short = client.post("/api/studio/jobs", json={"url": "https://a.example", "video_type": "pitch", "length": 10}).json()
    assert "at least 14 seconds" in short["detail"]


def test_private_addresses_are_refused_before_anything_starts(tmp_path):
    settings = make_settings(tmp_path, ai_prompt_api_key="test-key", rate_limit_per_minute=1000)  # the production rules
    with TestClient(create_app(settings)) as http:
        for url in ("http://127.0.0.1/", "http://169.254.169.254/latest", "http://localhost/", "http://10.1.2.3/", "file:///etc/passwd"):
            response = http.post("/api/studio/jobs", json={"url": url})
            assert response.status_code == 422 and response.json()["code"] in {"unsafe_url", "invalid_request"}, url
        assert not (settings.data_dir / "studio").exists() or not list((settings.data_dir / "studio").glob("*"))


def test_studio_needs_the_ai_writer_and_says_so(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, ai_prompt_api_key="", unsafe_allow_private_networks=True))) as http:
        config = http.get("/api/config").json()
        assert config["studio_available"] is False and "AI_PROMPT_API_KEY" in config["studio_message"]
        response = http.post("/api/studio/jobs", json={"url": "http://127.0.0.1/"})
        assert response.status_code == 409 and response.json()["code"] == "studio_unavailable"


def test_the_config_lists_the_video_types_for_the_picker(client):
    config = client.get("/api/config").json()
    assert config["studio_available"] is True
    types = {t["id"]: t for t in config["studio_types"]}
    assert list(types) == ["promo", "hook_ad", "pitch", "showcase", "explainer", "testimonial", "launch"]
    assert types["promo"]["min_length"] == 10 and types["hook_ad"]["min_length"] == 14 and types["promo"]["shots"][-1] == "Call to action"


def test_the_daily_limit_is_enforced(tmp_path):
    settings = make_settings(tmp_path, ai_prompt_api_key="k", unsafe_allow_private_networks=True, max_ads_per_day=1, rate_limit_per_minute=1000)
    with TestClient(create_app(settings)) as http:
        http.app.state.ctx.studio.stages = scripted_stages()
        start(http)
        limited = http.post("/api/studio/jobs", json={"url": "http://127.0.0.1:9/"})
        assert limited.status_code == 429 and limited.json()["code"] == "daily_limit"


def test_your_own_facts_are_kept_with_the_job(client):
    job_id = start(client, claims=["Priya said: great reach", "  ", "Price is ₹4,000"])
    request = json.loads((client.app.state.ctx.studio.root / job_id / "request.json").read_text(encoding="utf-8"))
    assert request["claims"] == ["Priya said: great reach", "Price is ₹4,000"] and request["url"] == "http://127.0.0.1:9/"


def test_the_browser_may_save_corrections_with_put_from_the_website(client):
    """The review screen saves with PUT; a browser asks first (CORS preflight), and a refusal shows up as 'cannot reach the server'."""
    answer = client.options(
        "/api/studio/jobs/" + "a" * 32 + "/assumptions",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"},
    )
    assert answer.status_code == 200, answer.text
    assert "PUT" in answer.headers["access-control-allow-methods"]
    assert answer.headers["access-control-allow-origin"] == "http://localhost:3000"
