"""Static option lists shared by the API, the prompt builder and the frontend (via GET /api/config)."""

from __future__ import annotations

PLATFORMS: dict[str, dict] = {
    "taxi_screen": {"label": "In-cab tablet", "aspect_ratio": "16:9", "audience": "riders in a cab, watching a silent landscape tablet on the back of the front seat. No voiceover, few words, large type",
        "viewing": "a rider seated in a cab watches a seat-back tablet for a few seconds, usually with the sound off and the car in motion, so the message must work from the text alone: one idea, big words, high contrast, and the first 2 seconds must already show or name what is offered",
        "shoot": "bold, simple, high-contrast frames with one clear hero subject near the centre, readable at a glance on a small cab screen, with calm space for large text",
        "max_chars": 40, "max_words": 7},
    "instagram_reel": {"label": "Instagram Reel", "aspect_ratio": "9:16", "audience": "mobile users scrolling a vertical feed",
        "viewing": "a phone viewer scrolls fast with the sound on: open with motion and the hook in the first second, keep every line short, end on one clear action",
        "shoot": "vertical framing, the subject centred, quick clear motion in the first second", "max_chars": 46, "max_words": 8},
    "youtube_shorts": {"label": "YouTube Shorts", "aspect_ratio": "9:16", "audience": "mobile users watching short vertical videos",
        "viewing": "a phone viewer swipes through short videos with the sound on: the hook must land in the first second, every line must be short, and the ending must be one clear action",
        "shoot": "vertical framing, the subject centred, quick clear motion in the first second", "max_chars": 46, "max_words": 8},
    "facebook_feed": {"label": "Facebook feed", "aspect_ratio": "1:1", "audience": "people scrolling a mixed social feed",
        "viewing": "autoplay in a square feed, usually muted: the message must read without sound and the first second must stop the scroll",
        "shoot": "square framing, a bold subject that is clear even at thumbnail size", "max_chars": 46, "max_words": 8},
}

GOALS: dict[str, dict] = {
    "awareness": {"label": "Brand awareness", "focus": "introduce the brand and what it does, ending on the name and a simple call to action"},
    "offer": {"label": "Promote offer", "focus": "make the offer the hero of the ad and end on the call to action"},
    "visits": {"label": "Drive visits", "focus": "show the place and the experience so viewers want to visit, ending with the location or call to action"},
    "event": {"label": "Event promo", "focus": "build excitement for the event and end on how to take part"},
    "product": {"label": "Product launch", "focus": "present the product as the hero from several flattering angles"},
}

