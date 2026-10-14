# Adsify — project report

This is the engineering report that goes with the code. The quick start is in [../README.md](../README.md).
Sections follow the deliverables of the brief: **1** file tree · **2** architecture summary · **3** broken / old paths found · **4** proposed architecture · **5** files changed · **6** full code · **7** new files · **8** install & run · **9** test plan · **10** remaining risks. Section **11** lists the decisions I took without asking.

**Size:** about 6,900 lines of backend code, 2,000 lines of backend tests (222 tests), 1,500 lines of frontend TypeScript.

---

## 1. Final file tree

```
adsify/
├── backend/
│   ├── app/
│   │   ├── ai/
│   │   │   ├── facts.py   # FactSheet (user values win)
│   │   │   ├── guard.py   # rejects invented facts in AI prompts
│   │   │   ├── llm.py   # OpenAI-compatible / OpenRouter client
│   │   │   ├── prompt_builder.py   # LLM -> validate -> retry -> template
│   │   │   └── template.py   # deterministic one-prompt builder
│   │   ├── api/
│   │   │   ├── core.py   # all request logic (framework-free, unit-tested)
│   │   │   ├── ranges.py   # HTTP Range for video seeking
│   │   │   └── routes.py   # thin FastAPI routes, one /api prefix
│   │   ├── scraper/
│   │   │   ├── crawl.py   # phase 2: inner pages
│   │   │   ├── detect.py   # CSR score, Cloudflare / captcha detection
│   │   │   ├── extract.py   # name / phone / address / images / colours
│   │   │   ├── fetch.py   # SSRF-safe httpx client, redirects, size limits
│   │   │   ├── phones.py   # phone parsing -> E.164
│   │   │   ├── render.py   # Playwright Firefox pool (async)
│   │   │   ├── safety.py   # URL normalisation + SSRF policy
│   │   │   └── service.py   # two-phase orchestration
│   │   ├── services/
│   │   │   ├── ads.py   # ad pipeline: prompt -> hero -> video -> overlay
│   │   │   ├── assets.py   # uploaded logo / photos
│   │   │   ├── maintenance.py   # retention cleanup loop
│   │   │   └── scrape_jobs.py   # two-phase scan jobs, cache, dedupe
│   │   ├── store/
│   │   │   ├── cache.py   # Redis or in-memory cache
│   │   │   └── db.py   # SQLite store
│   │   ├── video/
│   │   │   ├── base.py   # provider interface, errors, ffmpeg helpers
│   │   │   ├── finalize.py   # name / offer / phone / address / logo / QR burned in
│   │   │   ├── images.py   # hero / logo download, checks, cover crop
│   │   │   ├── magic_hour.py   # Magic Hour image-to-video
│   │   │   ├── mock.py   # demo provider (FFmpeg zoom clip)
│   │   │   └── service.py   # provider choice + demo fallback
│   │   ├── __main__.py
│   │   ├── catalog.py   # platforms, goals, styles, tones
│   │   ├── cli.py   # serve | scrape | demo | doctor
│   │   ├── config.py   # settings from environment
│   │   ├── context.py   # wires everything together
│   │   ├── main.py   # app factory, CORS, error format, lifespan
│   │   ├── ratelimit.py   # per-client limiter
│   │   └── schemas.py   # Pydantic models = the API contract
│   ├── scripts/
│   ├── tests/
│   │   ├── conftest.py   # async test runner + settings
│   │   ├── fixture_server.py   # local fake websites
│   │   ├── sites.py   # fixture sites (static, React shell, Cloudflare, ...)
│   │   ├── test_api.py
│   │   ├── test_config.py
│   │   ├── test_contract.py
│   │   ├── test_pipeline.py
│   │   ├── test_prompt.py
│   │   ├── test_scraper.py
│   │   └── test_video.py
│   ├── .dockerignore
│   ├── .env.example
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements-dev.txt
│   └── requirements.txt
├── docs/
│   ├── reference/   # original design notes
│   │   ├── SCRAPE.md
│   │   └── website-scraper-design.md
│   └── PROJECT_REPORT.md   # this report
├── frontend/
│   ├── app/
│   │   ├── ads/
│   │   │   ├── [adId]/
│   │   │   │   └── page.tsx
│   │   │   ├── create/
│   │   │   │   └── page.tsx
│   │   │   └── layout.tsx
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── ad/
│   │   │   ├── AdProgress.tsx
│   │   │   ├── AdResult.tsx
│   │   │   └── PromptView.tsx
│   │   ├── create/
│   │   │   ├── CreateFlow.tsx
│   │   │   ├── FactsForm.tsx
│   │   │   ├── ImagePicker.tsx
│   │   │   ├── ImageUpload.tsx
│   │   │   ├── OptionsStep.tsx
│   │   │   ├── ReviewStep.tsx
│   │   │   └── ScanProgress.tsx
│   │   └── ui/
│   │       ├── Alert.tsx
│   │       ├── Button.tsx
│   │       ├── InputField.tsx
│   │       ├── OptionCard.tsx
│   │       ├── ProgressBar.tsx
│   │       ├── SelectField.tsx
│   │       ├── Spinner.tsx
│   │       └── StepIndicator.tsx
│   ├── lib/
│   │   ├── api.ts   # THE only place that calls the backend
│   │   ├── draft.ts   # form state <-> business overrides
│   │   ├── types.ts   # mirror of backend schemas
│   │   └── usePolling.ts   # polling with backoff
│   ├── .dockerignore
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── next.config.ts
│   ├── package.json
│   ├── postcss.config.mjs
│   └── tsconfig.json
├── scripts/
│   ├── check_contract.py   # frontend <-> backend consistency check
│   └── smoke_test.py   # end-to-end test of a running server
├── .gitignore
├── docker-compose.yml   # backend + frontend + redis
├── Makefile   # setup / backend / frontend / test / smoke shortcuts
└── README.md   # start here: quick start + project docs
```

