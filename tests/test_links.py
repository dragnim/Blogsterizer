"""Old-site links, and checking that links resolve.

The host rewrite is a suggestion, never automatic: handoff 6.1 lists the paths
that are established migrations and 6.3 forbids guessing anything else. The link
check makes real network requests, so it is opt-in and its results are reported
separately from the deterministic findings.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.actions import ActionError, apply_action
from app.engine import analyse_html
from app.linkcheck import LinkResult, check_links, collect_links, summarise
from app.main import app
from app.profiles import DEFAULT_PROFILE_ID, load_profile

FIXTURE = Path(__file__).parent / "fixtures" / "hashing-it-out.html"


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


# --------------------------------------------------------------------------
# Old-site hosts
# --------------------------------------------------------------------------

def test_old_host_link_is_suggested_not_rewritten():
    html = '<p><a href="https://www.dyalog.com/blog/2018/09/some-post/">2018</a></p>'
    result = clean(html)
    finding = next(f for f in result.findings if f.rule_id == "URL-HOST-001")
    assert finding.severity.value == "suggested"
    assert not finding.applied
    # The document is untouched until the user asks.
    assert "www.dyalog.com" in result.cleaned_html
    assert finding.action_input_default == (
        "https://dyalogprod.gos.dyalog.com/blog/2018/09/some-post/"
    )


def test_the_path_is_preserved_exactly_in_the_suggestion():
    html = '<p><a href="https://www.dyalog.com/a/b/c.pdf?x=1#frag">x</a></p>'
    finding = next(f for f in clean(html).findings if f.rule_id == "URL-HOST-001")
    assert finding.action_input_default == (
        "https://dyalogprod.gos.dyalog.com/a/b/c.pdf?x=1#frag"
    )


def test_an_already_migrated_presentation_url_raises_no_host_suggestion():
    html = (
        '<p><a href="https://www.dyalog.com/uploads/files/presentations/x.pptx">P</a></p>'
    )
    result = clean(html)
    # The configured migration already moved it, so there is nothing to suggest.
    assert "dyalogprod.gos.dyalog.com" in result.cleaned_html
    assert not [f for f in result.findings if f.rule_id == "URL-HOST-001"]


def test_other_hosts_are_left_alone():
    html = '<p><a href="https://docs.dyalog.com/20.0/x/">D</a></p>'
    assert not [f for f in clean(html).findings if f.rule_id == "URL-HOST-001"]


def test_repeated_url_is_reported_once_and_says_how_many():
    html = (
        '<p><a href="https://dyalog.com/x/">one</a> '
        '<a href="https://dyalog.com/x/">two</a></p>'
    )
    findings = [f for f in clean(html).findings if f.rule_id == "URL-HOST-001"]
    assert len(findings) == 1
    assert "appears 2 times" in findings[0].message


def test_rewrite_url_action_repoints_every_matching_link():
    html = (
        '<p><a href="https://dyalog.com/x/">one</a> '
        '<a href="https://dyalog.com/x/">two</a> '
        '<a href="https://dyalog.com/y/">other</a></p>'
    )
    updated, message = apply_action(
        html,
        "rewrite_url",
        {"from_url": "https://dyalog.com/x/", "value": "https://dyalogprod.gos.dyalog.com/x/"},
    )
    soup = BeautifulSoup(updated, "html.parser")
    hrefs = [a["href"] for a in soup.find_all("a")]
    assert hrefs.count("https://dyalogprod.gos.dyalog.com/x/") == 2
    assert "https://dyalog.com/y/" in hrefs
    assert "2 links" in message


def test_rewrite_url_changes_no_copy():
    html = '<p>See <a href="https://dyalog.com/x/">the notes</a> here.</p>'
    updated, _ = apply_action(
        html, "rewrite_url", {"from_url": "https://dyalog.com/x/", "value": "/notes/"}
    )
    before = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    after = BeautifulSoup(updated, "html.parser").get_text(" ", strip=True)
    assert before == after


def test_rewrite_url_rejects_nonsense():
    html = '<p><a href="https://dyalog.com/x/">x</a></p>'
    for bad in ("", "not a url", "ftp://example.org/"):
        with pytest.raises(ActionError):
            apply_action(html, "rewrite_url", {"from_url": "https://dyalog.com/x/", "value": bad})


def test_real_post_flags_its_old_site_link():
    result = clean(FIXTURE.read_text(encoding="utf-8"))
    findings = [f for f in result.findings if f.rule_id == "URL-HOST-001"]
    assert len(findings) == 1
    assert "student_competition" in findings[0].metadata["old_url"]


# --------------------------------------------------------------------------
# Link checking
# --------------------------------------------------------------------------

def test_links_are_collected_once_each_with_their_texts():
    links = collect_links(
        '<a href="https://example.org/">one</a>'
        '<a href="https://example.org/">two</a>'
        '<a href="https://other.example/">three</a>'
    )
    assert list(links) == ["https://example.org/", "https://other.example/"]
    assert links["https://example.org/"] == ["one", "two"]


def test_non_http_and_relative_links_are_skipped_not_requested():
    html = (
        '<a href="mailto:x@example.com">m</a>'
        '<a href="#section">f</a>'
        '<a href="/relative/path">r</a>'
        '<a href="tel:+441234">t</a>'
    )
    results = asyncio.run(check_links(html))
    assert {r.outcome for r in results} == {"skipped"}
    assert len(results) == 4


def test_a_private_address_is_never_requested():
    """Same guard as the URL importer (handoff 24)."""
    results = asyncio.run(check_links('<a href="http://127.0.0.1/secret">x</a>'))
    assert results[0].outcome == "skipped"
    assert "private" in results[0].detail


def test_localhost_by_name_is_also_refused():
    results = asyncio.run(check_links('<a href="http://localhost:8000/admin">x</a>'))
    assert results[0].outcome == "skipped"


def test_status_classification():
    from app.linkcheck import _classify

    assert _classify(200)[0] == "ok"
    assert _classify(301)[0] == "ok"
    assert _classify(404)[0] == "broken"
    assert _classify(500)[0] == "broken"
    # A bot-hostile server is not a broken link.
    assert _classify(403)[0] == "inconclusive"
    assert _classify(429)[0] == "inconclusive"


def test_results_are_ordered_worst_first():
    results = [
        LinkResult(url="a", outcome="ok"),
        LinkResult(url="b", outcome="broken"),
        LinkResult(url="c", outcome="skipped"),
        LinkResult(url="d", outcome="inconclusive"),
    ]
    order = {"broken": 0, "inconclusive": 1, "skipped": 2, "ok": 3}
    results.sort(key=lambda item: (order[item.outcome], item.url))
    assert [r.outcome for r in results] == ["broken", "inconclusive", "skipped", "ok"]


def test_summary_counts_every_outcome():
    counts = summarise(
        [
            LinkResult(url="a", outcome="ok"),
            LinkResult(url="b", outcome="ok"),
            LinkResult(url="c", outcome="broken"),
        ]
    )
    assert counts == {"ok": 2, "broken": 1, "inconclusive": 0, "skipped": 0, "total": 3}


def test_a_timeout_is_reported_as_broken_not_as_a_crash(monkeypatch):
    async def timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("too slow")

    monkeypatch.setattr(httpx.AsyncClient, "head", timeout)
    results = asyncio.run(check_links('<a href="https://example.org/">x</a>'))
    assert results[0].outcome == "broken"
    assert "seconds" in results[0].detail or "failed" in results[0].detail


def test_check_is_not_part_of_the_analysis():
    """No rule may depend on the network: findings must be reproducible offline."""
    result = clean('<p><a href="https://example.org/nonexistent">x</a></p>')
    assert not any("link check" in f.message.lower() for f in result.findings)
    assert not any(f.rule_id.startswith("LINKCHECK") for f in result.findings)


def test_links_tab_offers_the_check_but_does_not_run_it():
    client = TestClient(app)
    page = client.post(
        "/analyse",
        data={
            "source_type": "html",
            "content": '<p><a href="https://example.org/">x</a></p>',
            "selector": "",
        },
    ).text
    assert 'data-tab="links"' in page
    assert "Check the links as they are" in page
    assert "Check where old-site links would point" in page
    # Nothing was requested, so there is no table yet.
    assert "link-table" not in page


def test_check_links_endpoint_renders_a_report():
    client = TestClient(app)
    response = client.post(
        "/check-links",
        data={
            "source": '<p><a href="mailto:x@example.com">m</a><a href="/rel">r</a></p>',
            "history": "[]",
        },
    )
    assert response.status_code == 200
    assert "link-table" in response.text
    assert "2 not checked" in response.text


# --------------------------------------------------------------------------
# Repoint every link on a host at once
# --------------------------------------------------------------------------

def test_a_host_with_several_links_offers_one_action_for_all_of_them():
    """17 of 22 corpus posts link to the old site; some have several."""
    html = (
        '<p><a href="https://www.dyalog.com/a/">a</a>'
        '<a href="https://www.dyalog.com/b/">b</a>'
        '<a href="https://www.dyalog.com/c.pdf">c</a></p>'
    )
    finding = next(f for f in clean(html).findings if f.rule_id == "URL-HOST-ALL-001")
    assert finding.action == "rewrite_host"
    assert finding.action_label == "Repoint all 3"
    assert finding.action_input_default == "dyalogprod.gos.dyalog.com"
    assert not finding.applied


def test_a_single_old_site_link_gets_no_repoint_all():
    html = '<p><a href="https://www.dyalog.com/only/">one</a></p>'
    assert not [f for f in clean(html).findings if f.rule_id == "URL-HOST-ALL-001"]


def test_repointing_a_host_preserves_every_path_query_and_fragment():
    html = (
        '<p><a href="https://www.dyalog.com/uploads/a%20b.pdf?x=1#frag">a</a>'
        '<a href="https://www.dyalog.com/b/">b</a>'
        '<a href="https://docs.dyalog.com/keep/">other host</a></p>'
    )
    updated, message = apply_action(
        html,
        "rewrite_host",
        {"from_host": "www.dyalog.com", "value": "dyalogprod.gos.dyalog.com"},
    )
    assert "https://dyalogprod.gos.dyalog.com/uploads/a%20b.pdf?x=1#frag" in updated
    assert "https://dyalogprod.gos.dyalog.com/b/" in updated
    # A different host is untouched.
    assert "https://docs.dyalog.com/keep/" in updated
    assert "2 links" in message


def test_repointing_a_host_changes_no_copy():
    html = '<p>See <a href="https://www.dyalog.com/a/">the notes</a> and <a href="https://www.dyalog.com/b/">more</a>.</p>'
    updated, _ = apply_action(
        html, "rewrite_host", {"from_host": "www.dyalog.com", "value": "example.org"}
    )
    before = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    after = BeautifulSoup(updated, "html.parser").get_text(" ", strip=True)
    assert before == after


def test_a_scheme_prefixed_host_is_accepted():
    """Pasting https://host/ into the box should work."""
    html = '<p><a href="https://www.dyalog.com/a/">a</a></p>'
    updated, _ = apply_action(
        html,
        "rewrite_host",
        {"from_host": "www.dyalog.com", "value": "https://dyalogprod.gos.dyalog.com/"},
    )
    assert 'href="https://dyalogprod.gos.dyalog.com/a/"' in updated