# What kind of ad this is. "auto" keeps the normal behaviour: the formula for the business and the chosen goal decide.
#   hint      one line on the picker
#   note      shown when selected (limits the user must know about)
#   focus     the objective given to every prompt writer (replaces the goal)
#   direction how the AI should film this kind of ad
#   story     the filmable scene when no AI writer is configured ({item} = the product or service)
#   captions  on-screen text patterns. A pattern is skipped when one of its values is unknown, so nothing is ever invented.
#             Values: {name} {service} {about} {offer} {phone} {domain} {place} {quote} {occasion}
#   cta       neutral call to action used when the business has none
#   emphasis  which panel line gets the big type: offer | phone
AD_TYPES: dict[str, dict] = {
    "auto": {
        "label": "Let AI choose", "hint": "The best fit for your business",
        "note": "", "focus": "", "direction": "", "story": "", "captions": (), "cta": "", "emphasis": "",
    },
    "ugc": {
        "label": "UGC", "hint": "Person-style, phone-shot review feel",
        "note": "Shows AI-generated people, not real customers. No review, quote or rating is invented.",
        "focus": "feel like an honest person sharing something useful, ending on the brand and a simple call to action",
        "direction": "handheld, selfie-style vertical phone footage of one ordinary person using the product in a real home or street, natural daylight, casual imperfect framing, reacting with genuine delight; never a studio look, and no speech or lip-syncing",
        "story": "A person films themselves on a phone in a real, lived-in room, unboxing and trying {item}, then turns it toward the camera and reacts with a genuine, surprised smile",
        "captions": ("Trying {name} today", "{service}, up close", "See for yourself at {name}"), "cta": "Try it yourself", "emphasis": "",
    },
    "product": {
        "label": "Product", "hint": "Show features and benefits",
        "note": "",
        "focus": "present the product as the hero, showing what it does and why it is useful, ending on the name and call to action",
        "direction": "the product fills the frame from several flattering angles; show one concrete feature working in each shot, then the benefit it gives the user",
        "story": "{item} is revealed in crisp light, the camera glides across its details, then a hand uses it and its main benefit is clearly visible",
        "captions": ("Meet {service}", "{about}", "Only from {name}"), "cta": "Shop now", "emphasis": "",
    },
    "brand_awareness": {
        "label": "Brand Awareness", "hint": "Make people remember you",
        "note": "",
        "focus": "make viewers remember the brand and what it stands for, ending on the name",
        "direction": "one memorable, distinctive visual idea built around the brand's colours and world; emotion over features; no hard sell",
        "story": "A striking, memorable moment built around {item}, in the brand's colours, that leaves the viewer smiling",
        "captions": ("This is {name}", "{about}", "Remember {name}"), "cta": "", "emphasis": "",
    },
    "offer": {
        "label": "Offer / Discount", "hint": "Sales, coupons, limited offers",
        "note": "Uses the offer from your website or the one you type. No discount is ever invented.",
        "focus": "make the offer the hero of the ad and end on the call to action",
        "direction": "high-energy reveal of the product being grabbed and enjoyed, quick and celebratory, leaving calm space for the offer text added in editing; never render prices or percentages in the footage",
        "story": "{item} is revealed with a burst of colour and movement as excited hands reach for it, then it settles centred in a calm, bright frame",
        "captions": ("{offer}", "{service} from {name}", "Don't miss it at {name}"), "cta": "Grab the offer", "emphasis": "offer",
    },
    "animation_3d": {
        "label": "3D Animation", "hint": "3D product and model animation",
        "note": "Best with AI Video. Website-photo ads use normal photo motion.",
        "focus": "wow the viewer with a stylised 3D world around the product, ending on the name",
        "direction": "fully computer-generated 3D animation, not live action: glossy materials, soft studio reflections, the product floating, rotating and assembling itself from parts on a clean coloured set",
        "story": "A glossy 3D-rendered {item} floats and slowly rotates on a clean coloured set, its parts assembling smoothly before it lands with a soft bounce",
        "captions": ("{service}, reimagined", "{about}", "Made by {name}"), "cta": "", "emphasis": "",
    },
    "explainer": {
        "label": "Explainer", "hint": "Explain your service simply",
        "note": "",
        "focus": "explain in the simplest terms what the business does and how it works, ending on the next step",
        "direction": "three clear visual steps a child could follow: the need, the service in action, the finished result; clean uncluttered frames and simple clear gestures",
        "story": "Step by step, a person needs {item}, uses it in one simple action, and enjoys the finished result, each step clear and uncluttered",
        "captions": ("What is {name}?", "{about}", "It's that simple with {name}"), "cta": "Learn how", "emphasis": "",
    },
    "problem_solution": {
        "label": "Problem → Solution", "hint": "Show the problem, then the fix",
        "note": "",
        "focus": "show a relatable everyday problem, then the product solving it, ending on the relief and the brand",
        "direction": "open on the frustrating problem in dull, cool light; the product arrives and the problem visibly disappears as the image warms and brightens; end on real relief",
        "story": "A person is visibly frustrated by an everyday problem in dull, cool light; then {item} arrives, the problem visibly disappears, the light warms and they relax with relief",
        "captions": ("Sound familiar?", "{service}, sorted", "{name} fixes that"), "cta": "Fix it today", "emphasis": "",
    },
    "testimonial": {
        "label": "Testimonial", "hint": "Customer reviews, social proof",
        "note": "Only real words are used. Paste a genuine customer quote in \"double quotes\" under Creative instructions. Without one, no review is shown.",
        "focus": "build trust by showing satisfied people enjoying the result, ending on the brand; never state reviews, ratings or numbers",
        "direction": "warm, honest portraits of people enjoying the result of the service in their real surroundings, soft window light; nobody speaks to camera and nothing suggests a specific real customer",
        "story": "A relaxed person enjoys the result of {item} in their own surroundings, in soft window light, with a calm, satisfied smile",
        "captions": ("{quote}", "See why people choose {name}", "{service} by {name}"), "cta": "See for yourself", "emphasis": "",
    },
    "app_website": {
        "label": "App / Website", "hint": "Drive downloads and visits",
        "note": "",
        "focus": "make viewers want to open the app or website right now, ending on where to go",
        "direction": "a person gets one real task done in seconds on a phone in everyday life; show the outcome in the real world rather than the screen; any interface is abstract shapes with no readable text",
        "story": "A person taps a phone once in everyday life and the result of {item} appears in the real world around them, and they smile at how quick it was",
        "captions": ("Everything {name}, in one place", "{service}", "Visit {domain}"), "cta": "Visit now", "emphasis": "",
    },
    "event": {
        "label": "Event", "hint": "Events, launches, openings",
        "note": "Put the date and place in Creative instructions or on your website. Nothing is guessed.",
        "focus": "build excitement for the event and end on how to take part",
        "direction": "anticipation building to a peak: preparations, doors opening, lights rising, a crowd arriving and celebrating",
        "story": "Lights rise and doors open as excited people arrive for {item}, the moment peaks in a burst of energy, and friends celebrate together",
        "captions": ("{name} presents", "{service}", "{about}", "Be there with {name}"), "cta": "Save your spot", "emphasis": "",
    },
    "local": {
        "label": "Local Business", "hint": "Restaurants, gyms, salons, stores",
        "note": "",
        "focus": "make people nearby want to walk in today, ending on where to find the business",
        "direction": "the real neighbourhood feel of the place: the street, the door opening, friendly staff, regulars enjoying the service; warm and human, never a generic stock look",
        "story": "A friendly neighbourhood storefront, the door opens and a regular walks in, is greeted warmly and enjoys {item}",
        "captions": ("{name}, {place}", "{service} near you", "Drop in at {name}"), "cta": "Visit us today", "emphasis": "",
    },
    "seasonal": {
        "label": "Seasonal", "hint": "Diwali, Christmas, IPL, New Year",
        "note": "Name the occasion in Creative instructions, e.g. Diwali. Otherwise the ad says \"this season\".",
        "focus": "tie the brand to the season or occasion the advertiser named, ending on the name and call to action",
        "direction": "the warmth of the occasion named in the advertiser direction (or a general festive feel if none): family, lights, colour and celebration around the product, with no logos of events, teams or leagues",
        "story": "Family and friends gather in warm festive light and colour, sharing {item} with joy",
        "captions": ("Celebrate {occasion} with {name}", "{offer}", "Celebrate with {name}"), "cta": "Celebrate with us", "emphasis": "offer",
    },
    "lead_generation": {
        "label": "Lead Generation", "hint": "Call, WhatsApp or book now",
        "note": "Your phone number becomes the biggest text, when there is one.",
        "focus": "get the viewer to call, message or book right now, ending on the contact details",
        "direction": "a person with a need picks up a phone, makes one quick call, and the problem is taken care of by a friendly professional; end calmly with space for the contact details",
        "story": "A person with a clear need picks up a phone and a friendly professional soon arrives and takes care of {item}, leaving them relieved",
        "captions": ("Need {service}?", "{name} can help", "Call {phone}"), "cta": "Book now", "emphasis": "phone",
    },
    "recruitment": {
        "label": "Recruitment", "hint": "Hiring campaigns",
        "note": "",
        "focus": "make good candidates want to join the team, ending on how to apply",
        "direction": "the team at work: collaboration, skill and pride, a newcomer being welcomed; real workplace energy with no product selling",
        "story": "A team works together with pride and focus around {item}, and a newcomer is welcomed with a handshake and a smile",
        "captions": ("{name} is hiring", "Build your career with {name}", "Visit {domain}"), "cta": "Apply now", "emphasis": "",
    },
    "public_awareness": {
        "label": "Public Awareness", "hint": "Social and public-service campaigns",
        "note": "",
        "focus": "make people care about the cause and take one small action; nothing is sold",
        "direction": "a sincere, human, documentary feel showing ordinary people and the one small action that helps; no selling, no shock imagery, no fear",
        "story": "Ordinary people in a real community take one small, simple action around {item}, and the people around them begin to follow",
        "captions": ("{about}", "Every small step counts", "A message from {name}"), "cta": "Join in", "emphasis": "",
    },
    "retargeting": {
        "label": "Retargeting", "hint": "Remind people who already know you",
        "note": "",
        "focus": "remind people who already know the brand and bring them back, ending on the call to action",
        "direction": "a short, familiar reminder: the product waiting exactly where they left it, a warm nudge to come back; one simple idea, no introduction needed",
        "story": "{item} sits ready and waiting in warm light, and a familiar hand comes back and picks it up with a smile",
        "captions": ("Still thinking about {name}?", "{service} is waiting", "{offer}", "Come back to {name}"), "cta": "Come back today", "emphasis": "",
    },
    "qr_code": {
        "label": "QR Code", "hint": "Scan to visit, order or download",
        "note": "Turns the QR code on and makes it bigger, with a Scan me label.",
        "focus": "make the viewer take out a phone and scan, ending on a calm frame that leaves room for the QR code",
        "direction": "a person notices the ad, lifts a phone and scans, then instantly enjoys the result; never draw a QR code in the footage, it is added in editing, so keep one side of the frame calm",
        "story": "A person notices something, lifts a phone to scan with a curious smile, and instantly enjoys {item}",
        "captions": ("Scan for {name}", "{service}", "Point your camera at the code"), "cta": "Scan the code", "emphasis": "",
    },
}


