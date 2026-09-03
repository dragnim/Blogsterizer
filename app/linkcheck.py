"""Check whether the links in a document actually resolve.

This is deliberately **not** part of the analysis. Every other rule is
deterministic and offline: the same input always gives the same findings. A link
check depends on the network, on the far site's mood, and on whether it likes
being probed by a script, so it runs only when the user asks and its results are
reported separately from the rule findings.

What it does not do: follow a redirect to a private address, check the same URL
twice, hammer a host with parallel requests, or treat its own result as
authoritative. A 403 from a bot-hostile server does not mean a broken link, and
the report says so.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.fetcher import FetchError, _is_public_hostname
from app.version import __version__


TIMEOUT = 10.0
MAX_CONCURRENCY = 4
MAX_LINKS = 200

# Sites that refuse automated requests answer with these rather than a 404. They
# say nothing about whether the link works in a browser.
INCONCLUSIVE_STATUSES = {401, 403, 405, 429, 999}


@dataclass
class LinkResult:
    url: str
    status: int | None = None
    outcome: str = "unknown"  # ok | broken | inconclusive | skipped
    detail: str = ""
    final_url: str | None = None
    occurrences: int = 1
    texts: list[str] = field(default_factory=list)

    @property
    def redirected(self) -> bool:
        return bool(self.final_url and self.final_url != self.url)


def collect_links(html: str) -> dict[str, list[str]]:
    """Unique hrefs mapped to the link texts that use them."""
    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, list[str]] = {}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href:
            continue
        links.setdefault(href, []).append(anchor.get_text(" ", strip=True)[:80])
    return links


def _classify(status: int) -> tuple[str, str]:
    if status < 400:
        return "ok", f"Responded {status}."
    if status in INCONCLUSIVE_STATUSES:
        return (
            "inconclusive",
            f"Responded {status}. Many sites answer this way to automated "
            "requests; check it in a browser before treating it as broken.",
        )
    if status == 404:
        return "broken", "Responded 404 Not Found."
    return "broken", f"Responded {status}."


async def _check_one(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> LinkResult:
    result = LinkResult(url=url)
    parsed = urlparse(url)

    if parsed.scheme in {"mailto", "tel", "javascript"}:
        result.outcome = "skipped"
        result.detail = f"Not an HTTP link ({parsed.scheme}:)."
        return result
    if not parsed.scheme and (url.startswith("#") or url.startswith("/")):
        result.outcome = "skipped"
        result.detail = (
            "Relative or in-page link. It cannot be checked without knowing the "
            "page it will live on."
        )
        return result
    if parsed.scheme not in {"http", "https"}:
        result.outcome = "skipped"
        result.detail = "Only http and https links can be checked."
        return result
    # Same guard the URL importer uses (handoff 24): never probe a private or
    # reserved address, and never resolve a name that maps to one.
    try:
        public = bool(parsed.hostname) and _is_public_hostname(parsed.hostname)
    except FetchError:
        result.outcome = "broken"
        result.detail = "Host could not be resolved."
        return result
    if not public:
        result.outcome = "skipped"
        result.detail = "Points at a private or reserved address, so it was not requested."
        return result

    async with semaphore:
        try:
            # HEAD first: cheaper for the far end. Plenty of servers do not
            # implement it, so fall back to a GET when the answer looks like that.
            response = await client.head(url)
            if response.status_code in {405, 501} or response.status_code >= 400:
                response = await client.get(url)
        except httpx.TimeoutException:
            result.outcome = "broken"
            result.detail = f"No response within {TIMEOUT:.0f} seconds."
            return result
        except httpx.HTTPError as exc:
            result.outcome = "broken"
            result.detail = f"Request failed: {type(exc).__name__}."
            return result

    result.status = response.status_code
    result.final_url = str(response.url)
    result.outcome, result.detail = _classify(response.status_code)

    if result.redirected:
        final_host = urlparse(result.final_url).hostname
        try:
            if not final_host or not _is_public_hostname(final_host):
                result.outcome = "skipped"
                result.detail = "Redirected to a private or reserved address."
        except FetchError:
            pass
    return result


async def check_links(html: str) -> list[LinkResult]:
    """Check every distinct link in the document. Never raises."""
    links = collect_links(html)
    urls = list(links)[:MAX_LINKS]

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    headers = {"User-Agent": f"The Blogsterizer/{__version__} (+link check)"}

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:
        results = await asyncio.gather(
            *(_check_one(client, url, semaphore) for url in urls),
            return_exceptions=False,
        )

    for result in results:
        result.occurrences = len(links[result.url])
        result.texts = links[result.url]

    order = {"broken": 0, "inconclusive": 1, "skipped": 2, "ok": 3}
    results.sort(key=lambda item: (order.get(item.outcome, 9), item.url))
    return list(results)


def summarise(results: list[LinkResult]) -> dict[str, int]:
    counts = {"ok": 0, "broken": 0, "inconclusive": 0, "skipped": 0}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    counts["total"] = len(results)
    return counts
