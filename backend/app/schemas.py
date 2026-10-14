"""Pydantic models: the single API contract shared by routes, scraper, prompt builder and tests."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import catalog

SCHEMA_VERSION = 1

ScrapeStatus = Literal[
    "ok", "partial", "blocked", "unreachable", "invalid_url", "unsupported_platform", "timeout", "internal_error"
]
JobStatus = Literal[
    "queued", "running",
    "ok", "partial", "blocked", "unreachable", "invalid_url", "unsupported_platform", "timeout", "internal_error",
]
ScrapeStage = Literal["queued", "fetching", "rendering", "extracting", "ad_ready"]
PhoneSource = Literal["tel_link", "whatsapp_link", "json_ld", "header", "footer", "body", "contact_page", "user"]
AdStatus = Literal["queued", "running", "completed", "completed_with_fallback", "failed"]
AdStage = Literal[
    "queued", "preparing", "prompt_building", "prompt_ready", "generating_video", "composing", "finalizing", "completed", "failed"
]
CreationMode = Literal["manual", "auto"]
CreativeMode = Literal["website", "ai", "mixed"]
SegmentKind = Literal["website_image", "uploaded_image", "uploaded_video", "ai_video", "fallback_video"]

TERMINAL_JOB_STATUSES = {"ok", "partial", "blocked", "unreachable", "invalid_url", "unsupported_platform", "timeout", "internal_error"}
TERMINAL_AD_STATUSES = {"completed", "completed_with_fallback", "failed"}


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


class ApiModel(BaseModel):
    """Base class: ignore unknown fields so old clients and cached JSON keep working."""

    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- scrape result


class Phone(ApiModel):
    """One phone number candidate with where it was found."""

    number: str
    display: str = ""
    source: PhoneSource = "body"


class SiteInfo(ApiModel):
    """Business facts and metadata taken from the website."""

    name: str = ""
    title: str = ""
    description: str = ""
    language: str = ""
    logo: str = ""
    favicon: str = ""
    phone: str = ""
    phones: list[Phone] = Field(default_factory=list)
    address: str = ""
    category: str = ""
    services: list[str] = Field(default_factory=list)
    offer: str = ""
    cta: str = ""
    brand_colors: list[str] = Field(default_factory=list)
    text_excerpt: str = ""


class Contacts(ApiModel):
    """Other contact channels found on the page."""

    whatsapp: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    social: list[str] = Field(default_factory=list)


class PageInfo(ApiModel):
    """A secondary page read during phase 2."""

    url: str
    title: str = ""
    description: str = ""
    text_excerpt: str = ""
    kind: str = ""
    rendered_with: Literal["httpx", "playwright"] = "httpx"


class ScrapeMeta(ApiModel):
    """How the page was read."""

    rendered_with: Literal["httpx", "playwright"] = "httpx"
    bot_protection: Optional[str] = None
    csr_score: int = 0
    embedded_data: bool = False
    took_ms: int = 0
    phase: int = 1
    browser: Optional[str] = None


class ScrapeResult(ApiModel):
    """Everything the scraper returns. It is always returned, never raised."""

    schema_version: int = SCHEMA_VERSION
    status: ScrapeStatus = "internal_error"
    message: str = ""
    final_url: str = ""
    home_url: str = ""
    site: SiteInfo = Field(default_factory=SiteInfo)
    images: list[str] = Field(default_factory=list)
    contacts: Contacts = Field(default_factory=Contacts)
    pages: list[PageInfo] = Field(default_factory=list)
    meta: ScrapeMeta = Field(default_factory=ScrapeMeta)
    flags: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- jobs


class ScrapeRequest(ApiModel):
    """Body of POST /api/scrape."""

    url: str = Field(min_length=3, max_length=2048)
    refresh: bool = False

    @field_validator("url")
    @classmethod
    def _strip(cls, value: str) -> str:
        """Trim whitespace around the URL."""
        return value.strip()


class Phase2Info(ApiModel):
    """Progress of the background crawl of extra pages."""

    state: Literal["pending", "running", "done", "skipped", "failed"] = "pending"
    pages_done: int = 0
    pages_total: int = 0


class JobResponse(ApiModel):
    """Body of GET /api/jobs/{job_id} and the response of POST /api/scrape."""

    job_id: str
    url: str
    status: JobStatus = "queued"
    stage: ScrapeStage = "queued"
    progress: int = 0
    message: str = ""
    cached: bool = False
    is_final: bool = False
    phase2: Phase2Info = Field(default_factory=Phase2Info)
    result: Optional[ScrapeResult] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- uploads


class AssetInfo(ApiModel):
    """A user uploaded image or video."""

    asset_id: str
    kind: Literal["logo", "photo", "video"]
    url: str
    filename: str = ""
    width: int = 0
    height: int = 0
    bytes: int = 0
    media_type: Literal["image", "video"] = "image"
    duration_seconds: float = 0.0
    has_audio: bool = False


class UploadResponse(ApiModel):
    """Body of POST /api/uploads."""

    assets: list[AssetInfo]


# --------------------------------------------------------------------------- ads


class AdOptions(ApiModel):
    """Creative options for ONE ad. For another ad, call the pipeline again with different options."""

    goal: str = "awareness"
    platform: str = "taxi_screen"
    duration_seconds: int = Field(default=5, ge=3, le=30)
    style: str = "cinematic_premium"
    tone: str = "friendly"
    special_instructions: str = Field(default="", max_length=600)
    add_overlays: bool = True

    @field_validator("goal")
    @classmethod
    def _goal(cls, value: str) -> str:
        """Accept only known goals."""
        if value not in catalog.GOALS:
            raise ValueError(f"goal must be one of {sorted(catalog.GOALS)}")
        return value

    @field_validator("platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        """Accept only known platforms."""
        if value not in catalog.PLATFORMS:
            raise ValueError(f"platform must be one of {sorted(catalog.PLATFORMS)}")
        return value

    @field_validator("style")
    @classmethod
    def _style(cls, value: str) -> str:
        """Accept only known styles."""
        if value not in catalog.STYLES:
            raise ValueError(f"style must be one of {sorted(catalog.STYLES)}")
        return value

    @field_validator("tone")
    @classmethod
    def _tone(cls, value: str) -> str:
        """Accept only known tones."""
        if value not in catalog.TONES:
            raise ValueError(f"tone must be one of {sorted(catalog.TONES)}")
        return value

    @property
    def aspect_ratio(self) -> str:
        """Aspect ratio implied by the platform."""
        return catalog.aspect_for(self.platform)


class BusinessOverrides(ApiModel):
    """Facts typed by the user. They win over scraped facts and count as verified."""

    name: str = Field(default="", max_length=120)
    website_url: str = Field(default="", max_length=2048)
    category: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=800)
    phone: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=240)
    offer: str = Field(default="", max_length=160)
    cta: str = Field(default="", max_length=80)
    services: list[str] = Field(default_factory=list, max_length=10)
    # Scraped facts the user deleted on purpose (for example a wrong phone number). They are left out of the ad.
    omit: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("omit")
    @classmethod
    def _omit_known(cls, value: list[str]) -> list[str]:
        """Only facts that can be scraped may be omitted."""
        allowed = {"description", "category", "phone", "address", "offer", "cta", "services"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"omit may only contain {sorted(allowed)}; got {unknown}")
        return value


class HeroRef(ApiModel):
    """Which ONE image becomes the first frame of the video."""

    source: Literal["scraped", "asset"] = "scraped"
    url: Optional[str] = None
    asset_id: Optional[str] = None

    @model_validator(mode="after")
    def _one_ref(self) -> "HeroRef":
        """A hero needs a url (scraped) or an asset id (uploaded)."""
        if self.source == "scraped" and not self.url:
            raise ValueError("hero.url is required when source is 'scraped'")
        if self.source == "asset" and not self.asset_id:
            raise ValueError("hero.asset_id is required when source is 'asset'")
        return self


def validate_destination_url(value: str) -> str:
    """A QR destination typed by the user: an absolute public http(s) address. It is encoded exactly as given (trimmed)."""
    url = (value or "").strip()
    if not url:
        raise ValueError("qr_url is required when include_qr is true")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ValueError("qr_url must not contain spaces")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  (raises ValueError for a bad port)
    except ValueError:
        raise ValueError("qr_url is not a valid web address") from None
    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("qr_url must start with http:// or https://")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("qr_url must contain a domain name")
    if parts.username or parts.password:
        raise ValueError("qr_url must not contain a user name or password")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError("qr_url must be a public web address")
    if ip is None and (host == "localhost" or "." not in host or host.endswith((".localhost", ".local", ".internal", ".lan"))):
        raise ValueError("qr_url must be a public web address")
    return url


class CreativeConfig(ApiModel):
    """How ONE ad is made. The backend validates every combination; the browser never decides alone what runs.

    manual          -> your uploaded images/videos, FFmpeg only (no scan, no prompt writer, no AI video)
    auto + website  -> original website images, FFmpeg only (no AI video, no prompt writer)
    auto + ai       -> website facts -> ONE prompt -> AI text-to-video (no website images) -> loop to length -> finalize
    auto + mixed    -> website image(s) -> AI video -> website image(s), composed with FFmpeg
    """

    creation_mode: CreationMode = "auto"
    creative_mode: Optional[CreativeMode] = None
    use_website_images: bool = False
    use_ai_video: bool = False
    use_uploaded_media: bool = False
    prefer_website_images: bool = True  # when website images and uploads are both used, website images come first
    include_logo: bool = True
    include_qr: bool = False
    qr_url: str = Field(default="", max_length=2048)
    selected_image_urls: list[str] = Field(default_factory=list, max_length=8)
    media_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    keep_audio: bool = True  # uploaded/generated sound is kept; False makes a silent MP4 (e.g. taxi screens)

    @field_validator("selected_image_urls")
    @classmethod
    def _image_urls(cls, value: list[str]) -> list[str]:
        """Absolute http(s) addresses only, without duplicates (they are re-checked against the scan later)."""
        out: list[str] = []
        for raw in value:
            url = raw.strip()
            if not url.lower().startswith(("http://", "https://")) or len(url) > 2048:
                raise ValueError("selected_image_urls must be http(s) image addresses from the website scan")
            if url not in out:
                out.append(url)
        return out

    @field_validator("media_asset_ids")
    @classmethod
    def _asset_ids(cls, value: list[str]) -> list[str]:
        """Upload ids only (32 hex characters), without duplicates."""
        out: list[str] = []
        for asset_id in value:
            if not (len(asset_id) == 32 and all(c in "0123456789abcdef" for c in asset_id)):
                raise ValueError("media_asset_ids must be ids returned by POST /api/uploads")
            if asset_id not in out:
                out.append(asset_id)
        return out

    @model_validator(mode="after")
    def _consistent(self) -> "CreativeConfig":
        """Reject contradictory combinations instead of guessing what the user meant."""
        if self.creation_mode == "manual":
            if self.creative_mode is not None:
                raise ValueError("creative_mode is only used by auto ads; leave it empty for a manual ad")
            if self.use_ai_video:
                raise ValueError("manual ads are made with FFmpeg only and never call the AI video provider")
            if self.use_website_images or self.selected_image_urls:
                raise ValueError("manual ads use only your uploaded media, not website images")
            if not self.use_uploaded_media or not self.media_asset_ids:
                raise ValueError("a manual ad needs at least one uploaded image or video (use_uploaded_media and media_asset_ids)")
        else:
            if self.creative_mode is None:
                raise ValueError("creative_mode (website, ai or mixed) is required for an auto ad")
            if self.creative_mode == "website":
                if self.use_ai_video:
                    raise ValueError("website mode never calls the AI video provider; choose ai or mixed for AI video")
                if not self.use_website_images:
                    raise ValueError("website mode needs use_website_images")
            elif self.creative_mode == "ai":
                if not self.use_ai_video:
                    raise ValueError("ai mode needs use_ai_video; choose website mode for an ad without AI video")
                if self.use_website_images:
                    raise ValueError("ai mode is AI-generated footage only; choose mixed to include website images")
            elif self.creative_mode == "mixed" and not (self.use_ai_video and self.use_website_images):
                raise ValueError("mixed mode needs both use_website_images and use_ai_video")
            if self.selected_image_urls and not self.use_website_images:
                raise ValueError("selected_image_urls needs use_website_images")
            if self.use_uploaded_media != bool(self.media_asset_ids):
                raise ValueError("use_uploaded_media and media_asset_ids must be given together")
        if self.include_qr:
            self.qr_url = validate_destination_url(self.qr_url)
        elif self.qr_url.strip():
            raise ValueError("qr_url is set but include_qr is false")
        return self

    @property
    def calls_ai_video(self) -> bool:
        """True when this configuration is allowed to call the (paid) AI video provider."""
        return self.creation_mode == "auto" and self.creative_mode in {"ai", "mixed"} and self.use_ai_video


class GenerateAdRequest(ApiModel):
    """Body of POST /api/generate-ad. Provide a scrape job_id, a scrape_result, or manual business details.

    Without `creative` the original one-prompt / one-hero AI flow runs unchanged (kept for older clients).
    """

    job_id: Optional[str] = None
    scrape_result: Optional[ScrapeResult] = None
    business: BusinessOverrides = Field(default_factory=BusinessOverrides)
    options: AdOptions = Field(default_factory=AdOptions)
    hero: Optional[HeroRef] = None
    logo_asset_id: Optional[str] = None
    photo_asset_ids: list[str] = Field(default_factory=list, max_length=15)
    wait_for_prompt: bool = True
    creative: Optional[CreativeConfig] = None

    @model_validator(mode="after")
    def _has_source(self) -> "GenerateAdRequest":
        """Need some business information (or uploaded media) and no fields that contradict the creative mode."""
        creative = self.creative
        has_scan = bool(self.job_id or self.scrape_result)
        if creative is not None:
            if self.photo_asset_ids:
                raise ValueError("with creative, list uploaded photos and videos in creative.media_asset_ids")
            if creative.creation_mode == "manual":
                if has_scan:
                    raise ValueError("manual ads do not use a website scan; remove job_id and scrape_result")
                if self.hero:
                    raise ValueError("hero is only used by the AI video modes")
                return self
            if creative.creative_mode in {"website", "mixed"} and not has_scan:
                raise ValueError(f"{creative.creative_mode} mode needs a website scan (job_id or scrape_result)")
            if creative.creative_mode == "website" and self.hero:
                raise ValueError("hero is only used by the AI video modes; website ads use creative.selected_image_urls")
        if not (has_scan or self.business.name.strip()):
            raise ValueError("Provide job_id, scrape_result, or business.name")
        return self


class ReferenceImage(ApiModel):
    """The hero image sent to the video model together with the prompt."""

    source: Literal["scraped", "asset"] = "scraped"
    url: Optional[str] = None
    asset_id: Optional[str] = None
    role: Literal["first_frame"] = "first_frame"
    width: int = 0
    height: int = 0


class AdPrompt(ApiModel):
    """The ONE video prompt for ONE ad, plus its negative prompt."""

    final_prompt: str
    positive_prompt: str
    negative_prompt: str
    platform: str
    duration_seconds: int
    aspect_ratio: str
    shot_count: int
    builder: Literal["llm", "template"] = "template"
    model: str = ""
    reference_image: Optional[ReferenceImage] = None
    warnings: list[str] = Field(default_factory=list)


class BriefFact(ApiModel):
    """One supporting fact in an ad brief, with where it came from."""

    field: str
    text: str
    origin: Literal["user", "website"] = "website"
    url: str = ""


class BriefConcept(ApiModel):
    """One creative concept: a visual idea and the scene(s) that film it."""

    title: str = Field(min_length=1, max_length=80)
    visual: str = Field(min_length=20, max_length=700)
    scenes: list[str] = Field(default_factory=list, max_length=4)


class AdBrief(ApiModel):
    """The validated plan between the facts and the video prompt: what the ad says, shows and puts on screen.

    Only facts from the FactSheet appear in `supporting_facts`, `cta` and `overlay_text`; missing facts are listed in
    `missing` instead of being invented, and claims about other businesses are listed in `rejected_claims`.
    """

    business_name: str
    product_focus: str = ""
    audience: str = ""
    objective: str = ""
    main_message: str = ""
    hook: str = ""
    cta: str = ""
    supporting_facts: list[BriefFact] = Field(default_factory=list)
    concepts: list[BriefConcept] = Field(default_factory=list, min_length=1, max_length=3)
    chosen_concept: int = 0
    overlay_text: list[str] = Field(default_factory=list)
    brand_assets: list[str] = Field(default_factory=list)
    duration_seconds: int = 5
    aspect_ratio: str = "16:9"
    missing: list[str] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)
    builder: Literal["llm", "template"] = "template"

    @model_validator(mode="after")
    def _chosen_exists(self) -> "AdBrief":
        """The chosen concept must be one of the concepts."""
        if not 0 <= self.chosen_concept < len(self.concepts):
            raise ValueError("chosen_concept must point at one of the concepts")
        return self

    @property
    def concept(self) -> BriefConcept:
        """The concept the video is made from."""
        return self.concepts[self.chosen_concept]


class CompositionSegment(ApiModel):
    """One part of the finished video, in order: what it is, where it came from, how long it plays."""

    kind: SegmentKind
    source: str = ""  # image URL, asset id or provider name
    seconds: float = 0.0


class AdResponse(ApiModel):
    """Body of GET /api/ads/{ad_id} and the response of POST /api/generate-ad."""

    ad_id: str
    job_id: Optional[str] = None
    status: AdStatus = "queued"
    stage: AdStage = "queued"
    progress: int = 0
    message: str = ""
    prompt: Optional[AdPrompt] = None
    video_url: Optional[str] = None
    provider: str = ""
    fallback_used: bool = False
    actual_duration_seconds: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    options: AdOptions = Field(default_factory=AdOptions)
    creative: Optional[CreativeConfig] = None
    ai_video_used: bool = False  # True only when the configured AI provider (not a fallback) made the footage
    qr_added: bool = False
    composition: list[CompositionSegment] = Field(default_factory=list)
    brief: Optional[AdBrief] = None  # the plan the AI video was made from (AI modes only)
    provider_error: Optional[str] = None  # why the video provider failed (kept even when a fallback clip was used)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CreativeModeInfo(ApiModel):
    """One way of making an ad, as offered by GET /api/config (the UI lists these instead of hard-coding them)."""

    id: Literal["manual", "website", "ai", "mixed"]
    creation_mode: CreationMode
    label: str
    description: str
    uses_scraper: bool
    uses_prompt_writer: bool
    uses_ai_video: bool
    available: bool = True
    unavailable_reason: str = ""


class ConfigResponse(ApiModel):
    """Body of GET /api/config: what this deployment can do, so the UI never hard-codes it."""

    api_version: str = "1"
    demo_mode: bool
    video_provider: str
    prompt_builder: Literal["llm", "template"]
    max_video_seconds: int
    durations: list[int]
    platforms: list[dict]
    goals: list[dict]
    styles: list[dict]
    tones: list[dict]
    categories: list[dict]
    max_upload_bytes: int
    max_upload_files: int
    phase2_mode: str
    ai_video_available: bool = False
    ai_video_message: str = ""
    creative_modes: list[CreativeModeInfo] = Field(default_factory=list)
    compose_durations: list[int] = Field(default_factory=list)
    website_image_seconds: float = 2.5
    max_video_upload_bytes: int = 0
    max_video_upload_seconds: int = 0


class HealthResponse(ApiModel):
    """Body of /health."""

    status: str = "ok"


class ReadyResponse(ApiModel):
    """Body of /ready."""

    status: str
    database: bool
    redis: Optional[bool] = None
    video_provider: str
    prompt_builder: str
    browser: str
    problems: list[str] = Field(default_factory=list)


class ErrorResponse(ApiModel):
    """Error body used by every non-2xx response."""

    detail: str
    code: str = "error"
