"""Block-markup output mode.

The point of this mode is that Gutenberg's paste sanitiser strips
class="language-apl" and class="ex-link", while its block parser does not.
These tests pin the delimiters and, above all, the survival of those classes.
"""
from __future__ import annotations

import re

from app.blocks import to_block_markup
from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


def test_paragraph_gets_paragraph_delimiters():
    markup, _ = to_block_markup("<p>Hello.</p>")
    assert markup == "<!-- wp:paragraph -->\n<p>Hello.</p>\n<!-- /wp:paragraph -->"


def test_h2_needs_no_level_attribute_but_h3_does():
    h2, _ = to_block_markup("<h2>Title</h2>")
    h3, _ = to_block_markup("<h3>Title</h3>")
    assert h2.startswith("<!-- wp:heading -->")
    assert h3.startswith('<!-- wp:heading {"level":3} -->')


def test_ordered_list_is_marked_ordered():
    unordered, _ = to_block_markup("<ul><li>a</li></ul>")
    ordered, _ = to_block_markup("<ol><li>a</li></ol>")
    assert unordered.startswith("<!-- wp:list -->")
    assert ordered.startswith('<!-- wp:list {"ordered":true} -->')


def test_pre_code_becomes_a_code_block_with_its_wrapper_class():
    markup, _ = to_block_markup('<pre><code class="language-apl">A←1 2 3</code></pre>')
    assert markup.startswith('<!-- wp:code {"className":"language-apl"} -->')
    assert 'class="wp-block-code language-apl"' in markup
    assert "A←1 2 3" in markup


def test_bare_image_is_wrapped_in_a_figure():
    markup, _ = to_block_markup('<img src="/a.jpg" alt="A"/>')
    assert markup.startswith("<!-- wp:image -->")
    assert '<figure class="wp-block-image">' in markup
    assert 'src="/a.jpg"' in markup


def test_unknown_element_falls_back_to_custom_html_and_is_reported():
    markup, findings = to_block_markup('<div class="callout">Note</div>')
    assert markup.startswith("<!-- wp:html -->")
    assert '<div class="callout">Note</div>' in markup
    assert any(f.rule_id == "BLOCK-MARKUP-001" for f in findings)


# --------------------------------------------------------------------------
# The reason this mode exists.
# --------------------------------------------------------------------------

def test_apl_and_exlink_classes_survive_into_block_markup():
    result = clean(
        '<p class="code-line" dir="auto">Use <code>Words</code> and see '
        '<a href="https://github.com/Dyalog/ride">RIDE</a>.</p>'
    )
    markup = result.block_markup
    assert 'class="language-apl"' in markup
    assert "ex-link" in markup
    assert markup.startswith("<!-- wp:paragraph -->")
    # The cleaner's own guarantees must not be undone by serialisation.
    assert "code-line" not in markup
    assert 'dir="auto"' not in markup


def test_block_markup_changes_no_copy():
    from bs4 import BeautifulSoup

    source = (
        "<h2>Word frequencies</h2>"
        "<p>We'll call these <code>Words</code> and <code>Freqs</code>.</p>"
        '<ul><li>See <a href="https://example.org/">the notes</a></li></ul>'
    )
    result = clean(source)
    cleaned_text = BeautifulSoup(result.cleaned_html, "html.parser").get_text(" ", strip=True)
    block_text = BeautifulSoup(result.block_markup, "html.parser").get_text(" ", strip=True)
    assert cleaned_text == block_text
    assert result.copy_preserved


def test_every_opened_block_is_closed():
    result = clean(
        "<h2>Title</h2><p>Text</p><ul><li>Item</li></ul>"
        "<pre><code>A←1</code></pre><blockquote><p>Quote</p></blockquote>"
    )
    assert_delimiters_balance(result.block_markup)
    assert "<!-- wp:" in result.block_markup


def test_a_quote_holds_paragraph_blocks_not_loose_text():
    """core/quote fails validation on bare text: "unexpected or invalid content"."""
    result = clean("<blockquote>If it walks like a duck.</blockquote>")
    markup = result.block_markup
    assert "<!-- wp:quote -->" in markup
    assert 'class="wp-block-quote"' in markup
    # The text is inside a nested paragraph block, as Gutenberg saves it.
    assert "<!-- wp:paragraph -->" in markup
    assert "<p>If it walks like a duck.</p>" in markup
    assert_delimiters_balance(markup)


def test_a_quote_that_already_has_paragraphs_is_not_double_wrapped():
    result = clean("<blockquote><p>One.</p><p>Two.</p></blockquote>")
    assert result.block_markup.count("<!-- wp:paragraph -->") == 2
    assert "<p><p>" not in result.block_markup
    assert_delimiters_balance(result.block_markup)


def test_a_citation_stays_in_the_quote_block():
    result = clean("<blockquote><p>Quoted.</p><cite>Someone</cite></blockquote>")
    assert "<cite>Someone</cite>" in result.block_markup
    assert_delimiters_balance(result.block_markup)


