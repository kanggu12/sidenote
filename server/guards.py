"""Who may talk to the server, and what every answer carries. The panel shows the screen and what was heard and has no
login, so only this machine's addresses (Host), the panel's own page (Origin) and the published port or this container
(the peer) reach it; and every HTTP answer carries the headers that keep a page of another site from framing or reading
it. Pure ASGI middleware and checks, with nothing of the server's state: app.py puts them in front of everything.
"""
from __future__ import annotations

import ipaddress
import struct
from urllib.parse import urlsplit

from fastapi import WebSocket

from . import telemetry
from .config import CONFIG

# Who may talk to the server. The panel shows your screen and what was heard, and has no login: any
# web page open in the browser could otherwise open ws://127.0.0.1:8777/panel (browsers allow
# cross-site WebSockets), or reach the server under its own domain pointed at 127.0.0.1 (DNS
# rebinding). So the Host must be this machine, and a browser's WebSocket must come from the panel.
LOCAL_HOSTS = ["127.0.0.1", "localhost"]


def same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True   # not a browser (the capture program, curl): a web page cannot open these
    return origin_ok(origin, ws.headers.get("host"))


def route_gateways(route_file: str = "/proc/net/route") -> set[ipaddress.IPv4Address]:
    """The gateway of this container's default route, from its routing table: the bridge Docker's proxy connects
    from when something comes in through the published port (any other route's gateway is not trusted)."""
    try:
        with open(route_file, encoding="ascii") as f:
            rows = [ln.split() for ln in f.readlines()[1:]]
    except OSError:
        return set()
    found = set()
    for row in rows:
        try:
            dest, gw, mask = (ipaddress.IPv4Address(struct.pack("<I", int(row[k], 16))) for k in (1, 2, 7))
        except (IndexError, ValueError, struct.error):
            continue
        if int(gw) and not int(dest) and not int(mask):
            found.add(gw)
    return found


class PeerGuard:
    """Pure ASGI middleware: only the published port and this container itself reach the server. The browser and
    the capture program come in through the published port, so from the gateway of the network the default route
    goes through; any other peer is another container, above all the code runner: the example check runs code a
    model wrote from what is on the screen, and that code could otherwise open /panel or /ingest the way the
    capture program does (no Origin header, any Host it likes) and change settings or answer a confirmation.
    Nothing is looked up by name (a lookup of the runner, the first way, made every request wait out a slow
    resolver and let everything through until it answered). A peer that is not an address (an in-process test
    client) passes."""

    def __init__(self, app, route_file: str = "/proc/net/route", trust_gateway: bool | None = None):
        self.app = app
        self.route_file = route_file
        # SIDENOTE_TRUST_GATEWAY off (the Helm chart): loopback alone, as kubectl port-forward arrives
        self.trust_gateway = CONFIG.trust_gateway if trust_gateway is None else trust_gateway
        self.gateways = route_gateways(route_file) if self.trust_gateway else set()

    def allowed(self, peer) -> bool:
        if peer.version == 6 and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        if peer.is_loopback or peer in self.gateways:
            return True
        if not self.trust_gateway:
            return False
        self.gateways = route_gateways(self.route_file)   # the networks may have changed since
        return peer in self.gateways

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        try:
            peer = ipaddress.ip_address((scope.get("client") or ("",))[0])
        except ValueError:
            return await self.app(scope, receive, send)
        if self.allowed(peer):
            return await self.app(scope, receive, send)
        telemetry.event("refused", path=str(scope.get("path"))[:120], origin=f"peer {peer}")
        if scope["type"] == "websocket":
            await receive()   # the handshake's websocket.connect, then the refusal (an HTTP 403)
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"), *SECURITY_HEADERS]})
        await send({"type": "http.response.body", "body": b"forbidden"})


# Every HTTP answer: scripts, styles, fonts and connections only from this server (the panel's
# libraries are served from vendor/, fetched and checksum-verified when the image is built), no
# framing, no sniffing, no referrer, no camera or microphone. Inline styles stay allowed: KaTeX
# draws formulas with them (answer HTML cannot carry style attributes: DOMPurify drops them).
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), display-capture=(), usb=(), payment=()"),
    (b"cache-control", b"no-cache"),   # after an update the browser asks again instead of mixing old files
]


class SecurityHeaders:
    """Pure ASGI middleware (BaseHTTPMiddleware would buffer and does not see WebSockets anyway)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = [h for h in message.get("headers", []) if h[0].lower() != b"cache-control"] + SECURITY_HEADERS
            await send(message)

        await self.app(scope, receive, send_with_headers)


def origin_ok(origin: str, host: str | None) -> bool:
    """An Origin header that is this server's own page: the address the request was sent to (its Host)."""
    try:
        u = urlsplit(origin)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and u.netloc.lower() == (host or "").lower()
