# Website Scraper: Design Document

Takes a website URL, reads the site, and returns the raw material needed to generate an ad: what the business does, good images, logo, and a phone number.

---

## 1. In Plain Words (for non-technical readers)

Think of the scraper as someone who looks at a shop to describe it to an ad designer.

1. They first read the **signboard** from outside (cheap and fast).
2. If the signboard is blank, they **walk inside** and look around (slow and costly).
3. They note: what the shop sells, its logo, a few good photos, a phone number.
4. If the door is locked (site blocks robots), they say so politely instead of breaking in.

Most of the design is about doing step 1 as often as possible and step 2 as rarely as possible. That is where the speed and the savings come from.

---

## 2. Goal and Scope

**Input:** any website URL (even `https://site.com/some/inner/page`).

**Output:**
- Site metadata (name, description, language, business hints)
- Logo and favicon
- Main-page images only (top 5 to 8)
- Phone number (if easy to find; otherwise from the contact page)
- Up to 5 to 10 important pages (for better understanding)
- Status, progress stage, confidence and flags for the frontend

**Not in scope:** logins, captcha solving, bypassing bot protection, scraping private data.

**Scale:** about 100,000 sites per day (average ~1.2/sec, plan for 5 to 10x at peak).

---

## 3. How It Works

```
URL in
 1. Normalize         https://site.com/a/b  ->  https://site.com/
 2. Safety check      block localhost / private networks (see Security)
 3. Cache lookup      seen this domain recently? return it
 4. Fetch (httpx)     fast, cheap
 5. Bot check         protected by Cloudflare etc.?  -> status "blocked", stop
 6. Content check     is the page complete or an empty shell?
 7. Render (browser)  only if the page is an empty shell
 8. Extract           metadata, logo, images, phone
 9. Crawl more pages  5 to 10 pages, in the background
10. Return            always a typed result, never an uncaught error
```

### Two phases (so the user never waits long)

| Phase | What | Time |
|---|---|---|
| 1 | Homepage only: metadata, logo, images, phone | target 5 s, hard cap 12 s |
| 2 | Extra pages (about, services, contact) in background | after phase 1 |

Phase 1 is enough to start the first ad draft. Phase 2 improves it later.

If phase 1 passes 12 s: stop, return `timeout`, and let the frontend show a "we'll notify you" screen or a manual input form.

---

## 4. Decision Rules

### 4.1 Is the page complete? (detecting client-side rendering)

Some sites (React, Vue) send an empty shell and fill it using JavaScript. A plain fetch sees nothing.

Score the httpx result. Score of **3 or more** means use the browser.

| Signal | Points |
|---|---|
| Visible text under 200 characters | +2 |
| Fewer than 3 `<a>` links | +2 |
| `#root`, `#app` or `#__next` is empty | +3 |
| `<noscript>` says "enable JavaScript" | +3 |
| Title is missing or generic | +1 |

**Before launching a browser, try cheaper sources:**
1. Embedded data: `__NEXT_DATA__`, `__NUXT__`, `window.__INITIAL_STATE__`
2. `sitemap.xml` (usually static, lists all pages)
3. JSON-LD (`<script type="application/ld+json">`)

### 4.2 Waiting correctly in the browser

Launching a browser does not mean the page has rendered. Wait for proof:
1. Load with `domcontentloaded`
2. Wait for real content: `nav a, header a, footer a`, or body text over 200 characters
3. Scroll to the bottom and back (footers often load on scroll)
4. Then read the HTML

Block images, fonts and media during this step. We only need their URLs, not the files.

### 4.3 Bot protection detection

Detect only. Do not try to bypass.

| Signal | Meaning |
|---|---|
| Header `server: cloudflare`, `cf-ray`, `cf-mitigated` | Cloudflare |
| Title "Just a moment..." or "Attention Required" | Cloudflare challenge |
| `datadome`, `_px`, `perimeterx` in body or cookies | DataDome / PerimeterX |
| Status 403 / 429 / 503 with challenge text | Generic block |
| 200 OK but empty body plus script-only redirect | Possible challenge |

Result: `status = "blocked"`, with a friendly message. This is a normal outcome, not an error.

### 4.4 Metadata priority (first found wins per field)

1. JSON-LD (Organization, LocalBusiness)
2. Open Graph (`og:title`, `og:description`, `og:image`, `og:site_name`)
3. Twitter card tags
4. `<title>`, `<meta name="description">`, `<meta name="keywords">`
5. `<h1>` and first few `<h2>`
6. `<html lang>`

### 4.5 Header and footer links when the HTML is messy

