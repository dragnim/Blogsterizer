"""Images never reach the new markup.

Found by pasting a real post's output into WordPress: the block serialiser was
emitting `wp:image` blocks whose src pointed at www.dyalog.com, hotlinking the
site being migrated away from. Images are processed separately and placed by
hand, so every `<img>` becomes a placeholder.

This overrides handoff section 11, "normal images must survive". That rule was
written when the app destroyed images silently; nothing is destroyed here, since
the filename survives in the placeholder and the alt text in the finding.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


MARTIN = (
    '<figure class="wp-block-image"><img alt="" height="300" '
    'src="https://www.dyalog.com/blog/wp-content/uploads/2026/08/'
    'employeespotlight_martin_oneyear_01-250x300.jpeg" width="250"/></figure>'
    "<p>When Martin joined Dyalog last year...</p>"
)


def test_no_old_site_url_survives_in_the_output():
    result = clean(MARTIN)
    assert "dyalog.com" not in result.cleaned_html
    assert "dyalog.com" not in result.block_markup
    assert "<img" not in result.cleaned_html


def test_the_placeholder_names_the_file():
    result = clean(MARTIN)
    assert (
        "Image here: employeespotlight_martin_oneyear_01-250x300.jpeg"
        in result.cleaned_html
    )


def test_no_wp_image_block_is_emitted():
    """A wp:image block would carry the old src into WordPress."""
    result = clean(MARTIN)
    assert "wp:image" not in result.block_markup
    assert result.block_markup.count("<!-- wp:paragraph -->") == 2


def test_original_alt_text_is_reported_not_discarded():
    result = clean('<p><img src="shot.png" alt="The RunTime output"></p>')
    findings = [f for f in result.findings if f.rule_id == "IMAGE-PLACEHOLDER-001"]
    assert len(findings) == 1
    assert findings[0].metadata["alt"] == "The RunTime output"
    assert "The RunTime output" in findings[0].message


def test_a_linked_thumbnail_keeps_its_link():
    """<a href="report.pdf"><img></a> is a link to the report.

    Swallowing the anchor with the image would lose the PDF entirely.
    """
    result = clean(
        '<p><a href="https://example.com/report.pdf">'
        '<img src="report-cover.jpg" width="600" height="800" alt="Report cover"></a></p>'
    )
    anchor = BeautifulSoup(result.cleaned_html, "html.parser").a
    assert anchor is not None
    assert anchor["href"] == "https://example.com/report.pdf"
    assert "Image here: report-cover.jpg" in anchor.get_text()
    assert "ex-link" in anchor.get("class", [])


def test_an_image_alone_in_a_paragraph_replaces_the_paragraph():
    result = clean('<p><img src="photo.jpg"></p>')
    soup = BeautifulSoup(result.cleaned_html, "html.parser")
    assert soup.p is not None
    assert soup.p.find("p") is None  # no nested block


def test_an_inline_image_gets_an_inline_placeholder():
    result = clean('<p>See <img src="shot.png"> for the output.</p>')
    soup = BeautifulSoup(result.cleaned_html, "html.parser")
    assert soup.p.find("p") is None
    assert soup.p.find("strong")["class"] == ["image-placeholder"]
    assert "See" in soup.p.get_text()
    assert "for the output." in soup.p.get_text()


def test_a_figure_keeps_its_caption():
    result = clean('<figure><img src="shot.png"><figcaption>Figure 1</figcaption></figure>')
    assert "<figcaption>Figure 1</figcaption>" in result.cleaned_html


def test_replacing_images_is_idempotent():
    once = clean('<p><img src="shot.png"></p>').cleaned_html
    twice = clean(once).cleaned_html
    assert once == twice


def test_the_seo_alt_check_still_sees_the_image():
    """The placeholder rule runs after the SEO pass, so a missing alt is caught."""
    result = clean('<p><img src="shot.png" width="800" height="600"></p>')
    assert any(f.rule_id == "SEO-IMG-ALT-001" for f in result.findings)


def test_the_rule_can_be_switched_off():
    import copy

    keep = copy.deepcopy(load_profile(DEFAULT_PROFILE_ID))
    keep["rules"]["image_placeholder"] = {"replace_images": False}
    result = analyse_html('<p><img src="shot.png"></p>', keep)
    assert "<img" in result.cleaned_html


# --------------------------------------------------------------------------
# One <p> holding the whole post.
# --------------------------------------------------------------------------

def test_a_paragraph_full_of_line_breaks_is_suggested_for_splitting():
    """Found in a real post: the whole article inside a single <p>."""
    result = clean(
        "<p>First para ends here and is long enough.\n"
        "Second para here also of some length.\n"
        "Third para to finish.</p>"
    )
    findings = [f for f in result.findings if f.rule_id == "PARAGRAPH-LINES-001"]
    assert len(findings) == 1
    assert findings[0].severity.value == "suggested"
    assert findings[0].action == "split_paragraph_lines"
    assert findings[0].action_label == "Split into 3 paragraphs"
    # Nothing was changed: splitting is editorial (handoff 9).
    assert not findings[0].applied
    assert result.cleaned_html.count("<p") == 1


def test_a_wrapped_line_is_not_mistaken_for_a_paragraph_break():
    result = clean("<p>One sentence\nwrapped over two lines.</p>")
    assert not [f for f in result.findings if f.rule_id == "PARAGRAPH-LINES-001"]


def test_splitting_at_line_breaks_keeps_every_word_and_the_class():
    from app.actions import apply_action

    html = '<p class="lead">First para.\nSecond para.\nThird para.</p>'
    updated, message = apply_action(html, "split_paragraph_lines", {"index": 0})
    soup = BeautifulSoup(updated, "html.parser")
    assert len(soup.find_all("p")) == 3
    assert all(p.get("class") == ["lead"] for p in soup.find_all("p"))
    assert "3" in message

    before = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split()
    after = BeautifulSoup(updated, "html.parser").get_text(" ", strip=True).split()
    assert before == after


def test_splitting_does_not_cut_inline_markup():
    from app.actions import apply_action

    html = "<p>Use <code>Words</code> here.\nAnd <code>Freqs</code> there.</p>"
    updated, _ = apply_action(html, "split_paragraph_lines", {"index": 0})
    soup = BeautifulSoup(updated, "html.parser")
    assert len(soup.find_all("p")) == 2
    assert len(soup.find_all("code")) == 2
