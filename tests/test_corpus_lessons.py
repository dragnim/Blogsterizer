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


# --------------------------------------------------------------------------
# Heading levels — 2 of 22 posts skipped h2 to h4, and one had four <h4>s in
# a row, so fixing one at a time would have left the outline worse.
# --------------------------------------------------------------------------

def test_a_skipped_heading_offers_to_promote_the_whole_run():
    result = clean(
        "<h2>The First Commits</h2>"
        "<h4>Setting up Poetry</h4><p>a</p>"
        "<h4>Auto-Formatting</h4><p>b</p>"
        "<h4>Fixing Imports</h4>"
    )
    finding = rule(result, "SEO-HEADING-ORDER-001")
    assert len(finding) == 1
    assert finding[0].action == "promote_heading_run"
    assert finding[0].action_label == "Promote all 3 to <h3>"
    assert finding[0].metadata["run"] == 3
    # It may have been a styling choice, so it is offered, not applied.
    assert not finding[0].applied
    assert "<h4>" in result.cleaned_html


def test_promoting_a_run_stops_at_the_next_section():
    updated, message = apply_action(
        "<h2>One</h2><h4>a</h4><h4>b</h4><h2>Two</h2><h4>c</h4>",
        "promote_heading_run",
        {"index": 1},
    )
    soup = BeautifulSoup(updated, "html.parser")
    levels = [(h.name, h.get_text()) for h in soup.find_all(["h2", "h3", "h4"])]
    assert levels == [
        ("h2", "One"), ("h3", "a"), ("h3", "b"), ("h2", "Two"), ("h4", "c"),
    ]
    assert "3 headings" not in message  # only two were in this run


def test_promoting_a_run_changes_no_copy():
    html = "<h2>One</h2><h4>Setting up Poetry</h4><h4>Auto-Formatting</h4>"
    updated, _ = apply_action(html, "promote_heading_run", {"index": 1})
    assert BeautifulSoup(updated, "html.parser").get_text(" ", strip=True) == (
        BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    )


def test_a_lone_skipped_heading_says_so():
    result = clean("<h2>One</h2><h4>Only one</h4>")
    finding = rule(result, "SEO-HEADING-ORDER-001")[0]
    assert finding.action_label == "Promote to <h3>"
    assert finding.metadata["run"] == 1


def test_an_h2_cannot_be_promoted_further():
    with pytest.raises(ActionError, match="as high as it can go"):
        apply_action("<h2>One</h2>", "promote_heading_run", {"index": 0})


# --------------------------------------------------------------------------
# Several bold paragraphs acting as headings — one post had four.
# --------------------------------------------------------------------------

def test_several_bold_paragraphs_offer_one_bulk_action():
    result = clean(
        "<p><strong>Why Hash?</strong></p><p>text</p>"
        "<p><strong>TANSTAAFL</strong></p><p>more</p>"
        "<p><strong>The Tradeoff</strong></p>"
    )
    bulk = rule(result, "SEO-FAKE-HEADING-ALL-001")
    assert len(bulk) == 1
    assert bulk[0].action_label == "Make all 3 headings"
    # The individual suggestions remain, for picking and choosing.
    assert len(rule(result, "SEO-FAKE-HEADING-001")) == 3


def test_a_single_bold_paragraph_gets_no_bulk_action():
    result = clean("<p><strong>Why Hash?</strong></p>")
    assert rule(result, "SEO-FAKE-HEADING-ALL-001") == []
    assert len(rule(result, "SEO-FAKE-HEADING-001")) == 1


def test_the_bulk_conversion_changes_every_one_and_no_copy():
    html = (
        "<p><strong>Why Hash?</strong></p><p>text</p>"
        "<p><strong>TANSTAAFL</strong></p>"
    )
    updated, message = apply_action(html, "promote_bold_paragraph_run", {"level": 3})
    soup = BeautifulSoup(updated, "html.parser")
    assert [h.get_text() for h in soup.find_all("h3")] == ["Why Hash?", "TANSTAAFL"]
    assert "2 bold paragraphs" in message
    assert soup.get_text(" ", strip=True) == BeautifulSoup(html, "html.parser").get_text(
        " ", strip=True
    )


