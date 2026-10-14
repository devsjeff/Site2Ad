"""Fetching pages with httpx: size caps, redirect re-checks, content-type checks, charset handling."""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from .safety import SafetyPolicy, UnsafeUrlError, check_url_shape

logger = logging.getLogger(__name__)

REDIRECT_CODES = (301, 302, 303, 307, 308)
ERROR_BODY_BYTES = 256 * 1024  # enough to recognise a challenge page, small enough to be harmless
HTML_TYPES = ("text/html", "application/xhtml")
TEXT_TYPES = ("text/plain", "text/xml", "application/xml", "text/html", "application/xhtml", "application/rss")
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-:.]+)""", re.I)


class Deadline:
    """One time budget passed down every step so the cap is enforced in a single place."""

    def __init__(self, seconds: float):
        """Start the clock now."""
        self.total = seconds
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        """Seconds left (never negative)."""
        return max(0.0, self._end - time.monotonic())

    @property
    def expired(self) -> bool:
        """True when no time is left."""
        return self.remaining() <= 0.0

    def cap(self, seconds: float) -> float:
        """The smaller of `seconds` and the time left."""
        return min(seconds, self.remaining())

    def child(self, seconds: float) -> "Deadline":
        """A deadline that ends after `seconds` or when this one ends, whichever is first."""
        return Deadline(self.cap(seconds))


@dataclass
class FetchResult:
    """Outcome of one fetch. `ok` pages carry decoded text in `html`."""

    ok: bool
    url: str
    status_code: int = 0
    html: str = ""
    body: bytes = b""  # raw bytes, filled only for binary fetches (images)
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""  # unsafe | timeout | too_large | not_html | wrong_type | http_error | ssl | network | redirects | budget
    redirects: list[str] = field(default_factory=list)


def decode_body(raw: bytes, content_type: str = "") -> str:
    """Decode bytes using the header charset, then a <meta charset>, then UTF-8, then Windows-1252."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    candidates: list[str] = []
    header_match = re.search(r"charset\s*=\s*([\w\-:.]+)", content_type or "", re.I)
    if header_match:
        candidates.append(header_match.group(1))
    meta = META_CHARSET.search(raw[:4096])
    if meta:
        candidates.append(meta.group(1).decode("ascii", errors="ignore"))
    for name in candidates:
        try:
            return raw.decode(name, errors="replace")
        except LookupError:
            continue
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("windows-1252", errors="replace")