---

## 2. Architecture summary

```
Browser (Next.js)  ──HTTP /api──▶  FastAPI (thin routes)  ──▶  Api (core.py, no framework)
                                                                   │
                  ┌────────────────────────────────────────────────┼─────────────────────────────┐
                  ▼                                                ▼                             ▼
            ScrapeJobs                                           Ads                       AssetStore
   (jobs, cache, dedupe, 2 phases)              (one ad = one background run)          (uploaded logo/photos)
                  │                                                │
        Scraper ──┤                         PromptBuilder ─────────┼───────── VideoService
   httpx → Firefox (CSR only)               FactSheet → AI or template        Magic Hour  | demo (FFmpeg)
   SSRF-safe fetch, robots, 5 MB            → fact guard → ONE prompt         hero image prep → finalize overlay
                  │                                                │
                  └──────────────────────  SQLite (records)  +  Cache (Redis or memory)  ─────────┘
```

* **Thin edges, fat core.** `routes.py` only converts HTTP to Python calls. All logic lives in `Api` (`core.py`) so it is unit-tested without a web server.
* **Two long-running things, both background jobs:** scanning a website, and making an ad. The browser starts them (`202 Accepted`) and polls.
* **One ad = one prompt = one hero image = one video.** Enforced in code (`Ads.create` creates exactly one `AdPrompt`; the prompt builder returns one string) and tested.
* **Facts, not fantasy.** Every fact that reaches the prompt or the video text comes from a `FactSheet` built from (1) what the user typed, then (2) what the scanner found. The AI-written prompt is checked against it.
* **Always finishes.** Every path ends in a terminal status (`ok/partial/blocked/…` for scans, `completed/completed_with_fallback/failed` for ads), including crashes, timeouts and server restarts.

---

## 3. Broken and old paths found in the upload

