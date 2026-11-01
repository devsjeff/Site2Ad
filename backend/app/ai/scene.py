"""Scene prompts for AI video models: ONE continuous, filmable scene in plain sentences.

Video models (Magic Hour text-to-video / image-to-video) work best with one coherent scene: a concrete subject, an
action, a setting, one camera movement, lighting and restrictions. Duration and aspect ratio are API parameters, so they
are not repeated here. Business data that is not visual (phone numbers, addresses, prices, offers) never goes into the
scene: exact text is added afterwards with FFmpeg, where it stays readable and correct.
"""

from __future__ import annotations

import re
from .facts import FactSheet
from .formula import formula_for
from .template import color_names, sanitize

SCENE_AVOID = (
    "No generated text, letters, numbers, logos, watermarks, posters, signs or printed clothing; no people just posing, "
    "talking or gesturing at the camera; no distorted hands or faces; no sudden cuts."
)

# Words that mark a service / description fragment as non-visual business data (it is left out of the scene).
NON_VISUAL = re.compile(
    r"\d|@|https?:|www\.|\b(office|offices|head ?office|address|contact|phone|call|email|login|sign ?in|register|privacy|terms|"
    r"cookie|career|careers|jobs|subscribe|newsletter|download|faq|support|price|pricing|offer|discount|sale|deal|book now)\b",
    re.I,
)

# (keywords, subject + action, setting) — the first match decides the visual concept of the ad.
CONCEPTS: list[tuple[tuple[str, ...], str, str]] = [
    (("walk", "walking", "steps", "step counter", "running", "jogging", "workout plan", "fitness plan", "health plan"),
     "A person walks briskly along a sunny park path, checking a step-count ring on a smartwatch that fills up, then smiles and keeps going, clearly fitter and energised",
     "a green city park on a bright morning"),
    (("mobile app", "app store", "play store", "android", "ios", "download the app"),
     "A person uses the app on a smartphone in everyday life, the screen showing a clean interface of abstract shapes and no readable text, and visibly gets the result they wanted",
     "a bright, real everyday setting"),
    (("news", "newspaper", "journal", "magazine", "publisher", "media", "editorial"),
     "A journalist reviews the day's stories on a tablet while colleagues work softly out of focus; the tablet shows a clean, generic news layout with photographs and abstract interface elements, without readable text",
     "a bright, modern newsroom with large windows"),
    (("bakery", "sweet", "mithai", "cake", "pastry", "dessert", "confection"),
     "Fresh {item} is arranged on a tray by careful hands, textures and glaze catching the light",
     "a warm, spotless bakery counter with glass display cases"),
    (("restaurant", "cafe", "café", "coffee", "kitchen", "food", "pizza", "burger", "dining", "bistro", "bar", "grill"),
     "{item} is freshly prepared and served, steam and texture clearly visible, as a guest smiles softly out of focus",
     "a warm, inviting {place} interior"),
    (("hotel", "resort", "stay", "villa", "homestay", "travel", "tour", "holiday"),
     "A guest steps into an elegant room and opens the curtains to a calm, beautiful view",
     "a stylish, light-filled hotel room"),
    (("salon", "spa", "beauty", "cosmetic", "skin", "makeup", "barber", "nail"),
     "A stylist gives a client a calm, careful treatment, the client relaxed and confident",
     "a clean, elegant salon with soft mirrors and plants"),
    (("gym", "fitness", "yoga", "pilates", "crossfit", "sport", "training"),
     "A person trains with focus and good form, movement smooth and powerful",
     "a modern, bright fitness studio"),
    (("clinic", "dental", "dentist", "doctor", "hospital", "health", "medical", "pharmacy", "physio"),
     "A friendly professional reassures a patient during a calm consultation",
     "a clean, modern clinic with soft daylight"),
    (("school", "academy", "course", "education", "coaching", "tuition", "learning", "university", "college"),
     "Students listen and take notes while an instructor explains with enthusiasm",
     "a bright, modern classroom"),
    (("real estate", "property", "properties", "apartment", "realty", "homes", "builder", "construction", "interior"),
     "The camera reveals a beautifully finished home, light falling across clean surfaces and furniture",
     "a spacious, modern living space"),
    (("car", "auto", "automobile", "garage", "motor", "bike", "vehicle"),
     "A gleaming vehicle is revealed under studio light, reflections gliding across the paint",
     "a clean, premium showroom"),
    (("fashion", "clothing", "apparel", "boutique", "wear", "jewel", "jewellery", "jewelry", "saree", "shoe"),
     "A model turns gracefully to show the fabric, cut and detail of {item}",
     "a stylish boutique with soft, flattering light"),
    (("software", "saas", "app", "web", "website", "digital", "agency", "tech", "it services", "develop", "design", "marketing", "studio", "startup", "consult"),
     "A small creative team collaborates around a large screen showing abstract interface designs and charts without readable text, one person pointing as the others nod",
     "a modern, bright studio office with plants and large windows"),
]
DEFAULT_CONCEPT = (
    "A customer clearly uses and benefits from {item}: the product or service itself is front and centre and easy to recognise",
    "a bright, real setting where it is used",
)

