"""The studio pipeline: structures, figures, claims and their sources, the storyboard rules, the scenes, the checks and the command line."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from PIL import Image

from app.ai.llm import LlmError
from app.studio import ai as studio_ai
from app.studio import check, cli, figures, notes, scenes, storyboard
from app.studio.config import FPS, STRUCTURES, VIDEO_TYPES, Run, StageError, allocate, min_length, slug_for, words_allowed, words_limit

from .fixture_server import FixtureServer, html

# ---------------------------------------------------------------------------------------------- structures


@pytest.mark.parametrize("video_type", VIDEO_TYPES)
def test_every_structure_ends_on_one_call_to_action(video_type):
    beats = STRUCTURES[video_type]
    assert beats[-1].id == "cta" and [b.id for b in beats].count("cta") == 1
    assert all(b.weight > 0 for b in beats) and len({b.id for b in beats}) == len(beats)


def test_the_structures_follow_the_table():
    ids = {t: [b.id for b in STRUCTURES[t]] for t in VIDEO_TYPES}
    assert ids["promo"] == ["offer_hook", "what_you_get", "proof", "price_deadline", "cta"]
    assert ids["hook_ad"] == ["pain", "setup", "turn", "product", "proof", "price", "cta"]
    assert ids["pitch"] == ["problem", "why_now", "solution", "how_it_works", "traction", "ask", "cta"]
    assert ids["showcase"] == ["result_first", "feature_1", "feature_2", "feature_3", "cta"]
    assert ids["explainer"] == ["question", "analogy", "step_1", "step_2", "step_3", "outcome", "cta"]
    assert ids["testimonial"] == ["customer_problem", "quote", "result_numbers", "cta"]
    assert ids["launch"] == ["teaser", "reveal", "key_feature", "availability_price", "cta"]
    assert all(b.visual == "screenshot" for b in STRUCTURES["showcase"][:-1])  # a showcase shows real footage


@pytest.mark.parametrize("video_type", VIDEO_TYPES)
@pytest.mark.parametrize("length", [15, 20, 30, 45])
def test_durations_add_up_and_every_shot_can_be_read(video_type, length):
    if length < min_length(video_type):
        return
    seconds = allocate(length, STRUCTURES[video_type])
    assert sum(seconds) == length and min(seconds) >= 1.8 and all(s * 2 == int(s * 2) for s in seconds)


def test_a_length_that_is_too_short_is_refused_clearly():
    with pytest.raises(StageError, match="too short"):
        allocate(8, STRUCTURES["pitch"])


def test_word_budget_matches_the_measured_voice_speed():
    assert words_allowed(4.0) == 7 and words_limit(4.0) == 8  # about two words a second, the speed of the Indian-English voices
    assert slug_for("https://www.backseatnetwork.com/pricing") == "backseatnetwork-com"


# ---------------------------------------------------------------------------------------------- figures

ALLOWED = "Media is ₹4,000 per cab per month plus GST. GST at 18% is added. 15K+ cabs. Passengers watch 20 to 45 minutes."


def test_a_figure_must_be_in_the_notes():
    assert figures.unsupported_figures("Starts at ₹4,000 per cab", ALLOWED) == []
    assert figures.unsupported_figures("from 4000 plus 18% GST", ALLOWED) == []  # the same figures, written without the symbol or comma
    assert figures.unsupported_figures("Starts at ₹5,000 and 50% off", ALLOWED) == ["₹5,000", "50%"]
    assert figures.unsupported_figures("in 3 steps", ALLOWED) == []  # a single digit counts the steps of the video itself
    assert figures.unsupported_figures("15K cabs", ALLOWED) == []


def test_the_currency_symbol_is_kept_on_screen_and_restored():
    assert figures.missing_symbols("Start at 4000 per cab", ALLOWED) and not figures.missing_symbols("Start at ₹4,000", ALLOWED)
    assert figures.restore_symbols("from 4000 per cab, 18% GST", ALLOWED) == "from ₹4,000 per cab, 18% GST"


def test_numbers_are_spoken_as_people_say_them():
    assert figures.speakable("₹4,000 per cab, 18%, 15K") == "4,000 rupees per cab, 18 percent, 15 thousand"
    assert figures.speakable("$5 a month") == "5 dollars a month"


def test_comparisons_and_unbacked_words_are_caught():
    assert figures.unsupported_words("The best and only choice, unlike traditional ads", "GPS tracked playouts") == ["best", "only", "traditional", "unlike"]
    assert figures.unsupported_words("only one cab", "you can book only one cab") == []
    claims = "Each passenger watches the ad for 20 to 45 minutes with no skip button"
    assert figures.grounded("watch time", claims) == 0.5 and figures.grounded("Passengers watch for 20 minutes", claims) == 1.0
    assert figures.grounded("Standard OOH unverified", claims) == 0.0
    assert figures.stem("watches") == "watch" and figures.stem("passengers") == "passenger"


# ---------------------------------------------------------------------------------------------- claims and their sources

CAPTURE = {
    "title": "Cab Ads | Backseat Network", "url": "https://backseatnetwork.com",
    "blocks": [
        {"line": 4, "text": "In-cab ads across India", "top": 0, "heading": 1, "button": False, "li": False, "quote": False, "region": "main"},
        {"line": 6, "text": "Media is ₹4,000 per cab per month.", "top": 50, "heading": 0, "button": False, "li": False, "quote": False, "region": "main"},
        {"line": 8, "text": "GST at 18% is added on the invoice.", "top": 80, "heading": 0, "button": False, "li": False, "quote": False, "region": "main"},
        {"line": 10, "text": "Every play is counted, a live GPS map shows the cabs carrying your ad.", "top": 120, "heading": 0, "button": False, "li": False, "quote": False, "region": "main"},
        {"line": 12, "text": "and QR scans land in your own analytics.", "top": 150, "heading": 0, "button": False, "li": False, "quote": False, "region": "main"},
    ],
    "screenshots": [{"id": "01", "file": "01_hero.png", "kind": "hero", "lines": [4, 12], "text": "In-cab ads across India | Media is ₹4,000 per cab per month.", "summary": "the hero"}],
}


def claim(text, source, evidence, kind="price"):
    return {"text": text, "kind": kind, "source": source, "evidence": evidence}


def test_a_claim_needs_a_real_source_that_really_says_it():
    data = {"claims": [
        claim("Media costs ₹4,000 per cab per month", "page.md line 6", "Media is ₹4,000 per cab per month"),
        claim("Free for everyone", "page.md line 6", "Free for everyone"),  # the words are not on that line
        claim("It is cheap", "page.md line 99", "It is cheap"),  # the line does not exist
        claim("Costs ₹5,000 per cab", "page.md line 6", "Media is ₹4,000 per cab per month"),  # the figure is not in the evidence
        claim("Starts at ₹4,000", "screenshot 01", "Media is ₹4,000 per cab per month"),
        claim("No source at all", "", "x y"),
    ]}
    valid, rejected = notes.validate_claims(data, CAPTURE)
    assert [c["id"] for c in valid] == ["C1", "C2"] and [c["source"] for c in valid] == ["page.md line 6", "screenshot 01"]
    assert [r["reason"] for r in rejected][:2] == ["the quoted evidence is not in the cited source", "no valid source"]
    assert "figure not in the evidence" in rejected[2]["reason"]


def test_a_fact_split_over_two_lines_is_cited_with_the_exact_lines():
    data = {"claims": [claim("Plays are counted and scans reach your analytics", "page.md line 10",
                             "a live GPS map shows the cabs carrying your ad. and QR scans land in your own analytics", "proof")]}
    valid, _ = notes.validate_claims(data, CAPTURE)
    assert valid and valid[0]["source"] == "page.md lines 10-12"


@pytest.mark.parametrize("written", ["page.md line 6", "page.md line L6", "L6", "line 6", "page.md:6"])
def test_the_ways_a_writer_cites_a_line_are_understood(written):
    assert notes.source_text(written, CAPTURE)[0] == "page.md line 6"


# ---------------------------------------------------------------------------------------------- the storyboard

NOTES = {"what_it_is": "x", "who_for": "y", "rejected": [], "claims": [
    {"id": "C1", "text": "Backseat Network runs silent screens in airport cabs and city fleets.", "kind": "feature", "source": "page.md line 4", "evidence": "silent screens in airport cabs and city fleets"},
    {"id": "C2", "text": "Media is ₹4,000 per cab per month plus GST at 18%.", "kind": "price", "source": "page.md line 6", "evidence": "Media is ₹4,000 per cab per month plus GST at 18%"},
    {"id": "C3", "text": "Every play is counted on a live GPS map.", "kind": "proof", "source": "page.md line 10", "evidence": "Every play is counted, a live GPS map"},
]}
BOARD_CAPTURE = {**CAPTURE, "screenshots": [{"id": "01", "file": "a.png", "kind": "hero", "lines": [], "text": "", "summary": "the hero"},
                                            {"id": "02", "file": "b.png", "kind": "pricing", "lines": [], "text": "", "summary": "pricing"}]}


def shot(beat, voice, visual, claims, caption="", transition="fade"):
    return {"beat": beat, "voice": voice, "visual": visual, "caption": caption, "claims": claims, "transition": transition}


def good_promo():
    return {"shots": [
        shot("offer_hook", "Silent screens in airport cabs", {"type": "screenshot", "id": "01", "focus": "top", "zoom": "in"}, ["C1"]),
        shot("what_you_get", "Silent screens in city fleets", {"type": "graphic", "template": "stats", "props": {"stats": [{"value": "Silent", "label": "screens in cabs"}]}}, ["C1"]),
        shot("proof", "Every play is counted live", {"type": "screenshot", "id": "02", "focus": "center", "zoom": "out"}, ["C3"], caption="Every play counted"),
        shot("price_deadline", "Media is ₹4,000 per cab per month", {"type": "graphic", "template": "price", "props": {"price": "₹4,000", "unit": "per cab per month", "note": "plus GST at 18%"}}, ["C2"]),
        shot("cta", "Launch a campaign", {"type": "graphic", "template": "cta", "props": {"headline": "Ready when you are", "button": "Launch", "url": "backseatnetwork.com"}}, ["C2"]),
    ]}


def problems_of(data, length=20.0):
    seconds = allocate(length, STRUCTURES["promo"])
    return storyboard.validate_storyboard(data, "promo", seconds, NOTES, BOARD_CAPTURE, "Launch")


def test_a_good_storyboard_passes():
    assert problems_of(good_promo()) == []


def test_the_storyboard_rules_are_enforced():
    data = good_promo()
    data["shots"][3]["voice"] = "Media is ₹9,999 per cab per month"
    assert any("not in the claims you cite" in p for p in problems_of(data))
    data = good_promo()
    data["shots"][1]["voice"] = "Best screens in the whole world for every business"
    assert any("not backed by the cited claims" in p or "uses" in p for p in problems_of(data))
    data = good_promo()
    data["shots"].pop()
    assert "exactly 5 shots" in problems_of(data)[0]
    data = good_promo()
    data["shots"][0]["claims"] = ["C9"]
    assert any("unknown claim ids" in p for p in problems_of(data))
    data = good_promo()
    data["shots"][3]["voice"] = "Media is priced per cab and charged by the month plus tax for every single vehicle"
    assert any("shorten it" in p for p in problems_of(data))
    data = good_promo()
    data["shots"][2]["visual"] = data["shots"][1]["visual"] = {"type": "graphic", "template": "price", "props": {"price": "₹4,000"}}
    assert any("same visual" in p for p in problems_of(data))
    data = good_promo()
    data["shots"][1]["visual"] = {"type": "graphic", "template": "cta", "props": {"button": "Launch"}}
    assert any("only the last shot may be a call to action" in p for p in problems_of(data))


def test_a_dropped_currency_symbol_is_repaired_not_rejected():
    data = good_promo()
    data["shots"][3]["visual"]["props"]["price"] = "4000"
    assert problems_of(data) == [] and data["shots"][3]["visual"]["props"]["price"] == "₹4,000"


def test_visuals_are_accepted_in_the_ways_a_writer_spells_them():
    assert storyboard.normalise_visual({"template": "cta", "props": {"button": "Go"}})["type"] == "graphic"
    assert storyboard.normalise_visual({"type": "cta", "button": "Go"}) == {"type": "graphic", "template": "cta", "props": {"button": "Go"}}
    assert storyboard.normalise_visual({"id": "05"})["type"] == "screenshot"


def test_a_testimonial_without_a_real_quote_stops_with_a_clear_message(tmp_path):
    run = Run(tmp_path)
    Run.write_json(run.request_json, {"url": "https://x.example", "video_type": "testimonial", "length": 20, "platform": "16:9", "claims": []})
    Run.write_json(run.product_json, NOTES)
    Run.write_json(run.brand_json, {"tone": "x"})
    Run.write_json(run.capture_json, BOARD_CAPTURE)
    Run.write_json(run.assumptions_json, {"video_type": "testimonial", "voice": "neerja", "music": "calm", "cta": {"text": "Go", "target": "x"}, "must_include": []})
    with pytest.raises(StageError, match="real customer quote"):
        storyboard.build_storyboard(run)


# ---------------------------------------------------------------------------------------------- the AI helper


class FakeWriter:
    """Stands in for LlmClient: canned answers in order."""

    enabled = True
    model = "fake"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.settings = types.SimpleNamespace(ai_prompt_base_url="https://gateway.example/v1", ai_prompt_model="fake")
        self.calls = 0

    async def complete(self, system, user, max_tokens=1400, *, model="", timeout=0.0, reasoning=None):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def fake_ai():
    def install(*answers):
        writer = FakeWriter(*answers)
        studio_ai.set_client(writer)
        return writer

    yield install
    studio_ai.set_client(None)


def test_a_bad_answer_is_sent_back_with_its_problems(fake_ai):
    writer = fake_ai("not json at all", '```json\n{"n": 1}\n```', '{"n": 2}')
    data = studio_ai.ask_json("sys", "user", lambda d: [] if d["n"] == 2 else ["n must be 2"], what="a test")
    assert data == {"n": 2} and writer.calls == 3


def test_when_the_writer_never_gets_it_right_the_stage_stops_with_the_reasons(fake_ai):
    fake_ai('{"n": 1}', '{"n": 1}')
    with pytest.raises(StageError, match="n must be 2"):
        studio_ai.ask_json("sys", "user", lambda d: ["n must be 2"], what="a test", tries=2)


def test_a_daily_limit_is_reported_plainly(fake_ai):
    fake_ai(LlmError("The AI writer's free daily limit is used up. Add credits at the provider, or wait for the daily reset."))
    with pytest.raises(StageError, match="daily limit"):
        studio_ai.ask_json("sys", "user", lambda d: [], what="a test", tries=1)


# ---------------------------------------------------------------------------------------------- scenes

THEME = {"mode": "light", "bg": "#faf8f5", "bg2": "#ffffff", "ink": "#171717", "muted": "#52525b", "primary": "#ff6600", "accent": "#ffb27a", "on_primary": "#ffffff",
         "card": "#ffffff", "line": "rgba(0,0,0,.1)", "head": "Outfit", "body": "Inter", "radius": "24px", "btn_radius": "999px"}
PROPS = {
    "title": {"headline": "Hello brand", "sub": "A line"}, "big_number": {"from": "20 MIN", "to": "45 MIN", "label": "ETA"},
    "steps": {"steps": ["One", "Two", "Three"]}, "stats": {"stats": [{"value": "15K+", "label": "cabs"}]}, "price": {"price": "₹4,000", "unit": "per cab", "note": "plus GST"},
    "quote": {"quote": "Great", "who": "A customer"}, "compare": {"left_label": "Before", "left": "Slow", "right_label": "After", "right": "Fast"},
    "cta": {"headline": "Go now", "button": "Launch", "url": "x.example"},
}


EXPECTED_TEXT = {"title": "Hello", "big_number": "45 MIN", "steps": "Two", "stats": "15K+", "price": "₹4,000", "quote": "Great", "compare": "Slow", "cta": "Launch"}


@pytest.mark.parametrize("name", sorted(PROPS))
def test_every_graphic_renders_in_the_brand_colours(name):
    page = scenes.scene_html({"seconds": 4, "visual": {"type": "graphic", "template": name, "props": PROPS[name]}, "caption": ""}, THEME, (1280, 720), "x.example")
    assert "--primary:#ff6600" in page and "'Outfit'" in page and "x.example" in page
    assert EXPECTED_TEXT[name] in page


def test_text_from_a_website_cannot_inject_html():
    props = {"headline": "<script>alert(1)</script> Buy", "sub": "<img src=x onerror=alert(1)>"}
    page = scenes.scene_html({"seconds": 4, "visual": {"type": "graphic", "template": "title", "props": props}, "caption": ""}, THEME, (1280, 720), "<b>x</b>")
    assert "<script>alert(1)" not in page and "<img src=x" not in page and "&lt;script&gt;" in page and "<b>x</b>" not in page


def test_the_theme_follows_the_brand_notes():
    brand = {"colors": {"mode": "dark", "primary": "#112233", "accent": "#445566", "background_dark": "#0a0a0a", "background_light": "#ffffff", "ink": "#111111", "on_primary": "#ffffff"},
             "fonts": {"heading": "Space Grotesk", "body": "Inter"}, "shapes": {"card_radius_px": 20, "button_radius_px": 9999}}
    theme = scenes.theme_from(brand)
    assert theme["bg"] == "#0a0a0a" and theme["ink"] == "#ffffff" and theme["btn_radius"] == "999px" and "Space+Grotesk" in scenes.font_links(theme)


# ---------------------------------------------------------------------------------------------- scenes in a real browser


def chromium_page(width=1280, height=720):
    playwright = pytest.importorskip("playwright.sync_api")
    manager = playwright.sync_playwright().start()
    try:
        browser = manager.chromium.launch()
    except Exception:
        manager.stop()
        pytest.skip("Chromium is not installed")
    return manager, browser, browser.new_page(viewport={"width": width, "height": height})


def test_scenes_animate_and_text_fits_in_a_real_browser(tmp_path):
    manager, browser, page = chromium_page()
    try:
        for name in ("price", "stats", "cta", "steps"):
            path = tmp_path / f"{name}.html"
            path.write_text(scenes.scene_html({"seconds": 3, "visual": {"type": "graphic", "template": name, "props": PROPS[name]}, "caption": ""}, THEME, (1280, 720), "x.example"), encoding="utf-8")
            page.goto(path.as_uri(), wait_until="load")
            seek = "ms => document.getAnimations().forEach(a => { a.pause(); a.currentTime = ms; })"
            page.evaluate(seek, 0)
            start = page.screenshot(type="jpeg", quality=80)
            page.evaluate(seek, 4000)
            page.evaluate("window.__fit()")
            assert page.evaluate("window.__overflow") == [], name
            end = page.screenshot(type="jpeg", quality=80)
            assert start != end, f"{name} did not animate"
    finally:
        browser.close()
        manager.stop()


def test_a_real_screenshot_scene_keeps_its_card_centred(tmp_path):
    image = tmp_path / "shot.png"
    Image.new("RGB", (1440, 900), (30, 90, 160)).save(image)
    manager, browser, page = chromium_page()
    try:
        path = tmp_path / "scene.html"
        path.write_text(scenes.scene_html({"seconds": 3, "visual": {"type": "screenshot", "id": "01", "focus": "top", "zoom": "in"}, "caption": "From ₹4,000"},
                                          THEME, (1280, 720), "x.example", image.as_uri()), encoding="utf-8")
        page.goto(path.as_uri(), wait_until="load")
        page.evaluate("ms => document.getAnimations().forEach(a => { a.pause(); a.currentTime = ms; })", 2500)
        box = page.evaluate("(() => { const r = document.querySelector('.shot-card').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")
        assert abs((box[0] + box[2]) / 2 - 640) < 3 and abs((box[1] + box[3]) / 2 - 360) < 3  # centred (its pop animation must not move it)
    finally:
        browser.close()
        manager.stop()


# ---------------------------------------------------------------------------------------------- capture, in a real browser

PAGE = """<html><head><title>Cab Ads Co</title><style>body{margin:0;font-family:sans-serif}section{padding:60px;min-height:420px}
.hero{background:#ff6600;color:#fff}.dark{background:#18181b;color:#fff}.btn{background:#ff6600;color:#fff;border-radius:999px;padding:12px 24px;border:0}
#chat{position:fixed;right:10px;bottom:10px;width:200px;height:80px;background:#25d366}</style></head><body>
<section class="hero"><h1>In-cab ads across India</h1><p>Silent screens in airport cabs and city fleets.</p><button class="btn">Launch a campaign</button></section>
<section><h2>Pricing</h2><p>Media costs ₹4,000 per cab per month plus GST at 18%.</p><p>Per cab per month, one price in every city.</p></section>
<section class="dark"><h2>Trusted by brands</h2><p>Every play is counted and a live GPS map shows where your ad runs. 15K+ cabs.</p></section>
<section><h2>How it works</h2><ul><li>Brief the creative</li><li>Pick cabs and months</li><li>Pay and go live</li></ul></section>
<footer><p>© Cab Ads Co. Privacy. Terms.</p></footer><div id="chat">Ask us anything</div></body></html>"""


def test_capture_saves_numbered_text_screenshots_and_styles(tmp_path):
    manager, browser, _ = chromium_page()  # skips the test when Chromium is missing
    browser.close()
    manager.stop()
    from app.studio.capture import capture

    with FixtureServer({"/": html(PAGE)}) as site:
        run = Run(tmp_path / "run")
        record = capture(run, site.base + "/")
    text = run.page_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "# In-cab ads across India" in text and "[Launch a campaign]" in text and "- Pick cabs and months" in text
    assert "Ask us anything" not in text  # the floating chat widget is hidden before reading the page
    for block in record["blocks"]:  # a citation "page.md line N" must point at the text it names
        assert lines[block["line"] - 1].lstrip("#-> []").rstrip("]").startswith(block["text"][:15]) or block["text"][:15] in lines[block["line"] - 1]
    assert 3 <= len(record["screenshots"]) <= 10 and all((run.shots_dir / s["file"]).is_file() for s in record["screenshots"])
    assert any(s["kind"] == "pricing" for s in record["screenshots"]) and any(s["kind"] == "hero" for s in record["screenshots"])
    shots_md = run.screenshots_md.read_text(encoding="utf-8")
    assert all(s["file"] in shots_md for s in record["screenshots"]) and "₹4,000" in shots_md
    assert record["styles"]["h1"]["font"] and "#ff6600" in {b["bg"] for b in record["styles"]["buttons"]}
    hero = next(s for s in record["screenshots"] if s["kind"] == "hero")
    with Image.open(run.shots_dir / hero["file"]) as image:  # the floating chat widget (bright green) must not be in the screenshot
        assert not any(px[:3] == (37, 211, 102) for px in image.convert("RGB").getdata())


# ---------------------------------------------------------------------------------------------- checks and the safe fallback


def test_blank_flat_and_repeated_frames_are_caught(tmp_path):
    paths = []
    for number, colour in enumerate([(0, 0, 0), (200, 120, 40), (200, 120, 40)], start=1):
        path = tmp_path / f"f{number}.jpg"
        Image.new("RGB", (160, 90), colour).save(path)
        paths.append(path)
    found = check.frame_problems(paths)
    assert any("shot 1" in p and "black" in p for p in found)
    assert any("shot 2" in p and "flat" in p for p in found) and any("shot 3" in p and "same" in p for p in found)


def test_the_safe_rewrite_always_passes_the_storyboard_rules():
    data = good_promo()
    data["shots"][1]["voice"] = "A sentence that is far too long to say in four seconds on any voice"
    data["shots"][1]["visual"] = {"type": "graphic", "template": "compare", "props": {"left": "Standard OOH", "right": "Us"}}
    data["shots"][1]["claims"] = ["C2"]
    for index, item in enumerate(data["shots"]):
        item["seconds"] = allocate(20, STRUCTURES["promo"])[index]
        item["n"] = index + 1
    check.safe_rewrite(data["shots"][1], NOTES, {"cta": {"text": "Launch"}, "must_include": []})
    assert problems_of(data) == [] and data["shots"][1]["visual"]["template"] == "title"


def test_a_comma_inside_a_number_is_not_a_place_to_cut():
    assert check.fit_clause("Advertising starts at ₹4,000 per cab per month, plus GST on every invoice", 8) == "Advertising starts at ₹4,000 per cab per month"
    assert not check.trim_words("Starts at ₹4,000 per cab per month plus", 7).endswith("plus")


# ---------------------------------------------------------------------------------------------- the command line


def test_the_command_line_runs_the_stages_in_order_and_can_stop_for_review(tmp_path, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(cli, "RUNNERS", {name: (lambda run, args, name=name: ran.append(name)) for name in cli.RUNNERS})
    assert cli.main(["run", "--url", "https://x.example", "--run", str(tmp_path / "a")]) == 0
    assert ran == ["capture", "notes", "brand", "assumptions", "storyboard", "build", "check"]
    ran.clear()
    assert cli.main(["run", "--url", "https://x.example", "--run", str(tmp_path / "b"), "--review"]) == 0
    assert ran == ["capture", "notes", "brand", "assumptions"] and "04_assumptions.json" in capsys.readouterr().out
    ran.clear()
    assert cli.main(["run", "--run", str(tmp_path / "b"), "--from", "storyboard"]) == 0
    assert ran == ["storyboard", "build", "check"]


def test_the_command_line_reports_a_stopped_stage_without_a_traceback(tmp_path, monkeypatch, capsys):
    def stop(run, args):
        raise StageError("the page could not be captured")

    monkeypatch.setattr(cli, "RUNNERS", {**cli.RUNNERS, "capture": stop})
    assert cli.main(["capture", "--url", "https://x.example", "--run", str(tmp_path / "c")]) == 1
    assert "STOPPED: the page could not be captured" in capsys.readouterr().out


def test_the_command_line_refuses_a_length_that_is_too_short(tmp_path, capsys):
    assert cli.main(["capture", "--url", "https://x.example", "--type", "pitch", "--length", "8", "--run", str(tmp_path / "d")]) == 1
    assert "needs at least 14 seconds" in capsys.readouterr().out
