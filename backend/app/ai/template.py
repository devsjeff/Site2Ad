"""Deterministic prompt writer. It needs no API key and is the fallback when the AI writer is off or fails.

It builds exactly ONE prompt for ONE ad. It only uses facts from the FactSheet and never writes phone numbers or
addresses into the video prompt (those are added afterwards as text overlays, which is far more reliable than asking a
video model to draw digits).
"""

from __future__ import annotations

import colorsys
import re

from .. import catalog
from ..schemas import AdOptions
from .facts import FactSheet
from .guard import MAX_SHOTS, MIN_SHOTS, PROMPT_MAX_CHARS

# Camera / motion / lighting for each shot position, per visual style. Index = shot position (0 is the opening).
STYLE_SHOTS: dict[str, list[tuple[str, str, str]]] = {
    "cinematic_premium": [
        ("wide establishing shot, 35mm lens, shallow depth of field", "slow dolly-in", "warm golden key light with a soft rim light"),
        ("medium close-up, 50mm lens", "slow lateral slide", "soft directional light with gentle highlights"),
        ("macro close-up of fine detail", "slow push-in with a subtle focus pull", "warm low-key light with glowing highlights"),
        ("low-angle hero shot", "slow upward tilt", "rich contrast with warm backlight"),
        ("overhead top-down shot", "slow gentle rotation", "soft diffused light"),
        ("centred hero framing with empty space for text", "slow pull-back", "warm golden glow on a clean background"),
    ],
    "bold_pop": [
        ("wide punchy shot, 24mm lens", "fast push-in", "bright high-key light with saturated colour"),
        ("medium shot at a playful tilted angle", "quick whip pan", "vivid colour with hard pop light"),
        ("tight close-up on the best detail", "snappy zoom-in", "bright even light, strong contrast"),
        ("low-angle shot full of energy", "quick tilt up", "bold colour light with crisp shadows"),
        ("top-down flat-lay shot", "rapid spin", "bright colourful light"),
        ("centred hero framing with empty space for text", "quick settle to a steady hold", "bright clean light with a pop of brand colour"),
    ],
    "minimal_modern": [
        ("wide, symmetrical, uncluttered frame", "gentle slow push-in", "soft even daylight"),
        ("medium shot with generous negative space", "slow lateral glide", "soft diffused window light"),
        ("close-up on a single clean detail", "barely perceptible drift", "soft shadowless light"),
        ("straight-on frontal shot", "slow tilt down", "clean neutral light"),
        ("overhead shot on a plain surface", "slow rotation", "even soft light"),
        ("centred composition with empty space for text", "slow pull-back to a still hold", "soft clean light"),
    ],
    "nightlife_neon": [
        ("wide night shot with deep shadows, 28mm lens", "rhythmic slow push-in", "glowing neon accent light with reflections"),
        ("medium shot through a haze of light", "smooth orbit", "coloured neon rim light"),
        ("close-up with bokeh lights behind", "quick focus pull", "deep shadows with glowing highlights"),
        ("low-angle shot toward the lights", "slow tilt up", "pulsing coloured light"),
        ("overhead shot with light trails", "slow spin", "neon glow on dark surfaces"),
        ("centred hero framing with empty space for text", "slow pull-back", "steady neon glow on a dark background"),
    ],
    "product_showcase": [
        ("clean studio wide shot", "slow orbit around the subject", "crisp three-point studio lighting"),
        ("hero close-up, 85mm lens", "slow push-in", "soft box key light with a clean rim"),
        ("macro detail shot", "slow slide across the surface", "controlled studio light with soft reflections"),
        ("three-quarter angle", "smooth half orbit", "crisp studio lighting on a clean background"),
        ("top-down shot on a seamless surface", "slow rotation", "even studio light"),
        ("centred hero framing with empty space for text", "slow pull-back to a still hold", "crisp clean studio light"),
    ],
    "corporate_clean": [
        ("bright wide establishing shot", "steady slow push-in", "bright natural daylight"),
        ("medium shot with tidy composition", "smooth lateral slide", "soft natural window light"),
        ("clean close-up on a detail", "slow steady push-in", "bright even light"),
        ("eye-level shot", "gentle tilt", "natural light with soft contrast"),
        ("wide shot of the whole space", "slow pan", "bright natural light"),
        ("centred composition with empty space for text", "steady pull-back to a still hold", "bright clean natural light"),
    ],
}

