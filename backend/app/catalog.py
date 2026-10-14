"""Static option lists shared by the API, the prompt builder and the frontend (via GET /api/config)."""

from __future__ import annotations

PLATFORMS: dict[str, dict] = {
    "taxi_screen": {"label": "Taxi screen", "aspect_ratio": "16:9", "audience": "commuters riding in a taxi, watching a seat-back screen with the sound often low"},
    "instagram_reel": {"label": "Instagram Reel", "aspect_ratio": "9:16", "audience": "mobile users scrolling a vertical feed"},
    "youtube_shorts": {"label": "YouTube Shorts", "aspect_ratio": "9:16", "audience": "mobile users watching short vertical videos"},
    "facebook_feed": {"label": "Facebook feed", "aspect_ratio": "1:1", "audience": "people scrolling a mixed social feed"},
}

GOALS: dict[str, dict] = {
    "awareness": {"label": "Brand awareness", "focus": "introduce the brand and what it does, ending on the name and a simple call to action"},
    "offer": {"label": "Promote offer", "focus": "make the offer the hero of the ad and end on the call to action"},
    "visits": {"label": "Drive visits", "focus": "show the place and the experience so viewers want to visit, ending with the location or call to action"},
    "event": {"label": "Event promo", "focus": "build excitement for the event and end on how to take part"},
    "product": {"label": "Product launch", "focus": "present the product as the hero from several flattering angles"},
}

STYLES: dict[str, dict] = {
    "cinematic_premium": {"label": "Cinematic", "visual": "cinematic premium look, shallow depth of field, rich contrast, warm highlights, smooth slow camera moves"},
    "bold_pop": {"label": "Bold & Pop", "visual": "bold pop look, saturated colours, punchy contrast, dynamic quick camera moves, playful energy"},
    "minimal_modern": {"label": "Minimal", "visual": "minimal modern look, clean uncluttered frames, soft even light, generous negative space, gentle motion"},
    "nightlife_neon": {"label": "Nightlife", "visual": "nightlife neon look, deep shadows, glowing coloured light, reflections, rhythmic camera motion"},
    "product_showcase": {"label": "Showcase", "visual": "product showcase look, crisp studio lighting, clean background, slow orbiting and push-in camera moves"},
    "corporate_clean": {"label": "Corporate", "visual": "corporate clean look, bright natural light, tidy composition, steady confident camera moves"},
}

TONES: dict[str, dict] = {
    "friendly": {"label": "Friendly", "mood": "warm, welcoming, upbeat", "music": "light upbeat acoustic-pop"},
    "premium": {"label": "Premium", "mood": "refined, confident, luxurious", "music": "smooth cinematic ambient with soft piano"},
    "energetic": {"label": "Energetic", "mood": "high energy, exciting, fast", "music": "driving upbeat electronic percussion"},
    "elegant": {"label": "Elegant", "mood": "graceful, calm, sophisticated", "music": "gentle strings and soft piano"},
    "family_friendly": {"label": "Family", "mood": "cheerful, safe, welcoming for all ages", "music": "playful bright instrumental"},
}

CATEGORIES: dict[str, str] = {
    "food_dining": "Food & Dining",
    "hotels_travel": "Hotels & Travel",
    "shops_fashion": "Shops & Fashion",
    "luxury_premium": "Luxury & Premium",
    "events_nightlife": "Events & Nightlife",
}

DURATION_CHOICES = (5, 10, 15, 20)

NEGATIVE_PROMPT_ITEMS = (
    "distorted or garbled text",
    "misspelled words",
    "extra or invented logos",
    "watermarks",
    "warped faces and hands",
    "blurry or low-resolution frames",
    "flickering",
    "sudden unrelated scene changes",
    "changing the product shape or colours",
    "phone numbers or addresses rendered inside the video",
    "violence or unsafe content",
)


def aspect_for(platform: str) -> str:
    """Return the aspect ratio for a platform id, defaulting to 16:9."""
    return PLATFORMS.get(platform, PLATFORMS["taxi_screen"])["aspect_ratio"]


def parse_aspect(aspect: str) -> tuple[int, int]:
    """Turn '16:9' into (16, 9); fall back to (16, 9) on bad input."""
    try:
        w, h = aspect.split(":")
        w_i, h_i = int(w), int(h)
        if w_i > 0 and h_i > 0:
            return w_i, h_i
    except (ValueError, AttributeError):
        pass
    return 16, 9
