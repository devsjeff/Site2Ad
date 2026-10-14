# Website Scraper: Design Document

Oct 12, 2026

## 1. Overview

The scraper takes a website URL and returns the raw material for an ad: what the business does, good images, logo, and phone number.

**In plain words.** Think of someone describing a shop to an ad designer. They read the **signboard** from outside first (cheap, fast). Only if it is blank do they **walk inside** (slow, costly). They note what the shop sells, its logo, a few photos, a phone number. If the door is locked (site blocks robots), they say so politely instead of breaking in. The design is about doing step one as often, and step two as rarely, as possible.

**Input:** any URL, including inner pages (`https://site.com/some/inner/page`).

**Output:**

- Site metadata: name, description, language, business hints, and a cleaned homepage text excerpt (2,000 to 3,000 characters, scripts/nav/footer removed) for the ad AI
- Logo and favicon
- Main-page images only (top 8)
- Phone numbers (from homepage; contact page in phase 2), plus WhatsApp, email and social links
- Up to 8 important pages
- Final URL after redirects, status, progress stage and flags

**Not in scope:** logins, captcha solving, bypassing bot protection, private data.

**Scale:** about 100,000 sites/day (average ~1.2/sec; plan for 5 to 10x at peak).

## 2. How it works

Every request runs the same ten steps and always ends in a typed result, never an uncaught error.

1. **Normalize:** `https://site.com/a/b` → `https://site.com/`. Exception: known platforms keep their path (see 3.9).
2. **Safety check:** block localhost and private networks (section 6); check `robots.txt` (cached with the result).
3. **Cache lookup:** key = host, or host + path for multi-tenant hosts. A Redis lock per URL means two identical requests trigger one scrape. A "refresh" option skips the cache.
4. **Fetch (httpx):** fast and cheap. Try HTTPS, then retry once over HTTP for broken SSL certificates (flag `insecure_ssl`). Detect charset properly (non-UTF-8, Hindi pages).
5. **Bot check:** challenge page? → status `blocked`, stop.
6. **Content check:** complete page or empty shell?
7. **Render (browser):** only for an empty shell; run the bot check again afterwards.
8. **Extract:** metadata, text excerpt, logo, images, phones, links.
9. **Crawl more pages:** up to 8, in the background.
10. **Return:** typed result with final URL after redirects.

**Two phases, so the user never waits long:**

| Phase | What | Time |
| --- | --- | --- |
| 1 | Homepage only: metadata, text, logo, images, phone | target 5 s, hard cap 12 s |
| 2 | Extra pages (about, services, contact) in background | after phase 1; automatic only when phase 1 lacks a phone or description |

Phase 1 is enough for the first ad draft; phase 2 improves it. Past 12 s, phase 1 stops with `timeout` and the frontend shows a "we'll notify you" screen or the manual form. One deadline object is passed down all steps, so the cap is enforced in one place.

**Job API:** `POST /scrape` returns a `job_id`; `GET /scrape/{job_id}` returns the current result, and the frontend polls it. Job state lives in Redis.

## 3. Decision rules

All thresholds, selectors and keyword lists below live in one config file, so tuning never needs a code change.

### 3.1 Is the page complete? (client-side rendering)

React/Vue sites send an empty shell filled by JavaScript, so a plain fetch sees nothing. Score the httpx result; **3 or more** means use the browser.

| Signal | Points |
| --- | --- |
| Visible text under 200 characters | +2 |
| Fewer than 3 `<a>` links | +2 |
| `#root`, `#app` or `#__next` empty | +3 |
| `<noscript>` says "enable JavaScript" | +3 |
| Title missing or generic | +1 |

Before the browser, try cheaper sources: embedded data (`__NEXT_DATA__`, `__NUXT__`, `window.__INITIAL_STATE__`), `sitemap.xml`, JSON-LD.

### 3.2 Waiting correctly in the browser

Load with `domcontentloaded`; wait for `nav a, header a, footer a` or body text over 200 characters; scroll to the bottom and back (footers load on scroll); then read the HTML. Block images, fonts and media; we need only their URLs. Recycle the browser every ~100 jobs (Chromium leaks memory).

### 3.3 Bot protection (detect only, never bypass)