Try in this order, stop at the first that works:
1. `<header>`, `<nav>`, `<footer>`
2. `role="banner"`, `role="contentinfo"`
3. Common class/id names: `header`, `navbar`, `site-header`, `footer`, `site-footer`
4. First N links on the page = header, last N = footer

Link cleaning: drop `#`, `javascript:`, `mailto:`, `tel:`, empty links. Make URLs absolute. Remove duplicates. Skip links pointing to the homepage itself.

### 4.6 Which 5 to 10 pages to crawl

Order of sources: sitemap, then nav links, then footer links. Same domain only.

| URL contains | Action |
|---|---|
| about, services, products, pricing, contact, team, solutions | high priority |
| privacy, terms, login, cart, account, old blog posts | skip |

### 4.7 Logo, favicon and images

**Favicon:** `apple-touch-icon` (largest), then `<link rel="icon">`, then `/favicon.ico`.

**Logo:** JSON-LD `logo`, then an `<img>` in the header with "logo" in its alt, class or src, then `og:image`.

**Ad images (main page only):**
- Priority: `og:image`, then large hero images, then the rest
- Use the largest `srcset` entry; read lazy-load attributes (`data-src`)
- Drop images under about 400 px, icons, sprites, tracking pixels
- Remove duplicates, keep the top 5 to 8
- Copy the chosen images to our own storage and return our URLs (originals can block hotlinking or expire)

### 4.8 Phone number

Sources in priority order:
1. `tel:` links
2. JSON-LD `telephone`
3. Pattern match in header/footer text (India: `+91` or 10 digits starting 6 to 9)
4. Contact page (phase 2 only)

Normalize with the `phonenumbers` library. Return all candidates, each with its source. Do not pick one silently.

---

## 5. Output Contract (what the frontend receives)

```json
{
  "status": "ok",
  "stage": "ad_ready",
  "message": "Safe-to-show text",
  "site": { "title": "", "description": "", "language": "", "logo": "", "favicon": "" },
  "images": [],
  "phones": [{ "number": "+91...", "source": "tel_link" }],
  "pages": [{ "url": "", "title": "", "description": "", "text_excerpt": "" }],
  "meta": { "rendered_with": "httpx", "bot_protection": null, "took_ms": 3400 },
  "confidence": { "business_info": 0.8, "images": 0.6, "phone": 0.3 },
  "flags": ["no_logo_found", "phone_from_footer", "spa_site"]
}
```

**Status values:** `ok`, `partial`, `blocked`, `unreachable`, `invalid_url`, `timeout`, `internal_error`

**Stage values (progress):** `queued`, `fetching`, `rendering`, `extracting`, `ad_ready`

**Flags** let the frontend add features later (for example "logo missing, ask user to upload") without backend changes.

### If scraping fails

Never show a dead end. Show: "We couldn't read your site. Describe your business in two lines and upload your logo and photos." The ad flow continues.

---

## 6. Architecture and Deployment

| Part | Where | Why |
|---|---|---|
| Fast path (httpx, about 80% of sites) | Serverless (Lambda or Cloud Run) | Light, quick start, pay per use |
| Browser path (about 20% of sites) | Separate small service with a browser pool (container or VM) | Chromium is heavy; cold starts hurt in serverless |
| Cache | Redis, keyed by domain | Repeat sites cost nothing |
| Image storage | Object storage (for example S3) | Stable URLs for the ad AI |
| Background crawl (phase 2) | Queue plus worker | Keeps phase 1 fast |

The fast path calls the browser service only when the content check says so.

**Capacity estimate** (assumes 20% need a browser; verify with real data): ~20,000 browser jobs/day, about 10 to 12 pages at once at peak, about 2.5 GB RAM. One modest server can handle it.

**Suggested module layout:**
```
scraper/
  safety.py     URL normalize + SSRF checks
  fetch.py      httpx client, limits, retries
  detect.py     bot protection + content score
  render.py     browser pool
  extract.py    metadata, links, images, phone
  crawl.py      page scoring + phase 2
  models.py     typed result
  service.py    orchestrator (never raises)
```

---

## 7. Security

This service fetches URLs chosen by strangers. Treat every input and every page as hostile.

### 7.1 SSRF (Server-Side Request Forgery)

**Risk:** a user submits `http://localhost`, an internal address, or the cloud metadata address `169.254.169.254`, and our server fetches it and leaks secrets such as cloud credentials.

**Controls:**
- Allow only `http` and `https`; ports 80 and 443 only
- Resolve the hostname and **block** private, loopback, link-local and reserved ranges (IPv4 and IPv6)
- Check again after every redirect
- Connect to the IP we checked (prevents DNS rebinding tricks)
- On AWS, enforce IMDSv2 and keep the scraper's role minimal

### 7.2 Resource abuse