def test_bold_inside_a_sentence_is_untouched_by_the_bulk_action():
    html = "<p>Once we have a table, <strong>all</strong> lookups are faster.</p>"
    with pytest.raises(ActionError, match="No all-bold paragraphs"):
        apply_action(html, "promote_bold_paragraph_run", {"level": 3})


# --------------------------------------------------------------------------
# A post with no <p> tags at all and single-newline paragraph breaks.
# Reported: the whole post arrived in WordPress as one paragraph, and the app
# had given no suggestions whatsoever to indicate it.
# --------------------------------------------------------------------------

MARTIN = (
    '<img src="https://www.dyalog.com/blog/wp-content/uploads/2026/08/martin_01-250x300.jpeg"'
    ' alt="" width="250" height="300" class="alignright size-medium wp-image-9757" />'
    "When Martin joined Dyalog last year, he confessed to a secret identity.\n"
    "Since arriving, Martin has taken on the behind-the-scenes work.\n"
    "Coming from more corporate environments, Martin found the culture refreshing.\n"
    '<img src="https://www.dyalog.com/blog/wp-content/uploads/2026/08/martin_02.jpeg"'
    ' alt="" width="2420" height="1816" class="aligncenter size-full wp-image-9756" />'
)


def test_a_post_with_no_paragraph_tags_is_flagged():
    """Previously silent: no suggestions at all on a post like this."""
    result = clean(MARTIN)
    finding = rule(result, "PARAGRAPH-LOOSE-001")
    assert len(finding) == 1
    assert finding[0].severity.value == "suggested"
    assert "single line breaks, not blank lines" in finding[0].message
    assert "1 paragraph block" in finding[0].message
    assert not finding[0].applied


def test_content_split_by_blank_lines_is_not_flagged():
    """The serialiser already handles those; suggesting it everywhere was noise.

    On the corpus this condition took the suggestion from 21 posts of 22 down to
    the 9 where it actually gains something.
    """
    result = clean("First paragraph.\n\nSecond paragraph.\n\nThird paragraph.")
    assert rule(result, "PARAGRAPH-LOOSE-001") == []
    # And they are already separate blocks.
    assert result.block_markup.count("<!-- wp:paragraph -->") == 3


def test_the_button_label_matches_what_it_does():
    """The count is taken before images become placeholders, so both must use
    the same definition of a line worth keeping."""
    result = clean(MARTIN)
    finding = rule(result, "PARAGRAPH-LOOSE-001")[0]
    updated, message = apply_action(
        result.cleaned_html, finding.action, finding.action_params
    )
    assert finding.action_label == "Wrap the lines in 4 paragraphs"
    assert "in 4 paragraphs" in message


def test_wrapping_the_lines_gives_separate_blocks():
    result = clean(MARTIN)
    finding = rule(result, "PARAGRAPH-LOOSE-001")[0]
    updated, _ = apply_action(result.cleaned_html, finding.action, finding.action_params)
    after = clean(updated)
    assert after.block_markup.count("<!-- wp:paragraph -->") == 4
    assert after.copy_preserved
    assert after.counts["error"] == 0


def test_wrapping_the_lines_changes_no_words():
    result = clean(MARTIN)
    finding = rule(result, "PARAGRAPH-LOOSE-001")[0]
    updated, _ = apply_action(result.cleaned_html, finding.action, finding.action_params)
    before_words = BeautifulSoup(result.cleaned_html, "html.parser").get_text(" ", strip=True).split()
    after_words = BeautifulSoup(updated, "html.parser").get_text(" ", strip=True).split()
    assert before_words == after_words


def test_an_image_only_line_gets_its_own_paragraph():
    """It has no text, but it is still a paragraph."""
    result = clean(MARTIN)
    finding = rule(result, "PARAGRAPH-LOOSE-001")[0]
    updated, _ = apply_action(result.cleaned_html, finding.action, finding.action_params)
    paragraphs = BeautifulSoup(updated, "html.parser").find_all("p")
    assert "martin_02.jpeg" in paragraphs[-1].get_text()


def test_content_that_already_has_paragraphs_is_not_flagged():
    result = clean("<p>First.</p>\n<p>Second.</p>")
    assert rule(result, "PARAGRAPH-LOOSE-001") == []


def test_a_single_line_of_loose_text_is_not_flagged():
    result = clean("Just one line of loose text.")
    assert rule(result, "PARAGRAPH-LOOSE-001") == []
