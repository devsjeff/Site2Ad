"""Motion graphics as HTML/CSS scenes, in the brand's colours and fonts, with the real screenshots as footage.

Every animation is a plain CSS animation, so the builder can render any frame exactly by setting the clock of the page
(document.getAnimations()). One function builds one shot: scene_html(shot, theme, size, ...).
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

FOCUS_Y = {"top": "0%", "center": "45%", "bottom": "100%"}


def esc(value: Any) -> str:
    """HTML-safe text."""
    return html.escape(str(value if value is not None else ""), quote=True)


def theme_from(brand: dict) -> dict[str, str]:
    """Colours and fonts for the scenes from the brand notes (a dark or a light design, like the site)."""
    c, f, s = brand["colors"], brand["fonts"], brand["shapes"]
    dark = c["mode"] == "dark"
    bg = c["background_dark"] if dark else c["background_light"]
    return {
        "mode": c["mode"], "bg": bg, "bg2": "#0b0b0e" if dark else "#ffffff", "ink": "#ffffff" if dark else c["ink"],
        "muted": "#a1a1aa" if dark else "#52525b", "primary": c["primary"], "accent": c["accent"], "on_primary": c["on_primary"],
        "card": "rgba(255,255,255,0.07)" if dark else "#ffffff", "line": "rgba(255,255,255,0.14)" if dark else "rgba(0,0,0,0.10)",
        "head": f["heading"], "body": f["body"], "radius": f"{max(10, min(36, s['card_radius_px']))}px",
        "btn_radius": "999px" if s["button_radius_px"] >= 40 else f"{max(6, s['button_radius_px'])}px",
    }


def font_links(theme: dict) -> str:
    """Google Fonts link for the brand's fonts (the page waits for them; without a network the fallback fonts are used)."""
    families = []
    for name in dict.fromkeys([theme["head"], theme["body"]]):
        if name and name.lower() not in {"system-ui", "arial", "helvetica"}:
            families.append(f"family={quote(name).replace('%20', '+')}:wght@400;500;600;700")
    if not families:
        return ""
    return f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?{"&".join(families)}&display=swap">'


BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--u:min(1vw,1vh);--pad:calc(var(--u)*7);--ease:cubic-bezier(.2,.8,.2,1)}
html,body{width:100vw;height:100vh;overflow:hidden;background:var(--bg);color:var(--ink);font-family:var(--body-font);-webkit-font-smoothing:antialiased}
h1,h2,h3,.head{font-family:var(--head-font);font-weight:600;letter-spacing:-0.02em;line-height:1.04}
.stage{position:absolute;inset:0;padding:var(--pad);display:flex;flex-direction:column;justify-content:center;gap:calc(var(--u)*3);overflow:hidden}
.bgfx{position:absolute;inset:0;background:
  radial-gradient(circle at 12% 18%,color-mix(in srgb,var(--primary) 26%,transparent),transparent 46%),
  radial-gradient(circle at 92% 88%,color-mix(in srgb,var(--accent) 22%,transparent),transparent 42%),
  linear-gradient(160deg,var(--bg),var(--bg2));animation:drift 14s ease-in-out infinite alternate}
@keyframes drift{from{transform:scale(1) translate(0,0)}to{transform:scale(1.12) translate(2%,-2%)}}
.chip{position:absolute;left:var(--pad);top:calc(var(--u)*4.2);z-index:5;display:flex;align-items:center;gap:calc(var(--u)*1.2);font-size:calc(var(--u)*2.3);
  font-weight:600;color:var(--ink);background:var(--card);border:1px solid var(--line);padding:calc(var(--u)*1) calc(var(--u)*2.2);border-radius:999px;
  animation:fadeIn .6s var(--ease) both}