`server: cloudflare` and `cf-ray` alone mean "uses Cloudflare", **not** blocked; most such sites are normal. Mark `blocked` only on a challenge:

| Signal | Meaning |
| --- | --- |
| `cf-mitigated: challenge`, title "Just a moment..." or "Attention Required" | Cloudflare challenge |
| `datadome`, `_px`, `perimeterx` in body or cookies | DataDome / PerimeterX |
| 403 / 429 / 503 with challenge text | Generic block |
| 200 OK, empty body plus script-only redirect | Possible challenge |

`blocked` comes with a friendly message; it is a normal outcome, not an error.

### 3.4 Metadata priority (first found wins per field)

1. JSON-LD (Organization, LocalBusiness)
2. Open Graph (`og:title`, `og:description`, `og:image`, `og:site_name`)
3. Twitter card tags
4. `<title>`, `<meta name="description">`, `<meta name="keywords">`
5. `<h1>` and first few `<h2>`
6. `<html lang>`

### 3.5 Header and footer links in messy HTML

Stop at the first that works: `<header>`/`<nav>`/`<footer>` → `role="banner"`/`role="contentinfo"` → class/id `header`, `navbar`, `site-header`, `footer`, `site-footer` → first N links = header, last N = footer.

Cleaning: drop `#`, `javascript:`, empty links; make URLs absolute; dedupe; skip homepage links. Before dropping, collect `mailto:` (email), `tel:` and WhatsApp links, and social profiles (Instagram, Facebook, etc.) in the same pass.

### 3.6 Which pages to crawl (max 8)

Sources in order: sitemap, nav links, footer links. Same domain only.

| URL contains | Action |
| --- | --- |
| about, services, products, pricing, contact, team, solutions | high priority |
| privacy, terms, login, cart, account, old blog posts | skip |

### 3.7 Logo, favicon and images

**Favicon:** `apple-touch-icon` (largest) → `<link rel="icon">` → `/favicon.ico`.

**Logo:** JSON-LD `logo` → header `<img>` with "logo" in alt, class or src → `og:image`. SVG logos are converted to PNG or sanitized; never serve raw SVG (it can carry scripts).

**Ad images (main page only):**

- Priority: `og:image`, large hero images (including CSS `style="background-image:url(...)"`), then the rest
- Largest `srcset` entry; read lazy-load attributes (`data-src`)
- Drop images under ~400 px, icons, sprites, tracking pixels
- Dedupe, keep the top 8
- Copy to our storage and return our URLs (originals may block hotlinking or expire)

### 3.8 Phone number

Sources in priority order:

1. `tel:` links and WhatsApp links (`wa.me/…`, `api.whatsapp.com/send?phone=`), often the only number on Indian sites
2. JSON-LD `telephone`
3. Header/footer text via `phonenumbers.PhoneNumberMatcher(text, "IN")`, not a custom regex. A regex for 10 digits starting 6 to 9 misses landlines (`0xx`) and `1800` toll-free, and matches order IDs and GST numbers.
4. Contact page (phase 2 only)

Normalize with `phonenumbers`. Return all candidates with their source; never pick one silently.

### 3.9 Social and platform links

Many small businesses submit Instagram, Facebook, Linktree, wa.me, IndiaMART, JustDial, Google Business, `*.wixsite.com/name` or `sites.google.com/view/name` links. One small known-platforms list handles them:

- Multi-tenant hosts keep their full path, and cache by host + path
- Unsupported platforms return status `unsupported_platform`, so the frontend shows the manual form
- Parked, "for sale" and "under construction" pages get the flag `parked_domain`

## 4. Output contract

The frontend always receives this shape, versioned by `schema_version`.

```json
{
  "schema_version": 1,
  "status": "ok",
  "stage": "ad_ready",
  "message": "Safe-to-show text",
  "final_url": "https://site.com/",
  "site": { "title": "", "description": "", "language": "", "logo": "", "favicon": "", "text_excerpt": "" },
  "images": [],
  "phones": [{ "number": "+91...", "source": "tel_link" }],
  "contacts": { "whatsapp": [], "emails": [], "social": [] },
  "pages": [{ "url": "", "title": "", "description": "", "text_excerpt": "" }],
  "meta": { "rendered_with": "httpx", "bot_protection": null, "took_ms": 3400 },
  "flags": ["no_logo_found", "phone_from_footer", "spa_site", "insecure_ssl", "parked_domain"]
}
```

