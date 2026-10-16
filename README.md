# Adsify — website → video ad

Paste a business website, pick a goal and a style, and get **one short video ad** made from **one prompt** and **one hero image**.

```
 website URL
     │
     ▼
 ┌──────────┐   real facts only    ┌───────────────┐   1 prompt + 1 hero image   ┌────────────┐   name / offer / phone
 │ Scanner  │ ───────────────────▶ │ Prompt writer │ ──────────────────────────▶ │ Video model│ ──▶ added as clean text ──▶ MP4
 │ httpx →  │   (never invented)   │ AI or built-in│   (image-to-video)          │ Magic Hour │     with FFmpeg overlay
 │ Firefox  │                      │ + fact guard  │                             │ or demo    │
 └──────────┘                      └───────────────┘                             └────────────┘
```

* **Next.js** website (`frontend/`) and **FastAPI** backend (`backend/`).
* Works **out of the box without any API key** (demo mode: the scan is real, the video is a simple zoom clip made with FFmpeg).
* Add a Magic Hour key for real AI video, and an OpenRouter/OpenAI-compatible key for an AI-written prompt. Both are optional.

> **Security first:** the `backend/env.example` in the original upload contained **live OpenRouter and Magic Hour keys**.
> Treat them as leaked: **revoke/rotate both keys** in their dashboards and put the new ones only in `backend/.env`.
> This project never contains keys; `.env` is git-ignored.

---

## 1. Quick start (about 5 minutes, no keys needed)

You need: **Python 3.11+**, **Node.js 20.9+**, and **FFmpeg** (`ffmpeg -version` must work).
Install FFmpeg with `brew install ffmpeg` (macOS), `sudo apt install ffmpeg` (Ubuntu/Debian) or `winget install Gyan.FFmpeg` (Windows).

### macOS / Linux

```bash
make setup          # creates backend/.venv, installs Python + Node packages and the Firefox browser, copies the .env files
make doctor         # checks FFmpeg, the browser and your settings
make backend        # terminal 1 → API on http://localhost:8000
make frontend       # terminal 2 → website on http://localhost:3000
```

### Windows (PowerShell) — or anywhere without `make`

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install firefox       # Linux servers: add --with-deps
copy .env.example .env                     # macOS/Linux: cp
python -m app.cli doctor                   # checks FFmpeg, the browser and your settings
python -m app                              # API on http://localhost:8000   (leave this window open)