.chip i{width:calc(var(--u)*1.6);height:calc(var(--u)*1.6);border-radius:50%;background:var(--primary);display:block}
.bar{position:absolute;left:0;bottom:0;height:calc(var(--u)*.7);background:var(--primary);transform-origin:left;animation:grow var(--D) linear both;z-index:6}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes rise{from{opacity:0;transform:translateY(calc(var(--u)*4))}to{opacity:1;transform:none}}
@keyframes pop{0%{opacity:0;transform:scale(.7)}60%{transform:scale(1.06)}100%{opacity:1;transform:scale(1)}}
@keyframes sweep{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes slideL{from{opacity:0;transform:translateX(calc(var(--u)*-8))}to{opacity:1;transform:none}}
@keyframes slideR{from{opacity:0;transform:translateX(calc(var(--u)*8))}to{opacity:1;transform:none}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--primary) 55%,transparent)}50%{box-shadow:0 0 0 calc(var(--u)*2.4) transparent}}
@keyframes strike{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.a{animation:rise .7s var(--ease) both;animation-delay:var(--d,0s)}
.pop{animation:pop .65s var(--ease) both;animation-delay:var(--d,0s)}
.word{display:inline-block;animation:rise .6s var(--ease) both;animation-delay:var(--d,0s);margin-right:.22em}
[data-fit]{overflow:hidden}
.deco{position:absolute;right:-8vmin;top:50%;width:62vmin;height:62vmin;margin-top:-31vmin;border-radius:50%;border:calc(var(--u)*1.6) solid color-mix(in srgb,var(--primary) 30%,transparent);
  animation:spinIn 1.2s var(--ease) both,float 9s ease-in-out 1.2s infinite alternate;z-index:0}
.deco::before{content:"";position:absolute;inset:11%;border-radius:50%;background:radial-gradient(circle at 35% 30%,color-mix(in srgb,var(--primary) 55%,transparent),color-mix(in srgb,var(--accent) 22%,transparent) 70%)}
.dots{position:absolute;right:calc(var(--u)*5);bottom:calc(var(--u)*6);width:calc(var(--u)*26);height:calc(var(--u)*14);z-index:0;opacity:.55;
  background:radial-gradient(circle,var(--primary) 18%,transparent 20%) 0 0/calc(var(--u)*3) calc(var(--u)*3);animation:fadeIn 1s .4s both}
@keyframes spinIn{from{opacity:0;transform:scale(.6) rotate(-40deg)}to{opacity:1;transform:none}}
@keyframes float{from{transform:translateY(-2%)}to{transform:translateY(3%)}}
.stage>*{position:relative;z-index:1}
.hl{color:var(--primary)}
.sub{font-size:calc(var(--u)*3.6);line-height:1.3;color:var(--muted);max-width:92%}
.eyebrow{font-size:calc(var(--u)*2.4);font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--primary)}
.line{height:calc(var(--u)*.9);width:calc(var(--u)*16);background:var(--primary);border-radius:99px;transform-origin:left;animation:sweep .8s var(--ease) both;animation-delay:var(--d,.5s)}
"""

FIT_JS = """
(function(){
  window.__overflow = [];
  function over(el, maxH){ return el.scrollWidth > el.clientWidth + 1 || (isFinite(maxH) && el.scrollHeight > maxH + 1); }
  function fit(){
    document.querySelectorAll('[data-fit]').forEach(function(el){
      var cs = getComputedStyle(el), maxH = cs.maxHeight === 'none' ? Infinity : parseFloat(cs.maxHeight);
      var start = parseFloat(cs.fontSize), size = start, n = 0;
      // shrink only while the text really does not fit its box (never below 45% of the designed size)
      while (over(el, maxH) && size > start * 0.45 && n < 30){ size *= 0.95; el.style.fontSize = size + 'px'; n++; }
      if (over(el, maxH)) window.__overflow.push((el.innerText||'').slice(0,60));
    });
    document.querySelectorAll('.stage *').forEach(function(el){
      var r = el.getBoundingClientRect();
      if (r.width > 0 && (r.right > innerWidth + 2 || r.bottom > innerHeight + 2 || r.left < -2) && !el.closest('.shot-card') && !el.closest('.bgfx'))
        window.__overflow.push('outside the frame: ' + (el.innerText||el.className||'').toString().slice(0,50));
    });
  }
  window.__fit = fit;
})();
"""


def words_html(text: str, start: float = 0.1, step: float = 0.09, highlight: str = "") -> str:
    """A headline whose words rise in one after another. `highlight` words (a figure, say) take the brand colour."""
    marks = {m.lower() for m in re.findall(r"\S+", highlight)} if highlight else set()
    out = []
    for index, word in enumerate(str(text).split()):
        cls = "word hl" if re.sub(r"[^\w₹$%]", "", word).lower() in {re.sub(r"[^\w₹$%]", "", m) for m in marks} or re.search(r"[₹$€£]\d|\d", word) else "word"
        out.append(f'<span class="{cls}" style="--d:{start + index * step:.2f}s">{esc(word)}</span>')
    return " ".join(out)


# ---- graphics ---------------------------------------------------------------------------------

def g_title(p: dict) -> str:
    return (f'<div class="eyebrow a" style="--d:.05s">&nbsp;</div>'
            f'<h1 data-fit style="font-size:calc(var(--u)*10.5);max-height:56vh">{words_html(p.get("headline", ""))}</h1>'
            f'<div class="line"></div><p class="sub a" style="--d:.9s;max-height:20vh" data-fit>{esc(p.get("sub", ""))}</p>')


def g_big_number(p: dict) -> str:
    return (f'<div class="eyebrow a" style="--d:.05s">{esc(p.get("label", ""))}</div>'
            f'<div style="display:flex;align-items:center;gap:calc(var(--u)*3);flex-wrap:wrap">'
            f'<div class="head a" style="--d:.2s;font-size:calc(var(--u)*13);color:var(--muted);position:relative" data-fit>{esc(p.get("from", ""))}'
            f'<span style="position:absolute;left:-2%;right:-2%;top:54%;height:calc(var(--u)*1);background:var(--primary);transform-origin:left;'
            f'animation:strike .5s var(--ease) both;animation-delay:1s"></span></div>'
            f'<div class="head a" style="--d:.7s;font-size:calc(var(--u)*9);color:var(--primary)">→</div>'
            f'<div class="head hl pop" style="--d:1.25s;font-size:calc(var(--u)*17);max-width:100%" data-fit>{esc(p.get("to", ""))}</div></div>'
            f'<div class="line" style="--d:1.6s"></div>')


def g_steps(p: dict) -> str:
    steps = [str(s) for s in (p.get("steps") or [])][:4]
    cards = "".join(
        f'<div class="a" style="--d:{0.15 + i * 0.4:.2f}s;display:flex;align-items:center;gap:calc(var(--u)*2.6);background:var(--card);border:1px solid var(--line);'
        f'border-radius:var(--radius);padding:calc(var(--u)*2.2) calc(var(--u)*3)">'
        f'<div class="head" style="flex:none;width:calc(var(--u)*7);height:calc(var(--u)*7);border-radius:50%;background:var(--primary);color:var(--on-primary);'
        f'display:flex;align-items:center;justify-content:center;font-size:calc(var(--u)*3.8)">{i + 1}</div>'
        f'<div data-fit style="font-size:calc(var(--u)*4.2);font-weight:500;max-height:calc(var(--u)*13);flex:1">{esc(s)}</div></div>'
        for i, s in enumerate(steps))
    return f'<div class="eyebrow a">How it works</div><div style="display:flex;flex-direction:column;gap:calc(var(--u)*2.2)">{cards}</div>'


def g_stats(p: dict) -> str:
    stats = [s for s in (p.get("stats") or []) if isinstance(s, dict)][:3]
    tiles = "".join(
        f'<div class="pop" style="--d:{0.15 + i * 0.35:.2f}s;flex:{1 if len(stats) > 2 else '0 1 auto'};min-width:{'30%' if len(stats) > 2 else '34%'};max-width:100%;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);'
        f'padding:calc(var(--u)*3.4);display:flex;flex-direction:column;gap:calc(var(--u)*1.2)">'
        f'<div class="head hl" data-fit style="font-size:calc(var(--u)*11);max-height:calc(var(--u)*17)">{esc(s.get("value", ""))}</div>'
        f'<div data-fit style="font-size:calc(var(--u)*3.4);color:var(--muted);max-height:calc(var(--u)*10)">{esc(s.get("label", ""))}</div></div>'
        for i, s in enumerate(stats))
    return f'<div style="display:flex;gap:calc(var(--u)*2.4);flex-wrap:wrap">{tiles}</div>'


def g_price(p: dict) -> str:
    return (f'<div class="eyebrow a" style="--d:.05s">Pricing</div>'
            f'<div class="head hl pop" style="--d:.3s;font-size:calc(var(--u)*20);max-width:100%;line-height:1" data-fit>{esc(p.get("price", ""))}</div>'
            f'<div class="a" style="--d:.8s;font-size:calc(var(--u)*5);font-weight:500" data-fit>{esc(p.get("unit", ""))}</div>'
            f'<div class="line" style="--d:1s"></div>'
            + (f'<div class="a" style="--d:1.2s;align-self:flex-start;background:var(--card);border:1px solid var(--line);border-radius:999px;'
               f'padding:calc(var(--u)*1.2) calc(var(--u)*3);font-size:calc(var(--u)*3);color:var(--muted)">{esc(p.get("note", ""))}</div>' if p.get("note") else ""))


def g_quote(p: dict) -> str:
    return (f'<div class="head hl a" style="font-size:calc(var(--u)*24);line-height:.6;height:calc(var(--u)*11)">“</div>'
            f'<div class="head a" data-fit style="--d:.3s;font-size:calc(var(--u)*6.4);font-weight:500;max-height:46vh;line-height:1.2">{esc(p.get("quote", ""))}</div>'
            f'<div class="a" style="--d:1.1s;font-size:calc(var(--u)*3.4);color:var(--muted)">— {esc(p.get("who", ""))}</div>')


def g_compare(p: dict) -> str:
    def card(label: str, text: str, strong: bool, delay: float, anim: str) -> str:
        background = "var(--primary)" if strong else "var(--card)"
        color = "var(--on-primary)" if strong else "var(--ink)"
        return (f'<div style="flex:1;min-width:38%;animation:{anim} .7s var(--ease) both;animation-delay:{delay}s;background:{background};color:{color};'
                f'border:1px solid var(--line);border-radius:var(--radius);padding:calc(var(--u)*3.2);display:flex;flex-direction:column;gap:calc(var(--u)*1.6)">'
                f'<div style="font-size:calc(var(--u)*2.5);font-weight:600;letter-spacing:.1em;text-transform:uppercase;opacity:.75">{esc(label)}</div>'
                f'<div class="head" data-fit style="font-size:calc(var(--u)*7.4);max-height:calc(var(--u)*34)">{esc(text)}</div></div>')
    return ('<div style="display:flex;gap:calc(var(--u)*2.4);flex-wrap:wrap">'
            + card(p.get("left_label", ""), p.get("left", ""), False, 0.1, "slideL") + card(p.get("right_label", ""), p.get("right", ""), True, 0.55, "slideR") + "</div>")


def g_cta(p: dict) -> str:
    return (f'<h1 data-fit style="font-size:calc(var(--u)*9);max-height:34vh">{words_html(p.get("headline", ""), 0.05)}</h1>'
            f'<div class="pop" style="--d:.8s;align-self:flex-start;background:var(--primary);color:var(--on-primary);border-radius:var(--btn-radius);'
            f'padding:calc(var(--u)*2.4) calc(var(--u)*5.5);font-size:calc(var(--u)*4.6);font-weight:700;animation:pop .65s var(--ease) both,pulse 1.6s ease-in-out 1.6s infinite;'
            f'font-family:var(--head-font)">{esc(p.get("button", ""))} →</div>'
            f'<div class="a" style="--d:1.2s;font-size:calc(var(--u)*4);font-weight:600;color:var(--ink);border-bottom:calc(var(--u)*.7) solid var(--primary);'
            f'align-self:flex-start;padding-bottom:calc(var(--u)*.6)">{esc(p.get("url", ""))}</div>')


GRAPHICS = {"title": g_title, "big_number": g_big_number, "steps": g_steps, "stats": g_stats, "price": g_price, "quote": g_quote, "compare": g_compare, "cta": g_cta}


# ---- screenshot footage -------------------------------------------------------------------------

def screenshot_scene(visual: dict, caption: str, image_url: str, size: tuple[int, int]) -> str:
    """A real screenshot as footage: a card with a slow pan and zoom over the picture, on a blurred copy of itself."""
    width, height = size
    landscape = width >= height
    focus = visual.get("focus", "top") if visual.get("focus") in FOCUS_Y else "top"
    start_y, end_y = ("0%", "55%") if focus == "top" else ("70%", "30%") if focus == "bottom" else ("25%", "65%")
    zoom_in = visual.get("zoom", "in") != "out"
    card_w, card_h = ("88vw", "78vh") if landscape else ("90vw", "62vh")
    scale_from, scale_to = (1.0, 1.14) if zoom_in else (1.14, 1.0)
    return f"""