| # | Where (original) | Problem | What the new code does |
|---|---|---|---|
| 1 | `backend/env.example` | Contained **live** OpenRouter and Magic Hour keys (the OpenRouter key twice). | No keys anywhere. `.env.example` has only empty values. **You must rotate both keys.** |
| 2 | `Fontend/app/app/ads/create/page.tsx` | `const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL \|\| "http://localhost:8000"` — a hard-coded localhost fallback that silently ships to production. | `lib/api.ts` reads only `NEXT_PUBLIC_API_BASE_URL`; empty means same-origin. No localhost in code (checked by `check_contract.py`). |
| 3 | same file, lines ~133 / 178 / 187 | Three hand-written `fetch` calls to `/api/v1/ads/generate`, `/api/v1/ads/{id}`, `/api/v1/ads/{id}/video`; polling, error handling and URL building inside the page component. | One client (`lib/api.ts`), one prefix (`/api`), no `/v1`, polling in `usePolling.ts` with backoff. |
| 4 | `routes/routes/ads.py` | Routes are declared as `/v1/ads/...` with **no prefix in the file**; the page calls `/api/v1/...`. The `/api` prefix can only come from an `app/main.py` that was **not in the upload**, so the contract is invisible and fragile. | One `APIRouter(prefix="/api")` in `routes.py`; `scripts/check_contract.py` fails the build if the frontend calls a route that does not exist. |
| 5 | `routes/routes/ads.py` imports | `app.database`, `app.models`, `app.schemas`, `app.config`, SQLAlchemy async session, `arq` + Redis, and a worker function `run_ad_pipeline` — none of which were provided. The backend could not start from the upload. | Self-contained backend: SQLite via stdlib, in-process jobs, Redis optional. Starts with `python -m app`. |
| 6 | `routes/routes/ads.py` enqueue | If Redis enqueue fails the error is logged and swallowed; the comment says "worker will pick it up if Redis comes back" but arq does not poll the database. The ad would stay `queued` forever. | Jobs run in-process; on restart unfinished jobs are closed with a clear message (and tested). |
| 7 | `routes/routes/ads.py` durations | Accepts `duration_seconds in (10, 15, 20)` while `generate_ad_video.py` hard-codes `end_seconds=5`. A 20-second ad was always 5 seconds, silently. | Requested length is clamped to `VIDEO_MAX_SECONDS`; the response says what was really made (`actual_duration_seconds`) and adds a warning. |
| 8 | `routes/routes/ads.py` uploads | `_safe_ext` trusts the client's file name; no size limit, no content check; user **videos** accepted although the brief says one hero image. | Uploads are decoded with Pillow and re-encoded (strips EXIF/GPS and hidden payloads), size/count limited, generated file names, no video upload. |
| 9 | `routes/routes/health.py` | `/ready` returns HTTP 200 with `"status": "not_ready"`; orchestrators read the status code, so a broken instance looks healthy. Requires Redis. | `/ready` answers 503 when the database is down; Redis and the browser are reported but optional. |
| 10 | `automatin flow/genrate/generate_ad_video.py` | Passes a **URL** as `assets.image_file_path`; the video model should get the exact cropped hero image; no fallback, no timeout, no credit protection. | Local, validated, aspect-ratio-cropped hero file; timeout; demo fallback flagged `completed_with_fallback`; daily cap. |
| 11 | `automatin flow/script/generate_ad_prompt.py` | **Empty file (0 bytes)** — the prompt step did not exist, while the generator reads a `final_video_prompt.txt` that nothing creates. | Full prompt builder (`app/ai/`) with fact guard and template fallback. |
| 12 | `automatin flow/srape/Bs_httpx.py` | One 643-line file. Its SSRF checks (including guarding every browser request) were good and were kept in spirit, but it launches **Chromium** (the brief requires **Firefox**) and has no robots.txt handling, no per-site result cache, no two-phase result and no Cloudflare / captcha status. | `app/scraper/` package covering every item of the scraper brief. |
| 13 | `automatin flow/final overlaps/finalize_ad_video.py` | Standalone script: draws name, phone, CTA, logo and a QR code, but no address or offer, Latin-only fonts, and nothing happens gracefully if FFmpeg fails. | `video/finalize.py`: name, offer, CTA, phone, address, logo, QR, script-specific fonts; keeps the raw video if the overlay fails. |
| 14 | `routes/routes/ads.py` `/v1/ads/{id}/storyboard` | A storyboard endpoint implies **several prompts/scenes per ad**; the brief requires exactly one prompt per ad. | Removed. The single prompt (with its shot timings) is returned inside the ad. |
| 15 | `backend/env.example` `OPENAI_BASE_URL` | Contains `…/api/v1` — this is OpenRouter's own URL, **not** an app path; no change needed, but it is why a naive search for `/api/v1` finds a hit. | Kept as `AI_PROMPT_BASE_URL`; old names still accepted. |