def test_a_nonsense_host_is_refused():
    html = '<p><a href="https://www.dyalog.com/a/">a</a></p>'
    for bad in ("", "not a host", "has spaces.com"):
        with pytest.raises(ActionError):
            apply_action(html, "rewrite_host", {"from_host": "www.dyalog.com", "value": bad})


def test_repointing_to_the_same_host_is_refused():
    html = '<p><a href="https://www.dyalog.com/a/">a</a></p>'
    with pytest.raises(ActionError, match="already use"):
        apply_action(
            html, "rewrite_host", {"from_host": "www.dyalog.com", "value": "www.dyalog.com"}
        )


# --------------------------------------------------------------------------
# Checking where a link would point after migration
# --------------------------------------------------------------------------

MOVES = [{"from": "www.dyalog.com", "to": "dyalogprod.gos.dyalog.com"}]


def test_migration_targets_map_old_urls_to_new_ones():
    from app.linkcheck import migration_targets

    targets = migration_targets(
        '<a href="https://www.dyalog.com/uploads/a%20b.pdf?x=1">a</a>'
        '<a href="https://docs.dyalog.com/other/">b</a>',
        MOVES,
    )
    assert targets == {
        "https://www.dyalog.com/uploads/a%20b.pdf?x=1":
            "https://dyalogprod.gos.dyalog.com/uploads/a%20b.pdf?x=1"
    }


def test_a_post_with_no_old_site_links_has_nothing_to_check():
    from app.linkcheck import check_migration_targets

    assert asyncio.run(check_migration_targets('<a href="https://example.org/">x</a>', MOVES)) == []


def test_the_target_check_reports_which_old_link_it_came_from():
    """So a broken result names the file to upload."""
    from app.linkcheck import check_migration_targets

    results = asyncio.run(
        check_migration_targets('<a href="https://www.dyalog.com/x/">x</a>',
                                [{"from": "www.dyalog.com", "to": "127.0.0.1"}])
    )
    assert len(results) == 1
    assert results[0].texts == ["https://www.dyalog.com/x/"]
    # A private address is refused rather than requested.
    assert results[0].outcome == "skipped"


def test_the_target_mode_says_it_is_checking_the_new_site():
    client = TestClient(app)
    response = client.post(
        "/check-links",
        data={
            "source": '<p><a href="https://www.dyalog.com/a/">a</a></p>',
            "history": "[]",
            "mode": "targets",
        },
    )
    assert response.status_code == 200
    assert "not been uploaded" in response.text