- Total time cap per job (12 s for phase 1)
- Response size cap (for example 5 MB for HTML), stop reading beyond it
- Allow only `text/html` for pages and `image/*` for images
- Redirect limit (for example 5)
- Max pages per job (10) and max images (8)
- Rate limit per user, per IP and per target domain
- Authenticate the API endpoint

### 7.3 Browser isolation

- Run the browser in its own container or VM with no secrets, no cloud credentials, and restricted network access to internal systems
- Fresh browser context per job; close it afterwards
- Disable downloads and `file://`
- Apply the same SSRF checks to requests made by the page
- Kill the browser on timeout

### 7.4 Untrusted content

- Scraped text is **data, not instructions**. A page can contain text like "ignore previous instructions". When sending it to the ad-generating AI, wrap it as quoted data and never let it change the AI's rules (prompt injection)
- Never execute or render scraped HTML on our own pages without sanitizing
- Images: verify the real type, limit size, re-encode, store with a generated name, and serve with a safe content type

### 7.5 Privacy and legal

- Collect only what the ad needs: public business info and public business phone number
- Do not store personal data beyond the cache period
- Respect `robots.txt`
- Do not bypass protections; report `blocked` instead

### 7.6 Secrets

- No keys in code; use environment variables or a secrets manager
- Least-privilege roles for storage and cache

---

## 8. Error Handling and Logging

- One top-level guard: nothing escapes the orchestrator
- Every outcome maps to a status code from section 5
- Expected outcomes (blocked, timeout, unreachable, invalid URL) are logged at INFO with a short code, no stack trace
- Only real bugs (`internal_error`) are logged as ERROR with a stack trace and a request ID
- Metrics to watch: success rate per status, browser-path share, average time, cache hit rate, block rate

---

## 9. Cost Cutting (and the Easy Way to Think About It)

**Simple rule:** every step is cheaper than the next. Stop as early as possible.

```
Cache (free)  <  Plain fetch  <  Embedded data / sitemap  <  Browser (expensive)
```

| Saving | What to do | Impact |
|---|---|---|
| Cache by domain | Store results 24 to 48 h; also remember "blocked" sites briefly | High |
| Fast path first | Plain fetch for every site; browser only when the score says so | High |
| Cheap sources before browser | Use embedded data, JSON-LD and sitemap | High |
| Phase 2 only when needed | Skip extra pages if the homepage gave enough | High |
| Lean browser | Block images, fonts, media; short timeouts; reuse a small pool | Medium |
| Few images | Copy only the top 5 to 8 to our storage | Medium |
| Right-size servers | Scale serverless to zero; keep the browser service small and scale on queue length | Medium |
| Stop early | Hard time caps and size caps so one bad site cannot burn money | Medium |
| Reject junk | Validate URLs first; do not fetch invalid or duplicate requests | Low |

**For non-technical readers:** the biggest costs are (1) opening a full browser for a page and (2) repeating work we already did. Caching and the "read the signboard first" approach remove most of both.

**Measure before optimizing:** track the percentage of sites needing a browser and the cache hit rate. These two numbers decide the real bill.

---

## 10. Testing Checklist

Keep saved HTML samples for each:
- Normal semantic site
- Messy site with no `<header>` or `<footer>`
- React single-page app (empty shell)
- Cloudflare challenge page
- Slow site (timeout)
- Very large response
- Redirect to a private address (must be blocked)
- Site with no logo, no phone
- Site with several phone numbers

Also test: the 12 s cap, the browser path under load, and that no error escapes the orchestrator.

---

## 11. Build Order

1. URL normalize, safety checks, httpx fetch, bot detection, content score
2. Metadata, logo, favicon, images, phone extraction
3. Browser service with pool
4. Link scoring, phase 2 crawl, cache

---

## 12. Open Decisions

- Cloud: AWS Lambda for the fast path, or Cloud Run?
- Browser service host: container service or VM?
- Cache duration (24 h or 48 h?)
- Phase 2 trigger: automatic, or only after the user continues?
- Image storage and retention period

---

## 13. Glossary

| Term | Meaning |
|---|---|
| httpx | Python tool that downloads a web page like a simple browser, no JavaScript |
| Playwright | Tool that controls a real browser by code, runs the page's JavaScript |
| CSR | Client-side rendering: the page is built in the browser, so the raw download is empty |
| SPA | Single-page app, usually built with React or Vue |
| SSRF | Tricking our server into fetching internal or private addresses |
| Serverless | Code that runs only when called; you pay per use |
| Cache | Saved results reused to avoid repeating work |
| JSON-LD | Structured business info hidden in a page for search engines |
| Sitemap | A site's own list of its pages |
| Prompt injection | Page text that tries to give orders to the AI reading it |