Not found in the upload (so nothing to fix): the strings `/fastapi` and `/backend` as URL paths.

---

## 4. Proposed (delivered) architecture

### 4.1 Request flow

1. `POST /api/scrape {url}` → `202` + job. The job runs **phase 1** (homepage; target 5 s, cap 12 s) and publishes the first result with stage `ad_ready`, then continues with **phase 2** (inner pages) until the 60 s budget or the page limit.
2. The UI polls `GET /api/jobs/{id}` (first after 1.2 s, slowing down to every 5 s, and stopping after repeated failures). When `stage = ad_ready` the user can already review the facts.
3. Optional: `POST /api/uploads` for a logo / photos.
4. `POST /api/generate-ad` with the scan (`job_id`), the user's corrected `business` fields, `options`, an optional `hero`. Creates **one** ad and returns `202`.
5. Background run: `preparing` (facts, hero download + crop) → `prompt_building` (AI, validated, template fallback) → `prompt_ready` (prompt visible in the UI) → `generating_video` (Magic Hour or demo) → `finalizing` (text overlay) → `completed`.
6. `GET /api/ads/{id}` returns progress, prompt, warnings and `video_url`; `GET /api/ads/{id}/video` streams the MP4 with Range support.

### 4.2 Scanner decision tree

```
normalise URL → SSRF check (every hop, every DNS answer) → robots.txt
   └─ httpx GET (≤5 MB, ≤5 redirects, timeouts)
        ├─ Cloudflare / captcha challenge  ........................  status "blocked"  (no bypass)
        ├─ HTTP error / DNS / refused  ............................  "unreachable"
        ├─ CSR score ≥ 3 (empty root, "enable JavaScript", generic title, no text)
        │     └─ __NEXT_DATA__ / embedded JSON has the data?  → use it, no browser
        │     └─ else Playwright Firefox render (pool, per-page timeout) → extract
        │            └─ browser missing / crashed → keep httpx result, status "partial"
        └─ static page → extract
extract: name, description, category, services, phone (E.164), address, offer, CTA, logo, colours, images
phase 2: contact/about/services/menu/pricing… (skip list: login, cart, blog archives, files) → merge → cache 24 h
```

### 4.3 Statuses

* Scan `status`: `queued · running · ok · partial · blocked · unreachable · invalid_url · unsupported_platform · timeout · internal_error`. `stage`: `queued · fetching · rendering · extracting · ad_ready`.
* Ad `status`: `queued · running · completed · completed_with_fallback · failed`. `stage`: `queued · preparing · prompt_building · prompt_ready · generating_video · finalizing · completed · failed`.
* The frontend types are generated by hand but **verified** against the Pydantic literals by `check_contract.py` and a unit test.

### 4.4 Safety design

* **SSRF:** scheme/port allow-list, no credentials in URLs, IP checked after DNS and again at connect time (custom network backend), redirects followed manually and re-checked, same rules for image downloads. Private, loopback, link-local, metadata and reserved ranges are refused. Tests cover localhost, loopback and mapped IPv6, 10/172.16/192.168/100.64 ranges, the cloud metadata address, `.internal` / `.local` names, decimal and hex IPv4 forms, redirects to private IPs, and redirect loops / long chains.
* **Prompt injection:** website text goes into the AI request only inside an `<untrusted_website_text>` block; the answer is validated (shape, length, shot structure, reference-image wording) and fact-checked (numbers, phones, prices, years, risky claims such as "guaranteed", "#1", "24/7") and replaced by the template if it fails twice.
* **Credits:** per-client rate limit, daily ad cap, concurrency semaphore, retention cleanup, the browser can never submit a prompt (only the short, length-limited `special_instructions` text, which goes through the same checks).
* **Uploads:** decoded and re-encoded; ids are random 32-hex; files are served only by id.
* **Errors:** every error body is `{detail, code}`; API keys are scrubbed from error text; stack traces never reach the client.
* **Not included:** user accounts / authentication (see risks).

