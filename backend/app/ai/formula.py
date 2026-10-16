"""Ad formulas: what a short ad should SHOW for each kind of business, as a hook -> turn -> payoff micro-story.

Built from common short-ad practice: the first second must make clear what is advertised (sound off), something must
change on screen every couple of seconds, and digital products are sold by their transformation (before -> after), never
by a static dashboard. Each formula is written for AI video models (LTX / Magic Hour): present tense, concrete subjects,
every motion spelled out, one continuous camera move, the most important visual first.

The business is matched to a formula by scoring keywords across its name, category, description and services, so a
"browser-based creative platform for generating video" lands on the AI-tool formula instead of a generic scene.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .facts import FactSheet


@dataclass(frozen=True)
class Formula:
    """One kind of business and the micro-story that sells it."""

    id: str
    keywords: tuple[str, ...]
    hook: str  # first 1-3 s: the clearest possible picture of what is advertised (or the 'before')
    turn: str  # the change: the product / service doing its job
    payoff: str  # the result / the human moment, ending on a calm hero frame
    setting: str
    camera: str  # one continuous camera move that serves the story


FORMULAS: tuple[Formula, ...] = (
    Formula(
        "creative_ai",
        ("ai", "artificial intelligence", "generative", "text-to-video", "image-to-video", "video generation", "generating video",
         "video editing", "photo editing", "image generator", "image editing", "face swap", "lip sync", "avatar", "voice generation",
         "creative platform", "creators", "editing video", "animation", "design tool", "creative tools"),
        "A creator holds up a smartphone showing an ordinary, slightly dull still photo of a young woman standing on a city rooftop",
        "the camera glides into the phone screen and the still photo comes alive: her hair begins to move in the wind, city lights flicker on behind her and the dull colours bloom into a rich, cinematic dusk",
        "the camera eases back out to reveal the creator grinning at the result and turning the phone toward a friend, who leans in and laughs in surprise",
        "a bright, modern creator's workspace with soft daylight",
        "one smooth continuous move: a slow push into the phone screen, then a gentle pull back",
    ),
    Formula(
        "software",
        ("software", "saas", "platform", "dashboard", "automation", "automate", "workflow", "crm", "cloud", "analytics", "productivity",
         "invoicing", "accounting software", "b2b", "integration", "tool for teams"),
        "A tired professional sits at a desk buried under paper stacks, sticky notes and a cluttered laptop, rubbing their temples",
        "they tap a single key and the clutter visibly clears: paper stacks slide aside, sticky notes flutter away and the laptop shows a tidy, colourful layout of abstract cards with no readable text",
        "they lean back with a relieved smile and close the laptop as warm light fills the calm, orderly desk",
        "a modern home office in late afternoon light",
        "a slow, steady dolly-in from a medium shot to a close shot",
    ),
    Formula(
        "food",
        ("restaurant", "cafe", "café", "coffee", "kitchen", "food", "pizza", "burger", "dining", "bistro", "grill", "biryani", "thali",
         "bakery", "sweet", "sweets", "mithai", "cake", "pastry", "dessert", "chef", "menu", "cuisine"),
        "Extreme close-up: freshly made {item} is set down on a plate, steam rising and textures glistening in warm light",
        "a chef's hands add a final garnish as the camera arcs slowly around the dish, revealing every layer",
        "a guest's hand reaches in and takes the first bite, smiling, and the dish settles centred and inviting on the table",
        "a warm, inviting dining room with soft bokeh lights",
        "a slow, low arc around the dish",
    ),
    Formula(
        "news",
        ("news", "newspaper", "journal", "journalism", "magazine", "publisher", "editorial", "headlines", "reporting"),
        "A journalist in a bright, modern newsroom finishes a story on a tablet showing a clean, generic news layout with photographs and no readable text",
        "they tap to publish and the camera follows the story onto the phone of a commuter on a morning train, who swipes through it with growing interest",
        "the commuter looks up from the screen, informed and engaged, as the city passes by outside",
        "a bright, modern newsroom with large windows, then a sunlit morning train",
        "a smooth gimbal move that carries from the newsroom to the train",
    ),
    Formula(
        "hotel",
        ("hotel", "resort", "villa", "homestay", "rooms", "suite", "travel", "tour", "holiday", "vacation", "booking"),
        "A hotel door swings open onto a bright, elegant room with a wide window",
        "a guest walks in, drops their bag, and pulls the curtains open to reveal a calm, beautiful view",
        "they step onto the balcony with a cup of coffee and exhale, the whole room glowing behind them",
        "a stylish, light-filled hotel room",
        "a smooth gimbal move that follows the guest through the room",
    ),
    Formula(
        "spa_beauty",
        ("spa", "salon", "beauty", "cosmetic", "skin", "skincare", "makeup", "barber", "nail", "facial", "massage", "hair"),
        "Close-up: a therapist's hands gently begin a calm, careful treatment on a relaxed client",
        "the camera drifts across warm stones, oils and soft towels as the client's shoulders visibly relax",
        "the client sits up, touches their glowing skin in a mirror and smiles, refreshed and confident",
        "a serene, softly lit treatment room with plants",
        "a slow, gliding lateral move",
    ),
    Formula(
        "fitness",
        ("gym", "fitness", "yoga", "pilates", "crossfit", "workout", "training", "walk", "walking", "steps", "running", "jogging", "coach"),
        "A person laces up their trainers and walks out briskly into the morning, determined",
        "they walk and train with strong, smooth form, breathing steadily, as a step ring on their smartwatch fills up",
        "they finish, smile with relief and raise a water bottle, clearly fitter and energised",
        "a bright park path or modern studio",
        "a tracking shot that moves alongside them",
    ),
    Formula(
        "retail",
        ("fashion", "clothing", "apparel", "boutique", "wear", "jewel", "jewellery", "jewelry", "saree", "shoe", "shoes", "bag", "watch", "store"),
        "A model turns into the light wearing {item}, fabric and detail catching the eye",
        "the camera slides past close details: stitching, texture and the way it moves",
        "they glance back over their shoulder with a confident smile, the outfit perfectly framed",
        "a stylish boutique with soft, flattering light",
        "a slow orbit around the model",
    ),
    Formula(
        "packaged_brand",
        ("chips", "snack", "snacks", "beverage", "drink", "juice", "tea", "chocolate", "biscuit", "cookies", "sauce", "pack", "bottle", "fmcg"),
        "The {item} pack stands centred on a clean surface as pieces of the product tumble into a neat ring around it",
        "hard cut to a macro of the product's real texture and ingredients, then a hand lifts one piece",
        "a person takes a real bite or sip and smiles, and the pack settles back to centre frame, still",
        "a clean studio surface with crisp light",
        "a slow push-in, then a gentle half orbit",
    ),
    Formula(
        "local_service",
        ("repair", "cleaning", "plumber", "plumbing", "electrician", "pest", "movers", "moving", "laundry", "car wash", "painting",
         "renovation", "carpentry", "service at home", "installation"),
        "Before: a visibly broken or messy {item} in a real home",
        "a friendly, uniformed technician works on it with skilled, careful hands",
        "after: it is spotless and working, and the relieved homeowner shakes the technician's hand",
        "a bright, real family home",
        "a steady push-in that ends on the finished result",
    ),
    Formula(
        "finance",
        ("bank", "banking", "loan", "loans", "insurance", "finance", "fintech", "payments", "wallet", "investment", "credit"),
        "A worried person looks at a pile of bills on a kitchen table",
        "they tap their phone a few times and the bills are neatly stacked away, a green check mark glowing on the screen",
        "their family joins them, relaxed and laughing together at the table",
        "a warm, real family kitchen",
        "a slow dolly-in that ends on the family",
    ),
    Formula(
        "health",
        ("clinic", "dental", "dentist", "doctor", "hospital", "health", "medical", "pharmacy", "physio", "diagnostic"),
        "A patient sits nervously in a bright, modern clinic",
        "a friendly professional explains calmly and begins a gentle check-up",
        "the patient leaves with a relaxed, confident smile",
        "a clean, modern clinic with soft daylight",
        "a gentle, steady push-in",
    ),
    Formula(
        "education",
        ("school", "academy", "course", "courses", "education", "coaching", "tuition", "learning", "university", "college", "classes"),
        "A student frowns at a hard problem in a notebook",
        "an instructor leans in and explains with enthusiasm, sketching it out",
        "the student's face lights up as they solve it and raise their hand with confidence",
        "a bright, modern classroom",
        "a slow, steady push-in",
    ),
    Formula(
        "real_estate",
        ("real estate", "property", "properties", "apartment", "apartments", "realty", "homes", "builder", "construction", "interior"),
        "Front doors open onto a beautifully finished living space flooded with light",
        "the camera glides through the rooms, past clean surfaces and furniture, to a wide window",
        "a family steps into frame and looks around, delighted, as the view opens up",
        "a spacious, modern home",
        "a smooth, continuous gimbal walk-through",
    ),
    Formula(
        "auto",
        ("car", "cars", "auto", "automobile", "garage", "motor", "bike", "vehicle", "dealership", "ev"),
        "A gleaming vehicle is revealed under studio light, reflections gliding across the paint",
        "headlights switch on and the camera sweeps along its lines to the wheels",
        "the driver gets in, smiles, and the car pulls smoothly away",
        "a clean, premium showroom",
        "a low, sweeping orbit",
    ),
    Formula(
        "events",
        ("event", "events", "concert", "club", "nightlife", "party", "festival", "wedding", "venue"),
        "Lights rise over a packed venue as the crowd turns toward the stage",
        "confetti bursts and hands go up as the moment peaks",
        "friends hug and laugh in the glow, the whole venue alive behind them",
        "a vibrant venue at night",
        "a sweeping crane-like move over the crowd",
    ),
)
DEFAULT_FORMULA = Formula(
    "general", (),
    "Before: a real customer struggles with the everyday problem that {item} solves",
    "they use {item} and the problem visibly goes away",
    "after: they smile, relieved and happy, with {item} clearly in frame",
    "a bright, real everyday setting",
    "a slow, steady push-in",
)


def _hits(text: str, keyword: str) -> int:
    """How often a keyword (whole word / phrase) appears."""
    return len(re.findall(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", text))


def formula_for(facts: FactSheet) -> Formula:
    """The best-matching formula: keywords scored over name and category (x3), services (x2) and description (x1)."""
    strong = f"{facts.name} {facts.category}".lower()
    services = " ".join(facts.services).lower()
    description = facts.description.lower()
    best, best_score = DEFAULT_FORMULA, 0
    for formula in FORMULAS:
        score = sum(3 * _hits(strong, k) + 2 * _hits(services, k) + _hits(description, k) for k in formula.keywords)
        if score > best_score:
            best, best_score = formula, score
    return best