# second terminal
cd frontend
npm install
copy .env.example .env.local               # macOS/Linux: cp
npm run dev                                # website on http://localhost:3000
```

Open **http://localhost:3000** → *Create your ad* → paste a website → follow the steps.

> Windows: start the API with `python -m app` (not with `--reload`). Playwright needs a subprocess-capable event loop and uvicorn's reload mode on Windows does not provide one.

### Docker (everything in containers)

```bash
cp backend/.env.example backend/.env       # optional: add your keys
docker compose up --build                  # needs Docker Compose 2.24+
```

Website: http://localhost:3000 · API: http://localhost:8000 (docs at `/docs` unless `APP_ENV=production`). Data (videos, uploads, database) lives in the `adsify-data` volume.

### No website, no browser? Use the command line

```bash
cd backend
python -m app.cli scrape https://example.com                       # prints what the scanner found (JSON)
python -m app.cli demo https://example.com --out ad.mp4            # whole pipeline → ad.mp4
python -m app.cli demo --name "Sweet Corner Bakery" --out ad.mp4   # no website at all
```

### Check that everything works

```bash
python scripts/smoke_test.py          # with the backend running: scan → one ad → download the video → seek test
cd backend && python -m pytest        # 222 tests, no internet and no keys needed
python scripts/check_contract.py      # frontend ↔ backend agree on routes, fields, statuses (no old /api/v1 paths)
```

---

## 2. Turn on real AI

Edit `backend/.env`, then restart the backend. Run `python -m app.cli doctor` to confirm.

| You want | Set | Notes |
|---|---|---|
| Real AI video | `VIDEO_MODEL_API_KEY=` your **Magic Hour** key | Uses image-to-video with the hero image as the first frame. Costs credits. |
| AI-written prompt | `AI_PROMPT_API_KEY=` your **OpenRouter** (or any OpenAI-compatible) key | Optional. Without it a built-in writer makes the prompt. `AI_PROMPT_BASE_URL` / `AI_PROMPT_MODEL` choose the service and model. |
| Protect your credits | `MAX_ADS_PER_DAY`, `RATE_LIMIT_PER_MINUTE`, `MAX_CONCURRENT_ADS` | The API has **no login**. Keep it private or put it behind your own auth before exposing it publicly (see §8). |

The old variable names (`OPENROUTER_API_KEY`, `OPENAI_BASE_URL`, `OPENROUTER_MODEL`, `MAGIC_HOUR_API_KEY`) still work.

If the video model fails, the ad is finished with a demo clip and flagged `completed_with_fallback` (switch off with `VIDEO_FALLBACK_ON_ERROR=false`).
The video model makes clips of up to `VIDEO_MAX_SECONDS` (default 5). A longer request is shortened and the user is told.

---

## 3. What the user sees

**Ads → Create ad → Manual or Auto → content → settings → review → result.**

One screen at a time (no step counter). 1. **Start** (`/ads`, then `/ads/create`) — choose an **Auto ad** (from your website) or a **Manual ad** (your own images/videos).
2. **Manual: your media** — upload photos and/or videos (MP4, MOV, WebM), an optional logo, and optional name, offer, call to action and phone. Nothing is scanned.
   **Auto: your website** — paste a URL and check the call to action; everything else comes from the scan. Website Content Priority is preselected.
3. **Auto: creative mode** — *Website Content Priority*, *AI Video Priority* or *Website + AI Mix* (see the table below). Modes that need the AI video provider are disabled, with the reason, when no provider is configured.
4. **Settings** — only the switches that fit the mode: which website images (and their order), logo, QR code and its exact destination URL, sound on/off, platform (taxi screen 16:9, Reel/Shorts 9:16, Facebook 1:1), length (5/10/15/20 s), style, and for AI modes goal, tone and creative instructions.
5. **Review** — mode, media and where it comes from, **whether the AI video provider will be called**, QR destination, format, length, overlays and the stages that will run.
6. **Result** — page `/ads/<id>` (safe to refresh or bookmark): live progress (with *Cancel*), what the video is made of (website image / AI video / your video…), whether it contains AI footage, whether the QR code was really added, the MP4 and any warnings.

| Mode | Website scan | Prompt writer | AI video provider | Final video |
|---|---|---|---|---|
| Manual | no | no | **no** | your images (with motion) and videos, FFmpeg |
| Website Content Priority | yes | no | **no** | original website images, 3 s each (5 s → 2, 15 s → 5, 20 s → 7), looping when there are fewer |
| AI Video Priority | yes (facts only) | yes | yes (text-to-video) | AI footage only, no website pictures; a short clip loops to 5/10/15/20 s |
| Website + AI Mix | yes | yes | yes (image-to-video) | website image(s) → AI video (looped to the length) → website image(s) |

Every mode adds the logo, the QR code (exactly the URL you typed) and the text overlays with FFmpeg on the complete video. The backend validates every combination (`creative` in the request) and refuses AI modes when no AI provider is configured instead of producing a demo clip. If the provider fails during an AI ad, the ad is marked `completed_with_fallback` and the replacement clip is labelled as *not* AI footage (or the ad fails when `VIDEO_FALLBACK_ON_ERROR=false`).

Scan statuses: `queued` · `running` · `ok` · `partial` · `blocked` (Cloudflare/captcha — the user types details instead) · `unreachable` · `invalid_url` · `unsupported_platform` · `timeout` · `internal_error`.

---

## 4. How it works

**Scanner** (`backend/app/scraper/`)
* Normalises the URL and blocks private/internal addresses (SSRF) before **every** connection, including each redirect and DNS result. Honours `robots.txt` and a 5 MB response limit.
* Plain **httpx** first. Cloudflare/captcha challenges → `blocked` (no bypass attempts). Pages that are JavaScript shells (CSR score ≥ 3, e.g. a React root with no content) are re-read with **Playwright Firefox** (async). If no browser is installed the scan still returns what httpx saw, as `partial`.
* **Phase 1** reads the homepage only (target 5 s, cap 12 s) so the user can continue quickly; **phase 2** reads 5–8 important inner pages (contact, about, services…) in the background within the 60 s budget.
* Results are cached per site for 24 h (blocked/partial: 60 min); identical simultaneous scans share one job.
* Extracts only what is on the site: name, description, category, services, phone (E.164 validated), address, offer, call to action, logo, brand colours and images (ranked, de-duplicated, junk removed). Missing items stay empty — they are never invented.

**Prompt writer** (`backend/app/ai/`)
* Builds a *fact sheet* (user values > scraped values). Website text is passed to the AI inside clearly marked *untrusted data* blocks, and whatever the AI answers is checked by the guard below.
* **One request → one prompt → one video.** The prompt has a positive part and a `NEGATIVE PROMPT:` part, 3–6 timed shots depending on length, and names the hero image as the first frame.
* A *fact guard* rejects any AI answer that contains a phone number, address, price, guarantee or claim that is not in the fact sheet; the AI gets one correction attempt, then the deterministic template is used. Phone and address are never put in the prompt at all — they are added as text on the video.

**Video** (`backend/app/video/`)
* One hero image (your choice → your uploads → best scraped image) is downloaded through the safe fetcher, checked, auto-rotated, flattened and cropped (never stretched) to the platform's aspect ratio.
* **Magic Hour** image-to-video, or the **demo provider** (FFmpeg zoom clip) when there is no key.
* **Finalize:** business name, offer, call to action, phone and address (plus optional logo and QR code) are drawn with Pillow and burned in with FFmpeg — video models draw digits badly, so these are always real text from real facts. Non-Latin text (Devanagari, Arabic, Tamil) uses Noto fonts when installed.

**Jobs:** scans and ads run as in-process asyncio tasks stored in SQLite; unfinished work is closed cleanly after a restart. Old data is deleted after `DATA_RETENTION_HOURS` (72).

---

## 5. API (all under `/api`)

Full OpenAPI 3.1 spec: [`docs/openapi.json`](docs/openapi.json) · Postman collection: [`docs/postman_collection.json`](docs/postman_collection.json) · integration guide for other teams: [`docs/API.md`](docs/API.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/scrape` | Start a scan → `202` + job. Body `{url, refresh?}` |
| GET | `/api/jobs/{job_id}` | Scan progress and result |
| POST | `/api/uploads` | Multipart `kind=logo\|photo\|video`, `files=…` → asset ids. Videos are checked by their bytes and ffprobe (MP4/MOV/WebM; H.264, H.265, VP8, VP9, AV1; `MAX_VIDEO_UPLOAD_BYTES`, `MAX_VIDEO_UPLOAD_SECONDS`) |
| GET | `/api/assets/{asset_id}` | An uploaded image or video |
| POST | `/api/generate-ad` | Create **one** ad → `202`. Body: `job_id` or `scrape_result`, `business`, `options`, `hero`, `logo_asset_id`, and `creative` (`creation_mode`, `creative_mode`, `use_website_images`, `use_ai_video`, `use_uploaded_media`, `include_logo`, `include_qr`, `qr_url`, `selected_image_urls`, `media_asset_ids`, `keep_audio`, `prefer_website_images`). Without `creative` the original one-prompt AI flow runs (with `photo_asset_ids`) |
| GET | `/api/ads/{ad_id}` | Status, stage, prompt, warnings, `video_url`, `composition`, `ai_video_used`, `qr_added` |
| POST | `/api/ads/{ad_id}/cancel` | Stop an ad that is still running (it ends as `failed`, "You cancelled this ad.") |
| GET | `/api/ads/{ad_id}/video` | The MP4 (`Range` supported, `?download=1`) |
| GET | `/api/config` | Options and limits for the UI |
| GET | `/health`, `/ready` | Liveness / readiness (database, cache, browser, providers) |

