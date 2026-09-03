import httpx
import pytest

from app import fetcher
from app.fetcher import FetchError, fetch_html


def test_fetcher_rejects_localhost():
    try:
        fetch_html("http://127.0.0.1/private")
    except FetchError as exc:
        assert "Private" in str(exc)
    else:
        raise AssertionError("Localhost URL should have been rejected")


def test_redirect_destination_is_validated_before_following(monkeypatch):
    checked: list[str] = []

    def fake_validate(url: str) -> None:
        checked.append(url)
        if "127.0.0.1" in url:
            raise FetchError("Private, local and reserved network addresses are not allowed.")

    monkeypatch.setattr(fetcher, "_validate_public_url", fake_validate)

    class FakeClient:
        def __init__(self):
            self.calls: list[str] = []

        def get(self, url: str, follow_redirects: bool = False):
            self.calls.append(url)
            request = httpx.Request("GET", url)
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
                request=request,
            )

    client = FakeClient()
    with pytest.raises(FetchError, match="Private"):
        fetcher._get_with_checked_redirects(client, "https://example.com/start")

    # The private redirect is checked, but it is never fetched.
    assert checked == ["https://example.com/start", "http://127.0.0.1/private"]
    assert client.calls == ["https://example.com/start"]


def test_auto_extraction_prefers_entry_content_over_whole_article():
    html = '<article><h1>Title</h1><div class="entry-content"><p>Body only</p></div></article>'
    extracted = fetcher._extract_content(html)
    assert extracted == '<p>Body only</p>'


def test_explicit_selector_overrides_auto_extraction():
    html = '<main><div class="entry-content"><p>Default</p></div><div id="wanted"><p>Wanted</p></div></main>'
    extracted = fetcher._extract_content(html, '#wanted')
    assert extracted == '<p>Wanted</p>'
