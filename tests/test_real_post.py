"""End-to-end test against a complete real post.

`tests/fixtures/hashing-it-out.html` is the exact HTML that was pasted into the
Blogsterizer and then into WordPress, where every code block failed validation.
Handoff 15 and 29: this is the full-document fixture, not a set of fragments.
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.engine import analyse_html, extract_body_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile

FIXTURE = Path(__file__).parent / "fixtures" / "hashing-it-out.html"


def result():
    return analyse_html(FIXTURE.read_text(encoding="utf-8"), load_profile(DEFAULT_PROFILE_ID))


# --------------------------------------------------------------------------
# Document wrapper
# --------------------------------------------------------------------------

def test_full_document_wrapper_is_dropped():
    """An exported page arrives wrapped in <html><head><body>.

    Left in place, the wrapper survived into the output and the whole post
    became a single Custom HTML block.
    """
    cleaned = result().cleaned_html
    for tag in ("<html", "<head", "<body", "<title"):
        assert tag not in cleaned, tag


def test_fragments_without_a_wrapper_are_untouched():
    assert extract_body_html("<p>Hello</p>") == "<p>Hello</p>"


def test_head_content_does_not_leak_into_the_output():
    extracted = extract_body_html(
        "<html><head><title>Page title</title></head><body><p>Body text</p></body></html>"
    )
    assert "Page title" not in extracted
    assert "Body text" in extracted


# --------------------------------------------------------------------------
# The cleaner's core guarantees, on a whole real page
# --------------------------------------------------------------------------

def test_no_legacy_cruft_survives_the_real_post():
    cleaned = result().cleaned_html
    assert "code-line" not in cleaned
    assert 'dir="auto"' not in cleaned
    assert "APLFont" not in cleaned


def test_real_post_has_no_errors_and_preserves_copy():
    outcome = result()
    assert outcome.counts["error"] == 0
    assert outcome.copy_preserved
    assert outcome.export_safe


def test_real_post_copy_is_word_for_word_identical():
    outcome = result()
    source_body = extract_body_html(FIXTURE.read_text(encoding="utf-8"))
    before = BeautifulSoup(source_body, "html.parser").get_text(" ", strip=True).split()
    after = BeautifulSoup(outcome.cleaned_html, "html.parser").get_text(" ", strip=True).split()
    assert before == after


def test_real_post_is_idempotent():
    once = result().cleaned_html
    twice = analyse_html(once, load_profile(DEFAULT_PROFILE_ID)).cleaned_html
    assert once == twice


def test_every_code_block_is_classified_and_inline_code_is_apl():
    soup = BeautifulSoup(result().cleaned_html, "html.parser")
    blocks = [c for c in soup.find_all("code") if c.parent and c.parent.name == "pre"]
    assert blocks
    for block in blocks:
        assert "language-apl" in block.get("class", []), str(block)[:120]
    inline = [c for c in soup.find_all("code") if not (c.parent and c.parent.name == "pre")]
    assert inline
    for code in inline:
        assert "language-apl" in code.get("class", []), str(code)[:120]


def test_external_links_get_the_full_policy():
    soup = BeautifulSoup(result().cleaned_html, "html.parser")
    github = soup.find("a", href=re.compile(r"github\.com/IlyaSemenov"))
    assert github is not None
    assert "ex-link" in github.get("class", [])
    assert github.get("target") == "_blank"
    assert "noopener" in github.get("rel", [])


def test_dyalog_domain_links_are_internal_and_docs_links_are_external():
    """Handoff 5.3/6.1: only the presentations path is migrated.

    This post's competition PDF is under /uploads/files/student_competition/,
    which no configured migration covers, so the URL is left exactly as written.
    www.dyalog.com is configured as internal, so it gets no ex-link; the
    docs.dyalog.com subdomain is not, so those links get the external policy.
    """
    soup = BeautifulSoup(result().cleaned_html, "html.parser")

    competition = soup.find("a", href=re.compile(r"student_competition"))
    assert competition is not None
    # Not invented, not guessed, not migrated (handoff 6.3).
    assert competition["href"] == (
        "https://www.dyalog.com/uploads/files/student_competition/2015_problems_phase2.pdf"
    )
    assert "ex-link" not in competition.get("class", [])
    # It opens in a new window, so it still needs noopener.
    assert "noopener" in competition.get("rel", [])

    docs = soup.find("a", href=re.compile(r"docs\.dyalog\.com"))
    assert docs is not None
    assert "ex-link" in docs.get("class", [])


# --------------------------------------------------------------------------
# Block markup for the whole post
# --------------------------------------------------------------------------

def test_whole_post_becomes_real_blocks_with_no_custom_html_fallback():
    markup = result().block_markup
    assert "<!-- wp:html" not in markup
    kinds = set(re.findall(r"<!-- wp:([a-z]+)", markup))
    assert {"paragraph", "heading", "code", "list"} <= kinds


def test_every_code_block_carries_its_language_on_the_pre():
    """The failure seen in WordPress: class on <code> is dropped on validation."""
    markup = result().block_markup
    opens = re.findall(r"<!-- wp:code( [^>]*)? -->", markup)
    assert opens
    for attributes in opens:
        assert '"className":"language-apl"' in (attributes or ""), attributes
    assert '<code class="language-apl">' not in markup.split("<!-- wp:paragraph")[0]


def test_block_markup_delimiters_are_balanced():
    markup = result().block_markup
    assert_delimiters_balance(markup)


def test_block_markup_keeps_every_word():
    outcome = result()
    cleaned = BeautifulSoup(outcome.cleaned_html, "html.parser").get_text(" ", strip=True).split()
    blocks = BeautifulSoup(outcome.block_markup, "html.parser").get_text(" ", strip=True).split()
    assert cleaned == blocks


# --------------------------------------------------------------------------
# SEO findings actually present in this post
# --------------------------------------------------------------------------

def test_real_post_seo_findings():
    findings = result().findings
    by_rule = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)

    # The <h1>Addendum</h1> near the end of the post.
    assert len(by_rule.get("SEO-H1-001", [])) == 1
    assert "Addendum" in by_rule["SEO-H1-001"][0].message

    # id="distraction-1" appears on both a heading and a paragraph, and either
    # can be renamed, so there is a finding for each.
    assert len(by_rule.get("SEO-DUPLICATE-ID-001", [])) == 2

    # Distraction #1, Why Hash?, TANSTAAFL, The Speed/Space Tradeoff.
    assert len(by_rule.get("SEO-FAKE-HEADING-001", [])) == 4

    # All advisory: nothing was altered.
    for rule_id, group in by_rule.items():
        if rule_id.startswith("SEO-"):
            assert all(not f.applied for f in group)

def assert_delimiters_balance(markup: str) -> None:
    """Blocks nest — a quote holds paragraph blocks — so compare with a stack."""
    stack: list[str] = []
    for closing, name in re.findall(r"<!-- (/?)wp:([a-z-]+)", markup):
        if closing:
            assert stack, f"closed {name} with nothing open"
            opened = stack.pop()
            assert opened == name, f"closed {name} but {opened} was open"
        else:
            stack.append(name)
    assert not stack, f"never closed: {stack}"
