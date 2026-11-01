"""Stage 1, CAPTURE: open the page in a headless browser, save its text as markdown, take about 10 screenshots, and note the
real styles (colours, fonts, shapes). Every screenshot gets a line: what it shows, and the lines of page.md it covers.

Files: page.md, screenshots/NN_kind.png, screenshots.md, capture.json
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Run, StageError

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1440, "height": 900}
MAX_SHOTS = 10
MAX_SLICE = 1000  # px: a tall section is shown in readable slices
MAX_BLOCKS = 600

COOKIE_WORDS = re.compile(r"^(accept( all)?( cookies)?|i agree|agree|allow all|got it|ok(ay)?|continue|that'?s ok)$", re.I)

BLOCKS_JS = r"""
() => {
  const BLOCK = new Set(['H1','H2','H3','H4','H5','H6','P','LI','BLOCKQUOTE','FIGCAPTION','BUTTON','A','TD','TH','LABEL','DT','DD','SUMMARY']);
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','CANVAS','IFRAME']);
  const blockOf = (node) => {
    let e = node.parentElement;
    while (e && e !== document.body) {
      if (BLOCK.has(e.tagName)) return e;
      const d = getComputedStyle(e).display;
      if (d === 'block' || d === 'flex' || d === 'grid' || d === 'list-item' || d === 'table-cell') return e;
      e = e.parentElement;
    }
    return e || document.body;
  };
  const shown = (el) => {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const groups = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.nodeValue.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const parent = n.parentElement;
    if (!parent || SKIP.has(parent.tagName.toUpperCase()) || parent.closest('script,style,noscript,template,svg')) continue;
    const el = blockOf(n);
    if (!groups.has(el)) groups.set(el, []);
    groups.get(el).push(text);
  }
  const sy = window.scrollY, sx = window.scrollX;
  const out = [];
  for (const [el, texts] of groups) {
    if (!shown(el)) continue;
    const r = el.getBoundingClientRect();
    const heading = el.closest('h1,h2,h3,h4,h5,h6');
    const link = el.closest('a,button');
    out.push({
      text: texts.join(' ').replace(/\s+/g, ' ').trim(),
      top: Math.round(r.top + sy), left: Math.round(r.left + sx), width: Math.round(r.width), height: Math.round(r.height),
      heading: heading ? parseInt(heading.tagName[1], 10) : 0,
      li: !!el.closest('li'), quote: !!el.closest('blockquote'),
      button: !!(link && (link.tagName === 'BUTTON' || /btn|button|cta/i.test(link.className || '') || link.getAttribute('role') === 'button')),
      region: (el.closest('nav,header,footer,main,aside') || {tagName: ''}).tagName.toLowerCase(),
    });
  }
  out.sort((a, b) => (Math.abs(a.top - b.top) < 8 ? a.left - b.left : a.top - b.top));
  return out;
}
"""

# Chat bubbles, cookie bars and "planning a campaign?" pop-ups float above the page and would end up in every screenshot.
HIDE_FLOATING_JS = r"""
() => {
  let hidden = 0;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    const nearTop = r.top <= 4 && r.width > innerWidth * 0.5;       // the site's own navigation bar stays
    const overlay = r.bottom > innerHeight * 0.45 || (r.top <= 4 && r.width <= innerWidth * 0.5);
    if (!nearTop && overlay && !el.closest('nav,header')) { el.style.setProperty('visibility', 'hidden', 'important'); hidden++; }
  }
  return hidden;
}
"""

BANDS_JS = r"""
() => {
  const total = document.documentElement.scrollHeight;
  let root = document.querySelector('main') || document.body;
  for (let i = 0; i < 4; i++) {
    const kids = [...root.children].filter(k => k.getBoundingClientRect().height > 40 && !/^(SCRIPT|STYLE|NOSCRIPT)$/.test(k.tagName));
    if (kids.length === 1 && kids[0].getBoundingClientRect().height > root.getBoundingClientRect().height * 0.8) root = kids[0]; else break;
  }
  const take = (els) => els.map(e => {
    const r = e.getBoundingClientRect();
    return {top: Math.round(r.top + scrollY), height: Math.round(r.height), tag: e.tagName.toLowerCase(), images: e.querySelectorAll('img,picture,video,canvas,svg').length};
  }).filter(b => b.height >= 180 && b.top < total);
  let bands = take([...root.children]);
  if (bands.length < 4) bands = take([...document.querySelectorAll('section')]);
  const footer = document.querySelector('footer');
  if (footer) { const f = take([footer])[0]; if (f && !bands.some(b => Math.abs(b.top - f.top) < 40)) bands.push({...f, tag: 'footer'}); }
  bands.sort((a, b) => a.top - b.top);
  return {total, bands};
}
"""

STYLES_JS = r"""
() => {
  const rgb = (c) => c;
  const cs = (el) => getComputedStyle(el);
  const pick = (sel) => { const el = document.querySelector(sel); if (!el) return null; const s = cs(el); return {color: s.color, font: s.fontFamily, size: s.fontSize, weight: s.fontWeight, tag: el.tagName.toLowerCase()}; };
  const vars = {};
  try {
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
      for (const rule of rules) {
        if (!rule.style || !/^(:root|html|body)$/.test(rule.selectorText || '')) continue;
        for (const name of rule.style) if (name.startsWith('--')) { const v = rule.style.getPropertyValue(name).trim(); if (/^(#[0-9a-f]{3,8}|rgba?\(|hsla?\()/i.test(v)) vars[name] = v; }
      }
    }
  } catch (e) {}
  const areas = {};
  const vw = innerWidth, vh = innerHeight;
  for (const el of document.querySelectorAll('body *')) {
    const s = cs(el);
    const bg = s.backgroundColor;
    if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 60 || r.height < 30) continue;
    const a = Math.min(r.width, vw) * Math.min(r.height, vh * 1.5);
    areas[bg] = (areas[bg] || 0) + a;
  }
  const buttons = [...document.querySelectorAll('button, a[class*=btn i], a[class*=button i], [role=button]')].slice(0, 12).map(e => {
    const s = cs(e); const r = e.getBoundingClientRect();
    return {text: (e.innerText || '').trim().slice(0, 40), bg: s.backgroundColor, color: s.color, radius: parseFloat(s.borderTopLeftRadius) || 0, font: s.fontFamily, h: Math.round(r.height)};
  }).filter(b => b.text && b.h > 20);
  const cards = [];
  for (const el of document.querySelectorAll('div, section, article, li')) {
    const r = el.getBoundingClientRect(); if (r.width < 160 || r.height < 100 || r.width > vw * 0.8) continue;
    const s = cs(el); const radius = parseFloat(s.borderTopLeftRadius) || 0;
    if (radius > 0 || (s.boxShadow && s.boxShadow !== 'none')) cards.push({radius, shadow: s.boxShadow !== 'none', bg: s.backgroundColor});
    if (cards.length > 60) break;
  }
  const images = [...document.images].filter(i => i.naturalWidth >= 200 && i.getBoundingClientRect().width >= 120).slice(0, 40).map(i => ({
    src: (i.currentSrc || i.src || '').split('?')[0].split('/').slice(-2).join('/'), alt: (i.alt || '').slice(0, 100), w: i.naturalWidth, h: i.naturalHeight}));
  const meta = document.querySelector('meta[name=theme-color]');
  return {
    body: {bg: cs(document.body).backgroundColor, color: cs(document.body).color, font: cs(document.body).fontFamily, size: cs(document.body).fontSize},
    h1: pick('h1'), h2: pick('h2'), p: pick('p'), a: pick('a'),
    vars, areas, buttons, cards, images, themeColor: meta ? meta.content : '',
    description: (document.querySelector('meta[name=description]') || {}).content || '',
  };
}
"""

# (kind, words that point to it, how many separate hits are needed). Pricing needs a real price, not just the word "plan".
SECTION_WORDS = (
    ("pricing", re.compile(r"[₹$€£]\s?\d|\bper (?:cab|month|vehicle|day|seat|user)\b|/\s?(?:month|year|mo)\b|\bpricing\b|\bcost\b|\bprice\b", re.I), 2),
    ("proof", re.compile(r"trusted by|our clients|testimonials?|reviews?|case stud|\bresults?\b|delivered|rated|\d[\d,]*\+|live (?:gps|data)|verified|campaigns? (?:run|delivered)", re.I), 2),
    ("how", re.compile(r"how it works|step ?1|\bsteps\b|\bprocess\b|get started|three steps|simple as", re.I), 1),
    ("features", re.compile(r"features?|what you get|benefits|\bwhy\b|solutions?|capabilit|formats?|included", re.I), 2),
)


def _hex(color: str) -> str:
    """'rgb(34, 51, 255)' or 'rgba(...)' -> '#2233ff'; '' when transparent or unreadable."""
    match = re.match(r"rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)(?:[ ,/]+([\d.]+))?", color or "")
    if not match:
        return color.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", color or "") else ""
    if match.group(4) is not None and float(match.group(4)) < 0.2:
        return ""  # transparent
    return "#{:02x}{:02x}{:02x}".format(*(int(match.group(i)) for i in (1, 2, 3)))


def hexify(styles: dict) -> dict:
    """Replace every CSS colour in the raw style sample with a hex colour (kept as the same structure)."""
    def walk(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str) and key in {"bg", "color"}:
            return _hex(value)  # "" when transparent
        return value

    cleaned = walk(styles)
    cleaned["areas"] = {(_hex(k) or k): round(v) for k, v in styles.get("areas", {}).items() if _hex(k)}
    cleaned["vars"] = {k: (_hex(v) or v) for k, v in styles.get("vars", {}).items()}
    return cleaned


def blocks_to_markdown(blocks: list[dict], title: str, url: str) -> tuple[list[str], list[dict]]:
    """page.md lines, and the blocks with the physical line number each one landed on (1-based, so a citation can be checked)."""
    lines = [f"Title: {title}", f"URL: {url}", ""]
    kept: list[dict] = []
    previous = ""
    for block in blocks:
        text = block["text"][:400]
        if len(text) < 2 or text == previous:
            continue
        previous = text
        if block["heading"]:
            line = f"{'#' * min(6, block['heading'])} {text}"
        elif block["quote"]:
            line = f"> {text}"
        elif block["button"]:
            line = f"[{text}]"
        elif block["li"]:
            line = f"- {text}"
        else:
            line = text
        lines.append(line)
        lines.append("")
        kept.append({**block, "text": text, "line": len(lines) - 1})
        if len(kept) >= MAX_BLOCKS:
            break
    return lines, kept


def classify(text: str, index: int, count: int, tag: str) -> str:
    """What a section is about: hero, pricing, proof, how, features, footer or section."""
    if index == 0:
        return "hero"
    if tag == "footer" or index == count - 1 and len(text) < 600 and re.search(r"©|privacy|terms|copyright|all rights", text, re.I):
        return "footer"
    best, best_hits = "section", 0
    for kind, pattern, needed in SECTION_WORDS:
        hits = len(pattern.findall(text))
        if hits >= needed and hits > best_hits:
            best, best_hits = kind, hits
    return best


def _summary(kind: str, blocks: list[dict]) -> str:
    """One line: what a screenshot shows, from the words that are on it."""
    headings = [b["text"] for b in blocks if b["heading"]][:2]
    buttons = [b["text"] for b in blocks if b["button"]][:2]
    numbers = [m.group(0) for b in blocks for m in re.finditer(r"[₹$€£]\s?\d[\d,.]*(?:\s?[kKmM])?|\d[\d,.]*\s?(?:%|\+|[kK]\b|min\b)", b["text"])][:3]
    parts = [f"the {kind}" if kind != "section" else "a section"]
    if headings:
        parts.append("with the heading " + " / ".join(f'"{h[:70]}"' for h in headings))
    if buttons:
        parts.append("and the button " + " / ".join(f'"{b[:30]}"' for b in buttons))
    if numbers:
        parts.append("showing " + ", ".join(numbers))
    if len(parts) == 1 and blocks:
        parts.append(f'with text such as "{blocks[0]["text"][:70]}"')
    return " ".join(parts)


def pick_clips(bands: list[dict], texts: list[str], total: int) -> list[dict]:
    """About ten regions of the page worth a screenshot: hero, features, pricing, proof, how-it-works, footer, then the richest others."""
    clips: list[dict] = []
    for index, band in enumerate(bands):
        kind = classify(texts[index], index, len(bands), band["tag"])
        for part in range(0, max(1, min(2, -(-band["height"] // MAX_SLICE)))):
            top = band["top"] + part * MAX_SLICE
            height = min(MAX_SLICE if band["height"] > MAX_SLICE else band["height"], total - top)
            if height >= 180:
                clips.append({"kind": kind, "top": top, "height": height, "weight": len(texts[index]) + 400 * band["images"], "part": part})
    if not clips:  # a page without usable structure: read it in screen-sized slices
        clips = [{"kind": "hero" if i == 0 else "section", "top": i * 900, "height": min(900, total - i * 900), "weight": 1, "part": 0} for i in range(min(MAX_SHOTS, max(1, total // 900)))]
    chosen: list[dict] = []

    def take(clip: dict) -> None:
        if clip not in chosen and len(chosen) < MAX_SHOTS:
            chosen.append(clip)

    for wanted in ("hero", "pricing", "proof", "how", "footer"):
        match = next((c for c in clips if c["kind"] == wanted), None)
        if match:
            take(match)
    for clip in [c for c in clips if c["kind"] == "features"][:2]:
        take(clip)
    for clip in sorted([c for c in clips if c not in chosen], key=lambda c: -c["weight"]):
        take(clip)
    chosen.sort(key=lambda c: c["top"])
    return chosen


def launch_browser(playwright):
    """Chromium when it is installed, else Firefox (the browser the scanner already uses on servers)."""
    try:
        return playwright.chromium.launch()
    except Exception as exc:  # the browser is not installed: try the other one
        logger.info("Chromium is not available (%s); using Firefox", str(exc).splitlines()[0] if str(exc) else exc)
        try:
            return playwright.firefox.launch()
        except Exception as second:
            raise StageError("No browser is installed for Playwright. Run: python -m playwright install chromium") from second


def dismiss_banners(page) -> None:
    """Close a cookie banner if there is one (a screenshot with a banner over it is useless)."""
    try:
        for button in page.query_selector_all("button, a[role=button], [class*=cookie i] a, [id*=cookie i] a"):
            label = (button.inner_text() or "").strip()
            if COOKIE_WORDS.match(label) and button.is_visible():
                button.click(timeout=1500)
                page.wait_for_timeout(500)
                return
    except Exception as exc:  # never let a banner stop a capture
        logger.info("cookie banner not closed: %s", exc)


def capture(run: Run, url: str) -> dict:
    """Run stage 1. Returns the capture record that is also saved as capture.json."""
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as exc:
        raise StageError("Playwright is not installed. Run: pip install playwright && python -m playwright install chromium") from exc
    for old in run.shots_dir.glob("*.png"):
        old.unlink()
    try:
        with sync_playwright() as p:
            browser = launch_browser(p)
            try:
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
                page.goto(url, wait_until="load", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightError:
                    pass
                dismiss_banners(page)
                height = page.evaluate("document.documentElement.scrollHeight")
                for y in range(0, min(height, 30000), 700):  # scroll through once so lazy images and reveal animations load
                    page.evaluate("y => window.scrollTo(0, y)", y)
                    page.wait_for_timeout(120)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(800)
                title = page.title() or url
                page.evaluate(HIDE_FLOATING_JS)
                blocks_raw = page.evaluate(BLOCKS_JS)
                layout = page.evaluate(BANDS_JS)
                styles = hexify(page.evaluate(STYLES_JS))
                lines, blocks = blocks_to_markdown(blocks_raw, title, url)
                run.page_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

                bands = layout["bands"]
                band_texts = [" ".join(b["text"] for b in blocks if band["top"] - 2 <= b["top"] < band["top"] + band["height"]) for band in bands]
                clips = pick_clips(bands, band_texts, layout["total"])
                shots = []
                for number, clip in enumerate(clips, start=1):
                    name = f"{number:02d}_{clip['kind']}.png"
                    page.screenshot(path=str(run.shots_dir / name), full_page=True,
                                    clip={"x": 0, "y": clip["top"], "width": VIEWPORT["width"], "height": clip["height"]})
                    inside = [b for b in blocks if clip["top"] - 2 <= b["top"] < clip["top"] + clip["height"] and b["region"] != "nav"]
                    shots.append({
                        "id": f"{number:02d}", "file": name, "kind": clip["kind"], "clip": {k: clip[k] for k in ("top", "height")},
                        "lines": [min(b["line"] for b in inside), max(b["line"] for b in inside)] if inside else [],
                        "text": " | ".join(b["text"] for b in inside)[:900], "summary": _summary(clip["kind"], inside),
                    })
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise StageError(f"The page could not be captured: {str(exc).splitlines()[0]}") from exc
    record = {
        "url": url, "title": title, "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "page_height": layout["total"], "blocks": kept_blocks(blocks), "styles": styles, "screenshots": shots,
    }
    run.write_json(run.capture_json, record)
    write_screenshots_md(run, record, claims=None)
    return record


def kept_blocks(blocks: list[dict]) -> list[dict]:
    """The blocks as saved (positions and flags kept, long text already cut)."""
    return [{k: b[k] for k in ("line", "text", "top", "heading", "button", "li", "quote", "region")} for b in blocks]


def write_screenshots_md(run: Run, record: dict, claims: list[dict] | None) -> None:
    """screenshots.md: one line per screenshot: what it shows, where in page.md, and (once stage 2 ran) which claims it supports."""
    out = ["# Screenshots", "", "One line each: id | file | what it shows | page.md lines | claims it supports", ""]
    for shot in record["screenshots"]:
        lines = f"lines {shot['lines'][0]}-{shot['lines'][1]}" if shot["lines"] else "no text"
        if claims is None:
            support = "(filled in by the notes stage)"
        else:
            ids = [c["id"] for c in claims if _supports(c, shot)]
            support = ", ".join(ids) if ids else "none"
        out.append(f"{shot['id']} | {shot['file']} | shows {shot['summary']} | {lines} | supports: {support}")
    run.screenshots_md.write_text("\n".join(out) + "\n", encoding="utf-8")


def _supports(claim: dict, shot: dict) -> bool:
    """True when a claim's source is this screenshot, or a page.md line this screenshot covers."""
    source = claim.get("source", "")
    if re.search(rf"screenshot\s*0*{int(shot['id'])}\b", source, re.I):
        return True
    if shot["lines"]:
        for number in re.findall(r"line[s]?\s*(\d+)(?:\s*-\s*(\d+))?", source, re.I):
            first, last = int(number[0]), int(number[1] or number[0])
            if first >= shot["lines"][0] and last <= shot["lines"][1]:
                return True
    return False