### 4.5 Data

One SQLite table `records(kind, id, status, data JSON, created_at, updated_at)` holds jobs, ads and assets; files live under `DATA_DIR` (`videos/`, `assets/`, `work/`). Scan results are cached under `scrape:v<schema>:<normalised host+path>`; a schema version bump invalidates old shapes automatically.

---

## 5. Files changed compared with the upload

| Original | Now |
|---|---|
| `Fontend/app/app/ads/create/page.tsx` (single page, inline fetches) | `frontend/app/ads/create/page.tsx` + `components/create/*` (6 step components) + `lib/api.ts`, `lib/types.ts`, `lib/draft.ts`, `lib/usePolling.ts` |
| `Fontend/app/app/ads/layout.tsx`, `layout.tsx`, `page.tsx`, `globals.css`, `components/ui/*` | Kept in spirit, rewritten with the same design tokens (ink / accent / surface / line); `FileUpload` and `CategoryCard` replaced by `ImageUpload`, `OptionCard` |
| *(none)* | `frontend/app/ads/[adId]/page.tsx` — refresh-safe result page |
| `routes/routes/ads.py`, `health.py`, `__init__.py` | `backend/app/api/routes.py` + `core.py` + `ranges.py`; `main.py` |
| `automatin flow/srape/Bs_httpx.py` | `backend/app/scraper/*` (7 modules) |
| `automatin flow/script/generate_ad_prompt.py` (empty) | `backend/app/ai/*` (5 modules) |
| `automatin flow/genrate/generate_ad_video.py` | `backend/app/video/{magic_hour,mock,service,images,base}.py` |
| `automatin flow/final overlaps/finalize_ad_video.py` | `backend/app/video/finalize.py` |
| `backend/env.example` | `backend/.env.example` (no keys, every setting documented) + `frontend/.env.example` |
| `SCRAPE.md`, `website-scraper-design.md` | Implemented; copied to `docs/reference/` |

---

## 6. Full code

Everything is in the ZIP; nothing is abbreviated. Reading order for a new developer:

1. `backend/app/schemas.py` — the API contract in one file.
2. `backend/app/api/core.py` — what each endpoint does.
3. `backend/app/services/ads.py` — the whole ad pipeline from request to MP4.
4. `backend/app/scraper/service.py` → `fetch.py` → `detect.py` → `render.py` → `extract.py`.
5. `backend/app/ai/prompt_builder.py` → `template.py`, `guard.py`.
6. `backend/app/video/service.py` → `magic_hour.py`, `finalize.py`.
7. `frontend/lib/api.ts`, `frontend/components/create/CreateFlow.tsx`.

Every function has a one-line comment saying what it does (your turn-1 rule).

---

## 7. New files (everything that did not exist in the upload)

* **Backend:** the entire `backend/app/` package (config, schemas, catalog, context, cli, ratelimit, store, services, api, scraper, ai, video), `requirements*.txt`, `pytest.ini`, `Dockerfile`, `.dockerignore`, `.env.example`, 10 test modules.
* **Frontend:** whole Next.js project config (`package.json`, `tsconfig.json`, `next.config.ts` with standalone output, `postcss.config.mjs`), `lib/`, `components/`, result page, `Dockerfile`, `.env.example`.
* **Root:** `README.md`, `docker-compose.yml`, `Makefile`, `.gitignore`, `scripts/check_contract.py`, `scripts/smoke_test.py`, `docs/`.

---

## 8. Install and run

```bash
# prerequisites: Python 3.11+, Node 20.9+, FFmpeg
make setup && make doctor
make backend      # terminal 1
make frontend     # terminal 2          → http://localhost:3000
```

Without `make`, Docker, CLI-only and Windows commands are in the README (§1). Production notes (reverse proxy, CORS, `TRUST_PROXY_HEADERS`, authentication) are in README §8.

