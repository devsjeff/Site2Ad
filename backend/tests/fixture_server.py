"""A tiny threaded HTTP server for tests. Each instance is one 'website' on its own port."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional, Union


@dataclass
class Route:
    """One canned response. `stream_bytes` sends that many filler bytes without holding them in memory."""

    body: Union[str, bytes] = ""
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    stream_bytes: int = 0
    delay: float = 0.0


def html(body: str, **kw) -> Route:
    """Shortcut for an HTML route."""
    return Route(body=body, **kw)


class FixtureServer:
    """Serve routes from a dict {path: Route | callable(path, headers) -> Route}."""

    def __init__(self, routes: dict[str, Union[Route, Callable[[str, dict], Route]]]):
        """Create the server; call start() or use as a context manager."""
        self.routes = routes
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            """Request handler bound to this FixtureServer."""

            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # silence test output
                """Log message."""
                return

            def do_GET(self) -> None:  # noqa: N802
                """Look up the route and write the response."""
                path = self.path
                headers = {k.lower(): v for k, v in self.headers.items()}
                outer.requests.append((path, headers))
                route = outer.routes.get(path) or outer.routes.get(path.split("?")[0])
                if callable(route):
                    route = route(path, headers)
                if route is None:
                    route = Route(body="<html><title>Not found</title><body>not found</body></html>", status=404)
                if route.delay:
                    time.sleep(route.delay)
                text = route.body.replace("{BASE}", outer.base) if isinstance(route.body, str) else None
                body = text.encode("utf-8") if text is not None else route.body
                self.send_response(route.status)
                self.send_header("Content-Type", route.content_type)
                length = route.stream_bytes or len(body)
                self.send_header("Content-Length", str(length))
                for key, value in route.headers.items():
                    self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    if route.stream_bytes:
                        chunk = b"x" * 65536
                        remaining = route.stream_bytes
                        while remaining > 0:
                            self.wfile.write(chunk[: min(len(chunk), remaining)])
                            remaining -= len(chunk)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._thread: Optional[threading.Thread] = None

    @property
    def base(self) -> str:
        """Origin URL of this server (plain http)."""
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "FixtureServer":
        """Start serving in a background thread."""
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop the server."""
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> "FixtureServer":
        """Context manager entry: start."""
        return self.start()

    def __exit__(self, *exc) -> None:
        """Context manager exit: stop."""
        self.stop()

    def hit_paths(self) -> list[str]:
        """Paths requested so far."""
        return [path for path, _ in self.requests]
