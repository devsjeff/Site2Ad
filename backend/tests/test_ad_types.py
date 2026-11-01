"""Ad types, brand-led captions and sound."""

from __future__ import annotations

import pytest
from PIL import Image

from app import catalog
from app.ai.brief import build_brief_request, build_template_brief
from app.ai.captions import ad_captions, brand_name, domain_of, occasion_in, place_of, real_quote
from app.ai.facts import FactSheet
from app.schemas import AdOptions
from app.video.finalize import OverlaySpec, render_layers
from app.video.voice import music_source, spoken


def facts(**extra) -> FactSheet:
    values = {"name": "Night Owl Cafe", "category": "Cafe", "description": "Fresh coffee brewed all night.", "services": ["filter coffee"]}
    return FactSheet(**{**values, **extra})


def test_the_seventeen_ad_types_are_complete():
    assert len(catalog.AD_TYPES) == 18  # 17 + "auto"
    for key, info in catalog.AD_TYPES.items():
        assert info["label"] and info["hint"]
        if key != "auto":
            assert info["focus"] and info["direction"] and "{item}" in info["story"] and any("{name}" in c for c in info["captions"])


def test_unknown_ad_type_voice_and_music_are_refused():
    for field in ("ad_type", "voice", "music"):
        with pytest.raises(ValueError):
            AdOptions(**{field: "nope"})


def test_ad_type_reaches_the_prompt_and_replaces_the_goal():
    options = AdOptions(ad_type="problem_solution", goal="offer")
    request = build_brief_request(facts(), options, 10)
    assert catalog.AD_TYPES["problem_solution"]["focus"] in request and catalog.AD_TYPES["problem_solution"]["direction"] in request
    assert catalog.GOALS["offer"]["focus"] not in request
    brief = build_template_brief(facts(), options, duration_seconds=10)
    assert brief.concepts[0].title == "Problem → Solution ad" and "filter coffee" in brief.concepts[0].visual


def test_auto_keeps_the_goal():
    assert catalog.objective("offer", "auto") == catalog.GOALS["offer"]["focus"]
    assert catalog.ad_type_line("auto") == ""
    assert ad_captions("auto", name="Night Owl Cafe") == []


def test_captions_name_the_brand_and_never_invent_values():
    assert ad_captions("recruitment", name="Night Owl Cafe")[0] == "Night Owl Cafe is hiring"
    assert not any("Call" in c for c in ad_captions("lead_generation", name="Night Owl Cafe"))  # no phone: no phone line
    assert "Call 98765 43210" in ad_captions("lead_generation", name="Night Owl Cafe", phone="98765 43210", services=["repairs"])
    offer = ad_captions("offer", name="Night Owl Cafe", services=["filter coffee"])
    assert all("%" not in c for c in offer) and offer[0] == "Filter coffee from Night Owl Cafe"


def test_testimonials_use_only_a_real_pasted_quote():
    assert real_quote("no quote here") == ""
    assert not any(c.startswith("“") for c in ad_captions("testimonial", name="Night Owl Cafe", instructions="Show the counter"))
    quoted = ad_captions("testimonial", name="Night Owl Cafe", instructions='Use: "Best coffee in town, every night"')
    assert quoted[0] == "“Best coffee in town, every night”"


def test_occasion_place_domain_and_brand_clean_up():
    assert occasion_in("a Diwali special") == "Diwali" and occasion_in("") == "this season"
    assert ad_captions("seasonal", name="Night Owl Cafe", instructions="for diwali")[0] == "Celebrate Diwali with Night Owl Cafe"
    assert place_of("12 MG Road, Indore, MP 452001, India") == "Indore" and place_of("") == ""
    assert domain_of("https://www.nightowl.in/menu") == "nightowl.in"
    assert brand_name("Home | Night Owl Cafe - Best Coffee") == "Night Owl Cafe"
    assert brand_name("Coca-Cola") == "Coca-Cola"


def test_short_ads_show_only_captions_that_can_be_read(tmp_path):
    spec = OverlaySpec(name="Night Owl Cafe", captions=["One", "Two", "Three"])
    short, _ = render_layers(854, 480, spec, tmp_path / "a", 5.0)
    long, _ = render_layers(854, 480, spec, tmp_path / "b", 12.0)
    assert sum(l.kind == "caption" for l in short) == 2 and sum(l.kind == "caption" for l in long) == 3  # 2.1 s is the least a line stays


