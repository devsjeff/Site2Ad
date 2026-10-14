"""HTML fixtures for the scraper tests: one function per kind of website."""

from __future__ import annotations

import json

from .fixture_server import Route, html

LOREM = (
    "Sharma Sweets has been making fresh mithai, namkeen and festival gift boxes in Bilaspur since 1985. "
    "Every morning our halwais prepare kaju katli, rasgulla and samosa using pure ghee and no preservatives. "
)


def static_site() -> dict:
    """A normal server-rendered business site with JSON-LD, nav, footer, phone, address, offer and CTA."""
    ld = {
        "@context": "https://schema.org", "@type": "Bakery", "name": "Sharma Sweets",
        "description": "Fresh mithai and namkeen made daily in Bilaspur.",
        "telephone": "+91 98765 43210", "logo": "/static/logo.png",
        "address": {"@type": "PostalAddress", "streetAddress": "12 Gandhi Chowk", "addressLocality": "Bilaspur", "addressRegion": "CG", "postalCode": "495001"},
        "sameAs": ["https://www.instagram.com/sharmasweets"],
    }
    home = f"""<!doctype html><html lang="en-IN"><head><meta charset="utf-8">
<title>Home | Sharma Sweets</title>
<meta name="description" content="Fresh mithai and namkeen made daily in Bilaspur.">
<meta property="og:image" content="/img/hero.jpg"><meta name="theme-color" content="#c0392b">
<link rel="icon" href="/favicon.png"><link rel="apple-touch-icon" sizes="180x180" href="/apple.png">
<script type="application/ld+json">{json.dumps(ld)}</script></head>
<body><header><a href="/"><img class="site-logo" src="/static/logo.png" alt="Sharma Sweets logo" width="120" height="40"></a>
<nav><a href="/about">About Us</a><a href="/services">Our Services</a><a href="/products">Products</a><a href="/contact">Contact</a><a href="/privacy">Privacy Policy</a></nav></header>
<main><section class="hero"><h1>Pure ghee sweets, made fresh daily</h1><p>{LOREM}</p>
<a class="btn" href="/contact">Order Now</a><h2>Diwali offer: 20% off on gift boxes</h2></section>
<img src="/img/a.jpg" width="800" height="600" alt="mithai box"><img src="/img/b.jpg" width="640" height="480" alt="kaju katli">
<img src="/img/pixel.gif" width="1" height="1"><img src="/img/tiny.png" width="32" height="32">
<img src="/img/lazy.jpg" data-src="/img/lazy-real.jpg" width="500" height="400">
</main>
<footer><p>12 Gandhi Chowk, Bilaspur, Chhattisgarh 495001</p><a href="tel:+919876543210">Call us</a>
<a href="https://wa.me/919876543210">WhatsApp</a><a href="mailto:hello@sharmasweets.example">Email</a>
<a href="/terms">Terms</a><a href="/about">About</a></footer></body></html>"""
    page = lambda title, body: html(f"<!doctype html><html><head><title>{title} | Sharma Sweets</title><meta name=\"description\" content=\"{title} page of Sharma Sweets.\"></head><body><header><nav><a href=\"/\">Home</a></nav></header><main><h1>{title}</h1><p>{body}</p></main></body></html>")
    return {
        "/": html(home),
        "/about": page("About Us", LOREM + "Our family has served Bilaspur for three generations."),
        "/services": html("<!doctype html><html><head><title>Services | Sharma Sweets</title></head><body><main><h1>Our Services</h1><section><h2>Our services</h2><ul><li>Wedding catering</li><li>Corporate gift boxes</li><li>Festival orders</li></ul></section></main></body></html>"),
        "/products": page("Products", "Kaju katli, rasgulla, samosa, namkeen and gift boxes."),
        "/contact": page("Contact", "Call us on 0771-2345678 or visit the shop on Gandhi Chowk."),
        "/privacy": page("Privacy", "legal text"),
        "/terms": page("Terms", "legal text"),
        "/robots.txt": Route(body="User-agent: *\nDisallow: /private/\nSitemap: {BASE}/sitemap.xml\n", content_type="text/plain"),
        "/sitemap.xml": Route(body="<urlset><url><loc>{BASE}/about</loc></url><url><loc>{BASE}/products</loc></url><url><loc>{BASE}/privacy</loc></url></urlset>", content_type="application/xml"),
    }


def react_shell(real_content: bool = False) -> dict:
    """A Create-React-App style shell. The real content is injected by JavaScript after 300 ms."""
    script = """
setTimeout(function(){
  document.title = 'Green Leaf Cafe';
  document.getElementById('root').innerHTML =
    '<header><nav><a href="/menu">Menu</a><a href="/about">About</a><a href="/contact">Contact</a></nav></header>' +
    '<main><h1>Green Leaf Cafe</h1><p>' + 'Organic coffee, fresh salads and homemade cakes in the heart of Raipur. '.repeat(5) + '</p>' +
    '<img src="/img/cafe1.jpg" width="900" height="600"><img src="/img/cafe2.jpg" width="900" height="600"></main>' +
    '<footer><a href="tel:+917712345678">+91 77123 45678</a><a href="/privacy">Privacy</a></footer>';
}, 300);
"""
    return {
        "/": html(f"""<!doctype html><html><head><title>React App</title></head><body>
<noscript>You need to enable JavaScript to run this app.</noscript><div id="root"></div><script>{script}</script></body></html>"""),
        "/menu": html(f"""<!doctype html><html><head><title>React App</title></head><body><div id="root"></div><script>{script}</script></body></html>"""),
    }


