"""The browser may only open public websites. The same rules as the scanner (app/scraper/safety.py), in a form a browser can call
for every request it makes (page, images, scripts), so a redirect or an embedded address cannot reach a private network."""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from ..scraper.safety import SafetyPolicy, UnsafeUrlError, check_url_shape, ip_is_public
from .config import StageError

LOCAL_SCHEMES = {"data", "blob", "about"}


def host_is_public(host: str, port: int, policy: SafetyPolicy, cache: dict[str, bool]) -> bool:
    """True when every address the host resolves to is public (cached per host, so a page with 80 images resolves once)."""
    if policy.allow_private or host in policy.exempt_hosts:
        return True
    key = f"{host}:{port}"
    if key not in cache:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            cache[key] = bool(infos) and all(ip_is_public(info[4][0]) for info in infos)
        except OSError:
            cache[key] = False
    return cache[key]


def request_allowed(url: str, policy: SafetyPolicy, cache: dict[str, bool]) -> bool:
    """Whether the browser may make this request."""
    scheme = urlparse(url).scheme.lower()
    if scheme in LOCAL_SCHEMES:
        return True
    try:
        parsed = check_url_shape(url, policy)
    except UnsafeUrlError:
        return False
    return host_is_public(parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80), policy, cache)


def check_page_url(url: str, policy: SafetyPolicy) -> None:
    """Stop before opening a browser at an address that is not a public website."""
    try:
        parsed = check_url_shape(url, policy)
    except UnsafeUrlError as exc:
        raise StageError(str(exc)) from None
    if not host_is_public(parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80), policy, {}):
        raise StageError("That address points to a private or internal network, so it cannot be opened.")