def test_qr_ad_gets_a_bigger_labelled_code(tmp_path):
    def size(label):
        layers, _ = render_layers(854, 480, OverlaySpec(qr_url="https://nightowl.example", qr_label=label), tmp_path / (label or "x"))
        with Image.open(next(l for l in layers if l.kind == "qr").path) as image:
            return image.size

    assert size("Scan me")[1] > size("")[1]


def test_brand_keeps_its_colours_when_a_caption_wraps():
    from app.video.finalize import _branded_line, load_font
    from app.video.palette import Palette

    fill = (0, 200, 255, 255)
    palette = Palette(text=(255, 255, 255, 255))
    words = {"night", "owl", "cafe"}

    def coloured(line):
        image = Image.new("RGBA", (420, 60), (0, 0, 0, 0))
        _branded_line(image, (4, 8), line, words, load_font(30, True), (palette.text, fill, fill), palette, 30)
        return sum(1 for r, g, b, a in image.getdata() if a > 200 and b > 200 and r < 90)

    assert coloured("Visit Night") and coloured("Owl Cafe today")  # both halves of the wrapped name
    assert coloured("Visit today") == 0


def test_phone_numbers_are_read_digit_by_digit():
    assert spoken("Call 98765 43210") == "Call 9 8 7 6 5 4 3 2 1 0"


def test_music_is_ffmpeg_generated():
    assert music_source("none", 5) is None
    assert music_source("upbeat", 5).startswith("aevalsrc=")


def test_ai_overlay_text_is_checked_and_names_the_brand():
    import json

    from app.ai.captions import text_plan
    from app.ai.copywriter import build_copy_request, parse_copy

    PLAN = text_plan(10, "taxi_screen")
    sheet = facts()
    answer = lambda *lines, **extra: json.dumps({"understanding": "A night cafe.", "captions": list(lines), "cta": "", **extra})  # noqa: E731
    good = parse_copy(answer("Coffee when the city sleeps", "Filter coffee brewed all night", "Night Owl Cafe stays open"), sheet, "Night Owl Cafe", PLAN)
    assert good.understanding == "A night cafe." and len(good.captions) == 3
    named = parse_copy(answer("Coffee when the city sleeps", "Filter coffee brewed all night"), sheet, "Night Owl Cafe", PLAN)
    assert named.captions[-1] == "Night Owl Cafe"  # the brand is always named
    fake = parse_copy(answer("Rated 5 stars by locals", "50% off tonight", "Night Owl Cafe"), sheet, "Night Owl Cafe", PLAN)
    assert fake is None  # invented proof and prices are dropped, too little is left
    assert parse_copy("not json", sheet, "Night Owl Cafe", PLAN) is None
    request = build_copy_request(sheet, AdOptions(ad_type="explainer"), "Night Owl Cafe", PLAN, __import__("app.ai.playbook", fromlist=["x"]).GENERAL, [])
    assert "Night Owl Cafe" in request and "Explainer" in request


# ------------------------------------------------------------------ playbooks, text plan, cues, looks, image ranking

def food_facts(**extra) -> FactSheet:
    values = {
        "name": "Spice Route", "category": "Restaurant", "description": "Hyderabadi biryani and kebabs cooked in a clay oven.",
        "services": ["Chicken biryani", "Galouti kebab", "Mutton haleem"], "address": "12 MG Road, Indore, MP 452001", "website": "https://spiceroute.in",
    }
    return FactSheet(**{**values, **extra})


def test_every_category_has_a_playbook_and_the_right_one_is_chosen():
    from app.ai.formula import FORMULAS
    from app.ai.playbook import PLAYBOOKS, playbook_for

    assert {f.id for f in FORMULAS} <= set(PLAYBOOKS)
    assert playbook_for(food_facts()).id == "food"
    assert playbook_for(facts(name="Iron Temple Gym", category="Gym", description="Strength training and yoga classes.", services=["yoga"])).id == "fitness"
    assert playbook_for(None).id == "general"
    for book in PLAYBOOKS.values():
        assert book.voice in catalog.VOICES and book.music in catalog.MUSIC and book.hook and book.close