**Status:** `ok`, `partial`, `blocked`, `unreachable`, `invalid_url`, `unsupported_platform`, `timeout`, `internal_error`.

**Stage (progress):** `queued`, `fetching`, `rendering`, `extracting`, `ad_ready`.

**Flags** let the frontend add features later (for example "logo missing, ask user to upload") without backend changes. The earlier `confidence` scores (business_info, images, phone) are dropped: they had no defined formula, and flags carry the same information. Add them back only with a written rule for each.

**If scraping fails, never show a dead end.** Show: "We couldn't read your site. Describe your business in two lines and upload your logo and photos." The ad flow continues.

## 5. Architecture and deployment

Recommended: run both paths on Cloud Run from one container image, so there is one platform to maintain and no Lambda-vs-VM choice.

| Part | Where | Why |
| --- | --- | --- |
| Fast path (httpx, ~80% of sites) | Cloud Run (or Lambda) | Light, quick start, pay per use, scales to zero |
| Browser path (~20% of sites) | Separate small Cloud Run service with a browser pool (or container/VM) | Chromium is heavy; cold starts hurt in serverless |
| Cache and job state | Redis | Repeat sites cost nothing; holds job status and per-URL locks |
| Image storage | Object storage (e.g. S3) | Stable URLs for the ad AI |
| Phase 2 crawl | Queue plus worker | Keeps phase 1 fast |

The fast path calls the browser service only when the content check says so.

**Capacity** (assumes 20% need a browser; verify with real data): ~20,000 browser jobs/day, 10 to 12 pages at once at peak, ~2.5 GB RAM. One modest server handles it.

**Module layout:**

```
scraper/
  config.py     all thresholds, caps, selectors, keyword and platform lists
  safety.py     URL normalize + SSRF checks; the ONLY way to make an outgoing request
  fetch.py      httpx client, limits, retries (1 retry on network errors, none on 4xx)
  detect.py     bot protection + content score
  render.py     browser pool
  extract.py    metadata, text, links, images, phones, contacts
  crawl.py      page scoring + phase 2
  models.py     typed result
  service.py    orchestrator (never raises)
```

## 6. Security

The service fetches URLs chosen by strangers, so every input and every page is treated as hostile.

### 6.1 SSRF (server-side request forgery)

**Risk:** a user submits `http://localhost`, an internal address, or the cloud metadata address `169.254.169.254`, and our server leaks secrets such as cloud credentials.

**Controls:**

- Only `http`/`https`, ports 80 and 443
- Resolve the hostname; block private, loopback, link-local and reserved ranges (IPv4 and IPv6)
- Re-check after every redirect
- Every outgoing request (pages, images, sitemap, `robots.txt`, phase 2) goes through `safety.py`; no direct `httpx` calls elsewhere
- **Network-level isolation:** scraper and browser run in a network with no route to internal ranges or `169.254.169.254`. This replaces pinning resolved IPs in code (fiddly in httpx and Playwright) and also stops DNS rebinding. The code check stays for clear error messages.
- On AWS, enforce IMDSv2 and keep the scraper's role minimal

### 6.2 Resource abuse

- Time cap per job (12 s for phase 1), one deadline object
- Response size cap (e.g. 5 MB HTML); stop reading beyond it
- Only `text/html` for pages, `image/*` for images
- Redirect limit (e.g. 5); max 8 pages and 8 images per job
- Rate limit per user, per IP and per target domain
- Authenticate the API endpoint

### 6.3 Browser isolation

- Own container/VM: no secrets, no cloud credentials, no network access to internal systems
- Fresh browser context per job, closed afterwards; recycle the browser every ~100 jobs
- Downloads and `file://` disabled
- Same SSRF rules for requests the page makes (enforced by the network isolation)
- Kill the browser on timeout

### 6.4 Untrusted content