<div class="bgfx" style="background:url('{image_url}') center/cover;filter:blur(calc(var(--u)*3)) brightness(.55) saturate(1.2);transform:scale(1.2);animation:none"></div>
<div style="position:absolute;inset:0;display:flex;align-items:{'center' if landscape else 'flex-start'};justify-content:center;padding-top:{'0' if landscape else '11vh'}">
 <div class="shot-card" style="position:relative;width:{card_w};height:{card_h};border-radius:var(--radius);overflow:hidden;
  box-shadow:0 calc(var(--u)*3) calc(var(--u)*9) rgba(0,0,0,.45);border:1px solid var(--line);animation:pop .7s var(--ease) both">
  <img src="{image_url}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% {start_y};transform-origin:50% 40%;
    animation:pan var(--D) ease-in-out both,zoom var(--D) ease-in-out both"></div></div>
{f'<div class="a" style="--d:.5s;position:absolute;left:50%;bottom:calc(var(--u)*5);transform:translateX(-50%);max-width:88%;z-index:5"><div style="background:var(--primary);color:var(--on-primary);border-radius:999px;padding:calc(var(--u)*1.6) calc(var(--u)*4);font-family:var(--head-font);font-weight:600;font-size:calc(var(--u)*4);white-space:nowrap" data-fit>{esc(caption)}</div></div>' if caption else ''}
<style>
@keyframes pan{{from{{object-position:50% {start_y}}}to{{object-position:50% {end_y}}}}}
@keyframes zoom{{from{{transform:scale({scale_from})}}to{{transform:scale({scale_to})}}}}
</style>"""


def scene_html(shot: dict, theme: dict, size: tuple[int, int], site: str, image_url: str = "") -> str:
    """The full HTML page of one shot. Its animations run for the shot's length and then hold."""
    visual = shot["visual"]
    width, height = size
    if visual.get("type") == "screenshot":
        body = screenshot_scene(visual, shot.get("caption", ""), image_url, size)
    else:
        make = GRAPHICS.get(visual.get("template"), g_title)
        deco = '<div class="deco"></div><div class="dots"></div>' if width > height else ""
        body = f'<div class="bgfx"></div>{deco}<div class="stage">{make(visual.get("props") or {})}</div>'
    css_vars = (f"--bg:{theme['bg']};--bg2:{theme['bg2']};--ink:{theme['ink']};--muted:{theme['muted']};--primary:{theme['primary']};--accent:{theme['accent']};"
                f"--on-primary:{theme['on_primary']};--card:{theme['card']};--line:{theme['line']};--radius:{theme['radius']};--btn-radius:{theme['btn_radius']};"
                f"--head-font:'{theme['head']}','Segoe UI',system-ui,sans-serif;--body-font:'{theme['body']}','Segoe UI',system-ui,sans-serif;--D:{shot['seconds'] + 1:.2f}s")
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width={width},height={height}">{font_links(theme)}'
            f'<style>:root{{{css_vars}}}{BASE_CSS}</style></head><body>{body}'
            f'<div class="chip"><i></i>{esc(site)}</div><div class="bar"></div><script>{FIT_JS}</script></body></html>')


def describe(shot: dict) -> str:
    """For logs."""
    return json.dumps(shot["visual"], ensure_ascii=False)[:100]
