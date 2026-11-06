# Adsify — website → video ad

Paste a business website, pick a goal and a style, and get **one short video ad** made from **one prompt** and **one hero image**.

```
 website URL
     │
     ▼
 ┌──────────┐   real facts only    ┌───────────────┐   1 prompt + 1 hero image   ┌────────────┐   name / offer / phone
 │ Scanner  │ ───────────────────▶ │ Prompt writer │ ──────────────────────────▶ │ Video model│ ──▶ added as clean text ──▶ MP4
 │ httpx →  │   (never invented)   │ AI or built-in│   (image-to-video)          │ Gemini Omni│     with FFmpeg overlay
 │ Firefox  │                      │ + fact guard  │                             │ or demo    │
 └──────────┘                      └───────────────┘                             └────────────┘
```

* **Next.js** website (`frontend/`) and **FastAPI** backend (`backend/`).
* Works **out of the box without any API key** (demo mode: the scan is real, the video is a simple zoom clip made with FFmpeg).
* Add a Gemini API key for real AI video and an AI-written prompt. Without it the app stays in demo mode.

> **Security first:** the `backend/env.example` in the original upload contained **live OpenRouter and Magic Hour keys**.
> Treat them as leaked: **revoke/rotate both keys** in their dashboards and put the new ones only in `backend/.env`.
> This project never contains keys; `.env` is git-ignored.

---

## Studio: typed videos in seven stages

Besides the one-prompt ad above, `backend/app/studio/` makes a video of a chosen type (**promo, hook ad, pitch, showcase, explainer,
testimonial, launch**) in seven stages that each save a file you can read and correct: capture (page text and about ten screenshots),
product notes (every claim cites its source), brand notes, assumptions, storyboard, build (voice, music, motion graphics in the brand
colours) and check (every figure compared with the notes). Example:

```bash
cd backend
python -m playwright install chromium
python -m app.studio run --url https://backseatnetwork.com --type promo --length 20 --platform 16:9
```

It is also on the website, as a choice inside the one **Make an ad** flow (`/ads/create`): Automated → media from my website → **Studio**
(instead of Caption + QR; it gives the better result but takes longer). Pick the video type, the length and the shape; watch the seven stages; **check and correct the plan** (audience, message, voice, music,
call to action, must-include and must-avoid, with the sourced claims and screenshots in front of you); then play and download the video
with every shot's claims listed. The page keeps `?job=<id>` in its address, so a reload or a shared link comes back to the same job.
The API is `POST /api/studio/jobs`, `GET /api/studio/jobs/{id}`, `PUT .../assumptions`, `POST .../continue`, `POST .../cancel`,
`GET .../video` and `GET .../screenshots/{file}` (see `docs/openapi.json`). It needs the AI writer (`AI_PROMPT_*` in `backend/.env`);
the Docker image installs Chromium for it. The daily ad limit (`MAX_ADS_PER_DAY`) applies, and private addresses are refused.