# What happens in a shot. Two wordings per role so a repeated role does not repeat itself.
ROLE_ACTIONS: dict[str, tuple[str, str]] = {
    "detail": (
        "Show {subject} up close with appealing detail, every item clean, recognisable and unchanged.",
        "Move to another attractive detail of {subject}, keeping shapes, colours and branding exactly the same.",
    ),
    "experience": (
        "Show the atmosphere and experience of {name}: the space, the service and the feeling of being there. Keep people soft-focus or seen from behind.",
        "Show a calm, inviting moment at {name}, with soft-focus people or no people at all.",
    ),
    "offer": (
        "Make the offer the hero: {offer}. Reveal it with a confident motion and a pop of the brand colours.",
        "Return to the offer, {offer}, with the product or space still clearly visible.",
    ),
    "buildup": (
        "Build anticipation for {name} with glimpses of the place getting ready: lights, details and movement.",
        "Add more anticipation with fast, flattering glimpses of {subject}.",
    ),
    "energy": (
        "Peak energy at {name}: lively light, movement and colour, with no faces in sharp close-up.",
        "Keep the energy high with rhythmic movement and glowing detail of {subject}.",
    ),
    "angle": (
        "Show {subject} from a new flattering angle while it stays identical to the reference.",
        "Show a final different angle of {subject}, still identical to the reference.",
    ),
}

MIDDLE_ROLES: dict[str, list[str]] = {
    "awareness": ["detail", "experience", "detail", "experience"],
    "offer": ["offer", "detail", "experience", "offer"],
    "visits": ["experience", "detail", "experience", "detail"],
    "event": ["buildup", "energy", "detail", "energy"],
    "product": ["detail", "angle", "detail", "angle"],
}


def shot_count_for(duration_seconds: int) -> int:
    """How many shots fit a duration (about 2 seconds a shot): 3 up to 5 s, then 4, 5 and at most 6."""
    if duration_seconds <= 5:
        count = 3
    elif duration_seconds <= 9:
        count = 4
    elif duration_seconds <= 14:
        count = 5
    else:
        count = 6
    return max(MIN_SHOTS, min(MAX_SHOTS, count))


def sanitize(text: str, limit: int = 400) -> str:
    """Make website text safe to place in a prompt: one line, no section markers, no code fences, length capped."""
    text = re.sub(r"(?i)negative\s+prompt\s*:", " ", text or "")
    text = re.sub(r"(?i)\bshot\s+\d+\b", "scene", text)
    text = re.sub(r"(?i)\b(option|concept|version|alternative|variant|idea)\s*(\d|[a-c]\b|one|two|three)", r"\1", text)
    text = text.replace("`", "").replace("<", "").replace(">", "")
    return " ".join(text.split())[:limit].strip()


def color_name(hex_value: str) -> str:
    """Rough English name for a #rrggbb colour (video models understand names better than hex codes)."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_value.strip())
    if not match:
        return ""
    raw = match.group(1)
    r, g, b = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    if lightness < 0.12:
        return "black"
    if lightness > 0.93:
        return "white"
    if s < 0.12:
        return "charcoal grey" if lightness < 0.35 else "light grey" if lightness > 0.7 else "grey"
    degrees = h * 360
    if degrees < 15 or degrees >= 345:
        name = "red"
    elif degrees < 40:
        name = "orange"
    elif degrees < 65:
        name = "yellow"
    elif degrees < 165:
        name = "green"
    elif degrees < 195:
        name = "teal"
    elif degrees < 255:
        name = "blue"
    elif degrees < 290:
        name = "purple"
    else:
        name = "pink"
    if lightness < 0.3:
        return f"deep {name}"
    if lightness > 0.72:
        return f"light {name}"
    return name


def color_names(hex_values: list[str], limit: int = 3) -> list[str]:
    """Distinct colour names for up to `limit` brand colours."""
    names: list[str] = []
    for value in hex_values:
        name = color_name(value)
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _fmt_seconds(value: float) -> str:
    """Format seconds without a trailing .0."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def shot_windows(duration_seconds: int, shots: int) -> list[tuple[str, str]]:
    """Split the duration into `shots` equal-ish windows, as (start, end) strings."""
    step = duration_seconds / shots
    return [(_fmt_seconds(i * step), _fmt_seconds((i + 1) * step if i < shots - 1 else duration_seconds)) for i in range(shots)]


