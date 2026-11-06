"""Motion graphics as HTML/CSS scenes, in the brand's colours and fonts, with the real screenshots as footage.

Every animation is a plain CSS animation, so the builder can render any frame exactly by setting the clock of the page
(document.getAnimations()). One function builds one shot: scene_html(shot, theme, size, ...).
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import quote

from .brand import hls, luminance

FOCUS_Y = {"top": "0%", "center": "45%", "bottom": "100%"}


def mix(color: str, other: str, share: float) -> str:
    """`color` moved `share` of the way towards `other` (both #rrggbb)."""
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (color, other))
    return "#{:02x}{:02x}{:02x}".format(*(round(x + (y - x) * share) for x, y in zip(a, b)))


def esc(value: Any) -> str:
    """HTML-safe text."""
    return html.escape(str(value if value is not None else ""), quote=True)


def bold_ok(primary: str) -> bool:
    """True when the brand colour is strong enough to fill whole frames (not near white, black or grey)."""
    _, light, saturation = hls(primary)
    return 0.12 <= light <= 0.62 and saturation >= 0.3


def complete_theme(theme: dict) -> dict:
    """The theme with every key the scenes use (a theme written by hand may lack the bold-look colours)."""
    light_text = luminance(theme["on_primary"]) > 0.55
    defaults = {
        "bold": "", "primary_dark": mix(theme["primary"], "#000000", 0.38), "hl_bold": theme["on_primary"], "pill_bg": theme["on_primary"],
        "pill_ink": "#111111" if light_text else "#ffffff", "bold_card": "rgba(255,255,255,0.14)" if light_text else "rgba(0,0,0,0.08)",
        "bold_line": "rgba(255,255,255,0.30)" if light_text else "rgba(0,0,0,0.18)",
    }
    return {**defaults, **theme}


