# Studio: typed videos from a website, in seven stages

The existing Adsify scanner and ad flow are untouched. Studio is a second, staged pipeline for videos that need to be
specific to the product: a promo, a hook ad, a pitch, a showcase, an explainer, a testimonial or a launch video.

```
URL ─► 1 capture ─► 2 product notes ─► 3 brand notes ─► 4 assumptions ─► 5 storyboard ─► 6 build ─► 7 check & fix ─► final.mp4
        page.md        claims + sources    colours, fonts      you correct        shots by video     voice, music,    compare with
        10 screenshots                     shapes, tone        these              type               motion graphics  the notes
```

Every stage saves files in the run folder and the next stage reads them. So you can run one stage alone, edit a file by hand,
or start again from any stage. Nothing is hidden in memory.

## Run it

You need what the backend already needs (`pip install -r requirements.txt`, FFmpeg) and the Playwright browser:

```bash
python -m playwright install chromium   # (Firefox, which the scanner uses, also works)
```

An AI writer must be configured in `backend/.env` (`AI_PROMPT_API_KEY`, and for OpenRouter `AI_PROMPT_BASE_URL`, `AI_PROMPT_MODEL`).
Voice uses `edge-tts` (no key). Run everything from the `backend` folder.

```bash
# all seven stages
python -m app.studio run --url https://backseatnetwork.com --type promo --length 20 --platform 16:9

# stop after the assumptions so you can correct them, then continue
python -m app.studio run --url https://backseatnetwork.com --type hook_ad --length 20 --review
python -m app.studio run --run data/studio/backseatnetwork-com-hook_ad --from storyboard
```

Input: `--url`, `--type` (`promo | hook_ad | pitch | showcase | explainer | testimonial | launch`), `--length` in seconds,
`--platform` (`16:9 | 9:16 | 1:1`). The run folder defaults to `backend/data/studio/<site>-<type>`; use `--run` to choose it.
Add your own sourced facts with `--claim "text"` (repeatable), for example a real customer quote or a price.

## The stages, one at a time

Each command needs the files of the stages before it. `--run` is the run folder.

| # | Command | Reads | Writes |
|---|---|---|---|
| 1 | `python -m app.studio capture --url … --type … --length … --platform … --run F` | the website | `01_capture/page.md`, `01_capture/screenshots/NN_kind.png`, `01_capture/screenshots.md`, `01_capture/capture.json`, `request.json` |
| 2 | `python -m app.studio notes --run F` | capture | `02_product_notes.md` / `.json` (and `screenshots.md` is filled in with the claims each screenshot supports) |
| 3 | `python -m app.studio brand --run F` | capture | `03_brand_notes.md` / `.json` |
| 4 | `python -m app.studio assumptions --run F` | notes, brand | `04_assumptions.md` / `.json` (printed, so you can correct them) |
| 5 | `python -m app.studio storyboard --run F` | notes, brand, assumptions | `05_storyboard.md` / `.json` |
| 6 | `python -m app.studio build --run F` | storyboard, brand, assumptions | `06_build/…`, `final.mp4` |
| 7 | `python -m app.studio check --run F [--fix-rounds 2]` | everything | `07_check/report.md` / `.json`, frames, and a corrected `final.mp4` |

### 1. Capture
Headless Chromium opens the page, closes a cookie banner, scrolls once so lazy images load, hides floating chat widgets, and saves:
the page text as markdown (`page.md`, one block per line, so "page.md line 9" means the ninth physical line); about ten screenshots
of the hero, features, pricing, proof, how-it-works and footer sections; and the real styles it measured. `screenshots.md` has one line
per screenshot: what it shows, which lines of `page.md` it covers, and (after stage 2) which claims it supports.

### 2. Product notes
What it is, who it is for, and a numbered list of claims. **Every claim cites its source** (`page.md line 9`, `page.md lines 10-12`,
`screenshot 05`) and quotes the words that prove it. The code verifies that: the line must exist, the quoted words must be on it (a fact
split over a few lines is re-cited with the exact lines), and every number in the claim must be in the quoted words. A claim that fails
is listed under "Left out" and can never be used in the video.

### 3. Brand notes
Hex colours (primary, accent, background, text, with where each was seen), fonts (the names the site really uses, not the hashed
Next.js names), corner radius and shadow habits, photo style (measured from the screenshots, then described) and the tone of the copy.