- Scraped text is **data, not instructions**. Text like "ignore previous instructions" is wrapped as quoted data for the ad AI and never changes its rules (prompt injection)
- Never render scraped HTML on our pages without sanitizing
- Images: verify real type, limit size, re-encode, store under a generated name, serve with a safe content type; SVG converted to PNG or sanitized

### 6.5 Privacy and legal

- Collect only what the ad needs: public business info and public business phone
- No personal data stored beyond the cache period
- Respect `robots.txt`; use an honest user-agent, e.g. `YourBrandBot/1.0 (+https://yoursite/bot)`
- Never bypass protections; report `blocked`
- User ticks "I own or have rights to this site" before their images are used in ads

### 6.6 Secrets

- No keys in code; environment variables or a secrets manager
- Least-privilege roles for storage and cache

## 7. Errors, logging and cost

### 7.1 Error handling and logging

- One top-level guard: nothing escapes the orchestrator; every outcome maps to a status from section 4
- Expected outcomes (blocked, timeout, unreachable, invalid URL, unsupported platform) → INFO with a short code, no stack trace
- Only real bugs (`internal_error`) → ERROR with stack trace and request ID
- Metrics: success rate per status, browser-path share, average time, cache hit rate, block rate

### 7.2 Cost cutting

**Rule:** each step is cheaper than the next, so stop as early as possible.

```
Cache (free)  <  Plain fetch  <  Embedded data / sitemap  <  Browser (expensive)
```

| Saving | What to do | Impact |
| --- | --- | --- |
| Cache | Store results 24 h (plus refresh button); remember "blocked" sites briefly | High |
| Fast path first | Plain fetch for every site; browser only when the score says so | High |
| Cheap sources before browser | Embedded data, JSON-LD, sitemap | High |
| Phase 2 only when needed | Skip extra pages if the homepage gave enough | High |
| Lean browser | Block images, fonts, media; short timeouts; small reused pool | Medium |
| Few images | Copy only the top 8 to storage | Medium |
| Right-size servers | Scale to zero; keep browser service small, scale on queue length | Medium |
| Stop early | Hard time and size caps so one bad site can't burn money | Medium |
| Reject junk | Validate URLs first; dedupe requests via the per-URL lock | Low |

**In plain words:** the biggest costs are opening a full browser and repeating work already done. Caching and "read the signboard first" remove most of both.

**Measure before optimizing:** browser-path share and cache hit rate decide the real bill.

## 8. Testing, build order and decisions

### 8.1 Testing checklist

Saved HTML samples for each:

- Normal semantic site; messy site with no `<header>`/`<footer>`
- React single-page app (empty shell)
- Cloudflare challenge page, and a normal site behind Cloudflare (must **not** be `blocked`)
- Slow site (timeout); very large response
- Redirect to a private address (must be blocked)
- No logo and no phone; several phone numbers; WhatsApp-only number
- Broken SSL certificate; Hindi or non-UTF-8 page
- Instagram link; Wix and Shopify sites; parked domain

Also test: the 12 s cap, the browser path under load, and that no error escapes the orchestrator.

### 8.2 Build order

1. URL normalize, platform list, safety checks, httpx fetch, bot detection, content score
2. Metadata, text excerpt, logo, favicon, images, phones, contacts
3. Browser service with pool
4. Job API, link scoring, phase 2 crawl, cache

### 8.3 Decisions

| Question | Recommendation |
| --- | --- |
| Cloud for the fast path | Cloud Run |
| Browser service host | Cloud Run, same image |
| Cache duration | 24 h plus refresh button |
| Phase 2 trigger | Automatic only when phase 1 lacks a phone or description |
| Image storage and retention period | Open |

### 8.4 Glossary

| Term | Meaning |
| --- | --- |
| httpx | Python tool that downloads a page like a simple browser, no JavaScript |
| Playwright | Controls a real browser by code; runs the page's JavaScript |
| CSR | Client-side rendering: page built in the browser, so the raw download is empty |
| SPA | Single-page app, usually React or Vue |
| SSRF | Tricking our server into fetching internal or private addresses |
| Serverless | Code that runs only when called; pay per use |
| Cache | Saved results reused to avoid repeating work |
| JSON-LD | Structured business info in a page for search engines |
| Sitemap | A site's own list of its pages |
| Prompt injection | Page text that tries to give orders to the AI reading it |
