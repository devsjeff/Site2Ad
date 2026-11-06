"""Studio jobs for the website: run the seven stages in a background worker, one job at a time, and keep every job's state in its run folder.

A job goes  queued -> running -> (review) -> running -> completed | failed | cancelled.
With `review` on it stops after the assumptions, so the person can correct them; `resume` carries on from the storyboard.
State lives in <data dir>/studio/<job id>/job.json next to the stage files, so a refresh or a restart never loses a job.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import Settings
from ..scraper.safety import SafetyPolicy
from . import ai as studio_ai
from . import assumptions as assumption_rules
from . import pipeline
from .config import STAGES, STRUCTURES, Run, StageError, VIDEO_TYPES, normalize_url
from .storyboard import describe_visual

logger = logging.getLogger(__name__)

JOB_ID = re.compile(r"^[0-9a-f]{32}$")
SHOT_FILE = re.compile(r"^\d{2}_[a-z]+\.png$")
FIRST_PART = STAGES[:STAGES.index("assumptions") + 1]
SECOND_PART = STAGES[STAGES.index("assumptions") + 1:]


class StudioError(Exception):
    """A problem the person can fix; `code` is stable for the website, `status` is the HTTP status."""

    def __init__(self, message: str, code: str, status: int = 422):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StudioJobs:
    """Creates, runs and describes studio jobs."""

    def __init__(self, settings: Settings, policy: Optional[SafetyPolicy] = None, stages: Optional[dict] = None):
        self.settings = settings
        self.policy = policy or SafetyPolicy.from_settings(settings)
        self.root = settings.data_dir / "studio"
        self.stages = stages or pipeline.RUNNERS  # tests swap in scripted stages
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="studio")  # one video at a time: the browser and FFmpeg are heavy
        self._active: dict[str, Future | None] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        studio_ai.configure(settings)

    # ------------------------------------------------------------------ files

    def run_for(self, job_id: str) -> Run:
        if not JOB_ID.match(job_id or "") or not (self.root / job_id / "job.json").is_file():
            raise StudioError("That Studio job was not found. It may have expired.", "studio_job_not_found", 404)
        return Run(self.root / job_id)

    def _read(self, run: Run) -> dict:
        for attempt in range(6):  # a file being replaced by another thread can be briefly unreadable (Windows locks it)
            try:
                return json.loads((run.root / "job.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
        raise AssertionError("unreachable")

    def _write(self, run: Run, state: dict) -> None:
        with self._lock:
            state["updated_at"] = now()
            temp = run.root / "job.json.tmp"
            temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            for attempt in range(6):  # replacing a file that another thread is reading fails on Windows: try again in a moment
                try:
                    temp.replace(run.root / "job.json")
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.02 * (attempt + 1))

    def _update(self, run: Run, **changes: Any) -> dict:
        state = self._read(run)
        state.update(changes)
        self._write(run, state)
        return state

    def _mark_stage(self, run: Run, name: str, status: str, seconds: float = 0.0, summary: str = "") -> None:
        state = self._read(run)
        for stage in state["stages"]:
            if stage["name"] == name:
                stage.update(status=status, seconds=round(seconds, 1), summary=summary)
        self._write(run, state)

    # ------------------------------------------------------------------ create and run

    def create(self, request: dict) -> dict:
        """Start a job. `request`: url, video_type, length, platform, claims, review. Returns the job's state."""
        today = datetime.now(timezone.utc).date().isoformat()
        self._purge()
        made_today = sum(1 for d in self._job_dirs() if self._created(d).startswith(today))
        if made_today >= self.settings.max_ads_per_day:
            raise StudioError("The daily limit of videos has been reached. Please try again tomorrow.", "daily_limit", 429)
        pipeline.validate_request(request)
        job_id = uuid.uuid4().hex
        run = Run(self.root / job_id)
        stored = {k: request[k] for k in ("url", "video_type", "length", "platform")}
        stored["url"] = normalize_url(stored["url"])
        stored.update(claims=[c.strip() for c in request.get("claims", []) if c.strip()][:5], fix_rounds=2, language=request.get("language", "en"),
                      voice=request.get("voice", "auto"), sound_effects=bool(request.get("sound_effects", True)))
        run.write_json(run.request_json, stored)
        state = {
            "id": job_id, "created_at": now(), "updated_at": now(), "status": "queued", "stage": "capture", "message": "Waiting to start…", "error": "",
            "review": bool(request.get("review", True)), "stages": [{"name": n, "label": pipeline.LABELS[n], "status": "pending", "seconds": 0.0, "summary": ""} for n in STAGES],
        }
        self._write(run, state)
        self._submit(job_id, FIRST_PART if state["review"] else STAGES)
        return state

    def _submit(self, job_id: str, names: tuple[str, ...]) -> None:
        self._active[job_id] = None  # registered before the worker can start: a poll in between must not take the job for one lost in a restart
        self.pool.submit(self._work, job_id, names)

    def _job_dirs(self) -> list[Path]:
        return [d for d in self.root.glob("*") if d.is_dir() and JOB_ID.match(d.name) and (d / "job.json").is_file()] if self.root.exists() else []

    def _created(self, directory: Path) -> str:
        try:
            return json.loads((directory / "job.json").read_text(encoding="utf-8")).get("created_at", "")
        except (OSError, ValueError):
            return ""

    def _purge(self) -> None:
        """Delete finished jobs older than the data retention time (the same rule as ads)."""
        cutoff = time.time() - self.settings.data_retention_hours * 3600
        for directory in self._job_dirs():
            if directory.name not in self._active and directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)

    def _work(self, job_id: str, names: tuple[str, ...]) -> None:
        """The worker: run the stages in order, saving progress after each. Never raises."""
        run = Run(self.root / job_id)
        try:
            self._update(run, status="running", error="")
            for name in names:
                if job_id in self._cancelled:
                    self._update(run, status="cancelled", message="Cancelled.")
                    return
                self._update(run, stage=name, message=pipeline.LABELS[name] + "…")
                self._mark_stage(run, name, "running")
                started = time.time()
                try:
                    summary = self.stages[name](run, self.policy)
                except StageError as exc:
                    self._mark_stage(run, name, "failed", time.time() - started)
                    self._update(run, status="failed", error=str(exc), message="This video could not be made.")
                    return
                except Exception:
                    logger.exception("studio job %s: stage %s crashed", job_id, name)
                    self._mark_stage(run, name, "failed", time.time() - started)
                    self._update(run, status="failed", error=f"Something went wrong in the step “{pipeline.LABELS[name]}”. Please try again.", message="This video could not be made.")
                    return
                self._mark_stage(run, name, "done", time.time() - started, summary)
                if name == "assumptions" and self._read(run)["review"]:
                    self._update(run, status="review", message="Check the choices below and correct anything, then make the video.")
                    return
            self._update(run, status="completed", message="Your video is ready.")
        except Exception:  # the worker itself broke (not a stage): say so instead of leaving the job looking lost
            logger.exception("studio job %s: the worker stopped", job_id)
            try:
                self._update(run, status="failed", error="Something went wrong while making the video. Please try again.", message="This video could not be made.")
            except Exception:
                logger.exception("studio job %s: could not record the failure", job_id)
        finally:
            self._cancelled.discard(job_id)
            self._active.pop(job_id, None)

    # ------------------------------------------------------------------ the person's steps

    def save_assumptions(self, job_id: str, edited: dict) -> dict:
        """Replace the assumptions with the person's corrections (only while the job waits for review)."""
        run = self.run_for(job_id)
        if self._read(run)["status"] != "review":
            raise StudioError("The choices can only be changed while the job is waiting for your review.", "not_in_review", 409)
        notes = run.read(run.product_json, "notes")
        current = run.read(run.assumptions_json, "assumptions")
        merged = {**current, **edited, "video_type": current["video_type"]}
        problems = assumption_rules.validate_edited(merged, notes)
        for field in ("audience", "key_message", "tone"):
            if not str(merged.get(field, "")).strip():
                problems.append(f"{field.replace('_', ' ')} cannot be empty")
        if len(str(merged.get("key_message", "")).split()) > 18:
            problems.append("the key message must be one short sentence")
        if problems:
            raise StudioError("; ".join(problems), "bad_assumptions", 422)
        run.write_json(run.assumptions_json, merged)
        assumption_rules.write_assumptions_md(run, merged)
        return merged

    def resume(self, job_id: str) -> dict:
        """Carry on after the review: make the storyboard, the video and the check."""
        run = self.run_for(job_id)
        if self._read(run)["status"] != "review":
            raise StudioError("This job is not waiting for your review.", "not_in_review", 409)
        state = self._update(run, status="queued", message="Making your video…", stage="storyboard")
        self._submit(job_id, SECOND_PART)
        return state

    def cancel(self, job_id: str) -> dict:
        """Stop a job after its current step (a job waiting for review is cancelled at once)."""
        run = self.run_for(job_id)
        state = self._read(run)
        if state["status"] in {"completed", "failed", "cancelled"}:
            raise StudioError("This job is already finished.", "studio_finished", 409)
        if state["status"] == "review":
            return self._update(run, status="cancelled", message="Cancelled.")
        self._cancelled.add(job_id)
        return state

    # ------------------------------------------------------------------ what the website shows

    def view(self, job_id: str) -> dict:
        """Everything about a job for the website: state, then whatever each finished stage produced."""
        run = self.run_for(job_id)
        state = self._read(run)
        if state["status"] in {"queued", "running"} and job_id not in self._active:  # the server restarted in the middle of it
            state = self._update(run, status="failed", error="This job was interrupted by a restart. Please start it again.", message="This video could not be made.")
        done = {s["name"] for s in state["stages"] if s["status"] == "done"}
        request = run.read(run.request_json, "capture")
        out: dict[str, Any] = {
            "job_id": job_id, "status": state["status"], "stage": state["stage"], "message": state["message"], "error": state["error"], "review": state["review"],
            "url": request["url"], "video_type": request["video_type"], "length": int(request["length"]), "platform": request["platform"],
            "stages": state["stages"], "created_at": state["created_at"], "updated_at": state["updated_at"],
            "progress": min(100, sum(pipeline.WEIGHTS[n] for n in done) + (pipeline.WEIGHTS[state["stage"]] // 3 if state["status"] == "running" and state["stage"] in pipeline.WEIGHTS else 0)),
            "what_it_is": "", "who_for": "", "claims": [], "brand": None, "assumptions": None, "shots": [], "screenshots": [], "problems": [], "passed": None, "video_url": None,
        }
        if "capture" in done:
            capture = run.read(run.capture_json, "capture")
            out["screenshots"] = [{"id": s["id"], "file": s["file"], "kind": s["kind"], "summary": s["summary"]} for s in capture["screenshots"]]
        if "notes" in done:
            notes = run.read(run.product_json, "notes")
            out["what_it_is"], out["who_for"] = notes["what_it_is"], notes["who_for"]
            out["claims"] = [{"id": c["id"], "text": c["text"], "kind": c["kind"], "source": c["source"]} for c in notes["claims"]]
        if "brand" in done:
            out["brand"] = self._brand(run.read(run.brand_json, "brand"))
        if "assumptions" in done:
            out["assumptions"] = self._assumptions(run.read(run.assumptions_json, "assumptions"))
        if "storyboard" in done:
            out["shots"] = self._shots(run.read(run.storyboard_json, "storyboard"))
        if "check" in done and (run.check_dir / "report.json").is_file():
            report = json.loads((run.check_dir / "report.json").read_text(encoding="utf-8"))
            out["problems"], out["passed"] = report["problems"], bool(report["passed"])
        if state["status"] == "completed" and run.final_mp4.is_file():
            out["video_url"] = f"/api/studio/jobs/{job_id}/video"
        return out

    @staticmethod
    def _brand(brand: dict) -> dict:
        c, f = brand["colors"], brand["fonts"]
        return {"primary": c["primary"], "accent": c["accent"], "background": c["background_dark"] if c["mode"] == "dark" else c["background_light"], "ink": c["ink"],
                "mode": c["mode"], "heading_font": f["heading"], "body_font": f["body"], "shapes": brand["shapes"]["summary"], "tone": brand["tone"], "photo_style": brand["photo_style"]}

    @staticmethod
    def _assumptions(a: dict) -> dict:
        return {"audience": a["audience"], "key_message": a["key_message"], "tone": a["tone"], "voice": a["voice"], "voice_reason": a.get("voice_reason", ""),
                "music": a["music"], "music_reason": a.get("music_reason", ""), "cta_text": a["cta"]["text"], "cta_target": a["cta"]["target"],
                "must_include": [{"what": i["what"], "claims": i["claims"]} for i in a["must_include"]], "must_avoid": list(a["must_avoid"]),
                "language": a.get("language", "en"), "sound_effects": bool(a.get("sound_effects", True))}

    @staticmethod
    def _shots(board: dict) -> list[dict]:
        shots = []
        for s in board["shots"]:
            visual = s["visual"]
            shots.append({"n": s["n"], "beat": s["beat"], "purpose": s["purpose"], "seconds": s["seconds"], "voice": s["voice"], "voice_local": s.get("voice_local", ""), "caption": s["caption"],
                          "transition": s["transition"], "claims": list(s["claims"]), "visual": describe_visual(visual),
                          "screenshot": visual.get("id") if visual.get("type") == "screenshot" else None})
        return shots

    def video_path(self, job_id: str) -> Path:
        run = self.run_for(job_id)
        if self._read(run)["status"] != "completed" or not run.final_mp4.is_file():
            raise StudioError("The video is not ready yet.", "video_not_ready", 409)
        return run.final_mp4

    def screenshot_path(self, job_id: str, file: str) -> Path:
        run = self.run_for(job_id)
        if not SHOT_FILE.match(file) or not (run.shots_dir / file).is_file():
            raise StudioError("That screenshot was not found.", "screenshot_not_found", 404)
        return run.shots_dir / file

    def types(self) -> list[dict]:
        """The video types for the website's picker."""
        from .config import min_length
        return [{"id": t, "label": TYPE_TEXT[t][0], "description": TYPE_TEXT[t][1], "min_length": min_length(t),
                 "shots": [b.purpose.split(":")[0] for b in STRUCTURES[t]]} for t in VIDEO_TYPES]


TYPE_TEXT = {
    "promo": ("Promo", "Lead with the offer, show what you get and the proof, then the price and a call to action."),
    "hook_ad": ("Hook ad", "Start from a pain people recognise, turn it with a punchline, then show the product."),
    "pitch": ("Pitch", "Problem, why now, solution, how it works, proof and a clear ask."),
    "showcase": ("Showcase", "Show the result first, then three real features on real screenshots."),
    "explainer": ("Explainer", "Ask the question, explain it with an analogy, then three simple steps."),
    "testimonial": ("Testimonial", "A customer's problem, their real words and the result in numbers."),
    "launch": ("Launch", "Tease it, reveal it, show the key feature, then when and how much."),
}
