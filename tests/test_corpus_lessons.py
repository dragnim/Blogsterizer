"""Things learned from running 22 real posts through the app.

Each test carries a shape actually found in the corpus, with a note on how many
posts had it. Frequency mattered: a pattern in one post is a curiosity, one in
seventeen is a rule.
"""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.actions import ActionError, apply_action
from app.engine import analyse_html, strip_embed_shortcodes
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


def rule(result, rule_id: str):
    return [f for f in result.findings if f.rule_id == rule_id]


# --------------------------------------------------------------------------
# class=" language-apl" with a leading space — 6 of 22 posts, 180 occurrences.
# --------------------------------------------------------------------------

def test_an_untidy_language_class_is_reported_not_silently_normalised():
    """One post had 58 such elements and produced almost no findings."""
    result = clean('<p><code class=" language-apl">\u2395io\u21900</code></p>')
    assert 'class="language-apl"' in result.cleaned_html
    assert 'class=" language-apl"' not in result.cleaned_html
    finding = rule(result, "APL-CLASS-WHITESPACE-001")
    assert len(finding) == 1
    assert finding[0].metadata["count"] == 1


def test_a_tidy_class_raises_nothing():
    result = clean('<p><code class="language-apl">\u2395io</code></p>')
    assert rule(result, "APL-CLASS-WHITESPACE-001") == []


# --------------------------------------------------------------------------
# [embedyt] video shortcode — 1 of 22 posts.
# --------------------------------------------------------------------------

def test_an_embedyt_shortcode_becomes_a_real_link():
    result = clean(
        "<p>look at:</p>[embedyt] https://www.youtube.com/watch?v=yfGsSLEifAs[/embedyt]"
    )
    assert "[embedyt]" not in result.cleaned_html
    anchor = BeautifulSoup(result.cleaned_html, "html.parser").find(
        "a", href="https://www.youtube.com/watch?v=yfGsSLEifAs"
    )
    assert anchor is not None
    # It is an external link, so the link policy applies to it.
    assert "ex-link" in anchor.get("class", [])
    assert anchor.get("target") == "_blank"
    assert any(f.rule_id == "EMBED-SHORTCODE-001" for f in result.findings)


def test_stripping_embeds_is_a_no_op_without_them():
    html = "<p>Ordinary text.</p>"
    assert strip_embed_shortcodes(html) == (html, 0)


# --------------------------------------------------------------------------
# Empty paragraphs from the classic editor — 1 of 22 posts.
# --------------------------------------------------------------------------

def test_a_paragraph_containing_only_nbsp_is_removed():
    result = clean("<p>Real text.</p>\n<p>&nbsp;</p>\n<p>More text.</p>")
    assert result.cleaned_html.count("<p") == 2
    assert any(f.rule_id == "EMPTY-PARAGRAPH-001" for f in result.findings)
    assert result.copy_preserved


def test_a_paragraph_holding_only_an_image_is_not_removed():
    """It has no text, but it is not empty."""
    result = clean('<p><img src="shot.png"></p>')
    assert "Image here: shot.png" in result.cleaned_html
    assert not [f for f in result.findings if f.rule_id == "EMPTY-PARAGRAPH-001"]


# --------------------------------------------------------------------------
# Legacy table attributes — 3 of 22 posts have tables.
# --------------------------------------------------------------------------

def test_width_on_a_table_cell_is_removed():
    result = clean('<table><tbody><tr><td width="200px">boolean</td></tr></tbody></table>')
    assert "width=" not in result.cleaned_html
    assert "boolean" in result.cleaned_html
    assert any(f.rule_id == "TABLE-ATTR-001" for f in result.findings)


def test_a_table_still_becomes_a_table_block():
    result = clean("<table><tbody><tr><td>a</td></tr></tbody></table>")
    assert "<!-- wp:table -->" in result.block_markup
    assert 'class="wp-block-table"' in result.block_markup


# --------------------------------------------------------------------------
# Indented div used as a pull-quote — 2 of 22 posts, and the only two things
# in the whole corpus landing in a Custom HTML block.
# --------------------------------------------------------------------------

def test_an_indented_div_is_suggested_as_a_blockquote():
    result = clean(
        '<div style="margin: 15px 50px 15px 50px;">If it walks like a duck.</div>'
    )
    finding = rule(result, "INDENTED-DIV-001")
    assert len(finding) == 1
    assert finding[0].action == "convert_to_blockquote"
    assert not finding[0].applied
    # Untouched until asked.
    assert "<div" in result.cleaned_html


def test_converting_it_removes_the_custom_html_block():
    html = '<div style="margin: 15px 50px;">If it walks like a duck.</div>'
    before = clean(html)
    assert "wp:html" in before.block_markup

    updated, message = apply_action(before.cleaned_html, "convert_to_blockquote", {"index": 0})
    after = clean(updated)
    assert "wp:html" not in after.block_markup
    assert "wp:quote" in after.block_markup
    assert "blockquote" in message


def test_converting_changes_no_copy():
    html = '<div style="margin: 15px 50px;">If it walks like a duck.</div>'
    updated, _ = apply_action(html, "convert_to_blockquote", {"index": 0})
    assert BeautifulSoup(updated, "html.parser").get_text(" ", strip=True) == (
        "If it walks like a duck."
    )


def test_an_ordinary_div_is_not_suggested():
    result = clean('<div class="wrapper"><p>Text.</p></div>')
    assert rule(result, "INDENTED-DIV-001") == []


# --------------------------------------------------------------------------
# A malformed video id — 1 of 22 posts, and it produced a dead link.
# --------------------------------------------------------------------------

def test_a_malformed_video_id_is_a_warning():
    """The source had ?v=https:aIqDxwlcoVU, which migrated into a dead URL."""
    result = clean('<p><a href="https://dyalog.tv/Dyalog24/?v=https:aIqDxwlcoVU">D06</a></p>')
    finding = rule(result, "VIDEO-ID-001")
    assert len(finding) == 1
    assert finding[0].severity.value == "warning"
    # Handoff 6.3: the id is not repaired, only reported.
    assert "https:aIqDxwlcoVU" in result.cleaned_html
    assert not finding[0].applied


def test_a_valid_video_id_raises_nothing():
    result = clean('<p><a href="https://dyalog.tv/Dyalog24/?v=cbkQSmjKZ8o">D06</a></p>')
    assert rule(result, "VIDEO-ID-001") == []
    assert "youtube.com/watch?v=cbkQSmjKZ8o" in result.cleaned_html


# --------------------------------------------------------------------------
# Nested <code> from malformed source — 1 of 22 posts.
# --------------------------------------------------------------------------

def test_nested_code_elements_are_a_warning():
    result = clean("<pre><code>outer<code>inner</code></code></pre>")
    finding = rule(result, "NESTED-CODE-001")
    assert finding
    assert finding[0].severity.value == "warning"


def test_ordinary_code_raises_nothing():
    result = clean("<pre><code>A\u21901 2 3</code></pre>")
    assert rule(result, "NESTED-CODE-001") == []