# One camera movement and one lighting look per style (from the first, most reliable entry of each style).
STYLE_CAMERA = {
    "cinematic_premium": ("slow, smooth dolly-in", "warm golden key light with a soft rim light and shallow depth of field"),
    "bold_pop": ("confident push-in", "bright, saturated, high-key light"),
    "minimal_modern": ("gentle, slow glide", "soft, even daylight and generous clean space"),
    "nightlife_neon": ("rhythmic slow push-in", "glowing neon accents, deep shadows and reflections"),
    "product_showcase": ("slow orbit around the subject", "crisp studio lighting on a clean background"),
    "corporate_clean": ("steady, slow push-in", "bright natural daylight with soft contrast"),
}
TEXT_SPACE = {"9:16": "the lower third", "1:1": "the lower part of the frame", "16:9": "the right side of the frame"}


def visual_items(facts: FactSheet, limit: int = 3) -> list[str]:
    """Services that can be filmed (no phone numbers, offices, prices or links)."""
    items: list[str] = []
    for service in facts.services:
        clean = sanitize(service, 60)
        if clean and not NON_VISUAL.search(clean) and clean.lower() not in {i.lower() for i in items}:
            items.append(clean)
        if len(items) >= limit:
            break
    return items


def about_line(facts: FactSheet) -> str:
    """The first one or two sentences of the description that describe the business itself (no numbers, links or offers)."""
    sentences = re.split(r"(?<=[.!?])\s+", sanitize(facts.description, 400))
    kept = [s for s in sentences if s and not NON_VISUAL.search(s)][:2]
    return " ".join(kept)


# Businesses whose product is a screen or a place get a set of three tailored concepts (title, subject + action, setting),
# written like real city footage: a real location, practical light, people, and the screen as the hero.
IN_CAB_KEYWORDS = ("in-cab", "in cab", "cab", "cabs", "taxi", "taxis", "rideshare", "ride-hailing", "uber", "ola", "car screen")
SCREEN_KEYWORDS = (
    "dooh", "out-of-home", "out of home", "ooh", "billboard", "billboards", "digital signage", "signage", "led screen",
    "screen advertising", "advertising", "advertisement", "advertise", "ad network", "media buying", "transit media",
) + IN_CAB_KEYWORDS
IN_CAB_SET: list[tuple[str, str, str]] = [
    ("In-cab screen at night",
     "A seat-back tablet screen inside a taxi glows with a bright, colourful advertisement (a product photo and bold abstract shapes, no readable text) while city lights and shopfronts slide past the window in soft bokeh",
     "a clean, modern taxi cabin moving through a busy Indian city at night"),
    ("Passenger scans the screen",
     "A passenger in the back seat notices the glowing seat-back ad screen, smiles, and holds up a phone to scan it, the screen's light reflecting softly on their face",
     "a taxi cabin at dusk, warm street lights streaking past the windows"),
    ("City screens at dusk",
     "A huge curved LED screen on a city building plays a vivid, colourful 3D animation (abstract shapes, no readable text) as crowds cross the street below and traffic flows",
     "a busy downtown intersection at dusk with glass towers and an elevated railway"),
]
SCREEN_SET: list[tuple[str, str, str]] = [IN_CAB_SET[2], IN_CAB_SET[0], IN_CAB_SET[1]]
REAL_FOOTAGE = "a smooth handheld gimbal shot on a cinema camera, with natural motion blur and authentic city detail"