def _is_ssl_error(exc: BaseException) -> bool:
    """True when the failure was a TLS/certificate problem."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLError):
            return True
        exc = exc.__cause__ or exc.__context__  # type: ignore[assignment]
    return False


class Fetcher:
    """Safe page fetcher. One instance is shared per scrape job; it never raises on network problems."""

    def __init__(self, client: httpx.AsyncClient, settings, policy: SafetyPolicy):
        """Store the shared client, settings and safety policy."""
        self.client = client
        self.settings = settings
        self.policy = policy

    async def get_binary(self, url: str, deadline: Deadline, *, max_bytes: int, content_types: tuple[str, ...] = ("image/",)) -> FetchResult:
        """GET a binary file (an image) with the same safety checks; the bytes come back in `FetchResult.body`."""
        return await self.get(url, deadline, max_bytes=max_bytes, binary_types=content_types)

    async def get(
        self, url: str, deadline: Deadline, *, as_text: bool = False, max_bytes: Optional[int] = None,
        binary_types: Optional[tuple[str, ...]] = None,
    ) -> FetchResult:
        """GET a URL following redirects by hand; every hop is checked, every failure becomes a FetchResult."""
        limit = max_bytes or self.settings.max_response_bytes
        current = url
        hops: list[str] = []
        for _ in range(self.settings.max_redirects + 1):
            if deadline.expired:
                return FetchResult(False, current, error="Ran out of time.", error_code="budget", redirects=hops)
            try:
                check_url_shape(current, self.policy)
            except UnsafeUrlError as exc:
                return FetchResult(False, current, error=exc.reason, error_code="unsafe", redirects=hops)
            result = await self._get_once(current, deadline, limit, as_text, binary_types)
            if result.error_code == "redirect":
                target = urljoin(current, result.error)
                hops.append(target)
                current = urlunparse(urlparse(target)._replace(fragment=""))
                continue
            result.redirects = hops
            return result
        return FetchResult(False, current, error="The site redirected too many times.", error_code="redirects", redirects=hops)

    async def get_with_fallback(
        self, url: str, deadline: Deadline, *, as_text: bool = False, max_bytes: Optional[int] = None
    ) -> tuple[FetchResult, list[str]]:
        """GET over https, falling back once to http when https cannot connect (flag insecure_ssl / http_only)."""
        flags: list[str] = []
        result = await self.get(url, deadline, as_text=as_text, max_bytes=max_bytes)
        if result.ok or result.error_code not in {"ssl", "network"} or not url.startswith("https://"):
            return result, flags
        fallback = await self.get("http://" + url[len("https://"):], deadline, as_text=as_text, max_bytes=max_bytes)
        if fallback.error_code not in {"ssl", "network"}:  # the server answered over http, even if with an error page
            flags.append("insecure_ssl" if result.error_code == "ssl" else "http_only")
            return fallback, flags
        return result, flags

    async def get_home(self, home_url: str, deadline: Deadline) -> tuple[FetchResult, list[str]]:
        """Fetch a homepage over https with the http fallback."""
        return await self.get_with_fallback(home_url, deadline)

    async def _get_once(
        self, url: str, deadline: Deadline, limit: int, as_text: bool, binary_types: Optional[tuple[str, ...]] = None
    ) -> FetchResult:
        """Make one request (no redirect following) with a retry for transient connection resets."""
        attempts = 2
        last = FetchResult(False, url, error="Could not connect.", error_code="network")
        for attempt in range(attempts):
            budget = deadline.cap(self.settings.request_timeout + 4)
            if budget <= 0.05:
                return FetchResult(False, url, error="Ran out of time.", error_code="budget")
            try:
                async with asyncio.timeout(budget):
                    return await self._stream(url, budget, limit, as_text, binary_types)
            except UnsafeUrlError as exc:
                return FetchResult(False, url, error=exc.reason, error_code="unsafe")
            except (TimeoutError, httpx.TimeoutException):
                return FetchResult(False, url, error="The site took too long to respond.", error_code="timeout")
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as exc:
                last = FetchResult(False, url, error="The connection was interrupted.", error_code="network")
                logger.debug("transient error on %s (attempt %s): %s", url, attempt + 1, exc)
                continue
            except httpx.HTTPError as exc:
                code = "ssl" if _is_ssl_error(exc) else "network"
                message = "The site's security certificate could not be verified." if code == "ssl" else "Could not connect to the site."
                return FetchResult(False, url, error=message, error_code=code)
            except Exception as exc:  # defensive: a bad response must never crash the scrape
                logger.warning("unexpected fetch error for %s: %r", url, exc)
                return FetchResult(False, url, error="Could not read the site.", error_code="network")
        return last

    async def _stream(
        self, url: str, budget: float, limit: int, as_text: bool, binary_types: Optional[tuple[str, ...]] = None
    ) -> FetchResult:
        """Stream one response, enforcing content-type and size limits before decoding."""
        timeout = httpx.Timeout(min(self.settings.request_timeout, budget), connect=min(5.0, budget))
        async with self.client.stream("GET", url, timeout=timeout) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            status = response.status_code
            if status in REDIRECT_CODES:
                location = headers.get("location", "")
                if not location:
                    return FetchResult(False, url, status, headers=headers, error="Bad redirect.", error_code="http_error")
                return FetchResult(False, url, status, headers=headers, error=location, error_code="redirect")
            content_type = headers.get("content-type", "").lower()
            if status >= 400:
                raw = await _read_limited(response, ERROR_BODY_BYTES, truncate=True)
                return FetchResult(
                    False, url, status, html=decode_body(raw or b"", content_type), headers=headers,
                    error=f"The site answered with status {status}.", error_code="http_error",
                )
            if binary_types:
                if content_type and not any(content_type.startswith(t) for t in binary_types):
                    return FetchResult(False, url, status, headers=headers, error="That address is not an image.", error_code="wrong_type")
            else:
                allowed = TEXT_TYPES if as_text else HTML_TYPES
                if content_type and not any(t in content_type for t in allowed):
                    return FetchResult(False, url, status, headers=headers, error="That address is not a web page.", error_code="not_html")
            too_large_message = "The image is too large." if binary_types else "The page is too large to scan."
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                return FetchResult(False, url, status, headers=headers, error=too_large_message, error_code="too_large")
            raw = await _read_limited(response, limit)
            if raw is None:
                return FetchResult(False, url, status, headers=headers, error=too_large_message, error_code="too_large")
            if binary_types:
                return FetchResult(True, url, status, body=raw, headers=headers)
            return FetchResult(True, url, status, html=decode_body(raw, content_type), headers=headers)


async def _read_limited(response: httpx.Response, limit: int, truncate: bool = False) -> Optional[bytes]:
    """Read at most `limit` decoded bytes. Returns None when over the limit (or the cut body if truncate)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            if truncate:
                chunks.append(chunk[: max(0, limit - (total - len(chunk)))])
                break
            return None
        chunks.append(chunk)
    return b"".join(chunks)
