"""Web search and page reading for the local LLM (tool calls).

The local model decides when it needs to look something up (a version, an exact option, an error
message it does not know) and calls these through OpenAI-style tools:
- web_search(query): a SearXNG instance in the compose project (no API key; it asks several engines
  and returns titles, URLs and snippets).
- fetch_page(url): the readable text of one page.

Page reads only go to public addresses on ports 80/443, checked again after every redirect: what
the model asks for can come from text on the screen, and the server also sits on the networks of
the code runner and the local LLM.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

log = logging.getLogger("sidenote.search")

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": ("Search the web. Use it for anything that must be current or exact and that you are not sure "
                        "of: versions and release notes, exact command options, API signatures or config keys of a "
                        "specific product, unfamiliar error messages, news. Returns titles, URLs and short snippets."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query; English usually finds more technical sources."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_page",
        "description": "Read the main text of a web page (for example a result of web_search) when its snippet is not enough.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "http or https URL"}},
            "required": ["url"]}}},
]

MAX_PAGE_BYTES = 2_000_000
PAGE_CHARS = 6000          # text handed back to the model per page
RESULTS = 6


def _global_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return addr.is_global and not addr.is_multicast


def _public(host: str) -> bool:
    """Every address the host resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        if not _global_ip(info[4][0]):
            return False
    return bool(infos)


def public_backend():
    """The network backend of the page fetches: it opens a connection only to an address it has checked itself.

    allowed_url checks the name and peer_ip the open socket, and between the two the request was already out: a name
    that resolved to a public address for the check and to a LAN one for the connect (DNS rebinding) still had its GET
    sent, on port 80 or 443 of a router or a NAS, before the socket's address turned it away. Here the name is resolved
    once, every address it gives must be public, and the socket opens to one of those same addresses. TLS still checks
    the certificate against the name: httpcore takes the server name from the URL, not from the address dialled."""
    import httpcore2  # lazy, as httpx2 in WebTools: only needed when search is on

    class PublicOnly(httpcore2.AsyncNetworkBackend):
        def __init__(self):
            self._inner = httpcore2.AnyIOBackend()   # what httpcore uses under asyncio, given an address instead of a name

        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            try:
                infos = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
            except OSError as exc:            # an unknown name: the same error a plain connect gives
                raise httpcore2.ConnectError(f"{host}: {exc}") from exc
            addrs = list(dict.fromkeys(info[4][0] for info in infos))   # in the resolver's order, each once
            if not addrs or not all(_global_ip(a) for a in addrs):
                raise httpcore2.ConnectError(f"not allowed: {host} resolves to an address that is not public")
            last = None
            for addr in addrs[:3]:            # the next address when one does not answer, as a connect by name does
                try:
                    return await self._inner.connect_tcp(addr, port, timeout=timeout, local_address=local_address,
                                                         socket_options=socket_options)
                except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                    last = exc
            raise last

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            raise httpcore2.ConnectError("not allowed: a local socket")

        async def sleep(self, seconds):
            await self._inner.sleep(seconds)

    return PublicOnly()


def peer_ip(response) -> str:
    """The address the page actually came from: the second check, after public_backend dialled only an address it
    checked. Empty when the transport does not say (then the name check holds)."""
    try:
        stream = response.extensions.get("network_stream")
        sock = stream.get_extra_info("socket") if stream is not None else None
        return str(sock.getpeername()[0]) if sock is not None else ""
    except Exception:
        return ""


def allowed_url(url: str) -> bool:
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    if u.port not in (None, 80, 443):
        return False
    return _public(u.hostname)