def theme_from(brand: dict) -> dict[str, str]:
    """Colours and fonts for the scenes from the brand notes (a dark or a light design, like the site)."""
    c, f, s = brand["colors"], brand["fonts"], brand["shapes"]
    dark = c["mode"] == "dark"
    bg = c["background_dark"] if dark else c["background_light"]
    on_primary = c["on_primary"]
    light_text = luminance(on_primary) > 0.55
    accent_ok = abs(luminance(c["accent"]) - luminance(c["primary"])) >= 0.3
    return {
        "bold": "1" if bold_ok(c["primary"]) else "", "primary_dark": mix(c["primary"], "#000000", 0.38), "hl_bold": c["accent"] if accent_ok else on_primary,
        "pill_bg": on_primary, "pill_ink": "#111111" if light_text else "#ffffff",
        "bold_card": "rgba(255,255,255,0.14)" if light_text else "rgba(0,0,0,0.08)", "bold_line": "rgba(255,255,255,0.30)" if light_text else "rgba(0,0,0,0.18)",
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
:root{--u:min(1vw,1vh);--pad:calc(var(--u)*7);--ease:cubic-bezier(.2,.8,.2,1);--bounce:cubic-bezier(.34,1.5,.64,1)}
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
@keyframes pop{0%{opacity:0;transform:scale(.4) rotate(-6deg)}55%{opacity:1;transform:scale(1.14) rotate(2deg)}80%{transform:scale(.97) rotate(0)}100%{opacity:1;transform:none}}
@keyframes wordPop{0%{opacity:0;transform:translateY(calc(var(--u)*3.5)) scale(.55) rotate(-5deg)}60%{opacity:1;transform:translateY(calc(var(--u)*-.6)) scale(1.1) rotate(1deg)}100%{opacity:1;transform:none}}
@keyframes stamp{0%{opacity:0;transform:scale(2.6) rotate(-9deg)}52%{opacity:1;transform:scale(.92) rotate(-2deg)}72%{transform:scale(1.06) rotate(-1deg)}100%{opacity:1;transform:rotate(-1deg)}}
@keyframes shock{0%{opacity:.85;transform:translate(-50%,-50%) scale(.2)}100%{opacity:0;transform:translate(-50%,-50%) scale(4.2)}}
@keyframes streak{from{transform:translateX(-130%) skewX(-18deg)}to{transform:translateX(330%) skewX(-18deg)}}
@keyframes orbA{from{transform:translate(0,0) scale(1)}to{transform:translate(4vw,-6vh) scale(1.25)}}
@keyframes orbB{from{transform:translate(0,0) scale(1.1)}to{transform:translate(-5vw,5vh) scale(.85)}}
@keyframes fly{0%{opacity:0;transform:translate(0,0) rotate(0) scale(.3)}12%{opacity:1}100%{opacity:0;transform:translate(var(--dx),var(--dy)) rotate(var(--rot)) scale(1)}}
@keyframes btnShine{0%{left:-60%}55%,100%{left:140%}}
@keyframes nudge{0%,100%{transform:none}50%{transform:translateX(.28em)}}
@keyframes mockIn{0%{opacity:0;transform:perspective(1600px) rotateX(16deg) rotateY(-12deg) translateY(7vh) scale(.86)}60%{opacity:1;transform:perspective(1600px) rotateX(-2deg) rotateY(1deg) scale(1.02)}100%{opacity:1;transform:none}}
@keyframes sweep{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes slideL{from{opacity:0;transform:translateX(calc(var(--u)*-8))}to{opacity:1;transform:none}}
@keyframes slideR{from{opacity:0;transform:translateX(calc(var(--u)*8))}to{opacity:1;transform:none}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--primary) 55%,transparent)}50%{box-shadow:0 0 0 calc(var(--u)*2.4) transparent}}
@keyframes strike{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.a{animation:rise .7s var(--ease) both;animation-delay:var(--d,0s)}
.pop{animation:pop .75s var(--bounce) both;animation-delay:var(--d,0s)}
.stamp{display:inline-block;align-self:flex-start;transform-origin:left center;animation:stamp .8s var(--bounce) both;animation-delay:var(--d,0s)}
.word{display:inline-block;animation:wordPop .6s var(--bounce) both;animation-delay:var(--d,0s);margin-right:.2em}
.sweep{position:absolute;top:-10%;bottom:-10%;left:0;width:14%;z-index:3;pointer-events:none;background:linear-gradient(100deg,transparent,rgba(255,255,255,.22),transparent);
  animation:streak 1.15s cubic-bezier(.5,0,.3,1) .15s both}
.orb{position:absolute;border-radius:50%;z-index:0;pointer-events:none;background:radial-gradient(circle at 35% 30%,color-mix(in srgb,var(--hl) 38%,transparent),transparent 70%)}
.orb.o1{width:22vmin;height:22vmin;left:62%;top:8%;animation:orbA 7s ease-in-out infinite alternate}
.orb.o2{width:16vmin;height:16vmin;left:8%;top:72%;animation:orbB 8.5s ease-in-out infinite alternate}
.orb.o3{width:11vmin;height:11vmin;left:84%;top:66%;animation:orbA 6s ease-in-out -2s infinite alternate}
.burst,.stage>.burst{position:absolute!important;left:50%;top:50%;width:0;height:0;z-index:4!important;pointer-events:none}
.burst i{position:absolute;left:0;top:0;width:var(--s);height:calc(var(--s)*.55);margin:calc(var(--s)*-.3);background:var(--c);border-radius:2px;opacity:0;animation:fly 1.15s cubic-bezier(.1,.75,.3,1) var(--d) both}
.burst i:nth-child(3n){border-radius:50%;height:var(--s)}
.burst b{position:absolute;left:0;top:0;width:calc(var(--u)*9);height:calc(var(--u)*9);border-radius:50%;border:calc(var(--u)*.7) solid var(--hl);opacity:0;animation:shock .9s ease-out var(--d) both}
.btn-shine{position:relative;overflow:hidden}
.btn-shine::after{content:"";position:absolute;top:0;left:-60%;width:38%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.6),transparent);transform:skewX(-20deg);animation:btnShine 2.2s ease-in-out 1.5s infinite}
.btn-shine .arrow{display:inline-block;animation:nudge 1.1s ease-in-out 1.4s infinite}
.word:last-child{margin-right:0}
[data-fit]{overflow:hidden}
.deco{position:absolute;right:-8vmin;top:50%;width:62vmin;height:62vmin;margin-top:-31vmin;border-radius:50%;border:calc(var(--u)*1.6) solid color-mix(in srgb,var(--primary) 30%,transparent);
  animation:spinIn 1.2s var(--ease) both,float 9s ease-in-out 1.2s infinite alternate;z-index:0}