Errors always look like `{"detail": "plain-language message", "code": "machine_code"}`. Interactive docs: `/docs` (not in production).

---

## 6. Configuration

Every setting is documented in **`backend/.env.example`** (copy it to `backend/.env`). The ones you are most likely to touch:

| Variable | Default | Meaning |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:3000` | Frontend address(es) allowed to call the API (comma separated) |
| `VIDEO_MODEL_API_KEY` | empty | Magic Hour key; empty = demo mode |
| `AI_PROMPT_API_KEY` | empty | OpenRouter/OpenAI-compatible key; empty = built-in prompt writer |
| `PLAYWRIGHT_BROWSER` | `firefox` | `firefox` (default), `chromium` or `webkit` |
| `REDIS_URL` | empty | Optional shared scan cache; memory cache otherwise |
| `MAX_ADS_PER_DAY` | `100` | Hard daily cap on ads (protects credits) |
| `DATA_RETENTION_HOURS` | `72` | Finished data is deleted after this |
| `TRUST_PROXY_HEADERS` | `false` | `true` only behind your own reverse proxy |

Frontend: `frontend/.env.local` → `NEXT_PUBLIC_API_BASE_URL` (the address the **browser** uses for the API; empty = same origin behind a reverse proxy). It is baked in at build time.

---

## 7. Project layout

```
adsify/
├── README.md                  ← you are here
├── docker-compose.yml  Makefile  .gitignore
├── backend/                   FastAPI app, Python 3.11+
│   ├── app/
│   │   ├── main.py            app factory, CORS, error format, startup/shutdown
│   │   ├── api/               routes.py (thin) · core.py (all logic, framework-free) · ranges.py
│   │   ├── scraper/           safety · fetch · detect · render · extract · crawl · service
│   │   ├── ai/                facts · template · llm · guard · prompt_builder
│   │   ├── video/             images · magic_hour · mock · finalize · service
│   │   ├── services/          scrape_jobs · ads · assets · maintenance
│   │   ├── store/             SQLite + cache (Redis or memory)
│   │   └── config.py  schemas.py  catalog.py  cli.py
│   ├── tests/                 222 tests (fixture web server, fake providers)
│   ├── .env.example  requirements.txt  Dockerfile
├── frontend/                  Next.js 16 · React 19 · Tailwind 4
│   ├── app/                   pages: /, /ads/create, /ads/[adId]
│   ├── components/            create/ (steps) · ad/ (progress, result, prompt) · ui/
│   └── lib/                   api.ts (the only place that calls the backend) · types.ts · draft.ts · usePolling.ts
├── scripts/                   smoke_test.py · check_contract.py
└── docs/                      PROJECT_REPORT.md · reference/ (original scraper design notes)
```

More detail — architecture, what was wrong in the original files, test plan, risks — in **[docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md)**.

---

## 8. Putting it on a server

* Build with Docker (above). One backend container, one frontend container, a volume for `/data`.
* Put both behind HTTPS (Caddy, Nginx, a cloud load balancer). Either serve them on one domain (`/api` → backend, everything else → frontend; build the frontend with an empty `NEXT_PUBLIC_API_BASE_URL`) or use two domains and set `CORS_ORIGINS` to the frontend's domain and `NEXT_PUBLIC_API_BASE_URL` to the API's domain.
* Set `APP_ENV=production` (hides `/docs`) and `TRUST_PROXY_HEADERS=true` (rate limits then use the real client address).
* **There is no user login.** Anyone who can open the site can spend your video credits (limited by `RATE_LIMIT_PER_MINUTE` and `MAX_ADS_PER_DAY`). For a public site add authentication in front (an auth proxy, or login in the app) before using a paid video key.
* The scanner fetches URLs that users type. It blocks private addresses itself, but also run the backend in a network that cannot reach your internal services (separate VPC/subnet or firewall rules) — defence in depth against DNS tricks inside the browser.
* Install fonts for the languages you serve (the Docker image includes DejaVu and Noto) or set `OVERLAY_FONT_PATH`.

### Showcase behind nginx (one address for everything)

1. `frontend/.env.local`: set `NEXT_PUBLIC_API_TARGET=nginx` (back to `direct` to call `NEXT_PUBLIC_API_BASE_URL`, e.g. `http://localhost:8000`). Restart `npm run dev` or rebuild.
2. `backend/.env`: `TRUST_PROXY_HEADERS=true` (rate limits per real visitor). No CORS change is needed: page and API share one origin.
3. nginx on your machine: use `deploy/nginx/adsify.local.conf` + `deploy/nginx/adsify-locations.conf` (backend on 127.0.0.1:8000, frontend on 127.0.0.1:3000, listens on port 80).
   Docker instead: `NEXT_PUBLIC_API_TARGET=nginx docker compose --profile nginx up --build` → http://localhost:8080 (`NGINX_PORT` changes it).

