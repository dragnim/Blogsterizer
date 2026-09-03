from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.version import __version__


class FetchError(ValueError):
    pass


MAX_REDIRECTS = 5


def _is_public_hostname(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {hostname}.") from exc

    for address in addresses:
        ip_text = address[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FetchError("Enter a complete http:// or https:// URL.")
    if not _is_public_hostname(parsed.hostname):
        raise FetchError("Private, local and reserved network addresses are not allowed.")


def _get_with_checked_redirects(client: httpx.Client, url: str) -> httpx.Response:
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        _validate_public_url(current)
        response = client.get(current, follow_redirects=False)

        if response.status_code not in {301, 302, 303, 307, 308}:
            response.raise_for_status()
            return response

        if redirect_count >= MAX_REDIRECTS:
            raise FetchError(f"Too many redirects (more than {MAX_REDIRECTS}).")

        location = response.headers.get("location")
        if not location:
            response.raise_for_status()
            return response

        current = urljoin(str(response.url), location)

    raise FetchError("Could not follow page redirects.")


def fetch_html(url: str, selector: str | None = None) -> str:
    url = url.strip()
    _validate_public_url(url)

    headers = {"User-Agent": f"The Blogsterizer/{__version__} (+local editorial tool)"}
    try:
        with httpx.Client(timeout=15.0, headers=headers) as client:
            response = _get_with_checked_redirects(client, url)
    except FetchError:
        raise
    except httpx.HTTPError as exc:
        raise FetchError(f"Could not retrieve the page: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower() and not response.text.lstrip().startswith("<"):
        raise FetchError("The URL did not return HTML.")

    return _extract_content(response.text, selector)


def _extract_content(html: str, selector: str | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if selector:
        try:
            selected = soup.select_one(selector)
        except Exception as exc:  # SoupSieve raises selector-specific exceptions.
            raise FetchError(f"Invalid CSS selector: {selector}") from exc
        if selected is None:
            raise FetchError(f"No element matched the selector: {selector}")
        return selected.decode_contents()

    for candidate in (".entry-content", ".post-content", "article", "main", "body"):
        selected = soup.select_one(candidate)
        if selected is not None:
            return selected.decode_contents()
    return html