def ad_type_info(ad_type: str) -> dict:
    """The catalog entry of an ad type, "auto" when unknown."""
    return AD_TYPES.get(ad_type, AD_TYPES["auto"])


def objective(goal: str, ad_type: str = "auto") -> str:
    """What the ad must achieve: the ad type's focus, else the goal's."""
    return ad_type_info(ad_type)["focus"] or GOALS.get(goal, GOALS["awareness"])["focus"]


def ad_type_line(ad_type: str) -> str:
    """One line for prompt writers; empty for "auto"."""
    info = ad_type_info(ad_type)
    return f"{info['label']} ad: {info['direction']}" if info["direction"] else ""

# Languages a Studio video can be spoken in. The picture text stays as the website wrote it; the voiceover is written (translated, with every
# figure kept) in the chosen language.
LANGUAGES: dict[str, dict] = {
    "en": {"label": "English", "native": "English"},
    "hi": {"label": "Hindi", "native": "हिन्दी"},
    "ta": {"label": "Tamil", "native": "தமிழ்"},
    "te": {"label": "Telugu", "native": "తెలుగు"},
    "bn": {"label": "Bengali", "native": "বাংলা"},
    "mr": {"label": "Marathi", "native": "मराठी"},
    "gu": {"label": "Gujarati", "native": "ગુજરાતી"},
    "kn": {"label": "Kannada", "native": "ಕನ್ನಡ"},
    "ml": {"label": "Malayalam", "native": "മലയാളം"},
    "es": {"label": "Spanish", "native": "Español"},
    "fr": {"label": "French", "native": "Français"},
    "de": {"label": "German", "native": "Deutsch"},
    "ar": {"label": "Arabic", "native": "العربية"},
    "pt": {"label": "Portuguese", "native": "Português"},
}