.deco::before{content:"";position:absolute;inset:11%;border-radius:50%;background:radial-gradient(circle at 35% 30%,color-mix(in srgb,var(--primary) 55%,transparent),color-mix(in srgb,var(--accent) 22%,transparent) 70%)}
.dots{position:absolute;right:calc(var(--u)*5);bottom:calc(var(--u)*6);width:calc(var(--u)*26);height:calc(var(--u)*14);z-index:0;opacity:.55;
  background:radial-gradient(circle,var(--primary) 18%,transparent 20%) 0 0/calc(var(--u)*3) calc(var(--u)*3);animation:fadeIn 1s .4s both}
@keyframes spinIn{from{opacity:0;transform:scale(.6) rotate(-40deg)}to{opacity:1;transform:none}}
@keyframes float{from{transform:translateY(-2%)}to{transform:translateY(3%)}}
.stage>*{position:relative;z-index:1}
.hl{color:var(--hl)}
.pillhead{line-height:1.5}
.pillhead .box{background:var(--pill-bg);color:var(--pill-ink);padding:.1em .55em;border-radius:.6em;-webkit-box-decoration-break:clone;box-decoration-break:clone;
  box-shadow:0 calc(var(--u)*.8) calc(var(--u)*2.4) rgba(0,0,0,.22)}