Routes: `/api/*`, `/health`, `/ready`, `/docs`, `/openapi.json` → backend; everything else → frontend (with WebSocket upgrade for hot reload). Uploads up to 60 MB, 300 s timeouts.

### Scaling

This build is intentionally simple: **one backend process**, SQLite, jobs inside the process. That comfortably serves a single business or a small team. To scale: move the `records` table to Postgres, move scan/ad jobs to a worker queue (arq/Celery/RQ — `ScrapeJobs` and `Ads` are the only two classes to change), share the video folder via object storage, and use Redis (`REDIS_URL`) for the scan cache.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Website shows "Cannot reach the server" | Backend not running, or `NEXT_PUBLIC_API_BASE_URL` wrong. Restart `npm run dev` after editing `.env.local`. |
| Browser console: CORS error | Add the website's address to `CORS_ORIGINS` and restart the backend. |
| "FFmpeg is not installed" | Install FFmpeg and make sure `ffmpeg -version` works in the same terminal. |
| JavaScript sites come back `partial` | `python -m playwright install firefox` (on Linux add `--with-deps`). `doctor` tells you if it is missing. |
| Scan says `blocked` | The site uses Cloudflare/captcha. This is reported, never bypassed — type the business details instead. |
| Video is only a zoom clip | Demo mode (no `VIDEO_MODEL_API_KEY`), or the video model failed and the clip says `completed_with_fallback`; see the warning text. |
| Text on the video shows empty boxes | Install a font that has the script (`fonts-noto-core`) or set `OVERLAY_FONT_PATH`. |
| `NotImplementedError` from Playwright on Windows | Start with `python -m app`, not `--reload`. |

---

## 10. Known limitations (read before production)

* **Not verified in the build environment** (no internet there): the live Magic Hour call (including whether the SDK uploads a local image path as expected), the real FastAPI server start, `next build` in a browser, and the Firefox engine (Chromium was exercised; the code launches Firefox by default and a test proves it). Run `make doctor`, `python scripts/smoke_test.py` and one real ad on your machine first — they take minutes. With a real key, the first generated video is the real test of the Magic Hour step.
* Single-instance design (see Scaling). SQLite only.
* No authentication/accounts.
* Cancelling an AI ad stops our side immediately, but a request already sent to the video provider may still finish (and use credits) on the provider's side.
* The video model sets the real clip length (default 5 s); longer requests are shortened and flagged.
* A page that only works after logging in, or sits behind aggressive bot protection, cannot be scanned (reported as `blocked`).