# ElevenLabs "multilingual v2" speaks these (any of its voices, in any of them). The other languages use Microsoft voices.
ELEVEN_LANGUAGES = ["en", "hi", "ta", "es", "fr", "de", "ar", "pt"]


def _edge(label: str, hint: str, voice: str, language: str, gender: str) -> dict:
    return {"label": label, "hint": hint, "voice": voice, "engine": "edge", "languages": [language], "gender": gender}


def _eleven(label: str, hint: str, eleven_id: str, gender: str) -> dict:
    return {"label": f"{label} (ElevenLabs)", "hint": hint, "voice": "", "eleven_id": eleven_id, "engine": "eleven", "languages": list(ELEVEN_LANGUAGES), "gender": gender}


# Voice packages. "edge" voices are Microsoft neural voices through edge-tts (free, no key). "eleven" voices are ElevenLabs studio voices; they
# need ELEVENLABS_API_KEY and quietly fall back to the Microsoft voice of the same language and gender when the key is missing or used up.
VOICES: dict[str, dict] = {
    "auto": {"label": "Auto", "hint": "The best voice for your business", "voice": "", "engine": "edge", "languages": list(LANGUAGES), "gender": ""},
    "none": {"label": "No voice", "hint": "Music or silence only", "voice": "", "engine": "edge", "languages": list(LANGUAGES), "gender": ""},
    "neerja": _edge("Neerja", "Warm female, Indian English", "en-IN-NeerjaExpressiveNeural", "en", "f"),
    "prabhat": _edge("Prabhat", "Clear male, Indian English", "en-IN-PrabhatNeural", "en", "m"),
    "ava": _edge("Ava", "Friendly female, American", "en-US-AvaNeural", "en", "f"),
    "andrew": _edge("Andrew", "Confident male, American", "en-US-AndrewNeural", "en", "m"),
    "sonia": _edge("Sonia", "Polished female, British", "en-GB-SoniaNeural", "en", "f"),
    "ryan": _edge("Ryan", "Clear male, British", "en-GB-RyanNeural", "en", "m"),
    "swara": _edge("Swara", "Female, Hindi", "hi-IN-SwaraNeural", "hi", "f"),
    "madhur": _edge("Madhur", "Male, Hindi", "hi-IN-MadhurNeural", "hi", "m"),
    "pallavi": _edge("Pallavi", "Female, Tamil", "ta-IN-PallaviNeural", "ta", "f"),
    "valluvar": _edge("Valluvar", "Male, Tamil", "ta-IN-ValluvarNeural", "ta", "m"),
    "shruti": _edge("Shruti", "Female, Telugu", "te-IN-ShrutiNeural", "te", "f"),
    "mohan": _edge("Mohan", "Male, Telugu", "te-IN-MohanNeural", "te", "m"),
    "tanishaa": _edge("Tanishaa", "Female, Bengali", "bn-IN-TanishaaNeural", "bn", "f"),
    "bashkar": _edge("Bashkar", "Male, Bengali", "bn-IN-BashkarNeural", "bn", "m"),
    "aarohi": _edge("Aarohi", "Female, Marathi", "mr-IN-AarohiNeural", "mr", "f"),
    "manohar": _edge("Manohar", "Male, Marathi", "mr-IN-ManoharNeural", "mr", "m"),
    "dhwani": _edge("Dhwani", "Female, Gujarati", "gu-IN-DhwaniNeural", "gu", "f"),
    "niranjan": _edge("Niranjan", "Male, Gujarati", "gu-IN-NiranjanNeural", "gu", "m"),
    "sapna": _edge("Sapna", "Female, Kannada", "kn-IN-SapnaNeural", "kn", "f"),
    "gagan": _edge("Gagan", "Male, Kannada", "kn-IN-GaganNeural", "kn", "m"),
    "sobhana": _edge("Sobhana", "Female, Malayalam", "ml-IN-SobhanaNeural", "ml", "f"),
    "midhun": _edge("Midhun", "Male, Malayalam", "ml-IN-MidhunNeural", "ml", "m"),
    "elvira": _edge("Elvira", "Female, Spanish", "es-ES-ElviraNeural", "es", "f"),
    "alvaro": _edge("Alvaro", "Male, Spanish", "es-ES-AlvaroNeural", "es", "m"),
    "denise": _edge("Denise", "Female, French", "fr-FR-DeniseNeural", "fr", "f"),
    "henri": _edge("Henri", "Male, French", "fr-FR-HenriNeural", "fr", "m"),
    "katja": _edge("Katja", "Female, German", "de-DE-KatjaNeural", "de", "f"),
    "conrad": _edge("Conrad", "Male, German", "de-DE-ConradNeural", "de", "m"),
    "zariyah": _edge("Zariyah", "Female, Arabic", "ar-SA-ZariyahNeural", "ar", "f"),
    "hamed": _edge("Hamed", "Male, Arabic", "ar-SA-HamedNeural", "ar", "m"),
    "francisca": _edge("Francisca", "Female, Portuguese", "pt-BR-FranciscaNeural", "pt", "f"),
    "antonio": _edge("Antonio", "Male, Portuguese", "pt-BR-AntonioNeural", "pt", "m"),
    "el_adam": _eleven("Adam", "Dominant and firm: made for ads", "pNInz6obpgDQGcFmaJgB", "m"),
    "el_liam": _eleven("Liam", "Energetic social-media creator", "TX3LPaxmHKxFdv7VOQHJ", "m"),
    "el_brian": _eleven("Brian", "Deep, resonant, comforting", "nPczCjzI2devNBz1zQrb", "m"),
    "el_eric": _eleven("Eric", "Smooth and trustworthy", "cjVigY5qzO86Huf0OWal", "m"),
    "el_bill": _eleven("Bill", "Wise, balanced, advertising voice", "pqHfZKP75CvOlQylNhV4", "m"),
    "el_sarah": _eleven("Sarah", "Confident and reassuring", "EXAVITQu4vr4xnSDxMaL", "f"),
    "el_jessica": _eleven("Jessica", "Playful, bright and warm", "cgSgspJ2msm6clMCkdW9", "f"),
    "el_laura": _eleven("Laura", "Enthusiastic with attitude", "FGY2WhTYpPnrIDTdsKH5", "f"),
    "el_alice": _eleven("Alice", "Clear, engaging educator", "Xb7hH8MSUJpSbSDYk0k2", "f"),
    "el_matilda": _eleven("Matilda", "Professional and knowledgeable", "XrExE9yKIg1WjnnlVkGX", "f"),
}