### 4. Assumptions
The AI fills in audience, **one** key message, tone, voice, music, the call to action (copied from a real button on the page),
must-include (each citing claim ids) and must-avoid. They are printed and saved as `04_assumptions.json`. **Edit that file to correct
them**; the storyboard uses exactly what is in it (a typo in a voice name or a claim id stops with a clear message).

### 5. Storyboard
The structure comes from this table, in code (not from the AI), and the length of each shot too (in half seconds, at least 1.8 s,
adding up to `--length`):

| video type | shots |
|---|---|
| promo | Offer hook → what you get → proof → price/deadline → CTA |
| hook_ad | Relatable pain → setup → turn (punchline) → product → proof → price → CTA |
| pitch | Problem → why now → solution → how it works → traction/proof → ask → CTA |
| showcase | Result first → feature 1 → feature 2 → feature 3 (real screenshots, slow zoom) → CTA |
| explainer | Question → simple analogy → 3 steps → outcome → CTA |
| testimonial | Customer problem → quote → result with numbers → CTA |
| launch | Teaser → reveal → key feature → availability/price → CTA |

The AI writes, for each shot: the voice-over line, the visual (a **real screenshot** or a **built graphic**: `title`, `big_number`,
`steps`, `stats`, `price`, `quote`, `compare`, `cta`), an optional caption and the transition (`cut | fade | slide | zoom`). The rules are
enforced in code and a failing answer is sent back with its problems (up to five tries): one idea and one CTA (only the last shot);
the voice fits the shot (the Indian-English voices speak about 2 words a second); **every figure, price and name must be in the claims the
shot cites** and keep their currency symbol; everything said must be backed by those claims (no comparisons with other companies, no
"best" or "traditional" unless a claim says so); a showcase shows real screenshots. A testimonial without a sourced quote stops with a
message (add one with `--claim`).

### 6. Build
Voice (`edge-tts`, the voice from your assumptions) and music (generated by FFmpeg) are made from the assumptions; each voice line is
placed exactly where its shot starts. The motion graphics are HTML/CSS scenes in the brand colours and fonts (`06_build/scenes/*.html`,
open one in a browser to see it); real screenshots play as footage with a slow pan and zoom. A headless browser renders every frame and
FFmpeg joins the shots with the storyboard's transitions. Text that does not fit its box is measured while rendering and reported.

### 7. Check and fix
Looks at the render and compares it with the notes: every figure, price and claim against the claims the shot cites; a frame from the middle
of each shot (not blank, not flat, not a repeat); text fits the frame; every voice line fits its shot without being cut or sped up
more than 1.22×; length and sound level. A shot that fails is **rewritten from the sourced claims only**, only that shot is rendered again,
and the checks run again (up to `--fix-rounds`, default 2). If the AI writer is unavailable the shot falls back to a plain line taken from
its own claim, so the cut is always valid. The result is in `07_check/report.md`.

## Files of a run

```
request.json                     the input of the run
01_capture/page.md               the page as numbered lines
01_capture/screenshots/          about ten screenshots
01_capture/screenshots.md        one line per screenshot
02_product_notes.md / .json      claims with sources
03_brand_notes.md / .json        colours, fonts, shapes, photo style, tone
04_assumptions.md / .json        the choices you can correct
05_storyboard.md / .json         the shots
06_build/                        scenes, per-shot videos, build.json
07_check/report.md               what was checked and fixed, frames
final.mp4                        the video
```

## Good to know

* **Cost and limits.** Stages 2 to 5 and every fix each make a few AI calls (about 6 to 10 for a whole run). On OpenRouter's free tier you get
  50 requests a day (1,000 after adding 10 credits). When the daily limit is reached the stage stops with a clear message; run it again after the reset.
* **Models.** Free "thinking" models can spend their whole answer budget on hidden reasoning. Studio turns reasoning off and tries the fast direct
  models `nvidia/nemotron-3.5-lightning:free` and `cohere/north-mini-code:free` first, then your configured model. Use `--model` (or `STUDIO_MODEL`) to try another first.
* **Fonts.** Brand fonts are fetched from Google Fonts while rendering; without a network the scenes fall back to a system font.
* **Screenshots are real.** They are taken from the live page, so the video never shows a picture of the product that is not the product.
* **Tests.** `python -m pytest tests/test_studio.py` (uses a fake AI writer; it renders real scenes in Chromium and runs FFmpeg).