def next_site() -> dict:
    """A Next.js pages-router site whose body is an empty #__next but whose __NEXT_DATA__ carries the content."""
    data = {
        "props": {"pageProps": {
            "siteName": "Urban Fitness Club",
            "hero": {"title": "Train hard in the heart of Nagpur", "description": "Strength, cardio and yoga classes with certified trainers, open from 5 am to 11 pm every single day of the week."},
            "sections": [
                {"heading": "Personal training with certified coaches who build a plan around your goals and schedule."},
                {"heading": "Group classes including zumba, yoga, spinning and functional training for every fitness level."},
            ],
            "images": ["/_next/static/gym1.jpg", "https://cdn.example.com/gym2.webp"],
            "nav": [{"href": "/classes", "label": "Classes"}, {"href": "/pricing", "label": "Pricing"}, {"href": "/contact", "label": "Contact"}],
        }},
        "page": "/", "buildId": "abc123",
    }
    return {
        "/": html(f"""<!doctype html><html><head><title>Create Next App</title></head><body><div id="__next"></div>
<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>"""),
    }


def cloudflare_challenge() -> dict:
    """A Cloudflare 'Just a moment...' interstitial."""
    body = """<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title></head><body>
<div class="main-wrapper"><h1>example.com</h1><h2 id="challenge-error-text">Enable JavaScript and cookies to continue</h2></div>
<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script></body></html>"""
    return {"/": html(body, status=403, headers={"cf-mitigated": "challenge", "server": "cloudflare"}),
            "/robots.txt": Route(body="", status=404)}


def cloudflare_normal() -> dict:
    """A normal, readable site that merely sits behind Cloudflare. Must NOT be reported as blocked."""
    body = f"<!doctype html><html lang=en><head><title>Blue Door Dental</title><meta name=description content='Family dentistry in Pune.'></head><body><header><nav><a href=/about>About</a><a href=/contact>Contact</a><a href=/services>Services</a></nav></header><main><h1>Blue Door Dental</h1><p>{LOREM * 2}</p></main><footer><a href=/privacy>Privacy</a></footer></body></html>"
    return {"/": html(body, headers={"server": "cloudflare", "cf-ray": "8abc-BOM"})}


def many_images(count: int = 30) -> dict:
    """A gallery page with many images of different sizes plus junk (pixels, icons, logo, svg)."""
    imgs = "".join(f'<img src="/img/photo{i}.jpg" width="{300 + i * 20}" height="400" alt="photo {i}">' for i in range(count))
    junk = '<img src="/img/pixel.gif" width="1" height="1"><img src="/i/icon-facebook.png" width="24" height="24"><img src="/img/logo.svg"><img src="data:image/png;base64,AAAA">'
    body = f"<!doctype html><html><head><title>Gallery Studio</title><meta name=description content='Photo studio'><meta property='og:image' content='/img/og.jpg'></head><body><header><nav><a href=/a>A</a><a href=/b>B</a><a href=/c>C</a></nav></header><main><h1>Gallery Studio</h1><p>{LOREM * 2}</p>{imgs}{junk}</main></body></html>"
    return {"/": html(body)}


def minimal_site() -> dict:
    """A site with no phone, no address, no logo, no images: the 'missing data' case."""
    body = f"<!doctype html><html lang=en><head><title>Quiet Books</title></head><body><header><nav><a href=/x>Shelf</a><a href=/y>Events</a><a href=/z>Blog</a></nav></header><main><h1>Quiet Books</h1><p>{LOREM}</p></main></body></html>"
    return {"/": html(body)}


def partial_crawl_site() -> dict:
    """A site whose nav lists four priority pages but two of them fail."""
    nav = '<a href="/about">About</a><a href="/services">Services</a><a href="/contact">Contact</a><a href="/pricing">Pricing</a>'
    home = f"<!doctype html><html><head><title>Metro Movers</title><meta name=description content='Packers and movers'></head><body><header><nav>{nav}</nav></header><main><h1>Metro Movers</h1><p>{LOREM * 2}</p></main><footer><a href=/privacy>Privacy</a></footer></body></html>"
    ok = lambda t: html(f"<!doctype html><html><head><title>{t} | Metro Movers</title></head><body><main><h1>{t}</h1><p>{LOREM}</p></main></body></html>")
    return {
        "/": html(home), "/about": ok("About"), "/services": ok("Services"),
        "/contact": Route(body="boom", status=500), "/pricing": Route(body="boom", status=500),
    }