def negative_prompt(add_overlays: bool) -> str:
    """The negative prompt text; in overlay mode it also forbids any text drawn by the video model."""
    items = list(catalog.NEGATIVE_PROMPT_ITEMS)
    if add_overlays:
        items.insert(0, "any text, letters, numbers, captions or logos drawn by the video model")
    return ", ".join(items)


def _subject_phrase(facts: FactSheet) -> str:
    """What the middle shots are about: a listed service, else the category, else the business itself."""
    return _subjects(facts)[0]


def _subjects(facts: FactSheet) -> list[str]:
    """Subjects for the middle shots, in turn: the listed services, else the category, else the business itself."""
    if facts.services:
        return list(facts.services[:4])
    if facts.category:
        return [f"the {facts.category.lower()} offering"]
    return ["what the business offers"]


def loop_line(duration_seconds: int, loop_seconds: int) -> str:
    """Instruction for a clip that will be repeated to fill a longer ad (empty when it is not looped)."""
    if loop_seconds <= duration_seconds:
        return ""
    return (
        f"LOOP: this {duration_seconds}-second clip is repeated to fill a {loop_seconds}-second ad, so the last shot must flow "
        "seamlessly back into the first: end with the same framing, lighting and colours as the opening, keep the camera "
        "moving smoothly and continuously, no hard ending, no fade to black and no title card."
    )


def _world_line(facts: FactSheet, has_reference: bool) -> str:
    """Without a reference image the model invents the visuals: anchor them in the real business."""
    if has_reference:
        return ""
    what = facts.category.lower() if facts.category else "business"
    things = ", ".join(facts.services[:4]) or "what the business offers"
    return (
        f"VISUAL WORLD: realistic, believable footage of a {what} setting showing {things}; appetising, high-end commercial "
        "look; generic unbranded props, no invented logos, brand names or signage."
    )


def _reference_line(has_reference: bool) -> str:
    """The instruction about the reference image (hero image)."""
    if has_reference:
        return (
            "REFERENCE IMAGE: the attached reference image is the exact first frame. Keep the product, logo, shapes and "
            "colours exactly as shown; start from it and animate gently without redrawing or replacing it."
        )
    return "REFERENCE IMAGE: none supplied; create believable, realistic visuals that fit the business and avoid inventing logos."


def _roles(goal: str, shots: int) -> list[str]:
    """Role of each shot: an opening, goal-specific middle shots and a closing shot."""
    middle = MIDDLE_ROLES.get(goal, MIDDLE_ROLES["awareness"])
    return ["opening"] + middle[: shots - 2] + ["closing"]


def _shot_action(role: str, repeat: int, facts: FactSheet, has_reference: bool, subject: str, looping: bool = False) -> str:
    """The action sentence of one shot; `repeat` is how many earlier shots had the same role."""
    name = facts.name
    if role == "opening":
        if has_reference:
            return f"The reference image of {name} fills the frame as the opening; bring it to life with a gentle, natural motion."
        return f"Open on an inviting, realistic scene that introduces {name} and {subject}."
    if role == "closing":
        if looping:
            return f"Ease back toward the opening framing of {name} with the same light and colours, so the clip can start again without a visible jump. Leave empty space for text."
        end = f"End on a clean, stable hero frame of {name}"
        if facts.cta:
            end += f", ready for the call to action: {facts.cta}"
        return end + ". Leave empty space for text and hold steady for the last second."
    variants = ROLE_ACTIONS.get(role, ROLE_ACTIONS["detail"])
    if role == "offer" and not facts.offer:
        variants = ROLE_ACTIONS["detail"]
    return variants[repeat % 2].format(name=name, subject=subject, offer=facts.offer)


def _overlay_line(facts: FactSheet, add_overlays: bool) -> str:
    """The text-overlay plan. With overlays on, text is added after generation; otherwise the model may draw short words."""
    texts: list[str] = [f'"{sanitize(facts.name, 80)}"']
    if facts.offer:
        texts.append(f'"{sanitize(facts.offer, 120)}"')
    if facts.cta:
        texts.append(f'"{sanitize(facts.cta, 60)}"')
    plan = " then ".join(texts)
    if add_overlays:
        return (
            f"TEXT OVERLAYS: short large text added in editing after the video is generated: {plan}. Do not draw any text, "
            "letters or numbers in the video itself and keep the lower third calm for the overlay."
        )
    return f"TEXT OVERLAYS: only these short words, in clean, large, correctly spelled lettering: {plan}. Nothing else is written."


