"""Command line helpers:  serve | scrape <url> | demo <url> | doctor"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path
from typing import Optional

from .config import Settings, redact


def _settings() -> Settings:
    """Settings from the environment (.env is loaded automatically)."""
    return Settings.from_env()


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the API with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


def cmd_scrape(args: argparse.Namespace) -> int:
    """Scan one website and print the ScrapeResult as JSON."""
    from .scraper.service import Scraper

    async def run() -> int:
        """Scan, print and always close the browser."""
        scraper = Scraper(_settings())
        try:
            result = await scraper.scrape(args.url)
        finally:
            await scraper.close()
        print(result.model_dump_json(indent=2))
        return 0 if result.status in {"ok", "partial"} else 2

    return asyncio.run(run())


def cmd_demo(args: argparse.Namespace) -> int:
    """Whole pipeline without the web server: scan a URL (or use --name), make the ad, save the MP4."""
    from .context import AppContext
    from .schemas import AdOptions, BusinessOverrides, GenerateAdRequest

    async def run() -> int:
        """Create the ad and wait for it to finish."""
        ctx = await AppContext.create(_settings(), start_background=False)
        try:
            job_id: Optional[str] = None
            if args.url:
                job = await ctx.scrape_jobs.create(args.url)
                while not job.is_final:
                    await asyncio.sleep(0.5)
                    job = await ctx.scrape_jobs.get(job.job_id) or job
                print(f"scan: {job.status} - {job.message}")
                job_id = job.job_id
            request = GenerateAdRequest(
                job_id=job_id, business=BusinessOverrides(name=args.name or ""),
                options=AdOptions(platform=args.platform, goal=args.goal, duration_seconds=args.seconds),
            )
            ad = await ctx.ads.create(request)
            print("\nPROMPT\n" + (ad.prompt.final_prompt if ad.prompt else "(none)") + "\n")
            while ad.status in {"queued", "running"}:
                await asyncio.sleep(1.0)
                ad = await ctx.ads.get(ad.ad_id) or ad
                print(f"  {ad.progress:3d}%  {ad.stage}: {ad.message}")
            if ad.status == "failed":
                print("FAILED:", ad.error, file=sys.stderr)
                return 1
            source = ctx.ads.video_path(ad.ad_id)
            target = Path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source:
                shutil.copyfile(source, target)
            for warning in ad.warnings:
                print("note:", warning)
            print(f"\nSaved {target} ({ad.status}, provider={ad.provider})")
            return 0
        finally:
            await ctx.close()

    return asyncio.run(run())


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check configuration and the tools the app needs, and say what to fix."""
    from .scraper.render import browser_installed

    settings = _settings()
    print("Settings (secrets hidden):")
    for key, value in redact(settings).items():
        if key in {"env", "database_url", "redis_url", "cors_origins", "playwright_browser", "video_provider", "ai_prompt_model", "ai_prompt_base_url", "gemini_video_model", "magic_hour_model", "video_model_api_key", "ai_prompt_api_key", "gemini_api_key"}:
            print(f"  {key} = {value}")
    problems = settings.validate()

    async def browser() -> tuple[bool, str]:
        """Is the Playwright browser installed?"""
        return await browser_installed(settings.playwright_browser)

    ok, detail = asyncio.run(browser())
    checks = [
        ("ffmpeg", bool(shutil.which("ffmpeg")), "install FFmpeg (needed for every video)"),
        ("ffprobe", bool(shutil.which("ffprobe")), "ffprobe ships with FFmpeg"),
        (f"{settings.playwright_browser} browser", ok, detail),
        ("video model key", bool(settings.gemini_key or settings.video_model_api_key), "optional: without a Gemini key, videos are simple zoom clips (demo mode)"),
        ("AI prompt key", bool(settings.ai_prompt_api_key), "optional: without it the built-in prompt writer is used"),
    ]
    print("\nChecks:")
    optional = {"video model key", "AI prompt key"}  # missing optional items are shown as [--], not as problems
    for name, passed, hint in checks:
        mark = "ok" if passed else ("--" if name in optional else "!!")
        print(f"  [{mark}] {name}" + ("" if passed else f"  -> {hint}"))
    for problem in problems:
        print(f"  [!!] config: {problem}")
    return 0 if not problems and checks[0][1] and checks[1][1] else 1


def main(argv: Optional[list[str]] = None) -> None:
    """Parse the command line and run the chosen command."""
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Adsify command line")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to accept connections from other machines")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)
    scrape = sub.add_parser("scrape", help="scan a website and print JSON")
    scrape.add_argument("url")
    scrape.set_defaults(func=cmd_scrape)
    demo = sub.add_parser("demo", help="scan a URL and create one ad video without the web server")
    demo.add_argument("url", nargs="?", default="")
    demo.add_argument("--name", default="", help="business name (needed when there is no URL)")
    demo.add_argument("--platform", default="taxi_screen")
    demo.add_argument("--goal", default="awareness")
    demo.add_argument("--seconds", type=int, default=5)
    demo.add_argument("--out", default="demo-ad.mp4")
    demo.set_defaults(func=cmd_demo)
    doctor = sub.add_parser("doctor", help="check configuration and required tools")
    doctor.set_defaults(func=cmd_doctor)
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
