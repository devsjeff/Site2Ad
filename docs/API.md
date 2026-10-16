# Site2Ad (Adsify) API — integration guide

This folder contains a machine-readable description of the backend API for developers in other teams and companies:

| File | What it is |
|---|---|
| [`openapi.json`](openapi.json) | OpenAPI **3.1** specification of every endpoint, request, response and error |
| [`postman_collection.json`](postman_collection.json) | Postman **v2.1** collection with one ready-to-send request per endpoint |

Both files are generated from the running FastAPI code (`backend/app/api/routes.py` and `backend/app/schemas.py`) by
`scripts/generate_openapi.py`, so they describe what the server really does. They contain no keys or secrets.

---

## 1. Import the specification

**Postman**
1. *Import* → choose `docs/postman_collection.json` (or `docs/openapi.json`; Postman can generate a collection from it).
2. Open the collection → *Variables* → set `baseUrl` (default `http://localhost:8000`).
3. After a call that returns an id, copy it into the `job_id`, `ad_id` or `asset_id` variable for the follow-up requests.

**Insomnia / Bruno / Hoppscotch** — import `docs/openapi.json` as an OpenAPI 3 document.

**Swagger UI / Redoc** — open `docs/openapi.json` in [editor.swagger.io](https://editor.swagger.io) or any Redoc
viewer. A running development server also serves it live at `GET /openapi.json` with an interactive UI at `/docs`
(both are switched off when `APP_ENV=production`).

**Generate a client SDK** (example with the official OpenAPI Generator):

```bash
npx @openapitools/openapi-generator-cli generate -i docs/openapi.json -g typescript-fetch -o ./site2ad-client
npx @openapitools/openapi-generator-cli generate -i docs/openapi.json -g python -o ./site2ad-client-py
```

---

## 2. How the API works

**Base URL.** All endpoints live under `/api` except the probes `/health` and `/ready`. Use the address your
deployment gives you (for example `https://api.example.com`); `http://localhost:8000` locally.

**Authentication.** The API has **no login and no API keys**. Anyone who can reach it can use it. Before exposing
it outside your network, put it behind your own gateway (API gateway, reverse proxy with auth, VPN or IP allow-list).
Expensive calls are limited per client (`RATE_LIMIT_PER_MINUTE`, answers `429 rate_limited`) and per day
(`MAX_ADS_PER_DAY`, answers `429 daily_limit`).

**Asynchronous jobs.** Scans and ads take seconds to minutes, so they run in the background:

```
POST /api/scrape {url}            -> 202 {job_id, ...}   then poll GET /api/jobs/{job_id}   until is_final = true
POST /api/generate-ad {...}       -> 202 {ad_id, ...}    then poll GET /api/ads/{ad_id}     until status is
                                                          completed | completed_with_fallback | failed
GET  /api/ads/{ad_id}/video                               -> the MP4 (supports HTTP Range; ?download=true for a file)
POST /api/ads/{ad_id}/cancel                              -> stops an ad that is still running
```

Poll every 1–5 seconds. `completed_with_fallback` means the AI video provider failed and a simple non-AI clip was
used; the reason is in `provider_error`. Never present such a video as AI footage.

**Uploads.** `POST /api/uploads` is `multipart/form-data` with `kind` = `logo` | `photo` | `video` and one or more
`files`. It returns asset ids to use in `creative.media_asset_ids` (manual ads) or `logo_asset_id`.

**Choosing how an ad is made.** The `creative` object of `POST /api/generate-ad` selects the mode; the server rejects
contradictory combinations with `422`:

| `creation_mode` / `creative_mode` | Needs | Calls the AI video provider |
|---|---|---|
| `manual` | `media_asset_ids` from `/api/uploads` | no |
| `auto` / `website` | a scan (`job_id`) | no |
| `auto` / `ai` | a scan or `business.name` | yes |
| `auto` / `mixed` | a scan | yes |

Ready-made request bodies for each mode are in the spec (`POST /api/generate-ad` → examples) and in the Postman request.

**Limits and options.** Never hard-code platforms, styles, lengths or upload limits: read them from
`GET /api/config` (it also says whether AI video is available on this deployment).

**Errors.** Every error has the same body:

```json
{ "detail": "plain-language message you can show to users", "code": "machine_readable_code" }
```

Branch on `code`, not on `detail`. The codes each endpoint can return are listed in the spec under its responses.

**CORS.** Browsers may call the API only from origins listed in the server's `CORS_ORIGINS` setting. Server-to-server
calls are not affected.

---

## 3. Minimal example (curl)

```bash
BASE=http://localhost:8000
curl -s $BASE/api/config
JOB=$(curl -s -X POST $BASE/api/scrape -H 'Content-Type: application/json' -d '{"url":"https://www.example.com"}' | jq -r .job_id)
curl -s $BASE/api/jobs/$JOB | jq '{status, stage, is_final}'
AD=$(curl -s -X POST $BASE/api/generate-ad -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB\",\"creative\":{\"creation_mode\":\"auto\",\"creative_mode\":\"website\",\"use_website_images\":true},\"wait_for_prompt\":false}" | jq -r .ad_id)
curl -s $BASE/api/ads/$AD | jq '{status, stage, progress}'
curl -s -o ad.mp4 "$BASE/api/ads/$AD/video?download=true"
```

---

## 4. Keeping the files up to date (for maintainers)

```bash
python scripts/generate_openapi.py           # regenerate docs/openapi.json and docs/postman_collection.json
python scripts/generate_openapi.py --check   # fails when the committed files no longer match the code
```

The backend test suite runs the `--check`, so a route or schema change without regenerating the docs fails CI.
