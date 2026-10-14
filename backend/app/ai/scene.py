"""Scene prompts for AI video models: ONE continuous, filmable scene in plain sentences.

Video models (Magic Hour text-to-video / image-to-video) work best with one coherent scene: a concrete subject, an
action, a setting, one camera movement, lighting and restrictions. Duration and aspect ratio are API parameters, so they
are not repeated here. Business data that is not visual (phone numbers, addresses, prices, offers) never goes into the
scene: exact text is added afterwards with FFmpeg, where it stays readable and correct.
"""

from __future__ import annotations

import re
from .facts import FactSheet
from .template import color_names, sanitize

SCENE_AVOID = "No generated text, letters, numbers, logos, watermarks or signage; no distorted hands or faces; no sudden cuts."

# Words that mark a service / description fragment as non-visual business data (it is left out of the scene).
NON_VISUAL = re.compile(
    r"\d|@|https?:|www\.|\b(office|offices|head ?office|address|contact|phone|call|email|login|sign ?in|register|privacy|terms|"
    r"cookie|career|careers|jobs|subscribe|newsletter|download|faq|support|price|pricing|offer|discount|sale|deal|book now)\b",
    re.I,
)

# (keywords, subject + action, setting) — the first match decides the visual concept of the ad.
CONCEPTS: list[tuple[tuple[str, ...], str, str]] = [
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
DEFAULT_CONCEPT = ("The people behind {name} at work, focused and welcoming, showing {item}", "their real, well-kept workplace")

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


def concept_for(facts: FactSheet) -> tuple[str, str]:
    """(subject + action, setting) for this business, chosen from what it is (category, name, description, services)."""
    haystack = " ".join([facts.name, facts.category, facts.description, " ".join(facts.services)]).lower()
    items = visual_items(facts)
    item = ", ".join(items[:2]) if items else (facts.category.lower() or "what they offer")
    place = (facts.category or "venue").lower()
    for keywords, action, setting in CONCEPTS:
        if any(re.search(rf"\b{re.escape(k)}\b", haystack) for k in keywords):
            return action.format(item=item, place=place, name=facts.name), setting.format(place=place)
    action, setting = DEFAULT_CONCEPT
    return action.format(item=item, name=sanitize(facts.name, 80)), setting


def build_scene_prompt(
    facts: FactSheet, *, style: str, aspect_ratio: str, has_reference: bool, looping: bool, notes: str = "", visual: str = "",
    mood: str = "",
) -> str:
    """ONE paragraph describing ONE continuous scene. `visual` is the brief's chosen concept (else one is picked here)."""
    name = sanitize(facts.name, 80)
    action, setting = concept_for(facts)
    camera, lighting = STYLE_CAMERA.get(style, STYLE_CAMERA["cinematic_premium"])
    category = facts.category.lower().strip()
    kind = category if category.endswith(("business", "shop", "store", "studio", "agency", "company", "bakery", "restaurant", "cafe", "hotel", "salon", "clinic", "gym", "school", "publisher")) else (f"{category} business" if category else "business")
    parts = [f"A premium, realistic commercial for {name}, a {kind}."]
    about = about_line(facts)
    if about:
        parts.append(f"About the business: {about}")
    if has_reference:
        parts.append("Start exactly from the provided image and bring it to life gently, keeping everything in it unchanged.")
    parts.append(sanitize(visual, 600) if visual else f"{action}, in {setting}.")
    parts.append(f"The camera makes a {camera}; {lighting}; natural skin tones and believable real-world detail.")
    if mood:
        parts.append(f"Mood: {mood}.")
    colours = color_names(facts.brand_colors)
    if colours:
        parts.append(f"Subtle {' and '.join(colours[:2])} accents in the set echo the brand colours.")
    if notes:
        parts.append(f"Direction from the advertiser: {sanitize(notes, 200)}")
    if looping:
        parts.append("The clip will loop, so it ends with the same framing, light and colours as it begins, with no hard ending.")
    parts.append(f"Keep {TEXT_SPACE.get(aspect_ratio, 'some of the frame')} calm and uncluttered for text added in editing.")
    parts.append("One continuous shot, smooth natural movement, consistent lighting and realistic proportions.")
    parts.append(SCENE_AVOID)
    return " ".join(parts)