class _Text(HTMLParser):
    """Readable text of an HTML page: skips scripts, styles, navigation and similar chrome, and keeps
    the text inside <main>/<article> apart so a page's own content wins over its menus.

    What is open is held as a stack, and an end tag closes everything opened inside the element it
    closes, as a browser does. A counter instead of a stack loses a page whose chrome is left open:
    go.dev/dl opens four nested <nav> in its menu drawer and closes one, so from there on the counter
    never came back to zero and the whole download list was read as menu (66 characters of the page
    came back)."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button", "iframe"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "tr", "section", "article", "table",
             "blockquote", "dt", "dd"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
            "track", "wbr"}
    MAIN = ("main", "article")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.main: list[str] = []
        self.stack: list[str] = []
        self.in_main = 0
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)
            if tag in self.MAIN:
                self.in_main += 1
            if tag in self.SKIP:
                self.skip += 1
        if tag in self.SKIP:
            return
        if tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.out.append("\n")
            if self.in_main:
                self.main.append("\n")

    def handle_endtag(self, tag):
        if tag in self.stack:            # a stray end tag closes nothing, as a browser does
            while self.stack:
                open_tag = self.stack.pop()
                if open_tag in self.MAIN and self.in_main:
                    self.in_main -= 1
                if open_tag in self.SKIP and self.skip:
                    self.skip -= 1
                if open_tag == tag:
                    break
        if tag in self.SKIP:
            return
        if tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.out.append("\n")
            if self.in_main:
                self.main.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)
            if self.in_main:
                self.main.append(data)

    @staticmethod
    def _tidy(parts: list[str]) -> str:
        t = re.sub(r"[ \t\r\f\v]+", " ", "".join(parts))
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()

    def text(self) -> str:
        main = self._tidy(self.main)
        return main if len(main) >= 300 else self._tidy(self.out)


def read_html(page: str) -> tuple[str, str]:
    """A page's readable text and its title. Called in a thread, never on the event loop: measured
    0.19 s for 0.4 MB of HTML, 0.78 s for 1.6 MB (near enough linear, and MAX_PAGE_BYTES caps it at
    2 MB), and for all of that time the loop would be doing nothing else: no panel, no frames from
    the capture client, no running analysis."""
    p = _Text()
    p.feed(page)
    return p.text(), p.title.strip()


class WebTools:
    """Runs the tool calls; one shared HTTP client."""

    def __init__(self, cfg):
        import httpcore2  # lazy, both: only needed when search is on
        import httpx2

        self.cfg = cfg
        self._http = httpx2
        timeout = httpx2.Timeout(cfg.search_timeout, connect=4.0)
        headers = {"User-Agent": "Mozilla/5.0 (sidenote)"}
        # The search engine is the one private address this asks (the searxng container): its own client.
        self._client = httpx2.AsyncClient(timeout=timeout, headers=headers)
        # Pages come through a pool that dials only public addresses it resolved and checked (public_backend). The
        # transport takes no backend of its own, so its pool is swapped for one built with it; integ checks the swap.
        transport = httpx2.AsyncHTTPTransport()
        transport._pool = httpcore2.AsyncConnectionPool(ssl_context=transport._pool._ssl_context,
                                                        network_backend=public_backend())
        self._pages = httpx2.AsyncClient(timeout=timeout, headers=headers, transport=transport)
        self._kept: dict[tuple, tuple[float, str]] = {}   # (tool, query or address) -> (when, result): _cached

    # The same search and the same page within a few minutes are answered from here: a problem solved again, its check
    # and the thinking pass after the fast one ask the same things, and the search engines turn away a client that asks
    # often (after a day of benches: too many requests, CAPTCHA). Results that failed or came back empty are not kept.
    KEEP_SECONDS = 600
    KEEP_MAX = 64

    async def _cached(self, key: tuple, make) -> str:
        now = time.monotonic()
        hit = self._kept.get(key)
        if hit and now - hit[0] < self.KEEP_SECONDS:
            return hit[1]
        out = await make()
        try:
            good = not (d := json.loads(out)).get("error") and (d.get("results") or d.get("text"))
        except ValueError:
            good = False
        if good:
            if len(self._kept) >= self.KEEP_MAX:   # the oldest goes
                self._kept.pop(min(self._kept, key=lambda k: self._kept[k][0]))
            self._kept[key] = (now, out)
        return out

    # A question about the newest version of something is the one search where a snippet is reliably
    # useless: a search engine answers it with release notes and blog posts, and the number itself is
    # on the download page. The model is told to open that page and does not always do it, so for these
    # questions one official page is read here and handed back with the results. Measured: the search
    # for the newest Go release returned the release-notes page, the model answered "1.27.x", and the
    # download page it did not open held go1.27.3.
    VERSION_Q = re.compile(r"(latest|newest|current|최신|현재)[^\n]{0,40}(version|release|릴리스|버전)"
                           r"|(version|release|릴리스|버전)[^\n]{0,20}(latest|newest|최신)", re.I)
    # No word boundary in front: the number is written go1.27.3 and v26.12.1 as often as 1.27.3.
    VERSION_IN_TEXT = re.compile(r"\d+\.\d+\.\d+")
    OFFICIAL = ("go.dev/dl", "python.org/downloads", "nodejs.org", "/releases/latest", "/releases/tag/",
                "rust-lang.org", "golang.org/dl", "kernel.org", "kubernetes.io/releases",
                "docker.com/release-notes", "releases.hashicorp.com", "endoflife.date")
    PAGE_EXTRACT = 2000   # enough for the newest entries of a download list or a release channel

    # Where a version lives, for the few whose own page is not plain text. Everything else goes to
    # endoflife.date, which carries the current release of some hundreds of products, and a search
    # result that is an official page is used as the last way in.
    VERSION_SOURCES = {
        "go": "https://go.dev/dl/?mode=json",
        "golang": "https://go.dev/dl/?mode=json",
        "node": "https://nodejs.org/dist/index.json",
        "nodejs": "https://nodejs.org/dist/index.json",
        "rust": "https://static.rust-lang.org/dist/channel-rust-stable.toml",
    }
    EOL_API = "https://endoflife.date/api/{}.json"
    STOPWORDS = {"latest", "newest", "current", "stable", "version", "release", "releases", "최신", "현재",
                 "안정", "버전", "릴리스", "릴리즈", "의", "는", "은", "이", "가", "what", "is", "the", "of",
                 "지금", "오늘", "요즘", "lts"}

    def _product(self, query: str) -> str:
        """The thing the question is about: the query without the words that ask for a version."""
        words = [w.strip(".,?!'\"()[]") for w in re.split(r"[\s/]+", query.lower())]
        for w in words:
            w = re.sub(r"(의|는|은|이|가|을|를)$", "", w)
            if w and w not in self.STOPWORDS and not w.isdigit():
                return w
        return ""

    async def _version_page(self, query: str, items: list[dict]) -> dict | None:
        """The current version of what the question asks about, read from an official source.

        The search engines answer these questions with forum threads and release notes (asked for the
        newest Go release, the first five results were zhihu threads), so the number is
        fetched where it is kept instead of hoping for a snippet."""
        name = self._product(query)
        tries = []
        if name:
            tries.append(self.VERSION_SOURCES.get(name) or self.EOL_API.format(name))
        tries += [it.get("url") or "" for it in items if any(m in (it.get("url") or "") for m in self.OFFICIAL)]
        for url in tries[:3]:
            if not url:
                continue
            try:
                page = json.loads(await self.fetch_page(url))
            except Exception:
                continue
            text = (page.get("text") or "")[:self.PAGE_EXTRACT]
            if page.get("error") or not self.VERSION_IN_TEXT.search(text):
                continue
            return {"url": url, "title": page.get("title", ""), "text": text,
                    "note": "공식 배포 정보를 직접 읽은 것입니다. 검색 결과보다 이 번호를 믿고 그대로 쓰세요."}
        return None

    async def web_search(self, query: str) -> str:
        r = await self._client.get(self.cfg.search_url, params={"q": query, "format": "json"})
        r.raise_for_status()
        data = r.json()
        items = []
        for it in (data.get("results") or [])[:RESULTS]:
            snippet = re.sub(r"\s+", " ", it.get("content") or "").strip()[:400]
            date = (it.get("publishedDate") or "")[:10]
            items.append({"title": (it.get("title") or "").strip()[:200], "url": it.get("url"), "snippet": snippet,
                          **({"date": date} if date else {})})
        out = {"query": query, "results": items}
        if self.VERSION_Q.search(query):
            page = await self._version_page(query, items)
            if page is not None:
                out["page"] = page
        why = [f"{e[0]} ({e[1]})" for e in data.get("unresponsive_engines") or () if isinstance(e, list) and len(e) == 2]
        if not items and why:
            # The engines turn a busy client away (after a day of benches: too many requests, CAPTCHA),
            # and with no reason the model answered from memory, an old version as the latest
            log.warning("web search: no results, the search engines did not answer: %s", ", ".join(why))
            out["error"] = ("검색 엔진이 응답하지 않아 결과가 없습니다: " + ", ".join(why)
                            + ". 최신 정보는 확인하지 못했다고 답에 밝히세요.")
        return json.dumps(out, ensure_ascii=False)

    async def fetch_page(self, url: str) -> str:
        for _ in range(4):   # follow redirects by hand, checking each hop
            if not await asyncio.to_thread(allowed_url, url):
                return json.dumps({"url": url, "error": "not allowed: only public http/https pages"})
            async with self._pages.stream("GET", url, follow_redirects=False) as r:
                peer = peer_ip(r)
                if peer and not _global_ip(peer):
                    return json.dumps({"url": url, "error": f"not allowed: {peer} is not a public address"})
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    return json.dumps({"url": url, "error": f"HTTP {r.status_code}"})
                ctype = r.headers.get("content-type", "")
                parts, size = [], 0            # a list, not bytes +=: that copies the page per chunk
                async for chunk in r.aiter_bytes():
                    parts.append(chunk)
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        break
                body = b"".join(parts)
            text = body.decode(r.encoding or "utf-8", "replace")
            title = ""
            if "html" in ctype or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
                text, title = await asyncio.to_thread(read_html, text)
            return json.dumps({"url": url, "title": title[:200], "text": text[:PAGE_CHARS],
                               "truncated": len(text) > PAGE_CHARS}, ensure_ascii=False)
        return json.dumps({"url": url, "error": "too many redirects"})

    async def call(self, name: str, arguments: str | dict) -> str:
        """One tool call -> its JSON result (errors are results too: the model reads them and goes on)."""
        try:
            args = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
            if name == "web_search":
                query = str(args.get("query", ""))[:300]
                return await self._cached(("search", query.strip().lower()), lambda: self.web_search(query))
            if name == "fetch_page":
                url = str(args.get("url", ""))
                return await self._cached(("page", url), lambda: self.fetch_page(url))
            return json.dumps({"error": f"unknown tool {name}"})
        except Exception as exc:
            log.warning("tool %s failed: %s", name, exc)
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"[:300]})

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._pages.aclose()
