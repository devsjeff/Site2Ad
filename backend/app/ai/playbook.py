"""Category playbooks: how each kind of business is sold in a few seconds on screen.

A playbook is picked from the same keyword score as the ad formulas (`formula_for`), so it follows what the business really
does. It holds the on-screen line patterns (hook -> value -> detail -> close), the FFmpeg look, the voice and the music that
suit the category, and a plain-language lens that is given to the AI writers. Patterns only use facts that exist: a pattern
whose value is unknown is skipped, so nothing is invented.

Pattern values: {name} {service} {service2} {about} {offer} {phone} {domain} {place} {quote} {occasion}
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import catalog
from .facts import FactSheet
from .formula import formula_for


@dataclass(frozen=True)
class Playbook:
    """What works for one kind of business."""

    id: str
    lens: str  # one line for the AI: how this category is sold
    visual: str  # what sells it on screen (for AI video prompts)
    hook: tuple[str, ...]
    value: tuple[str, ...]
    detail: tuple[str, ...]
    close: tuple[str, ...]
    look: str  # FFmpeg look name (video/compose.py LOOKS)
    voice: str  # voice id used when the user picks "Auto"
    rate: str  # edge-tts speaking rate
    music: str  # music id used when the user picks "Auto"
    cta: str  # call to action when the business has none


GENERAL = Playbook(
    "general",
    "Say who you are and what you offer in the first line, then invite one clear action.",
    "the real product or service in use, close and clearly in frame, then a happy customer",
    hook=("Meet {name}", "Looking for {service}?", "Discover {service}"),
    value=("{service} and {service2}", "{about}"),
    detail=("{about}", "More from {name}"),
    close=("Visit {name} today", "Call {phone}", "Visit {domain}"),
    look="default", voice="neerja", rate="+3%", music="upbeat", cta="Visit us today",
)

PLAYBOOKS: dict[str, Playbook] = {
    "food": Playbook(
        "food",
        "Name the dish and invite them in. Make them hungry in the first second, sell one hero dish, then the place.",
        "close-ups of the finished dish with steam and texture, a hand taking the first bite, a warm inviting table",
        hook=("Hungry? Try our {service}", "Craving {service}?", "Taste {service} at {name}", "Hungry? Visit {name}"),
        value=("{service} and {service2}", "Try {service2} too", "{service} and more"),
        detail=("Try {service2} too", "More at {name}", "{about}"),
        close=("Visit {name} in {place}", "Dine at {name} today", "Order from {name}", "Visit {name} today"),
        look="warm_food", voice="neerja", rate="+2%", music="upbeat", cta="Order now",
    ),
    "hotel": Playbook(
        "hotel",
        "Sell the feeling of arriving and relaxing, then make booking the obvious next step.",
        "an elegant room opening onto a view, a guest relaxing, calm and light",
        hook=("Your stay starts at {name}", "Escape to {name}", "Relax at {name}"),
        value=("{service} and {service2}", "{about}"),
        detail=("{service2} awaits", "{about}"),
        close=("Book your stay at {name}", "Plan your trip with {name}", "Visit {name} today"),
        look="soft_calm", voice="neerja", rate="-2%", music="calm", cta="Book now",
    ),
    "spa_beauty": Playbook(
        "spa_beauty",
        "Sell the feeling after the treatment: calm, confident, cared for. Name the treatment, then invite a visit.",
        "a calm treatment, soft light, the client relaxed and confident afterwards",
        hook=("Treat yourself at {name}", "Feel your best with {service}", "Time to relax at {name}"),
        value=("{service} and {service2}", "Relax with {service}", "{about}"),
        detail=("Try {service2} too", "{about}"),
        close=("Book your visit to {name}", "Visit {name} in {place}", "Visit {name} today"),
        look="soft_calm", voice="neerja", rate="-3%", music="calm", cta="Book now",
    ),
    "fitness": Playbook(
        "fitness",
        "Energy and momentum: start with the decision to move, name the programme, then make joining easy.",
        "powerful, well-formed movement, sweat and focus, a confident finish",
        hook=("Ready to move?", "Train at {name}", "Start your fitness at {name}"),
        value=("Join {service}", "{service} and {service2}", "{about}"),
        detail=("Also {service2}", "{about}"),
        close=("Join {name} today", "Start at {name} in {place}", "Visit {name} today"),
        look="punchy", voice="prabhat", rate="+7%", music="upbeat", cta="Join today",
    ),
    "retail": Playbook(
        "retail",
        "Show the product and the choice: name what they can buy, then bring them into the shop.",
        "the product turning in good light, details of fabric and finish, a shopper delighted",
        hook=("New finds at {name}", "Shop {service} at {name}", "Looking for {service}?"),
        value=("{service}, {service2} and more", "Discover {service2}", "{about}"),
        detail=("Also {service2}", "{about}"),
        close=("Shop at {name} today", "Visit {name} in {place}", "Visit {name} today"),
        look="bright_pop", voice="neerja", rate="+4%", music="upbeat", cta="Shop now",
    ),
    "packaged_brand": Playbook(
        "packaged_brand",
        "Make the product the hero and easy to recognise: its look, its taste, its moment of use.",
        "the pack and the product from flattering angles, a moment of enjoying it",
        hook=("Meet {service}", "Say hello to {name}", "{service} from {name}"),
        value=("Enjoy {service2}", "{about}"),
        detail=("{about}", "Also {service2}"),
        close=("Look for {name}", "Pick up {name} today", "Visit {domain}"),
        look="bright_pop", voice="neerja", rate="+4%", music="upbeat", cta="Try it today",
    ),
    "local_service": Playbook(
        "local_service",
        "Start from the problem the customer has, show it solved, and make calling the easy next step.",
        "the problem, a friendly professional arriving, the job done and a relieved customer",
        hook=("Need {service}?", "Call {name} for {service}", "Sorting {service}?"),
        value=("{name} can help", "{service} and {service2}", "{about}"),
        detail=("{about}", "Also {service2}"),
        close=("Call {phone}", "Book {name} today", "Contact {name}"),
        look="clean_trust", voice="prabhat", rate="+2%", music="calm", cta="Call now",
    ),
    "finance": Playbook(
        "finance",
        "Build trust with calm, plain words. Name the service, then make the next step small.",
        "a calm, confident person, tidy desk, clear simple visuals, no jargon on screen",
        hook=("Plan your money with {name}", "Looking for {service}?", "Meet {name}"),
        value=("Explore {service}", "{service} and {service2}", "{about}"),
        detail=("{about}", "Also {service2}"),
        close=("Talk to {name} today", "Visit {domain}", "Call {phone}"),
        look="clean_trust", voice="prabhat", rate="0%", music="premium", cta="Get started",
    ),
    "health": Playbook(
        "health",
        "Reassure first: calm, clean, caring. Name the service and make booking simple.",
        "a calm consultation, clean bright clinic, a reassured patient",
        hook=("See {name} for {service}", "Your health comes first", "Meet {name}"),
        value=("{service} and {service2}", "{about}"),
        detail=("{about}", "Also {service2}"),
        close=("Book a visit at {name}", "Call {phone}", "Visit {name} in {place}"),
        look="clean_trust", voice="neerja", rate="-1%", music="calm", cta="Book a visit",
    ),
    "education": Playbook(
        "education",
        "Sell the outcome of learning: name the course, then make starting feel easy.",
        "a bright classroom, curious students, an instructor explaining, a moment of understanding",
        hook=("Learn {service}", "Start learning with {name}", "Ready to learn?"),
        value=("{service} and {service2}", "{about}"),
        detail=("{about}", "Also {service2}"),
        close=("Enrol at {name}", "Join {name} today", "Visit {domain}"),
        look="clean_trust", voice="neerja", rate="+2%", music="upbeat", cta="Enrol now",
    ),
    "real_estate": Playbook(
        "real_estate",
        "Sell the home they could live in: light, space, a view, then a visit.",
        "a bright finished home, the camera gliding through rooms to a window view, a family delighted",
        hook=("Find your next home", "Discover {name}", "Your space awaits at {name}"),
        value=("{service} and {service2}", "{about}"),
        detail=("In {place}", "{about}"),
        close=("Visit {name} today", "Talk to {name} today", "Call {phone}"),
        look="cool_sleek", voice="prabhat", rate="-1%", music="premium", cta="Book a visit",
    ),
    "auto": Playbook(
        "auto",
        "Sell the drive: the vehicle revealed, its lines, the feeling of setting off. End on the showroom or call.",
        "the vehicle revealed under light, reflections sliding over the paint, the driver pulling away",
        hook=("Ready to drive?", "Meet {service}", "Drive with {name}"),
        value=("{service} and {service2}", "{about}"),
        detail=("{about}", "Also {service2}"),
        close=("Visit {name} in {place}", "Visit {name} today", "Call {phone}"),
        look="cool_sleek", voice="prabhat", rate="+1%", music="premium", cta="Visit us today",
    ),
    "events": Playbook(
        "events",
        "Build anticipation and a fear of missing out without inventing details: name the event, then say be there.",
        "lights rising, a crowd arriving, a burst of celebration",
        hook=("{name} is coming", "Be part of {name}", "Join us at {name}"),
        value=("{service}", "{about}"),
        detail=("In {place}", "{about}"),
        close=("Don't miss {name}", "Save your spot", "Visit {domain}"),
        look="festive", voice="neerja", rate="+6%", music="upbeat", cta="Save your spot",
    ),
    "software": Playbook(
        "software",
        "Sell the change, not the screen: the painful way before, the easy way with the product.",
        "a cluttered task becoming tidy, a relieved person, abstract interface shapes with no readable text",
        hook=("Still doing it by hand?", "Meet {name}", "Work smarter with {name}"),
        value=("{service}", "{about}"),
        detail=("{service2}", "{about}"),
        close=("Try {name} today", "Visit {domain}"),
        look="cool_sleek", voice="prabhat", rate="+3%", music="upbeat", cta="Try it today",
    ),
    "creative_ai": Playbook(
        "creative_ai",
        "Show the magic in one move: an ordinary picture becoming something striking.",
        "an ordinary still coming to life as a cinematic scene, a delighted creator",
        hook=("Bring your ideas to life", "Create with {name}", "Meet {name}"),
        value=("{service}", "{about}"),
        detail=("{service2}", "{about}"),
        close=("Try {name} today", "Visit {domain}"),
        look="cool_sleek", voice="prabhat", rate="+4%", music="upbeat", cta="Try it today",
    ),
    "news": Playbook(
        "news",
        "Sell being informed: the story, the reader, the moment of 'now I know'.",
        "a newsroom finishing a story, a commuter reading it, an informed look",
        hook=("Stay informed with {name}", "Today's stories at {name}"),
        value=("{about}", "{service}"),
        detail=("{service}", "{about}"),
        close=("Read {name} today", "Visit {domain}"),
        look="clean_trust", voice="prabhat", rate="+2%", music="calm", cta="Read now",
    ),
}

PLACEHOLDER_NOTE = "Playbook patterns are checked against the facts: an unknown value skips the pattern."


def playbook_for(facts: FactSheet | None) -> Playbook:
    """The playbook for this business (the general one when unknown or when only an uploaded photo is known)."""
    if facts is None:
        return GENERAL
    return PLAYBOOKS.get(formula_for(facts).id, GENERAL)


def context_lines(facts: FactSheet | None, platform: str) -> list[str]:
    """Request lines for every AI writer: where the ad is seen and how this kind of business is sold."""
    info = catalog.PLATFORMS.get(platform, catalog.PLATFORMS["taxi_screen"])
    book = playbook_for(facts)
    lines = [f"- how it is watched: {info['viewing']}"]
    if book.id != "general":
        lines.append(f"- how this kind of business is sold: {book.lens}")
        lines.append(f"- what sells it on screen: {book.visual}")
    return lines
