"""URL normalisation and SSRF protection.

Every outgoing request of the scraper goes through this module:

* `normalize_input_url` turns whatever the user typed into a clean https URL.
* `resolve_public` resolves a hostname and rejects it unless EVERY address is public.
* `SafeNetworkBackend` plugs into httpcore so the check happens at connect time and the socket is opened
  to the exact IP that was checked. That closes the DNS-rebinding gap between "check" and "connect".
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import ParseResult, urlparse, urlunparse

import httpcore
import httpx

MAX_URL_LENGTH = 2048

BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "broadcasthost",
        "metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal",
    }
)
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa", ".intranet", ".lan")

MEDIA_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".avif",
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".ogg", ".flac",
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".exe", ".dmg", ".apk", ".msi",
    ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)

# Hosts we do not scrape: login walls, apps or marketplaces. The frontend shows the manual form instead.
UNSUPPORTED_PLATFORMS = {
    "instagram.com": "Instagram", "facebook.com": "Facebook", "fb.com": "Facebook", "fb.me": "Facebook",
    "twitter.com": "X (Twitter)", "x.com": "X (Twitter)", "tiktok.com": "TikTok", "youtube.com": "YouTube",
    "youtu.be": "YouTube", "linkedin.com": "LinkedIn", "wa.me": "WhatsApp", "whatsapp.com": "WhatsApp",
    "t.me": "Telegram", "linktr.ee": "Linktree", "justdial.com": "Justdial", "indiamart.com": "IndiaMART",
    "g.page": "Google Business", "goo.gl": "Google Maps", "maps.app.goo.gl": "Google Maps",
    "play.google.com": "Google Play", "apps.apple.com": "the App Store", "amazon.in": "Amazon", "amazon.com": "Amazon",
    "flipkart.com": "Flipkart", "pinterest.com": "Pinterest", "snapchat.com": "Snapchat",
}

# Hosts where many businesses share one domain and the business is identified by the path.
# value = how many path segments identify the tenant (sites.google.com/view/<name> -> 2).
PATH_TENANT_HOSTS = {"sites.google.com": 2, "wixsite.com": 1}


class UnsafeUrlError(Exception):
    """Raised when a URL or address must not be fetched. `reason` is safe to show to users."""

    def __init__(self, reason: str, kind: str = "unsafe"):
        """Store the user-safe reason; kind is 'unsafe' (forbidden target) or 'dns' (name does not exist)."""
        super().__init__(reason)
        self.reason = reason
        self.kind = kind


@dataclass(frozen=True)
class SafetyPolicy:
    """What the scraper may connect to. The defaults are the production rules."""

    allow_private: bool = False
    allowed_ports: Optional[tuple[int, ...]] = (80, 443)  # None = any port
    exempt_hosts: frozenset[str] = field(default_factory=frozenset)  # exact host names skipped by the IP check (tests only)

    @classmethod
    def from_settings(cls, settings) -> "SafetyPolicy":
        """Build the policy from Settings (UNSAFE_ALLOW_PRIVATE_NETWORKS lifts the checks)."""
        if settings.unsafe_allow_private_networks:
            return cls(allow_private=True, allowed_ports=None)
        return cls()


DEFAULT_POLICY = SafetyPolicy()


@dataclass(frozen=True)
class NormalizedUrl:
    """A user-typed URL after cleaning."""

    url: str  # full URL the user pointed at (fragment removed)
    home_url: str  # homepage to scrape, e.g. https://site.com/
    host: str
    scheme: str
    path: str
    scheme_explicit: bool
    is_inner_page: bool

    @property
    def cache_key(self) -> str:
        """Key used by the per-site result cache: host, plus tenant path on multi-tenant hosts."""
        parsed = urlparse(self.home_url)
        return (parsed.netloc + parsed.path.rstrip("/")).lower()


def is_media_url(path: str) -> bool:
    """True when the path ends in an extension of a non-HTML file (image, video, archive, script...)."""
    return path.lower().split("?")[0].endswith(MEDIA_EXTENSIONS)


def match_platform(host: str) -> Optional[str]:
    """Return the platform name when host belongs to an unsupported platform, else None."""
    host = host.lower()
    for domain, name in UNSUPPORTED_PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def _tenant_segments(host: str) -> int:
    """How many leading path segments identify the business on a shared host (0 for normal sites)."""
    for domain, count in PATH_TENANT_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return count
    return 0


def normalize_input_url(raw: str, policy: Optional["SafetyPolicy"] = None) -> NormalizedUrl:
    """Clean user input into a NormalizedUrl or raise UnsafeUrlError with a friendly reason."""
    policy = policy or DEFAULT_POLICY
    text = (raw or "").strip()
    if not text:
        raise UnsafeUrlError("No website address was given.")
    if len(text) > MAX_URL_LENGTH:
        raise UnsafeUrlError("That web address is too long.")
    if any(ch in text for ch in ("\x00", "\r", "\n", "\t", " ")):
        raise UnsafeUrlError("That web address contains invalid characters.")
    explicit = "://" in text
    candidate = text if explicit else "https://" + text.lstrip("/")
    try:
        parsed = urlparse(candidate)
        port = parsed.port
    except ValueError:
        raise UnsafeUrlError("That web address could not be read.") from None
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https web addresses are allowed.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Web addresses with a username or password are not allowed.")
    host = (parsed.hostname or "").strip(".").lower()
    if not host:
        raise UnsafeUrlError("That web address has no website name.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise UnsafeUrlError("That website name is not valid.") from None
    exempt = policy.allow_private or host in policy.exempt_hosts
    if not exempt and (host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES)):
        raise UnsafeUrlError("Internal addresses are not allowed.")
    looks_numeric = host.isdigit() or host.startswith("0x")  # decimal/hex IPv4 forms are caught by the DNS check
    if "." not in host and ":" not in host and not looks_numeric:
        raise UnsafeUrlError("That doesn't look like a website address (for example: yourbusiness.com).")
    if policy.allowed_ports is not None and port not in (None, *policy.allowed_ports):
        raise UnsafeUrlError("Only the standard web ports (80 and 443) are allowed.")
    if is_media_url(parsed.path):
        raise UnsafeUrlError("Links to images, videos and files cannot be scanned. Please enter your website address.")

    netloc = host if ":" not in host else f"[{host}]"
    if port not in (None, 80, 443):
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    clean = urlunparse((parsed.scheme, netloc, path, "", parsed.query, ""))
    tenant = _tenant_segments(host)
    if tenant:
        parts = [p for p in path.split("/") if p][:tenant]
        home_path = "/" + "/".join(parts) + "/" if parts else "/"
    else:
        home_path = "/"
    home = urlunparse(("https", netloc, home_path, "", "", ""))
    is_inner = path.rstrip("/") != home_path.rstrip("/") or bool(parsed.query)
    return NormalizedUrl(clean, home, host, parsed.scheme, path, explicit, is_inner)


def home_url_of(url: str) -> str:
    """Homepage URL for any page URL (keeps the tenant path on shared hosts such as sites.google.com)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    tenant = _tenant_segments(host)
    parts = [p for p in parsed.path.split("/") if p][:tenant] if tenant else []
    path = "/" + "/".join(parts) + "/" if parts else "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


