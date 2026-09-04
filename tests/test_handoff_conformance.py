"""Conformance tests written from the handoff document, not from the code.

Per handoff section 29, each of these was written to fail against v0.5.0 before
any rule is changed. Section references point at the paragraph of the handoff
that each test encodes.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


# --------------------------------------------------------------------------
# Section 4.3 — unknown classes must not be destroyed just because the app
# does not recognise them.
# --------------------------------------------------------------------------

def test_unknown_class_on_div_is_not_destroyed():
    result = clean('<div class="callout-important">Important</div>')
    assert "callout-important" in result.cleaned_html


def test_unknown_class_on_paragraph_is_not_destroyed():
    result = clean('<p class="lead-paragraph">Intro text</p>')
    assert "lead-paragraph" in result.cleaned_html


def test_span_with_meaningful_class_is_not_unwrapped():
    result = clean('<p><span class="highlight">key term</span></p>')
    assert "highlight" in result.cleaned_html
    assert "<span" in result.cleaned_html


def test_unknown_class_on_table_is_not_destroyed():
    result = clean('<table class="pricing"><tr><td>1</td></tr></table>')
    assert "pricing" in result.cleaned_html


# --------------------------------------------------------------------------
# Section 5.1 — "If an anchor already has another legitimate class, append
# ex-link; do not delete the existing class."
# --------------------------------------------------------------------------

def test_existing_anchor_class_survives_alongside_ex_link():
    result = clean('<p><a class="button-primary" href="https://example.org/">Go</a></p>')
    classes = BeautifulSoup(result.cleaned_html, "html.parser").a.get("class", [])
    assert "ex-link" in classes
    assert "button-primary" in classes


# --------------------------------------------------------------------------
# Section 11 / 27 — a normal content image must survive. Resource-icon removal
# must only fire on a genuine legacy icon, not on a large screenshot whose
# filename happens to contain a resource word.
# --------------------------------------------------------------------------

def test_large_linked_screenshot_is_not_treated_as_a_resource_icon():
    """Content images become placeholders; legacy icons are destroyed outright.

    The distinction still matters after images stopped being carried into the
    markup: a placeholder names the file so it can be put back, while the
    resource-icon rule removes it and leaves "View resource".
    """
    result = clean(
        '<p><a href="/full.png">'
        '<img src="/uploads/pdf-export-screenshot.png" '
        'alt="Screenshot of the PDF export dialog" width="800" height="500">'
        "</a></p>"
    )
    assert "Image here: pdf-export-screenshot.png" in result.cleaned_html
    assert "View resource" not in result.cleaned_html
    # The original alt text is not lost: it is reported for the sidecar file.
    assert any(
        f.metadata.get("alt") == "Screenshot of the PDF export dialog"
        for f in result.findings
        if f.rule_id == "IMAGE-PLACEHOLDER-001"
    )


def test_an_image_that_is_removed_still_names_the_file_it_was():
    """Replacing an image is only acceptable because nothing is lost.

    The filename survives in the placeholder and the alt text survives in the
    finding, so the image can be put back by hand.
    """
    result = clean(
        '<p><a href="/full.png">'
        '<img src="/uploads/pdf-export-screenshot.png" '
        'alt="Screenshot of the PDF export dialog" width="800" height="500">'
        "</a></p>"
    )
    assert BeautifulSoup(result.cleaned_html, "html.parser").img is None
    assert "pdf-export-screenshot.png" in result.cleaned_html


# --------------------------------------------------------------------------
# Sections 2 and 3.5 — raw-APL detection must be conservative. Ordinary
# typographic characters in prose are not APL and must not be wrapped.
# --------------------------------------------------------------------------

def test_multiplication_sign_in_prose_is_not_apl():
    result = clean("<p>The grid is 3 \u00d7 4 in size.</p>")
    assert "<code" not in result.cleaned_html


def test_inequality_in_prose_is_not_apl():
    result = clean("<p>Results were \u2264 20 milliseconds.</p>")
    assert "<code" not in result.cleaned_html


def test_menu_arrow_in_prose_is_not_apl():
    result = clean("<p>Choose File \u2192 Save from the menu.</p>")
    assert "<code" not in result.cleaned_html


# --------------------------------------------------------------------------
# Section 7 — spacing quality of a generated resource label.
# --------------------------------------------------------------------------

def test_inline_icon_removal_does_not_leave_a_double_space():
    result = clean(
        '<p>See the <a href="/notes.pdf">notes '
        '<img src="/img/pdf_24.png" width="24" height="24" alt=""></a> for detail.</p>'
    )
    assert "  " not in BeautifulSoup(result.cleaned_html, "html.parser").get_text()


# --------------------------------------------------------------------------
# Section 4.1 — syntax-highlighter spans are editor cruft, in the same family
# as code-line. Unwrapping must keep the text exactly.
# --------------------------------------------------------------------------

def test_prism_token_span_is_unwrapped():
    result = clean(
        '<p>the experimental <code class="language-apl">'
        '<span class="token punctuation">]</span>Get</code> user command.</p>'
    )
    assert result.cleaned_html == (
        '<p>the experimental <code class="language-apl">]Get</code> user command.</p>'
    )
    assert result.copy_preserved


def test_every_prism_token_type_is_unwrapped():
    """Prism always emits `token` alongside the type, so one marker covers all."""
    for token_type in ("punctuation", "keyword", "string", "comment", "operator", "number"):
        result = clean(f'<p><code><span class="token {token_type}">x</span>y</code></p>')
        assert "<span" not in result.cleaned_html, token_type
        assert ">xy<" in result.cleaned_html, token_type


def test_highlight_js_spans_are_unwrapped():
    result = clean('<pre><code><span class="hljs-keyword">:If</span> x</code></pre>')
    assert "<span" not in result.cleaned_html
    assert ":If x" in result.cleaned_html


def test_unwrapping_a_highlighter_span_changes_no_text():
    from bs4 import BeautifulSoup

    source = (
        '<p>Run <code class="language-apl">'
        '<span class="token punctuation">]</span>'
        '<span class="token function">LINK</span>'
        '<span class="token punctuation">.</span>Export</code> now.</p>'
    )
    result = clean(source)
    assert "<span" not in result.cleaned_html
    assert BeautifulSoup(source, "html.parser").get_text() == BeautifulSoup(
        result.cleaned_html, "html.parser"
    ).get_text()


def test_a_meaningful_span_class_is_still_not_unwrapped():
    """The 4.3 guarantee holds: only highlighter markers are treated as cruft."""
    result = clean('<p><span class="highlight">key term</span></p>')
    assert "highlight" in result.cleaned_html
    assert "<span" in result.cleaned_html


# --------------------------------------------------------------------------
# The copy guard's idea of visible text (section 2).
# --------------------------------------------------------------------------

def test_inline_elements_contribute_no_whitespace():
    """A browser renders <span>x</span>y as "xy".

    Reading it as "x y" made the guard reject any change that added or removed
    an inline wrapper mid-word, and roll back the whole cleanup rule.
    """
    from app.engine import _visible_text

    assert _visible_text('<p><code><span class="token keyword">x</span>y</code></p>') == "xy"
    assert _visible_text("<p>Use <code>Words</code>.</p>") == "Use Words."


def test_block_elements_still_separate_words():
    from app.engine import _visible_text

    assert _visible_text("<p>a</p><p>b</p>") == "a b"
    assert _visible_text("<ul><li>one</li><li>two</li></ul>") == "one two"
    assert _visible_text("<p>line one<br>line two</p>") == "line one line two"


def test_comments_are_not_visible_copy():
    """Block markup carries its structure in comments."""
    from app.engine import _visible_text

    assert _visible_text("<!-- wp:paragraph --><p>Text.</p><!-- /wp:paragraph -->") == "Text."


def test_the_guard_still_catches_a_real_word_change():
    """The whole point of the guard: it must not have been loosened."""
    from app.engine import _tokens

    assert _tokens("<p>Dyalog v7.0 is old</p>") != _tokens("<p>Dyalog v17.0 is old</p>")
    assert _tokens("<p>one two three</p>") != _tokens("<p>one three</p>")
    assert _tokens("<p>hello</p>") != _tokens("<p>hullo</p>")


def test_reimporting_block_markup_is_stable():
    result = clean('<p class="code-line">Use <code>Words</code>.</p>')
    once = result.block_markup
    twice = clean(once).block_markup
    assert once == twice
    assert "wp:paragraph</p>" not in twice  # the comment must not become text
