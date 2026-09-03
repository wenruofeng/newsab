"""Loopback static serving for trees whose pages use root-relative URLs.

Every production page links `/zh-CN/...`, `/assets/site.css` and friends from the site
root, so a tree is only reviewable when it *is* a root.  That is why nothing here mounts a
tree under a path prefix: each root gets its own loopback port instead.

The overlay exists because of the content/chrome split.  A candidate bundle deliberately
carries no stylesheet or script — those are a site release fact — so anything serving
candidate bytes has to supply the chrome without writing it into the immutable bundle.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import threading
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional


class OverlayHandler(http.server.SimpleHTTPRequestHandler):
    """Serve a directory, falling back to in-memory bytes for absent paths."""

    #: Bundle-relative path -> bytes.  Disk always wins, so a deployed tree that really
    #: ships its own chrome is served exactly as deployed.
    overlay: Mapping[str, bytes] = {}

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        payload = self._overlaid()
        if payload is None:
            return super().do_GET()
        self.send_payload(payload)

    def do_HEAD(self) -> None:  # noqa: N802
        payload = self._overlaid()
        if payload is None:
            return super().do_HEAD()
        self.send_payload(payload, body=False)

    def _overlaid(self) -> Optional[bytes]:
        relative = self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        payload = self.overlay.get(relative)
        if payload is None:
            return None
        return None if (Path(self.directory) / relative).is_file() else payload

    def send_payload(
        self, payload: bytes, *, body: bool = True, content_type: Optional[str] = None
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type or self.guess_type(self.path))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(payload)


def make_handler(
    overlay: Optional[Mapping[str, bytes]] = None,
    base: type[OverlayHandler] = OverlayHandler,
) -> type[OverlayHandler]:
    return type("_BoundOverlayHandler", (base,), {"overlay": dict(overlay or {})})


def serve_forever_in_thread(
    root: Path,
    port: int,
    *,
    overlay: Optional[Mapping[str, bytes]] = None,
    handler_factory: Optional[Callable[[], type[http.server.BaseHTTPRequestHandler]]] = None,
) -> http.server.ThreadingHTTPServer:
    """Bind one loopback port and start serving; the caller owns shutdown."""
    handler_class = handler_factory() if handler_factory else make_handler(overlay)
    handler = functools.partial(handler_class, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@contextlib.contextmanager
def temporary_server(
    root: Path, overlay: Optional[Mapping[str, bytes]] = None
) -> Iterator[str]:
    """Serve ``root`` on an ephemeral loopback port for the duration of the block."""
    server = serve_forever_in_thread(root, 0, overlay=overlay)
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