def concept_set_for(facts: FactSheet) -> list[tuple[str, str, str]]:
    """Three tailored (title, action, setting) concepts when the business sells screens or places; empty otherwise."""
    haystack = " ".join([facts.name, facts.category, facts.description, " ".join(facts.services)]).lower()
    if not any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", haystack) for k in SCREEN_KEYWORDS):
        return []
    in_cab = any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", haystack) for k in IN_CAB_KEYWORDS)
    return IN_CAB_SET if in_cab else SCREEN_SET


def concept_for(facts: FactSheet) -> tuple[str, str]:
    """(story, setting) for this business: hook -> turn -> payoff from its ad formula (screen businesses: their own set)."""
    tailored = concept_set_for(facts)
    if tailored:
        return tailored[0][1], tailored[0][2]
    formula = formula_for(facts)
    items = visual_items(facts)
    item = items[0] if items else (facts.category.lower() or "the service")
    story = f"{formula.hook}; then {formula.turn}; finally {formula.payoff}".format(item=item)
    return story, formula.setting


def build_scene_prompt(
    facts: FactSheet, *, style: str, aspect_ratio: str, has_reference: bool, looping: bool, notes: str = "", visual: str = "",
    mood: str = "", ad_style: str = "", placement: str = "",
) -> str:
    """ONE flowing present-tense paragraph that opens on the hero visual, then setting, camera, light and limits.

    `visual` is the brief's chosen concept (else the business's ad formula). Non-visual text (what the business is called)
    comes last, because video models give the first words the most weight.
    """
    action, setting = concept_for(facts)
    camera, lighting = STYLE_CAMERA.get(style, STYLE_CAMERA["cinematic_premium"])
    tailored = bool(concept_set_for(facts))
    formula = None if tailored or visual else formula_for(facts)
    story = sanitize(visual, 600) if visual else f"{action}."
    story = story[:1].upper() + story[1:]
    parts = []
    if has_reference:
        parts.append("Starting exactly from the provided image, which comes to life without changing:")
    parts.append(story if story.endswith(".") else story + ".")
    parts.append(f"Setting: {setting}." if not visual else "")
    focus = ", ".join(visual_items(facts)[:2]) or (facts.category.lower() if facts.category else "")
    parts.append(
        "Say it visually: with the sound off, the first second makes clear what is advertised"
        + (f" ({focus})" if focus else "") + ", shown in use and clearly in frame."
    )
    if ad_style:
        parts.append(f"This is a {ad_style}.")
    if placement:
        parts.append(f"Composition: {placement}.")
    parts.append(f"Camera: {formula.camera if formula else camera}. Light: {lighting}.")
    if tailored:
        parts.append(f"It looks like real footage: {REAL_FOOTAGE}.")
    if mood:
        parts.append(f"Mood: {mood}.")
    colours = color_names(facts.brand_colors)
    if colours:
        parts.append(f"Subtle {' and '.join(colours[:2])} accents echo the brand colours.")
    if notes:
        parts.append(f"Direction from the advertiser: {sanitize(notes, 200)}")
    if looping:
        parts.append("The clip will loop, so it ends with the same framing and light as it begins.")
    parts.append(f"Keep {TEXT_SPACE.get(aspect_ratio, 'some of the frame')} calm for text added in editing.")
    parts.append("One continuous shot, smooth natural motion, realistic proportions.")
    parts.append(f"An ad for {sanitize(facts.name, 80)}.")
    parts.append(SCENE_AVOID)
    return " ".join(part for part in parts if part)