def test_block_markup_is_idempotent_through_the_cleaner():
    """Re-cleaning block markup must not disturb the delimiters or the classes."""
    source = '<p class="code-line">Use <code>Words</code>.</p>'
    once = clean(source).block_markup
    twice = clean(once).block_markup
    assert once == twice
    assert "<!-- wp:paragraph -->" in twice
    assert 'class="language-apl"' in twice


# --------------------------------------------------------------------------
# Real failures found by pasting a full Dyalog post into WordPress.
# Handoff 29: the exact input that exposed each bug is kept here.
# --------------------------------------------------------------------------

def test_code_block_language_rides_on_the_pre_so_the_block_validates():
    """core/code stores content via the <code> selector.

    A class on <code> is dropped when Gutenberg regenerates the block, so every
    code block reported "unexpected or invalid content". The language must be the
    block's own className, on the <pre>.
    """
    result = clean("<pre>      (Words Freqs)←⎕CSV</pre>")
    markup = result.block_markup
    assert markup.startswith('<!-- wp:code {"className":"language-apl"} -->')
    assert '<pre class="wp-block-code language-apl">' in markup
    assert "<code>" in markup
    assert '<code class="language-apl">' not in markup
    # The plain HTML output still follows handoff 3.4 and is unaffected.
    assert '<pre><code class="language-apl">' in result.cleaned_html


def test_loose_inline_content_does_not_shatter_a_sentence():
    """A top-level <a>/<code>/<strong> used to become its own Custom HTML block,
    splitting one sentence across three blocks."""
    result = clean(
        'can do some amazing things. <a href="https://example.org/">'
        "Parsing content using <code>⎕CSV</code></a>. From that list:"
    )
    markup = result.block_markup
    assert markup.count("<!-- wp:paragraph -->") == 1
    assert "wp:html" not in markup
    assert "can do some amazing things." in markup
    assert "From that list:" in markup


def test_loose_inline_run_keeps_its_classes():
    result = clean('Text <strong>"I Feel the Need for Speed"</strong> more text')
    assert result.block_markup.count("<!-- wp:paragraph -->") == 1
    assert "<strong>" in result.block_markup


def test_block_markup_preserves_every_word_of_the_cleaned_html():
    """The copy guard covers cleaned HTML, not the block view; check it here."""
    from bs4 import BeautifulSoup

    source = (
        "<pre>A←1 2 3</pre>"
        'Loose text with <a href="https://example.org/">a link</a> and <code>Words</code>.'
        "<h2>Heading</h2><ul><li>Item</li></ul>"
    )
    result = clean(source)
    cleaned = BeautifulSoup(result.cleaned_html, "html.parser").get_text(" ", strip=True).split()
    blocks = BeautifulSoup(result.block_markup, "html.parser").get_text(" ", strip=True).split()
    assert cleaned == blocks


# --------------------------------------------------------------------------
# Classic WordPress content: no <p> tags, paragraphs separated by blank lines.
# --------------------------------------------------------------------------

def test_blank_lines_separate_paragraphs_in_classic_content():
    """Older Dyalog posts have no <p> tags at all.

    Grouping loose inline content merged the whole post into one paragraph,
    because the blank lines between them are whitespace-only text nodes.
    """
    result = clean("First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here.")
    markup = result.block_markup
    assert markup.count("<!-- wp:paragraph -->") == 3
    assert "<p>First paragraph here.</p>" in markup
    assert "<p>Second paragraph here.</p>" in markup
    assert "<p>Third paragraph here.</p>" in markup


def test_a_blank_line_inside_a_run_with_inline_markup_still_splits():
    result = clean(
        'Text with <em>emphasis</em> here.\n\nAnd <a href="https://example.org/">a link</a> here.'
    )
    markup = result.block_markup
    assert markup.count("<!-- wp:paragraph -->") == 2
    assert "<em>emphasis</em>" in markup
    assert "ex-link" in markup


def test_a_single_newline_does_not_split_a_paragraph():
    """Only a blank line is a paragraph break; a wrapped line is not."""
    result = clean("One sentence\nwrapped across lines.")
    assert result.block_markup.count("<!-- wp:paragraph -->") == 1


def test_classic_content_keeps_every_word():
    from bs4 import BeautifulSoup

    source = (
        "Opening paragraph.\n\n"
        "Second with <code>code</code> in it.\n\n"
        '<h2 id="x">A heading</h2>\n'
        "Text right after the heading.\n\n"
        "<pre><code>A←1 2 3</code></pre>\n"
        "Closing paragraph."
    )
    result = clean(source)
    cleaned = BeautifulSoup(result.cleaned_html, "html.parser").get_text(" ", strip=True).split()
    blocks = BeautifulSoup(result.block_markup, "html.parser").get_text(" ", strip=True).split()
    assert cleaned == blocks
    assert result.copy_preserved


def test_definition_list_falls_back_to_custom_html_and_says_so():
    """Gutenberg has no core block for <dl>, so Custom HTML is correct here."""
    result = clean("<dl><dt>Feature</dt><dd>Does a thing.</dd></dl>")
    assert "<!-- wp:html -->" in result.block_markup
    assert "<dt>Feature</dt>" in result.block_markup
    assert any(f.rule_id == "BLOCK-MARKUP-001" for f in result.findings)

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