def voices_for(language: str, *, eleven: bool = True) -> list[str]:
    """Voice ids that can speak `language` (without the pseudo voices "auto" and "none"), Microsoft voices first."""
    ids = [key for key, v in VOICES.items() if key not in {"auto", "none"} and language in v["languages"] and (eleven or v["engine"] != "eleven")]
    return sorted(ids, key=lambda key: VOICES[key]["engine"] == "eleven")


def default_voice(language: str, gender: str = "f") -> str:
    """A Microsoft voice for `language` with this gender (any gender when there is none)."""
    edge = [key for key in voices_for(language, eleven=False)]
    return next((key for key in edge if VOICES[key]["gender"] == gender), edge[0] if edge else "neerja")


def fallback_voice(voice_id: str, language: str = "en") -> str:
    """The Microsoft voice that stands in for `voice_id` when its own engine cannot be used (same language, same gender)."""
    info = VOICES.get(voice_id, {})
    if info.get("engine") == "edge" and language in info.get("languages", [language]):
        return voice_id
    return default_voice(language, info.get("gender") or "f")


def voice_language(voice_id: str) -> str:
    """The language a Microsoft voice speaks (its first language), "en" for the others."""
    return (VOICES.get(voice_id, {}).get("languages") or ["en"])[0]


# Soft backgrounds synthesised by FFmpeg: two chords (note frequencies), seconds per chord, volume pulses per second.
MUSIC: dict[str, dict] = {
    "auto": {"label": "Auto", "chords": ()},
    "none": {"label": "No music", "chords": ()},
    "upbeat": {"label": "Upbeat", "chords": ((261.63, 329.63, 392.0), (293.66, 369.99, 440.0)), "bar": 2, "pulse": 2.0},
    "calm": {"label": "Calm", "chords": ((220.0, 261.63, 329.63), (174.61, 220.0, 261.63)), "bar": 4, "pulse": 0.5},
    "premium": {"label": "Premium", "chords": ((146.83, 220.0, 293.66), (130.81, 196.0, 261.63)), "bar": 4, "pulse": 0.25},
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