.pillhead .hl{color:var(--bg)}
.dotgrid{position:absolute;inset:0;background:radial-gradient(circle,color-mix(in srgb,var(--ink) 18%,transparent) calc(var(--u)*.16),transparent calc(var(--u)*.22)) 0 0/calc(var(--u)*4) calc(var(--u)*4);
  opacity:.8;mask-image:linear-gradient(120deg,transparent 10%,#000 60%,transparent);-webkit-mask-image:linear-gradient(120deg,transparent 10%,#000 60%,transparent)}
.blob{position:absolute;left:-14vmin;bottom:-18vmin;width:58vmin;height:58vmin;border-radius:46% 54% 60% 40%;background:color-mix(in srgb,var(--ink) 9%,transparent);
  animation:spinIn 1.1s var(--ease) both,float 10s ease-in-out 1s infinite alternate;z-index:0}
.band{position:absolute;right:-10vw;top:-30vh;width:46vw;height:170vh;transform:rotate(18deg);background:color-mix(in srgb,var(--ink) 8%,transparent);
  animation:fadeIn 1s var(--ease) both;z-index:0}
.art{position:absolute;right:6vw;top:50%;width:31vw;height:56vh;margin-top:-28vh;border-radius:calc(var(--radius)*1.2);overflow:hidden;background:#fff;z-index:2;
  box-shadow:0 calc(var(--u)*3) calc(var(--u)*9) rgba(0,0,0,.4);transform:rotate(2.2deg);animation:artIn .9s var(--ease) .25s both}
.art img{width:100%;height:100%;object-fit:cover;object-position:50% 30%;animation:artZoom var(--D) ease-in-out both}
@keyframes artIn{from{opacity:0;transform:translateX(8vw) rotate(8deg)}to{opacity:1;transform:rotate(2.2deg)}}
@keyframes artZoom{from{transform:scale(1)}to{transform:scale(1.1)}}
.has-art>*{max-width:58%}
.mock{position:relative;display:flex;flex-direction:column;overflow:hidden;background:#fff;border-radius:calc(var(--radius)*.9);
  box-shadow:0 calc(var(--u)*3.4) calc(var(--u)*10) rgba(0,0,0,.45),0 0 0 1px rgba(0,0,0,.08);animation:mockIn .95s var(--ease) both}
.chrome{flex:none;display:flex;align-items:center;gap:calc(var(--u)*1);padding:0 calc(var(--u)*2);background:#eceff3;border-bottom:1px solid rgba(0,0,0,.08)}
.chrome i{width:calc(var(--u)*1.5);height:calc(var(--u)*1.5);border-radius:50%;background:#ff5f57;display:block}
.chrome i:nth-child(2){background:#febc2e}.chrome i:nth-child(3){background:#28c840}
.addr{margin:0 auto;transform:translateX(-4%);background:#fff;color:#555;border-radius:99px;padding:calc(var(--u)*.4) calc(var(--u)*6);font-size:calc(var(--u)*1.9);font-family:system-ui,sans-serif}
.view{position:relative;flex:1;overflow:hidden;background:#fff}
.pan{position:absolute;inset:0;transform-origin:50% 35%;animation:kb var(--D) ease-in-out both}
.pan img{position:absolute;display:block}
@keyframes kb{from{transform:scale(1) translate(0,0)}to{transform:scale(1.08) translate(0,-2.5%)}}
@keyframes kbOut{from{transform:scale(1.08) translate(0,-2.5%)}to{transform:scale(1) translate(0,0)}}
.logo-card{align-self:flex-start;background:#fff;border-radius:calc(var(--radius)*1.1);padding:calc(var(--u)*2.4) calc(var(--u)*4);box-shadow:0 calc(var(--u)*2) calc(var(--u)*6) rgba(0,0,0,.3)}
.logo-card img{display:block;max-height:calc(var(--u)*12);max-width:calc(var(--u)*46);object-fit:contain}
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
      if (r.width > 0 && (r.right > innerWidth + 2 || r.bottom > innerHeight + 2 || r.left < -2) && !el.closest('.shot-card') && !el.closest('.bgfx') && !el.closest('.burst'))
        window.__overflow.push('outside the frame: ' + (el.innerText||el.className||'').toString().slice(0,50));
    });
  }
  function place(){
    document.querySelectorAll('.burst[data-for]').forEach(function(b){
      var t = document.getElementById(b.getAttribute('data-for'));
      if (!t) return;
      var r = t.getBoundingClientRect();
      b.style.left = (r.left + r.width / 2) + 'px';
      b.style.top = (r.top + r.height / 2) + 'px';
    });
  }
  window.__fit = function(){ fit(); place(); };
})();
"""


def words_html(text: str, start: float = 0.1, step: float = 0.09, highlight: str = "") -> str:
    """A headline whose words rise in one after another. `highlight` words (a figure, say) take the brand colour."""
    marks = {m.lower() for m in re.findall(r"\S+", highlight)} if highlight else set()
    out = []
    for index, word in enumerate(str(text).split()):
        cls = "word hl" if re.sub(r"[^\w₹$%]", "", word).lower() in {re.sub(r"[^\w₹$%]", "", m) for m in marks} or re.search(r"[₹$€£]\d|\d", word) else "word"
        out.append(f'<span class="{cls}" style="--d:{start + index * step:.2f}s">{esc(word)}</span>')
    return "".join(out)


# ---- graphics ---------------------------------------------------------------------------------

BURST_COLORS = ("var(--hl)", "var(--ink)", "var(--accent)", "var(--primary)")
BURST_PIECES = (  # (angle degrees, distance in vmin, size in vmin, spin degrees): fixed, so a render is always the same
    (0, 24, 1.8, 220), (24, 17, 1.2, -180), (47, 28, 1.6, 300), (70, 19, 1.1, -240), (95, 26, 1.9, 160), (118, 16, 1.3, -300), (140, 29, 1.5, 260), (163, 20, 1.2, -140),
    (186, 25, 1.8, 330), (209, 18, 1.2, -200), (231, 28, 1.6, 180), (255, 21, 1.1, -280), (277, 27, 1.9, 240), (299, 17, 1.3, -160), (321, 29, 1.5, 310), (343, 22, 1.2, -220),
)


def burst(target: str, delay: float) -> str:
    """Confetti and a shockwave ring that burst out of the element `target` (an id) at `delay` seconds. They finish invisible."""
    import math

    pieces = "".join(
        f'<i style="--dx:{math.cos(math.radians(a)) * dist * 1.35:.1f}vmin;--dy:{math.sin(math.radians(a)) * dist * 1.35:.1f}vmin;--rot:{spin}deg;--s:{size * 2.4:.1f}vmin;'
        f'--c:{BURST_COLORS[index % len(BURST_COLORS)]};--d:{delay + (index % 4) * 0.025:.3f}s"></i>'
        for index, (a, dist, size, spin) in enumerate(BURST_PIECES))
    return f'<div class="burst" data-for="{target}"><b style="--d:{delay:.3f}s"></b>{pieces}</div>'

def g_title(p: dict, ctx: dict | None = None) -> str:
    if ctx and ctx.get("bold"):  # white pills behind the words, like a caption: reads on any brand colour and looks designed
        return (f'<h1 class="pillhead" data-fit style="font-size:calc(var(--u)*10);max-height:56vh"><span class="box">{words_html(p.get("headline", ""))}</span></h1>'
                f'<p class="sub a" style="--d:.9s;max-height:20vh;font-weight:500;font-size:calc(var(--u)*4)" data-fit>{esc(p.get("sub", ""))}</p>')
    return (f'<div class="eyebrow a" style="--d:.05s">&nbsp;</div>'
            f'<h1 data-fit style="font-size:calc(var(--u)*11);max-height:56vh">{words_html(p.get("headline", ""))}</h1>'
            f'<div class="line"></div><p class="sub a" style="--d:.9s;max-height:20vh" data-fit>{esc(p.get("sub", ""))}</p>')


def g_big_number(p: dict, ctx: dict | None = None) -> str:
    return (f'<div class="eyebrow a" style="--d:.05s">{esc(p.get("label", ""))}</div>'
            f'<div style="display:flex;align-items:center;gap:calc(var(--u)*3);flex-wrap:wrap">'
            f'<div class="head a" style="--d:.2s;font-size:calc(var(--u)*13);color:var(--muted);position:relative" data-fit>{esc(p.get("from", ""))}'
            f'<span style="position:absolute;left:0;right:0;top:54%;height:calc(var(--u)*1);background:var(--primary);transform-origin:left;'
            f'animation:strike .5s var(--ease) both;animation-delay:1s"></span></div>'
            f'<div class="head a" style="--d:.7s;font-size:calc(var(--u)*9);color:var(--primary)">→</div>'
            f'<div class="head hl stamp" id="num-to" style="--d:1.25s;font-size:calc(var(--u)*17);max-width:100%" data-fit>{esc(p.get("to", ""))}</div></div>'
            f'<div class="line" style="--d:1.6s"></div>' + burst("num-to", 1.3))


def g_steps(p: dict, ctx: dict | None = None) -> str:
    steps = [str(s) for s in (p.get("steps") or [])][:4]
    cards = "".join(
        f'<div class="a" style="--d:{0.15 + i * 0.4:.2f}s;display:flex;align-items:center;gap:calc(var(--u)*2.6);background:var(--card);border:1px solid var(--line);'
        f'border-radius:var(--radius);padding:calc(var(--u)*2.2) calc(var(--u)*3)">'
        f'<div class="head" style="flex:none;width:calc(var(--u)*7);height:calc(var(--u)*7);border-radius:50%;background:var(--primary);color:var(--on-primary);'
        f'display:flex;align-items:center;justify-content:center;font-size:calc(var(--u)*3.8)">{i + 1}</div>'
        f'<div data-fit style="font-size:calc(var(--u)*4.2);font-weight:500;max-height:calc(var(--u)*13);flex:1">{esc(s)}</div></div>'
        for i, s in enumerate(steps))
    return f'<div class="eyebrow a">How it works</div><div style="display:flex;flex-direction:column;gap:calc(var(--u)*2.2)">{cards}</div>'


def g_stats(p: dict, ctx: dict | None = None) -> str:
    stats = [s for s in (p.get("stats") or []) if isinstance(s, dict)][:3]
    tiles = "".join(
        f'<div class="pop" style="--d:{0.15 + i * 0.35:.2f}s;flex:{1 if len(stats) > 2 else '0 1 auto'};min-width:{'30%' if len(stats) > 2 else '34%'};max-width:100%;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);'
        f'padding:calc(var(--u)*3.4);display:flex;flex-direction:column;gap:calc(var(--u)*1.2)">'
        f'<div class="head hl" data-fit style="font-size:calc(var(--u)*11);max-height:calc(var(--u)*17)">{esc(s.get("value", ""))}</div>'
        f'<div data-fit style="font-size:calc(var(--u)*3.4);color:var(--muted);max-height:calc(var(--u)*10)">{esc(s.get("label", ""))}</div></div>'
        for i, s in enumerate(stats))
    return f'<div style="display:flex;gap:calc(var(--u)*2.4);flex-wrap:wrap">{tiles}</div>'


def g_price(p: dict, ctx: dict | None = None) -> str:
    return (f'<div class="eyebrow a" style="--d:.05s">Pricing</div>'
            f'<div class="head hl stamp" id="price-val" style="--d:.3s;font-size:calc(var(--u)*20);max-width:100%;line-height:1" data-fit>{esc(p.get("price", ""))}</div>'
            f'<div class="a" style="--d:.8s;font-size:calc(var(--u)*5);font-weight:500" data-fit>{esc(p.get("unit", ""))}</div>'
            f'<div class="line" style="--d:1s"></div>'
            + (f'<div class="a" style="--d:1.2s;align-self:flex-start;background:var(--card);border:1px solid var(--line);border-radius:999px;'
               f'padding:calc(var(--u)*1.2) calc(var(--u)*3);font-size:calc(var(--u)*3);color:var(--muted)">{esc(p.get("note", ""))}</div>' if p.get("note") else "")
            + burst("price-val", 0.34))


def g_quote(p: dict, ctx: dict | None = None) -> str:
    return (f'<div class="head hl a" style="font-size:calc(var(--u)*24);line-height:.6;height:calc(var(--u)*11)">“</div>'
            f'<div class="head a" data-fit style="--d:.3s;font-size:calc(var(--u)*6.4);font-weight:500;max-height:46vh;line-height:1.2">{esc(p.get("quote", ""))}</div>'
            f'<div class="a" style="--d:1.1s;font-size:calc(var(--u)*3.4);color:var(--muted)">— {esc(p.get("who", ""))}</div>')


def g_compare(p: dict, ctx: dict | None = None) -> str:
    def card(label: str, text: str, strong: bool, delay: float, anim: str) -> str:
        background = "var(--primary)" if strong else "var(--card)"
        color = "var(--on-primary)" if strong else "var(--ink)"
        return (f'<div style="flex:1;min-width:38%;animation:{anim} .7s var(--ease) both;animation-delay:{delay}s;background:{background};color:{color};'
                f'border:1px solid var(--line);border-radius:var(--radius);padding:calc(var(--u)*3.2);display:flex;flex-direction:column;gap:calc(var(--u)*1.6)">'
                f'<div style="font-size:calc(var(--u)*2.5);font-weight:600;letter-spacing:.1em;text-transform:uppercase;opacity:.75">{esc(label)}</div>'
                f'<div class="head" data-fit style="font-size:calc(var(--u)*7.4);max-height:calc(var(--u)*34)">{esc(text)}</div></div>')
    return ('<div style="display:flex;gap:calc(var(--u)*2.4);flex-wrap:wrap">'
            + card(p.get("left_label", ""), p.get("left", ""), False, 0.1, "slideL") + card(p.get("right_label", ""), p.get("right", ""), True, 0.55, "slideR") + "</div>")


def g_cta(p: dict, ctx: dict | None = None) -> str:
    logo = (f'<div class="logo-card pop" style="--d:.05s"><img src="{esc(ctx["logo"])}" alt=""></div>' if ctx and ctx.get("logo") else "")
    return (logo + f'<h1 data-fit style="font-size:calc(var(--u)*9);max-height:34vh">{words_html(p.get("headline", ""), 0.05)}</h1>'
            f'<div class="btn-shine" id="cta-btn" style="align-self:flex-start;background:var(--primary);color:var(--on-primary);border-radius:var(--btn-radius);'
            f'padding:calc(var(--u)*2.4) calc(var(--u)*5.5);font-size:calc(var(--u)*5);font-weight:700;animation:pop .75s var(--bounce) .8s both,pulse 1.6s ease-in-out 1.7s infinite;'
            f'font-family:var(--head-font)">{esc(p.get("button", ""))} <span class="arrow">→</span></div>'
            f'<div class="a" style="--d:1.2s;font-size:calc(var(--u)*4);font-weight:600;color:var(--ink);border-bottom:calc(var(--u)*.7) solid var(--primary);'
            f'align-self:flex-start;padding-bottom:calc(var(--u)*.6)">{esc(p.get("url", ""))}</div>' + burst("cta-btn", 0.86))


GRAPHICS = {"title": g_title, "big_number": g_big_number, "steps": g_steps, "stats": g_stats, "price": g_price, "quote": g_quote, "compare": g_compare, "cta": g_cta}


# ---- screenshot footage -------------------------------------------------------------------------

def screenshot_box(size: tuple[int, int]) -> tuple[float, float, float]:
    """(card width, card height, address bar height) in pixels of the browser window a screenshot is shown in."""
    width, height = size
    if width >= height:
        return 0.84 * width, 0.80 * height, 0.055 * height
    return 0.92 * width, 0.60 * height, 0.034 * height


def art_aspect(size: tuple[int, int]) -> float:
    """Width / height of the picture card shown beside a headline."""
    return 0.31 * size[0] / (0.56 * size[1])


def screenshot_aspect(size: tuple[int, int]) -> float:
    """Width / height of the part of the window that shows the page (the crop of the screenshot must have this shape)."""
    card_w, card_h, bar = screenshot_box(size)
    return card_w / (card_h - bar)


def screenshot_scene(visual: dict, caption: str, image_url: str, size: tuple[int, int], site: str = "", crop: dict | None = None) -> str:
    """A real screenshot as footage: a large browser window showing the part of the page that has content, with a slow push-in."""
    width, height = size
    landscape = width >= height
    card_w, card_h, bar = screenshot_box(size)
    zoom_out = visual.get("zoom", "in") == "out"
    if crop:
        pan_w, pan_x, pan_y = crop["iw"] / crop["w"] * 100, -crop["x"] / crop["w"] * 100, -crop["y"] / crop["h"] * 100
        image = f'<img src="{image_url}" style="width:{pan_w:.3f}%;left:{pan_x:.3f}%;top:{pan_y:.3f}%" alt="">'
    else:
        image = f'<img src="{image_url}" style="width:100%;height:100%;left:0;top:0;object-fit:cover;object-position:50% 0%" alt="">'
    pill = (f'<div class="a" style="--d:.5s;position:absolute;left:50%;bottom:{3.2 if landscape else 9}vh;transform:translateX(-50%);max-width:88%;z-index:5">'
            f'<div style="background:var(--pill-bg);color:var(--pill-ink);border-radius:999px;padding:calc(var(--u)*1.6) calc(var(--u)*4.2);font-family:var(--head-font);'
            f'font-weight:700;font-size:calc(var(--u)*{4.2 if landscape else 4.6});white-space:nowrap;box-shadow:0 calc(var(--u)*1.2) calc(var(--u)*3.4) rgba(0,0,0,.3)" data-fit>{esc(caption)}</div></div>'
            if caption else "")
    return f"""
<div class="bgfx"></div><div class="dotgrid"></div>
<div style="position:absolute;inset:0;display:flex;align-items:{'center' if landscape else 'flex-start'};justify-content:center;padding-top:{'0' if landscape else '10vh'}">
 <div class="shot-card mock" style="width:{card_w / width * 100:.2f}vw;height:{card_h / height * 100:.2f}vh">
  <div class="chrome" style="height:{bar / height * 100:.2f}vh"><i></i><i></i><i></i><span class="addr">{esc(site)}</span></div>
  <div class="view"><div class="pan" style="{'animation-name:kbOut' if zoom_out else ''}">{image}</div></div></div></div>
{pill}"""


def scene_html(shot: dict, theme: dict, size: tuple[int, int], site: str, image_url: str = "", crop: dict | None = None, logo_url: str = "", art_url: str = "") -> str:
    """The full HTML page of one shot. Its animations run for the shot's length and then hold.

    Odd shots (and the last one) fill the frame with the brand colour when the brand has a strong one, the others use the site's own
    background, so the video has the rhythm of a designed piece rather than one look repeated. `crop` is the part of the screenshot to
    show (from imaging.crop_for), `logo_url` the site's logo for the end card, `art_url` one of the site's pictures to show beside a headline.
    """
    theme = complete_theme(theme)
    visual = shot["visual"]
    width, height = size
    number = int(shot.get("n", 1))
    template = visual.get("template")
    bold = bool(theme.get("bold")) and (number % 2 == 1 or template == "cta")
    ctx = {"bold": bold, "logo": logo_url if template == "cta" else ""}
    if visual.get("type") == "screenshot":
        body = screenshot_scene(visual, shot.get("caption", ""), image_url, size, site, crop)
    else:
        make = GRAPHICS.get(template, g_title)
        shape = ("", "blob", "band")[number % 3]
        if bold:
            deco = '<div class="dotgrid"></div>' + (f'<div class="{shape}"></div>' if shape else "")
        else:
            deco = '<div class="deco"></div><div class="dots"></div>' if not shape else f'<div class="{shape}"></div>'
        with_art = bool(art_url) and width > height and template in {"title", "price", "quote", "big_number", "cta"}
        art = f'<div class="art"><img src="{esc(art_url)}" alt=""></div>' if with_art else ""
        body = f'<div class="bgfx"></div>{deco}<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div><div class="stage{" has-art" if with_art else ""}">{make(visual.get("props") or {}, ctx)}</div>{art}<div class="sweep"></div>'
    if bold:
        colors = {"bg": theme["primary"], "bg2": theme["primary_dark"], "ink": theme["on_primary"], "muted": f"color-mix(in srgb,{theme['on_primary']} 82%,transparent)",
                  "primary": theme["on_primary"], "on_primary": theme["primary"], "card": theme["bold_card"], "line": theme["bold_line"], "hl": theme["hl_bold"], "accent": theme["hl_bold"]}
    else:
        colors = {"bg": theme["bg"], "bg2": theme["bg2"], "ink": theme["ink"], "muted": theme["muted"], "primary": theme["primary"], "on_primary": theme["on_primary"],
                  "card": theme["card"], "line": theme["line"], "hl": theme["primary"], "accent": theme["accent"]}
    css_vars = (f"--bg:{colors['bg']};--bg2:{colors['bg2']};--ink:{colors['ink']};--muted:{colors['muted']};--primary:{colors['primary']};--accent:{colors['accent']};"
                f"--on-primary:{colors['on_primary']};--card:{colors['card']};--line:{colors['line']};--hl:{colors['hl']};--pill-bg:{theme['pill_bg']};--pill-ink:{theme['pill_ink']};"
                f"--radius:{theme['radius']};--btn-radius:{theme['btn_radius']};"
                f"--head-font:'{theme['head']}','Segoe UI',system-ui,sans-serif;--body-font:'{theme['body']}','Segoe UI',system-ui,sans-serif;--D:{shot['seconds'] + 1:.2f}s")
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width={width},height={height}">{font_links(theme)}'
            f'<style>:root{{{css_vars}}}{BASE_CSS}</style></head><body>{body}'
            f'<div class="chip"><i></i>{esc(site)}</div><div class="bar"></div><script>{FIT_JS}</script></body></html>')


def describe(shot: dict) -> str:
    """For logs."""
    return json.dumps(shot["visual"], ensure_ascii=False)[:100]