def test_text_plan_fits_the_length_and_the_screen():
    from app.ai.captions import text_plan

    assert [text_plan(d, "taxi_screen").count for d in (5, 10, 15, 20)] == [2, 3, 4, 5]
    cab, reel = text_plan(10, "taxi_screen"), text_plan(10, "instagram_reel")
    assert cab.max_chars < reel.max_chars and cab.seconds_each >= 2.0
    assert cab.beats[0] == "hook" and cab.beats[-1] == "close"


def test_restaurant_lines_name_real_dishes_and_the_brand():
    from app.ai.captions import plan_captions, text_plan
    from app.ai.playbook import playbook_for

    book = playbook_for(food_facts())
    kw = dict(name="Spice Route", about="Hyderabadi biryani and kebabs", services=["Chicken biryani", "Galouti kebab", "Mutton haleem"], place="Indore")
    ten = plan_captions("auto", book, plan=text_plan(10, "taxi_screen"), **kw)
    assert ten[0] == "Hungry? Try our chicken biryani" and len(ten) == 3
    assert any("Galouti kebab" in line for line in ten) and "Spice Route" in ten[-1]
    twenty = plan_captions("auto", book, plan=text_plan(20, "taxi_screen"), **kw)
    assert len(twenty) == 5 and len({line.lower() for line in twenty}) == 5
    assert all(len(line) <= 40 for line in twenty)  # readable at a glance on a cab tablet


def test_lines_never_invent_missing_facts():
    from app.ai.captions import plan_captions, text_plan
    from app.ai.playbook import GENERAL, PLAYBOOKS

    for book in (*PLAYBOOKS.values(), GENERAL):
        lines = plan_captions("auto", book, plan=text_plan(20, "taxi_screen"), name="Acme Co")
        assert lines and any("Acme Co" in line for line in lines)
        assert not any(token in " ".join(lines) for token in ("{", "}", "None", "%", "$"))


def test_ad_type_leads_and_offer_stays_real():
    from app.ai.captions import plan_captions, text_plan
    from app.ai.playbook import PLAYBOOKS

    plan = text_plan(10, "taxi_screen")
    lines = plan_captions("offer", PLAYBOOKS["retail"], plan=plan, name="Style Hub", services=["Cotton kurtas"], offer="Flat 20% off today")
    assert lines[0] == "Flat 20% off today"
    none = plan_captions("offer", PLAYBOOKS["retail"], plan=plan, name="Style Hub", services=["Cotton kurtas"])
    assert not any("%" in line for line in none)


def test_caption_schedule_and_voice_cues_share_one_timeline():
    from app.video.finalize import caption_schedule, visible_captions
    from app.video.voice import build_cues

    schedule = caption_schedule(3, 10.0)
    assert schedule[0][0] == 0.3 and schedule[-1][1] == 10.0
    assert all(a[1] == b[0] for a, b in zip(schedule, schedule[1:]))  # no gap, no overlap
    assert len(visible_captions(["a"] * 9, 5.0)) == 2 and len(visible_captions(["a"] * 9, 20.0)) == 5
    lines = ["Hungry? Try our chicken biryani", "Galouti kebab and mutton haleem", "Visit Spice Route in Indore"]
    cues = build_cues("Spice Route", lines, "Order now", "Flat 20% off", 10.0, schedule)
    assert [round(c.start, 2) for c in cues] == [round(s + 0.12, 2) for s, _ in schedule]
    assert all(c.end > c.start for c in cues) and cues[0].end <= cues[1].start
    assert cues[1].extra == "Flat 20% off" and cues[-1].extra == "Order now"  # offer rides on line two, the call to action closes
    assert not build_cues("Spice Route", ["“Best biryani in town”"], "", "", 5.0, [(0.3, 5.0)])  # a customer quote is never voiced


def test_every_look_renders_with_real_ffmpeg(tmp_path):
    import asyncio

    from app.video.compose import LOOKS, Segment, compose

    frames = []
    for number, colour in enumerate(("#c0392b", "#27ae60", "#2980b9")):
        path = tmp_path / f"f{number}.jpg"
        Image.new("RGB", (320, 180), colour).save(path)
        frames.append(path)

    async def run():
        for name, look in LOOKS.items():
            segments = [Segment("website_image", path, True, 2.0, str(path)) for path in frames]
            result = await compose(segments, tmp_path / f"{name}.mp4", size=(320, 180), style="cinematic_premium", keep_audio=False, work_dir=tmp_path / name, look=look)
            assert result.duration > 4.5, name

    asyncio.run(run())