**What the video looks like.** 1080p at 30 fps. When the brand has a strong colour it fills every other frame (white pill headlines, a
highlight colour for figures), the others use the site's own background. Screenshots appear in a large browser window cropped to the part
that has content (never a small card on empty white), the site's logo closes the video on a call-to-action card, and a close crop of a
real screenshot (or one of the site's own pictures) sits beside the headlines. A page that is blank, or only asks you to sign in, is
refused with a clear message instead of making an empty video.

**Voices, languages and sound.** Pick the language of the voiceover (English, Hindi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada,
Malayalam, Spanish, French, German, Arabic, Portuguese) and a voice, or let the AI choose. The storyboard is written and checked in English;
only the voice lines are then translated (one request, every figure kept, a line is translated again only when its English changed), and the
words on screen stay as your website wrote them. Free Microsoft voices work out of the box. With `ELEVENLABS_API_KEY` in `backend/.env`,
studio-quality ElevenLabs voices appear too (the free plan has 10,000 characters a month; every line is cached, so rebuilding costs nothing,
and when the key fails or the plan runs out a Microsoft voice of the same language and gender takes over). Every video also gets original
sound effects that follow the animation (whooshes on slides, pops, a stamp-and-ding on prices, a chime and sparkle on the call to action).
They are synthesised by FFmpeg, so they are copyright-free and nothing is downloaded. Turn them off with "Sound effects".

See [backend/app/studio/README.md](backend/app/studio/README.md) to run each stage, and [samples/backseatnetwork-promo](samples/backseatnetwork-promo/NOTES.md) for a finished run.

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
| Real AI video and AI-written prompt | `GEMINI_API_KEY=` your **Gemini** key | One key does both. Prompts use `GEMINI_MODEL` (`gemini-flash-latest`). Video uses `GEMINI_VIDEO_MODEL` (`gemini-omni-1.1-flash`), because the flash model does not generate video. Costs credits. |
| Protect your credits | `MAX_ADS_PER_DAY`, `RATE_LIMIT_PER_MINUTE`, `MAX_CONCURRENT_ADS` | The API has **no login**. Keep it private or put it behind your own auth before exposing it publicly (see §8). |

`AI_PROMPT_BASE_URL` / `AI_PROMPT_MODEL` still override the prompt writer. The old names (`OPENROUTER_API_KEY`, `OPENAI_BASE_URL`, `OPENROUTER_MODEL`, `MAGIC_HOUR_API_KEY`) still work. `VIDEO_PROVIDER=magic_hour` keeps the previous video provider.

If the video model fails, the ad is finished with a demo clip and flagged `completed_with_fallback` (switch off with `VIDEO_FALLBACK_ON_ERROR=false`).
The video model makes clips of up to `VIDEO_MAX_SECONDS` (default 5). A longer request is shortened and the user is told.

---

## 3. What the user sees

**One flow: Make an ad → Manual or Automated → media → (Caption + QR or Studio) → settings → review → result.**

One screen at a time, with a step indicator. The flow lives at `/ads/create` (the home page, "My ads" and the top bar all lead to it).

1. **Make an ad: how?** Two big cards. **Manual** (you give your own photos or videos) or **Automated** (we start from your website).
2. **Media.**
   * **Manual:** upload photos and/or videos (MP4, MOV, WebM), an optional logo, and optional name, offer, call to action and phone. Nothing is scanned and no AI video is made.
   * **Automated:** pick where the media comes from, then paste your website (we scan it for your name, details and pictures):
     **From my website** (its own pictures), **Full AI** (a new AI video from your business details) or **Mix** (website pictures around an AI clip).
     Modes that need the AI video provider are disabled, with the reason, when none is configured.
3. **How should we build it?** *(Automated with website media only)*
   * **Caption + QR:** fast (about 1 to 2 minutes). Your pictures with motion, animated captions, your offer, logo and a QR code. Next: settings and review.
   * **Studio:** the better result, but it takes longer (about 3 to 5 minutes). A designed, story-driven video with a plan you approve first, your brand colours and fonts, a voice-over in your language
     (free Microsoft voices or ElevenLabs studio voices), sound effects, and every number checked against your website. Next: the Studio screens.
   Studio is built from the website's own pictures and wording, so Full AI and Mix go straight to settings with Caption + QR.
4. **Settings** *(Caption + QR and Manual)*: the kind of ad (17 types), platform (taxi screen 16:9, Reel/Shorts 9:16, Facebook 1:1), length, voice and music, plus (under Advanced) which website images, logo, QR destination, style and, for AI modes, goal, tone and creative instructions.
5. **Review** *(Caption + QR and Manual)*: mode, media and where it comes from, **whether the AI video provider will be called**, QR destination, format, length and the stages that will run.
6. **Result:** page `/ads/<id>` (safe to refresh or bookmark): live progress (with *Cancel*), what the video is made of, whether it contains AI footage, whether the QR code was really added, the MP4 and any warnings.

**Studio screens** (inside the same flow): choose the kind of video (promo, hook ad, pitch, showcase, explainer, testimonial, launch), its length and shape, the **language and voice** and whether to add **sound effects** →
live progress through seven stages → **check the plan** (what was found with its sources, screenshots, brand colours, and the audience, message, tone, voice, music and call to action the AI chose, all editable) →
the finished video with every shot's claims. The job id is kept in the address (`?studio=<id>`), so a reload or shared link comes back to the same video.

| Mode | Website scan | Prompt writer | AI video provider | Final video |
|---|---|---|---|---|
| Manual | no | no | **no** | your images (with motion) and videos, FFmpeg |
| Website Content Priority | yes | no | **no** | original website images, 3 s each (5 s → 2, 15 s → 5, 20 s → 7), looping when there are fewer |
| AI Video Priority | yes (facts only) | yes | yes (text-to-video) | AI footage only, no website pictures; a short clip loops to 5/10/15/20 s |
| Website + AI Mix | yes | yes | yes (image-to-video) | website image(s) → AI video (looped to the length) → website image(s) |
| Studio | yes (page text, screenshots, logo, pictures, brand) | yes (notes, plan, storyboard, translation) | **no** | HTML/CSS motion graphics in your brand colours with your real screenshots, voice-over, music and sound effects, rendered with FFmpeg |

Every Caption + QR mode adds the logo, the QR code (exactly the URL you typed) and the text overlays with FFmpeg on the complete video. The backend validates every combination (`creative` in the request) and refuses AI modes when no AI provider is configured instead of producing a demo clip. If the provider fails during an AI ad, the ad is marked `completed_with_fallback` and the replacement clip is labelled as *not* AI footage (or the ad fails when `VIDEO_FALLBACK_ON_ERROR=false`).

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
* **Gemini Omni** text-to-video or image-to-video, or the **demo provider** (FFmpeg zoom clip) when there is no key.
* **Finalize:** business name, offer, call to action, phone and address (plus optional logo and QR code) are drawn with Pillow and burned in with FFmpeg — video models draw digits badly, so these are always real text from real facts. Non-Latin text (Devanagari, Arabic, Tamil) uses Noto fonts when installed.

**Jobs:** scans and ads run as in-process asyncio tasks stored in SQLite; unfinished work is closed cleanly after a restart. Old data is deleted after `DATA_RETENTION_HOURS` (72).

---

## 5. API: use it as a backend

The website is just one client. Everything it does is a plain JSON/HTTP API under `/api`, so you can run the backend on its own and call it from your own app, script or another service.

* Machine-readable spec: [`docs/openapi.json`](docs/openapi.json) (OpenAPI 3.1) · Postman collection: [`docs/postman_collection.json`](docs/postman_collection.json) · integration guide: [`docs/API.md`](docs/API.md).
* Interactive docs of a running development server: `http://localhost:8000/docs` (switched off when `APP_ENV=production`).

### Run only the backend

```bash
cp backend/.env.example backend/.env        # add the keys you have (all optional: see below)
docker compose up -d --build backend redis  # API on http://localhost:8000   (or: make backend)
curl http://localhost:8000/health           # {"status": "ok", ...}
curl http://localhost:8000/api/config       # what this server can do (see "Reading the options")
```

| Key in `backend/.env` | Turns on |
|---|---|
| *(none)* | scanning, manual ads, Website Content Priority ads, free Microsoft voices, music, sound effects (demo clips instead of AI video) |
| `AI_PROMPT_API_KEY` (+ `AI_PROMPT_BASE_URL`, `AI_PROMPT_MODEL`; OpenRouter, Gemini or any OpenAI-compatible gateway) | the AI writer: AI video prompts, **Studio** (notes, plan, storyboard, translation), better caption copy |
| `VIDEO_MODEL_API_KEY` (Magic Hour) or `GEMINI_API_KEY` | AI video: Full AI and Mix modes |
| `ELEVENLABS_API_KEY` | ElevenLabs studio voices (falls back to a free voice when missing or used up) |

### The basics

* **Base URL:** your server (`http://localhost:8000` locally). All endpoints are under `/api`, except the probes `/health` and `/ready`.
* **No login, no API keys.** Anyone who can reach the API can use it (and spend your credits). Before exposing it, put it behind your own gateway, proxy with auth, VPN or allow-list. Expensive calls are limited per client (`RATE_LIMIT_PER_MINUTE`, answers `429 rate_limited`) and per day (`MAX_ADS_PER_DAY`, answers `429 daily_limit`).
* **Everything slow is a job.** A `POST` returns `202` with an id straight away; **poll** the matching `GET` every 1 to 5 seconds until it is final; then fetch the video:

  | Job | Start | Poll | Done when | Result |
  |---|---|---|---|---|
  | Website scan | `POST /api/scrape` | `GET /api/jobs/{job_id}` | `is_final` is `true` | the scan (`result`) |
  | Ad | `POST /api/generate-ad` | `GET /api/ads/{ad_id}` | `status` is `completed`, `completed_with_fallback` or `failed` | `GET /api/ads/{ad_id}/video` |
  | Studio video | `POST /api/studio/jobs` | `GET /api/studio/jobs/{job_id}` | `status` is `review` (your turn), `completed`, `failed` or `cancelled` | `GET /api/studio/jobs/{job_id}/video` |
* **Errors** always look like `{"detail": "a sentence you can show to people", "code": "machine_code"}`. Branch on `code`.
* **Videos** are MP4 and support HTTP `Range`; add `?download=1` for a file download.
* **CORS:** browsers may call the API only from origins in `CORS_ORIGINS` (server-to-server calls are not affected).

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Options and limits: platforms, ad types, voices, **languages**, music, durations, upload limits, which modes and **Studio** are available |
| POST | `/api/scrape` | Start a website scan → `202` + job. Body `{url, refresh?}` |
| GET | `/api/jobs/{job_id}` | Scan progress and result (name, details, images, brand) |
| POST | `/api/uploads` | Multipart `kind=logo\|photo\|video`, `files=…` → asset ids. Videos are checked by their bytes and ffprobe (MP4/MOV/WebM; `MAX_VIDEO_UPLOAD_BYTES`, `MAX_VIDEO_UPLOAD_SECONDS`) |
| GET | `/api/assets/{asset_id}` | An uploaded image or video |
| POST | `/api/generate-ad` | Create **one** ad → `202`. Body: `job_id` or `scrape_result`, `business`, `options`, `hero`, `logo_asset_id`, `creative` (below) |
| GET | `/api/ads/{ad_id}` | Status, stage, progress, prompt, warnings, `video_url`, `composition`, `ai_video_used`, `qr_added` |
| POST | `/api/ads/{ad_id}/cancel` | Stop an ad that is still running |
| GET | `/api/ads/{ad_id}/video` | The MP4 |
| POST | `/api/studio/jobs` | Start a **Studio** video from a website → `202` + job. Body `{url, video_type, length, platform, claims?, review?, language?, voice?, sound_effects?}` |
| GET | `/api/studio/jobs/{job_id}` | Progress of the seven stages and what each produced (claims, brand, plan, shots, screenshots, check result) |
| PUT | `/api/studio/jobs/{job_id}/assumptions` | Correct the AI's plan (audience, message, tone, voice, language, music, call to action, must include/avoid) while the job waits in `review` |
| POST | `/api/studio/jobs/{job_id}/continue` | Make the video after the review → `202` |
| POST | `/api/studio/jobs/{job_id}/cancel` | Stop a Studio job after its current step (a job waiting for review is cancelled at once) |
| GET | `/api/studio/jobs/{job_id}/video` | The finished MP4 |
| GET | `/api/studio/jobs/{job_id}/screenshots/{file}` | A screenshot captured from the website |
| GET | `/health`, `/ready` | Liveness / readiness (database, cache, browser, providers) |

### Recipes (curl)

```bash
BASE=http://localhost:8000
JSON='Content-Type: application/json'
```

**1. An ad from a website (Caption + QR, no AI video).**

```bash
JOB=$(curl -s -X POST $BASE/api/scrape -H "$JSON" -d '{"url":"https://www.example.com"}' | jq -r .job_id)
until [ "$(curl -s $BASE/api/jobs/$JOB | jq -r .is_final)" = true ]; do sleep 2; done          # the scan
AD=$(curl -s -X POST $BASE/api/generate-ad -H "$JSON" -d "{
  \"job_id\": \"$JOB\",
  \"options\": {\"platform\": \"taxi_screen\", \"duration_seconds\": 10, \"voice\": \"auto\", \"music\": \"auto\"},
  \"creative\": {\"creation_mode\": \"auto\", \"creative_mode\": \"website\", \"use_website_images\": true,
                \"include_qr\": true, \"qr_url\": \"https://www.example.com\"},
  \"wait_for_prompt\": false}" | jq -r .ad_id)
until curl -s $BASE/api/ads/$AD | jq -e '.status | IN("completed","completed_with_fallback","failed")' >/dev/null; do sleep 3; done
curl -s $BASE/api/ads/$AD | jq '{status, video_url, ai_video_used, qr_added, warnings}'
curl -s -o ad.mp4 "$BASE/api/ads/$AD/video?download=1"
```

**2. A manual ad from your own photos and videos.**

```bash
A1=$(curl -s -X POST $BASE/api/uploads -F kind=photo -F files=@shop.jpg -F files=@menu.jpg | jq -c '[.assets[].asset_id]')
curl -s -X POST $BASE/api/generate-ad -H "$JSON" -d "{
  \"business\": {\"name\": \"Joe's Cafe\", \"offer\": \"2 for 1 coffee\", \"cta\": \"Scan to order\"},
  \"creative\": {\"creation_mode\": \"manual\", \"use_uploaded_media\": true, \"media_asset_ids\": $A1, \"include_qr\": true, \"qr_url\": \"https://joes.example/order\"}}" | jq .ad_id
```

**3. AI video or a mix.** Same as recipe 1 with `"creative_mode": "ai"` or `"mixed"` (needs `VIDEO_MODEL_API_KEY` or `GEMINI_API_KEY`; `GET /api/config` → `ai_video_available` says whether it is on). The server answers `422` instead of faking AI footage when it is off.

**4. A Studio video** (the better, slower one: a plan you approve first, voice-over in any of 14 languages, sound effects).

```bash
# a) start it: video_type promo|hook_ad|pitch|showcase|explainer|testimonial|launch, length 8-60 s, platform 16:9|9:16|1:1
ST=$(curl -s -X POST $BASE/api/studio/jobs -H "$JSON" -d '{
  "url": "https://www.example.com", "video_type": "promo", "length": 20, "platform": "16:9",
  "language": "hi", "voice": "auto", "sound_effects": true, "review": true,
  "claims": ["Free demo every Friday"]}' | jq -r .job_id)

# b) wait for the review (or "failed", with a plain-language "error")
until curl -s $BASE/api/studio/jobs/$ST | jq -e '.status | IN("review","failed")' >/dev/null; do sleep 4; done
curl -s $BASE/api/studio/jobs/$ST | jq '{claims: .claims, brand, assumptions}'     # what was found, with sources, and the AI's plan

# c) (optional) correct the plan: send back the assumptions object with your changes
curl -s $BASE/api/studio/jobs/$ST | jq '.assumptions | .key_message = "Free demo every Friday"' \
  | curl -s -X PUT $BASE/api/studio/jobs/$ST/assumptions -H "$JSON" -d @- >/dev/null

# d) make the video, wait, download
curl -s -X POST $BASE/api/studio/jobs/$ST/continue >/dev/null
until curl -s $BASE/api/studio/jobs/$ST | jq -e '.status | IN("completed","failed","cancelled")' >/dev/null; do sleep 6; done
curl -s $BASE/api/studio/jobs/$ST | jq '{status, passed, problems, shots: [.shots[] | {n, voice, voice_local}]}'
curl -s -o studio.mp4 "$BASE/api/studio/jobs/$ST/video?download=1"
```

Studio request fields: `review` (default `true`) stops after the plan so you can correct it, `false` runs straight through; `claims` are up to 5 facts of your own (a real customer quote, a price) that are used as if they were on the website;
`language` is one of the ids in `/api/config` → `languages` (`en hi ta te bn mr gu kn ml es fr de ar pt`); `voice` is `auto` (the AI chooses) or an id from `/api/config` → `voices` that speaks that language (a mismatch is `422`);
`sound_effects` turns the whooshes, pops and chimes on or off. The video is spoken in the chosen language: only the voice lines are translated (every figure kept) and the words on screen stay as the website wrote them.
A Studio video needs the AI writer (`studio_available` in `/api/config`); without it `POST /api/studio/jobs` answers `409 studio_unavailable`.

### Reading the options

Never hard-code platforms, lengths, voices or limits: read `GET /api/config`. It returns, among others:

```json
{
  "platforms": [{"id": "taxi_screen", "label": "...", "aspect_ratio": "16:9"}, ...],
  "ad_types": [...], "music": [...], "durations": [...], "compose_durations": [5, 10, 15, 20],
  "languages": [{"id": "hi", "label": "Hindi", "native": "हिन्दी"}, ...],
  "voices": [{"id": "swara", "label": "Swara", "engine": "edge", "languages": ["hi"], "gender": "f"},
             {"id": "el_adam", "label": "Adam (ElevenLabs)", "engine": "eleven", "languages": ["en", "hi", ...], "gender": "m"}, ...],
  "eleven_available": true,
  "ai_video_available": false, "ai_video_message": "...",
  "studio_available": true, "studio_types": [{"id": "promo", "label": "Promo", "min_length": 16, "shots": [...]}, ...],
  "creative_modes": [{"id": "website", "available": true, ...}, ...]
}
```

`engine` is `edge` (free Microsoft voice) or `eleven` (ElevenLabs; listed only while that key works). Each video type has a `min_length` (its shots need about two seconds each to be read).

### Status values and error codes

* **Ad** `status`: `queued` · `running` · `completed` · `completed_with_fallback` (the AI provider failed and a plain clip was used: see `provider_error`, never present it as AI footage) · `failed`.
* **Studio** `status`: `queued` · `running` · `review` (waiting for you: `PUT` the plan, then `continue`) · `completed` · `failed` · `cancelled`. Each of the seven `stages` is `pending` · `running` · `done` · `failed`. `passed` and `problems` are the result of the final check (every number compared with the website notes).

| `code` | HTTP | Meaning |
|---|---|---|
| `invalid_request` | 422 | A field is missing or wrong (the `detail` says which) |
| `unsafe_url` | 422 | The address is private, internal or not a public website (SSRF protection) |
| `rate_limited` | 429 | Too many requests from this client: wait a minute |
| `daily_limit` | 429 | The daily cap on ads or Studio videos is reached |
| `studio_unavailable` | 409 | Studio needs the AI writer and none is configured |
| `not_in_review` · `video_not_ready` · `studio_finished` | 409 | The action does not fit the job's state (for example `continue` before `review`) |
| `job_not_found` · `ad_not_found` · `studio_job_not_found` · `asset_not_found` · `screenshot_not_found` | 404 | Unknown or expired id (data is deleted after `DATA_RETENTION_HOURS`, 72 by default) |
| `file_too_large` · `too_many_files` · `no_files` | 413 / 422 | Upload limits (see `/api/config`) |

Generate a typed client from the spec: `npx @openapitools/openapi-generator-cli generate -i docs/openapi.json -g typescript-fetch -o ./site2ad-client` (or `-g python`). After you change a route or schema, run `python scripts/generate_openapi.py` to refresh the spec and Postman files (the test suite checks they match the code).

---

## 6. Configuration

Every setting is documented in **`backend/.env.example`** (copy it to `backend/.env`). The ones you are most likely to touch:

| Variable | Default | Meaning |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:3000` | Frontend address(es) allowed to call the API (comma separated) |
| `GEMINI_API_KEY` | empty | Gemini key for prompts and video; empty = demo mode |
| `GEMINI_MODEL` | `gemini-flash-latest` | Model that writes the ad prompt |
| `GEMINI_VIDEO_MODEL` | `gemini-omni-1.1-flash` | Model that generates the video |
| `VIDEO_MODEL_API_KEY` | empty | Legacy Magic Hour key, used only when that provider is selected |
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
│   │   ├── video/             images · gemini · magic_hour · mock · finalize · service
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
