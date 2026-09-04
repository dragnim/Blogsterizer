"""Every post in tests/fixtures, end to end.

Handoff 28 and 29: the authority is real content, not a checklist. This asserts
the invariants that must hold for any post rather than post-specific detail, so
dropping a file into tests/fixtures extends the coverage without editing a test.

**The folder is deliberately almost empty.** Dyalog's blog HTML is not part of
the app and is not committed. To check a change against real content, copy some
posts into tests/fixtures and run this file; the tests skip whatever is not
there. `.gitignore` keeps anything you add out of the repository.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.engine import (
    analyse_html,
    extract_body_html,
    strip_caption_shortcodes,
    strip_embed_shortcodes,
)
from app.profiles import DEFAULT_PROFILE_ID, load_profile

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.txt"))
FIXTURES += sorted((Path(__file__).parent / "fixtures").glob("*.html"))
IDS = [path.stem for path in FIXTURES]

# Nothing to run against is not a failure: the corpus is supplied locally.
pytestmark = pytest.mark.skipif(not FIXTURES, reason="no posts in tests/fixtures")


def prepared(source: str) -> str:
    """The source as the copy guard sees it, after markup-only stripping."""
    html = extract_body_html(source)
    html, _ = strip_caption_shortcodes(html)
    html, _ = strip_embed_shortcodes(html)
    return html


@pytest.fixture(scope="module")
def profile():
    return load_profile(DEFAULT_PROFILE_ID)


def test_the_fixture_folder_is_readable():
    """Not an assertion about how many posts are there: usually there is one."""
    assert (Path(__file__).parent / "fixtures").is_dir()


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_post_produces_an_error(path, profile):
    result = analyse_html(path.read_text(encoding="utf-8"), profile)
    errors = [f for f in result.findings if f.severity.value == "error"]
    assert not errors, [f"{f.rule_id}: {f.message[:80]}" for f in errors]
    assert result.export_safe


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_post_loses_a_word(path, profile):
    source = path.read_text(encoding="utf-8")
    result = analyse_html(source, profile)
    before = BeautifulSoup(prepared(source), "html.parser").get_text(" ", strip=True).split()
    after = BeautifulSoup(result.cleaned_html, "html.parser").get_text(" ", strip=True).split()

    # Placeholders add words; nothing may be removed. Every original word must
    # still appear, in order.
    iterator = iter(after)
    missing = [word for word in before if not any(word == candidate for candidate in iterator)]
    assert not missing, f"lost: {missing[:6]}"
    assert result.copy_preserved


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_every_post_is_idempotent(path, profile):
    once = analyse_html(path.read_text(encoding="utf-8"), profile).cleaned_html
    twice = analyse_html(once, profile).cleaned_html
    assert once == twice


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_legacy_cruft_survives_any_post(path, profile):
    cleaned = analyse_html(path.read_text(encoding="utf-8"), profile).cleaned_html
    for junk in ("code-line", 'dir="auto"', "APLFont", "[caption", "[/caption]", "[embedyt]"):
        assert junk not in cleaned, junk


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_post_carries_an_image_into_the_markup(path, profile):
    """The old src points at the site being migrated away from."""
    cleaned = analyse_html(path.read_text(encoding="utf-8"), profile).cleaned_html
    assert "<img" not in cleaned


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_every_external_link_gets_the_policy(path, profile):
    cleaned = analyse_html(path.read_text(encoding="utf-8"), profile).cleaned_html
    for anchor in BeautifulSoup(cleaned, "html.parser").find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith(("http://", "https://")):
            continue
        if "ex-link" not in anchor.get("class", []):
            continue
        assert "noopener" in anchor.get("rel", []), href


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_block_markup_delimiters_balance_for_every_post(path, profile):
    markup = analyse_html(path.read_text(encoding="utf-8"), profile).block_markup
    assert re.findall(r"<!-- wp:([a-z-]+)", markup) == re.findall(r"<!-- /wp:([a-z-]+)", markup)


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_block_markup_keeps_every_word_of_the_cleaned_html(path, profile):
    result = analyse_html(path.read_text(encoding="utf-8"), profile)
    cleaned = BeautifulSoup(result.cleaned_html, "html.parser").get_text(" ", strip=True).split()
    blocks = BeautifulSoup(result.block_markup, "html.parser").get_text(" ", strip=True).split()
    assert cleaned == blocks


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_stale_dyalog_tv_url_survives(path, profile):
    cleaned = analyse_html(path.read_text(encoding="utf-8"), profile).cleaned_html
    assert "dyalog.tv" not in cleaned