def _photo(seed: int) -> Image.Image:
    """A photo-like picture: soft coloured shapes with real edges."""
    import random

    from PIL import ImageDraw, ImageFilter

    rng = random.Random(seed)
    image = Image.new("RGB", (640, 360), (200, 190, 170))
    draw = ImageDraw.Draw(image)
    for _ in range(40):
        x, y = rng.randint(0, 600), rng.randint(0, 320)
        draw.ellipse((x, y, x + rng.randint(40, 200), y + rng.randint(40, 160)), fill=tuple(rng.randint(30, 230) for _ in range(3)))
    return image.filter(ImageFilter.GaussianBlur(1.5))


def test_best_pictures_are_kept_and_duplicates_dropped(tmp_path):
    from app.video.images import rank_frames

    pictures = {
        "banner": Image.linear_gradient("L").resize((640, 360)).convert("RGB"),  # a smooth gradient banner
        "card": Image.new("RGB", (640, 360), (30, 30, 34)),  # a plain card
        "photo": _photo(1),
        "twin": _photo(1),  # the same picture again
        "other": _photo(2),
    }
    paths = {}
    for name, image in pictures.items():
        path = tmp_path / f"{name}.jpg"
        image.save(path, quality=95)
        paths[name] = path
    # the real shape in the pipeline: (kind, source url, file path)
    names = [source for _, source, _ in rank_frames([("website_image", name, path) for name, path in paths.items()], 2)]
    assert len(names) == 2 and "banner" not in names and "card" not in names
    assert not ({"photo", "twin"} <= set(names))  # a duplicate never takes the second place
    small = {paths["other"]: 200}  # a tiny original ranks below a full-size one
    assert [source for _, source, _ in rank_frames([("website_image", "photo", paths["photo"]), ("website_image", "other", paths["other"])], 1, small)] == ["photo"]


def test_auto_voice_and_music_resolve_from_the_category():
    from app.ai.playbook import PLAYBOOKS

    assert catalog.VOICES["auto"]["voice"] == "" and "auto" in catalog.MUSIC
    assert PLAYBOOKS["fitness"].music == "upbeat" and PLAYBOOKS["hotel"].music == "calm"
    assert PLAYBOOKS["finance"].voice != PLAYBOOKS["food"].voice  # a confident voice for money, a warm one for food


def test_cab_context_reaches_every_ai_writer():
    from app.ai.brief import build_brief_request
    from app.ai.captions import text_plan
    from app.ai.copywriter import build_copy_request
    from app.ai.playbook import playbook_for

    sheet = food_facts()
    options = AdOptions(platform="taxi_screen", duration_seconds=15)
    request = build_brief_request(sheet, options, 10)
    assert "seat-back tablet" in request and "how this kind of business is sold" in request
    copy = build_copy_request(sheet, options, "Spice Route", text_plan(15, "taxi_screen"), playbook_for(sheet), ["Hungry? Try our chicken biryani"])
    assert "exactly 4 captions" in copy and "at most 40 characters and 7 words" in copy and "sound off" in copy
    assert catalog.PLATFORMS["taxi_screen"]["shoot"].startswith("bold, simple")


def test_overlay_with_every_layer_does_not_stall(tmp_path):
    """Logo, QR, name, offer, phone, call to action and five captions together: looping layer inputs must be capped,
    otherwise FFmpeg stalls (a 15-second ad once took longer than the 3-minute limit)."""
    import asyncio
    import subprocess

    from app.video.finalize import finalize_video
    from app.video.base import ffmpeg_path

    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=8", "-pix_fmt", "yuv420p", str(src)], check=True)
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (96, 96), (200, 30, 30, 255)).save(logo)
    spec = OverlaySpec(
        name="Night Owl Cafe", offer="2 for 1 coffee", phone="98765 43210", cta="Order now", qr_url="https://nightowl.example", logo_path=logo,
        captions=["Coffee when the city sleeps", "Filter coffee, all night", "Fresh pastries too", "Open till 4 am", "Visit Night Owl Cafe"],
    )
    result = asyncio.run(finalize_video(src, tmp_path / "out.mp4", spec, timeout=60.0))
    assert result.applied and not result.warnings and result.qr_added