---

## 9. Test plan and results

**Automated: 222 tests, all passing, no internet and no API keys required.** Run: `cd backend && python -m pytest`.
(Chromium was used for the one real-browser render test in the build environment: `TEST_BROWSER=chromium python -m pytest`. By default the tests use Firefox, and one test proves that Firefox is the engine that gets launched.)

| Area | Scenario | Test module |
|---|---|---|
| Scanner | Static site extracts name / phone / address / offer / images without a browser | `test_scraper.py` |
| | React shell rendered with the browser; `__NEXT_DATA__` used instead of a browser; missing browser → `partial` | `test_scraper.py` |
| | Cloudflare challenge → `blocked`; merely hosted behind Cloudflare → not blocked; captcha page vs contact-form reCAPTCHA | `test_scraper.py` |
| | robots.txt disallow (whole site and inner pages) | `test_scraper.py` |
| | Invalid URLs; unsupported platforms (social profiles); unreachable hosts / HTTP errors | `test_scraper.py` |
| | SSRF: localhost, metadata IP, private ranges, IPv6, odd numeric hosts, redirect to private IP, redirect loops/chains | `test_scraper.py` |
| | Size limit (5 MB), non-HTML, non-UTF-8 pages | `test_scraper.py` |
| | Phase 1 homepage only → phase 2 adds pages; hard cap returns `timeout`; budget exhaustion; partial crawl; phase-2 modes | `test_scraper.py` |
| | Missing phone / address / logo reported, never invented | `test_scraper.py` |
| Jobs & cache | Both phases with progress; second scan from cache; two requests share one job; blocked / invalid end cleanly; restart closes unfinished jobs | `test_pipeline.py` |
| Prompt | Always exactly one valid prompt per request; every style × platform; shot count follows duration | `test_prompt.py` |
| | No phone / address in the prompt; only known offer / CTA; reference-image sentence only when a hero exists | `test_prompt.py` |
| | Injection text on the website cannot add sections or concepts; very long inputs still fit the cap | `test_prompt.py` |
| | Guard: accepts real facts, rejects invented phone / price / year / claims, no false positives on look-alike words | `test_prompt.py` |
| | AI path: good answer used; bad first answer corrected; invented phone → template; AI outage never fails the ad; markdown-wrapped answer cleaned; key never leaked | `test_prompt.py` |
| Video | Output sizes even and on-ratio; hero crop never stretches; transparency flattened; bad / tiny / SVG images rejected | `test_video.py` |
| | Magic Hour: one prompt + one image sent; duration clamped; failures become safe messages; demo fallback flagged | `test_video.py` |
| | Overlay: text / logo / QR placed, missing pieces skipped, wrap + ellipsis, playable output, FFmpeg failure keeps raw video | `test_video.py` |
| Ad pipeline | Full flow scan → prompt → video; each request makes exactly one ad; manual business without image; user values beat scraped values; deleted facts never used | `test_pipeline.py` |
| | Daily limit; video failure with / without fallback; unexpected crash cannot hang; uploaded photo / logo used; bad explicit hero → warning + another image | `test_pipeline.py` |
| API layer | Rate limit per client; upload validation and all-or-nothing; error mapping (422 / 404 / 409 / 429); polling; video download; Range parsing; `/health`, `/ready`, `/api/config` hides secrets | `test_api.py` |
| Settings | `.env.example` gives demo defaults and contains no secrets; comments never become values; legacy names; validation messages | `test_config.py` |
| Contract | Frontend routes ↔ backend routes, TypeScript ↔ Pydantic fields and enums, multipart field names, env vars documented, no old paths | `test_contract.py`, `scripts/check_contract.py` |

**Manual / end-to-end (do these once on your machine, ~10 minutes):**

1. `make doctor` — all `ok` (FFmpeg, Firefox).
2. `python scripts/smoke_test.py` — scan → one ad → download → seek (demo mode, free). *Ran successfully against a stand-in server in the build environment.*
3. In the browser: scan a static site, a React/Next site and a Cloudflare-protected site; check the three outcomes (`ok`, `ok` with `rendered_with: playwright`, `blocked` + "type details" path).
4. Add `VIDEO_MODEL_API_KEY` and make **one** 5-second ad — check the video really starts from your hero image and the overlay text is readable.
5. Add `AI_PROMPT_API_KEY` and check the prompt panel says `builder: llm`; check no phone / price appears that is not on the site.