def build_template_prompt(
    facts: FactSheet, options: AdOptions, *, has_reference: bool, duration_seconds: int, loop_seconds: int = 0,
) -> str:
    """Write the full prompt (positive part, then 'NEGATIVE PROMPT: ...') for ONE ad.

    `loop_seconds` > `duration_seconds` means the clip will be repeated to fill that length, so it is asked to loop cleanly.
    """
    platform = catalog.PLATFORMS[options.platform]
    goal = catalog.GOALS[options.goal]
    style = catalog.STYLES[options.style]
    tone = catalog.TONES[options.tone]
    aspect = options.aspect_ratio
    shots = shot_count_for(duration_seconds)
    subject = sanitize(_subject_phrase(facts), 80)
    subjects = [sanitize(s, 80) for s in _subjects(facts)]
    looping = loop_seconds > duration_seconds
    name = sanitize(facts.name, 120)
    clean = FactSheet(
        name=name, category=sanitize(facts.category, 60), services=[sanitize(s, 60) for s in facts.services],
        offer=sanitize(facts.offer, 140), cta=sanitize(facts.cta, 60),
    )

    business = f"BUSINESS: {name}"
    if clean.category:
        business += f" ({clean.category})"
    if clean.offer:
        business += f" | OFFER: {clean.offer}"
    if clean.cta:
        business += f" | CALL TO ACTION: {clean.cta}"

    head = [
        f"Create ONE {duration_seconds}-second advertising video for {name}.",
        f"FORMAT: {aspect}, {duration_seconds} seconds, one continuous ad with {shots} shots, made for {platform['label']} ({platform['audience']}).",
        business,
    ]
    optional: dict[str, str] = {}
    description = sanitize(facts.description, 300)
    if description:
        optional["about"] = f"ABOUT: {description}"
    if clean.services:
        optional["offering"] = "OFFERING: " + ", ".join(clean.services[:5])
    notes = sanitize(facts.user_notes, 300)
    if notes:
        optional["notes"] = f"EXTRA DIRECTION FROM THE ADVERTISER: {notes}"
    world = _world_line(clean, has_reference)
    if world:
        optional["world"] = world
    loop = loop_line(duration_seconds, loop_seconds)
    colours = color_names(facts.brand_colors)
    if colours:
        optional["colours"] = "BRAND COLOURS: " + ", ".join(colours) + " (use as accents; never recolour the product)."
    style_lines = [f"GOAL: {goal['focus']}.", f"STYLE: {style['visual']}.", f"TONE: {tone['mood']}."]
    roles = _roles(options.goal, shots)
    windows = shot_windows(duration_seconds, shots)
    tech = STYLE_SHOTS[options.style]
    shot_lines: list[str] = []
    seen: dict[str, int] = {}
    for index, role in enumerate(roles):
        camera, motion, lighting = tech[-1] if role == "closing" else tech[min(index, len(tech) - 1)]
        shot_subject = subjects[(index - 1) % len(subjects)] if 0 < index < shots - 1 else subject
        action = _shot_action(role, seen.get(role, 0), clean, has_reference, shot_subject, looping)
        seen[role] = seen.get(role, 0) + 1
        start, end = windows[index]
        shot_lines.append(
            f"SHOT {index + 1} ({start}-{end}s): Camera: {camera}; Motion: {motion}; Lighting: {lighting}; Action: {action}"
        )
    tail = [
        _overlay_line(clean, options.add_overlays),
        f"AUDIO: {tone['music']}, no spoken voice-over because the sound may be off.",
        "NEGATIVE PROMPT: " + negative_prompt(options.add_overlays),
    ]

    def assemble() -> str:
        """Join all parts in reading order."""
        order = [optional.get("about"), optional.get("offering")]
        return "\n".join(
            head + [x for x in order if x] + style_lines
            + [x for x in (optional.get("world"), optional.get("colours"), optional.get("notes")) if x]
            + [_reference_line(has_reference)] + ([loop] if loop else []) + shot_lines + tail
        )

    text = assemble()
    for key in ("about", "notes", "world", "offering", "colours"):  # drop optional parts, least important first, if too long
        if len(text) <= PROMPT_MAX_CHARS:
            break
        optional.pop(key, None)
        text = assemble()
    return text