# --------------------------------------------------------------------------- address checks


def _embedded_v4(ip: ipaddress.IPv6Address) -> Optional[ipaddress.IPv4Address]:
    """Return the IPv4 hidden inside IPv4-mapped, NAT64 or 6to4 IPv6 addresses, if any."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in ipaddress.ip_network("64:ff9b::/96"):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in ipaddress.ip_network("2002::/16"):
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return None


def ip_is_public(ip_text: str) -> bool:
    """True only for globally routable unicast addresses (IPv4 or IPv6)."""
    try:
        ip = ipaddress.ip_address(ip_text.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None:
            return ip_is_public(str(inner))
    if (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    ):
        return False
    return bool(ip.is_global)


async def resolve_public(host: str, port: int, policy: SafetyPolicy = DEFAULT_POLICY) -> list[str]:
    """Resolve host and return its IPs; raise UnsafeUrlError unless every address is allowed."""
    host = host.strip("[]").lower()
    if policy.allowed_ports is not None and port not in policy.allowed_ports:
        raise UnsafeUrlError("Only the standard web ports (80 and 443) are allowed.")
    exempt = policy.allow_private or host in policy.exempt_hosts
    if not exempt and (host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES)):
        raise UnsafeUrlError("Internal addresses are not allowed.")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise UnsafeUrlError("That website name could not be found.", kind="dns") from None
    ips: list[str] = []
    for info in infos:
        ip = str(info[4][0]).split("%")[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise UnsafeUrlError("That website name could not be found.", kind="dns")
    if not exempt:
        for ip in ips:
            if not ip_is_public(ip):
                raise UnsafeUrlError("That address points to a private or internal network, so it cannot be scanned.")
    return ips


def check_url_shape(url: str, policy: SafetyPolicy = DEFAULT_POLICY) -> ParseResult:
    """Cheap, no-network validation of a URL we are about to fetch; returns the parsed URL or raises."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise UnsafeUrlError("That web address could not be read.") from None
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https web addresses are allowed.")
    if not parsed.hostname:
        raise UnsafeUrlError("That web address has no website name.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Web addresses with a username or password are not allowed.")
    if policy.allowed_ports is not None and port not in (None, *policy.allowed_ports):
        raise UnsafeUrlError("Only the standard web ports (80 and 443) are allowed.")
    host = parsed.hostname.lower()
    if not policy.allow_private and host not in policy.exempt_hosts and (host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES)):
        raise UnsafeUrlError("Internal addresses are not allowed.")
    return parsed


async def check_url_is_safe(url: str, policy: SafetyPolicy = DEFAULT_POLICY) -> None:
    """Full pre-flight for a URL: shape plus DNS. Raises UnsafeUrlError when it must not be fetched."""
    parsed = check_url_shape(url, policy)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    await resolve_public(parsed.hostname, port, policy)


# --------------------------------------------------------------------------- httpx integration


class SafeNetworkBackend(httpcore.AnyIOBackend):
    """Network backend that validates the resolved IPs and then connects to the validated IP itself."""

    def __init__(self, policy: SafetyPolicy = DEFAULT_POLICY):
        """Keep the policy used for every connection."""
        super().__init__()
        self.policy = policy

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        """Resolve, check, then open the socket to a checked address (never to the hostname again)."""
        ips = await resolve_public(host, port, self.policy)
        last_error: Exception | None = None
        for ip in ips:
            try:
                return await super().connect_tcp(
                    ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError("could not connect")


def build_http_client(settings, policy: Optional[SafetyPolicy] = None) -> httpx.AsyncClient:
    """Create the shared httpx client: no env proxies, no auto redirects, SSRF-safe connections."""
    policy = policy or SafetyPolicy.from_settings(settings)
    transport = httpx.AsyncHTTPTransport(
        retries=0,
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=10, keepalive_expiry=15),
    )
    # httpx does not expose network_backend; swapping it on the pool is the documented httpcore extension point.
    transport._pool._network_backend = SafeNetworkBackend(policy)  # type: ignore[attr-defined]
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(settings.request_timeout, connect=min(5.0, settings.request_timeout)),
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8,hi;q=0.5",
        },
    )