**Verified in the build environment:** all 222 backend tests; `pyflakes` clean; frontend type-checks against stub typings and server-renders (react-dom) without errors; contract checker passes; stand-in-server smoke test passes.
**Not verifiable there** (no internet / packages): see §10.

---

## 10. Remaining risks

| Risk | Impact | What to do |
|---|---|---|
| **Leaked keys** in the uploaded `env.example` | Anyone with the zip can use your OpenRouter / Magic Hour credit | Rotate both keys now. |
| **No authentication** | A public deployment lets strangers spend credits | Keep private, or add auth in front; `MAX_ADS_PER_DAY` and rate limits are only a safety net. |
| **Magic Hour call never run live** | The SDK call follows the original script (`image_to_video.generate`, `ltx-2.5`, `480p`) but I could not call the service. Unknown: whether the SDK uploads a local `image_file_path` itself (the original passed a URL). | Run one real ad. If it errors about the file, upload the image to a public/signed URL first (one function in `video/magic_hour.py`). The failure is safe: fallback clip + warning. |
| **FastAPI wiring and `next build` not executed** | `routes.py` / `main.py` are thin and checked by the contract tool, but I could not start uvicorn or build Next in the build environment. | `python -m app` + `npm run build`; `smoke_test.py` is the check. Expect, at worst, a small import or typing fix. |
| **Firefox engine** | Tests exercised Chromium for the real render; Firefox is selected by config (tested with a fake Playwright). | `python -m playwright install firefox` and scan a React site. |
| **DNS rebinding inside the browser** | The headless browser resolves names itself; a hostile page could try to reach an internal host after the first check. | Run the backend in a network that cannot reach internal services. |
| **Single process** | Jobs live in the API process; a restart interrupts running scans/ads (they are closed with a message). SQLite = one machine. | See README "Scaling". |
| **Video length** | Model limit (default 5 s) shorter than the 10–20 s the UI offers. | UI warns; raise `VIDEO_MAX_SECONDS` only if your video model supports it. |
| **Scraper coverage** | Sites with login walls, heavy bot protection or unusual markup yield `blocked` / `partial` / sparse facts. | By design the user can type the facts. |
| **Fonts** | Scripts without an installed font draw empty boxes in the overlay. | Docker image has Noto + DejaVu; otherwise set `OVERLAY_FONT_PATH`. |
| **Legal / content** | Scraping third-party sites and generating ads from their images may need the owner's consent; robots.txt is respected but is not legal clearance. | Use for the user's own business or with permission. |
| **Dependency versions** | `requirements.txt` uses lower bounds with a major-version cap (no lock file could be generated offline). | After your first successful install run `pip freeze > requirements.lock` and `npm install` creates `package-lock.json`; commit both. |

---

## 11. Decisions made without asking (change any of them)

* **SQLite and in-process jobs** instead of Postgres + arq: runs anywhere with no services. Redis is optional. Both are isolated behind two classes.
* **Demo mode** (FFmpeg zoom clip) when no video key is set, so the whole product can be tried and tested for free.
* **Firefox** for rendering (as in the brief); `PLAYWRIGHT_BROWSER` can switch.
* **Phone and address are never sent to the AI or the video model** — they are drawn afterwards as real text. Names / offers / CTA are drawn too, and the prompt tells the model not to render text.
* **The hero image** is chosen: explicit pick → your uploads → best scraped image; small images produce a warning rather than a failure.
* **Daily cap 100 ads, 20 requests/min/client, 72 h retention** as safe starting values.
* **Removed** from the old design: storyboard endpoint, user video uploads, multi-scene prompts (they contradict "one prompt per ad").
* **Dev server binds to 127.0.0.1** by default (`--host 0.0.0.0` to expose); the Docker image binds all interfaces.
