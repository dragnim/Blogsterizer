"""Image preparation.

Images are matched to <img> tags by filename, processed to 1200px WebP, and each
tag is replaced by a visible placeholder. Nothing is guessed: an unmatched tag or
an unreferenced file is reported.

The drafting tests use a stubbed API. There is no key in the test environment,
and the no-key path is the one most people will hit first, so it is tested
explicitly rather than assumed.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from app.images import (
    basename_of,
    classify,
    list_folder,
    plan_images,
    process_images,
    replace_with_placeholders,
    slugify,
)
from app.imagetext import Draft, draft_all, sidecar_text


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """A screenshot of text, a photograph, and a small screenshot."""
    source = tmp_path / "source"
    source.mkdir()

    shot = Image.new("RGB", (1600, 500), "white")
    draw = ImageDraw.Draw(shot)
    for row in range(12):
        draw.text((20, 20 + row * 36), "      hWords←1500⌶Words  ⍝ hashed", fill="black")
    shot.save(source / "screenshot.png")

    photo = Image.new("RGB", (2000, 1200))
    pixels = photo.load()
    for y in range(1200):
        for x in range(0, 2000, 2):
            colour = ((x * 7) % 256, (y * 11) % 256, (x + y) % 256)
            pixels[x, y] = colour
            if x + 1 < 2000:
                pixels[x + 1, y] = colour
    photo.save(source / "photo.jpg", quality=95)

    small = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(small).text((10, 10), ":For i :In \u2373n", fill="black")
    small.save(source / "small.png")

    return source


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------

def test_slug_comes_from_the_post_url():
    assert slugify(
        "https://www.dyalog.com/blog/2018/09/enhanced-debugging-with-function-keys/"
    ) == "enhanced-debugging-with-function-keys"


def test_trailing_date_segments_are_not_the_slug():
    assert slugify("https://www.dyalog.com/blog/2018/09/") == "blog"


def test_a_plain_title_also_works():
    assert slugify("Hashing It Out: Lookup Performance") == "hashing-it-out-lookup-performance"


def test_output_names_follow_the_convention(folder):
    html = '<p><img src="screenshot.png"></p><p><img src="photo.jpg"></p>'
    report = plan_images(html, folder, "my-post")
    assert [plan.output_name for plan in report.plans] == [
        "blog_my-post_01.webp",
        "blog_my-post_02.webp",
    ]


def test_numbering_follows_document_order(folder):
    html = '<p><img src="photo.jpg"></p><p><img src="screenshot.png"></p>'
    report = plan_images(html, folder, "p")
    assert report.plans[0].source.name == "photo.jpg"
    assert report.plans[1].source.name == "screenshot.png"


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def test_an_absolute_src_matches_on_filename():
    assert basename_of("https://www.dyalog.com/uploads/2019/03/shot.png") == "shot.png"
    assert basename_of("/wp-content/a%20b.png") == "a b.png"
    assert basename_of("shot.png") == "shot.png"


def test_absolute_urls_in_the_html_match_local_files(folder):
    html = '<p><img src="https://www.dyalog.com/uploads/2019/03/screenshot.png"></p>'
    report = plan_images(html, folder, "p")
    assert report.plans[0].matched
    assert report.plans[0].source.name == "screenshot.png"


def test_a_missing_file_is_reported_never_guessed(folder):
    html = '<p><img src="screenshot.png"></p><p><img src="nowhere.png"></p>'
    report = plan_images(html, folder, "p")
    assert len(report.matched) == 1
    unmatched = report.unmatched
    assert len(unmatched) == 1
    assert "nowhere.png" in unmatched[0].note
    assert "guessed" in unmatched[0].note


def test_an_unreferenced_file_is_reported(folder):
    html = '<p><img src="screenshot.png"></p>'
    report = plan_images(html, folder, "p")
    assert report.unreferenced == ["photo.jpg", "small.png"]


def test_existing_alt_text_is_carried_through(folder):
    html = '<p><img src="screenshot.png" alt="Timing three words against four"></p>'
    report = plan_images(html, folder, "p")
    assert report.plans[0].existing_alt == "Timing three words against four"


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

def test_wide_images_are_resized_to_1200(folder, tmp_path):
    html = '<p><img src="photo.jpg"></p>'
    report = process_images(plan_images(html, folder, "p"), tmp_path / "out")
    with Image.open(tmp_path / "out" / "blog_p_01.webp") as result:
        assert result.width == 1200
        assert result.height == 720  # aspect ratio kept: 2000x1200 -> 1200x720


def test_small_images_are_never_upscaled(folder, tmp_path):
    html = '<p><img src="small.png"></p>'
    process_images(plan_images(html, folder, "p"), tmp_path / "out")
    with Image.open(tmp_path / "out" / "blog_p_01.webp") as result:
        assert result.size == (400, 300)


def test_output_is_webp(folder, tmp_path):
    html = '<p><img src="screenshot.png"></p>'
    process_images(plan_images(html, folder, "p"), tmp_path / "out")
    with Image.open(tmp_path / "out" / "blog_p_01.webp") as result:
        assert result.format == "WEBP"


def test_originals_are_left_untouched(folder, tmp_path):
    before = {path.name: path.read_bytes() for path in list_folder(folder)}
    html = '<p><img src="screenshot.png"></p><p><img src="photo.jpg"></p>'
    process_images(plan_images(html, folder, "p"), tmp_path / "out")
    after = {path.name: path.read_bytes() for path in list_folder(folder)}
    assert before == after


def test_an_existing_output_file_is_not_overwritten_silently(folder, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "blog_p_01.webp").write_bytes(b"do not lose me")

    html = '<p><img src="screenshot.png"></p>'
    report = process_images(plan_images(html, folder, "p"), out)
    assert (out / "blog_p_01.webp").read_bytes() == b"do not lose me"
    assert any("already exists" in error for error in report.errors)
    assert report.written == []


def test_overwrite_is_possible_when_asked(folder, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "blog_p_01.webp").write_bytes(b"replace me")

    html = '<p><img src="screenshot.png"></p>'
    report = process_images(plan_images(html, folder, "p"), out, overwrite=True)
    assert (out / "blog_p_01.webp").read_bytes() != b"replace me"
    assert report.written == ["blog_p_01.webp"]


def test_exif_is_not_carried_into_the_output(folder, tmp_path):
    """Photographs can carry camera and location data."""
    html = '<p><img src="photo.jpg"></p>'
    process_images(plan_images(html, folder, "p"), tmp_path / "out")
    with Image.open(tmp_path / "out" / "blog_p_01.webp") as result:
        assert not result.getexif()


# --------------------------------------------------------------------------
# Compression choice
# --------------------------------------------------------------------------

def test_a_screenshot_of_text_is_classified_as_a_screenshot(folder):
    with Image.open(folder / "screenshot.png") as image:
        assert classify(image) == "screenshot"


def test_a_photograph_is_classified_as_a_photo(folder):
    with Image.open(folder / "photo.jpg") as image:
        assert classify(image) == "photo"


def test_the_chosen_encoding_is_reported(folder):
    html = '<p><img src="screenshot.png"></p><p><img src="photo.jpg"></p>'
    report = plan_images(html, folder, "p")
    assert report.plans[0].encoding == "near-lossless"
    assert report.plans[1].encoding == "lossy"


def test_a_screenshot_keeps_its_text_crisp(folder, tmp_path):
    """Near-lossless must actually preserve the glyphs.

    Lossy WebP rings around monospaced text; this checks the screenshot path
    stays close to the original rather than trusting the flag was passed.
    """
    html = '<p><img src="small.png"></p>'
    process_images(plan_images(html, folder, "p"), tmp_path / "out")
    from PIL import ImageChops

    with Image.open(folder / "small.png") as original, Image.open(
        tmp_path / "out" / "blog_p_01.webp"
    ) as result:
        difference = ImageChops.difference(original.convert("RGB"), result.convert("RGB"))
        worst = max(high for _low, high in difference.getextrema())
        assert worst <= 40, f"text was visibly degraded (worst channel delta {worst})"


# --------------------------------------------------------------------------
# Placeholders
# --------------------------------------------------------------------------

def test_an_image_alone_in_a_paragraph_becomes_a_block_placeholder(folder):
    html = '<p><img src="screenshot.png"></p>'
    report = plan_images(html, folder, "p")
    updated, placeholders = replace_with_placeholders(html, report)
    assert updated == (
        '<p class="image-placeholder"><strong>Image here: blog_p_01.webp</strong></p>'
    )
    assert placeholders == ["Image here: blog_p_01.webp"]


def test_a_linked_image_does_not_leave_an_empty_link(folder):
    html = '<p><a href="/full.png"><img src="screenshot.png"></a></p>'
    updated, _ = replace_with_placeholders(html, plan_images(html, folder, "p"))
    assert "<a" not in updated


def test_an_inline_image_gets_an_inline_placeholder(folder):
    """A block element inside a paragraph would be invalid HTML."""
    html = '<p>See <img src="screenshot.png"> for the output.</p>'
    updated, _ = replace_with_placeholders(html, plan_images(html, folder, "p"))
    soup = BeautifulSoup(updated, "html.parser")
    assert soup.p is not None
    assert soup.p.find("p") is None
    assert soup.p.find("strong")["class"] == ["image-placeholder"]


def test_a_figure_with_a_caption_keeps_its_caption(folder):
    html = '<figure><img src="screenshot.png"><figcaption>Figure 1</figcaption></figure>'
    updated, _ = replace_with_placeholders(html, plan_images(html, folder, "p"))
    assert "<figcaption>Figure 1</figcaption>" in updated


def test_no_placeholder_for_an_unmatched_image(folder):
    html = '<p><img src="nowhere.png"></p>'
    updated, placeholders = replace_with_placeholders(html, plan_images(html, folder, "p"))
    assert placeholders == []
    assert "<img" in updated  # left as it was, for the user to deal with


def test_the_placeholder_names_the_file_it_refers_to(folder):
    html = '<p><img src="screenshot.png"></p><p><img src="photo.jpg"></p>'
    _, placeholders = replace_with_placeholders(html, plan_images(html, folder, "p"))
    assert placeholders == [
        "Image here: blog_p_01.webp",
        "Image here: blog_p_02.webp",
    ]


# --------------------------------------------------------------------------
# Alt text and titles
# --------------------------------------------------------------------------

def test_existing_alt_text_wins_over_drafting(folder, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    html = '<p><img src="screenshot.png" alt="Timing three words against four"></p>'
    drafts = draft_all(plan_images(html, folder, "p"), client=_never_called_client())
    assert drafts[1].status == "KEPT"
    assert drafts[1].alt == "Timing three words against four"


def test_without_a_key_nothing_is_invented(folder, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    html = '<p><img src="screenshot.png"></p>'
    drafts = draft_all(plan_images(html, folder, "p"))
    assert drafts[1].status == "TODO"
    assert drafts[1].alt == ""
    assert "ANTHROPIC_API_KEY" in drafts[1].detail


def test_a_filename_is_never_turned_into_a_description(folder, monkeypatch):
    """"screenshot.png" says nothing about what the screenshot shows."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    html = '<p><img src="screenshot.png"></p>'
    drafts = draft_all(plan_images(html, folder, "p"))
    assert "screenshot" not in drafts[1].alt.lower()
    assert drafts[1].alt == ""


def _never_called_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("the model should not have been called")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _stub_client(text: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"content": [{"type": "text", "text": text}]}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_model_draft_is_marked_unreviewed(folder, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    html = '<p><img src="screenshot.png"></p>'
    client = _stub_client(
        "ALT: A Dyalog session timing an indexed lookup against a hashed array.\n"
        "TITLE: Timing a hashed lookup"
    )
    drafts = draft_all(plan_images(html, folder, "p"), client=client)
    assert drafts[1].status == "UNREVIEWED"
    assert drafts[1].alt.startswith("A Dyalog session")
    assert drafts[1].title == "Timing a hashed lookup"


def test_a_model_that_cannot_tell_says_so(folder, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    html = '<p><img src="screenshot.png"></p>'
    drafts = draft_all(plan_images(html, folder, "p"), client=_stub_client("UNCLEAR"))
    assert drafts[1].status == "TODO"
    assert drafts[1].alt == ""


def test_an_api_error_does_not_lose_the_run(folder, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    html = '<p><img src="screenshot.png"></p>'
    drafts = draft_all(plan_images(html, folder, "p"), client=_stub_client("", status=529))
    assert drafts[1].status == "FAILED"
    assert "529" in drafts[1].detail


# --------------------------------------------------------------------------
# The sidecar file
# --------------------------------------------------------------------------

def test_sidecar_warns_that_nothing_has_been_checked(folder):
    html = '<p><img src="screenshot.png"></p>'
    report = plan_images(html, folder, "my-post")
    text = sidecar_text(report, {1: Draft(alt="x", status="UNREVIEWED")}, "my-post")
    assert "NOTHING IN THIS FILE HAS BEEN PUBLISHED OR CHECKED." in text
    assert "UNREVIEWED" in text


def test_sidecar_lists_unmatched_images_and_unreferenced_files(folder):
    html = '<p><img src="screenshot.png"></p><p><img src="nowhere.png"></p>'
    report = plan_images(html, folder, "p")
    text = sidecar_text(report, draft_all(report), "p")
    assert "NOT PROCESSED" in text
    assert "nowhere.png" in text
    assert "no <img> in the post refers to" in text
    assert "photo.jpg" in text


def test_sidecar_records_the_encoding_decision_and_final_size(folder, tmp_path):
    html = '<p><img src="screenshot.png"></p>'
    report = process_images(plan_images(html, folder, "p"), tmp_path / "out")
    text = sidecar_text(report, draft_all(report), "p")
    assert "screenshot" in text
    assert "near-lossless" in text
    # The size recorded is the processed size, not the original 1600x500.
    assert "1200x375px" in text


# --------------------------------------------------------------------------
# Through the interface
# --------------------------------------------------------------------------

def test_processing_through_the_endpoint_writes_files_and_a_sidecar(folder, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    out = tmp_path / "out"
    response = client.post(
        "/images",
        data={
            "source": '<p>Intro.</p><p><img src="screenshot.png" alt="Timing output"></p>',
            "history": "[]",
            "folder": str(folder),
            "post_url": "https://www.dyalog.com/blog/2026/01/hashing-it-out/",
            "output_folder": str(out),
        },
    )
    assert response.status_code == 200
    assert "Processed 1 image(s)" in response.text
    assert (out / "blog_hashing-it-out_01.webp").exists()
    assert (out / "hashing-it-out-images.txt").exists()
    # The cleaner's placeholder names the *original* file, because it runs on
    # every analysis and knows nothing about this processing run. The Images
    # table and the sidecar carry the mapping to the processed name.
    assert "Image here: screenshot.png" in response.text
    assert 'src="screenshot.png"' not in response.text
    assert "blog_hashing-it-out_01.webp" in response.text  # shown in the table


def test_a_bad_folder_path_is_reported_not_a_crash(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/images",
        data={
            "source": '<p><img src="a.png"></p>',
            "history": "[]",
            "folder": str(tmp_path / "does-not-exist"),
            "post_url": "test",
        },
    )
    assert response.status_code == 200
    assert "Not applied:" in response.text or "NotADirectoryError" in response.text


def test_placeholder_text_survives_the_cleaner(folder, tmp_path):
    """The placeholder adds words, so the copy guard must allow it through."""
    from app.profiles import DEFAULT_PROFILE_ID, load_profile
    from app.session import build_session

    html = '<p><img src="screenshot.png"></p>'
    report = plan_images(html, folder, "p")
    report = process_images(report, tmp_path / "out")
    updated, _ = replace_with_placeholders(html, report)

    session = build_session(updated, load_profile(DEFAULT_PROFILE_ID))
    assert "Image here: blog_p_01.webp" in session.cleaned_html
    assert session.counts["error"] == 0
    assert session.copy_preserved


# --------------------------------------------------------------------------
# Reported after processing a real post's images.
# --------------------------------------------------------------------------

def test_the_post_url_is_required():
    """Without it every file is called blog_post_01.webp."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/images",
        data={
            "source": '<p><img src="a.png"></p>',
            "history": "[]",
            "folder": "/tmp",
            "post_url": "",
            "tab": "images",
        },
    )
    assert response.status_code == 200
    assert "names every output file" in response.text
    # Nothing was processed.
    assert "Processed" not in response.text


def test_the_field_is_marked_required_in_the_form():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    page = client.post(
        "/analyse",
        data={"source_type": "html", "content": '<p><img src="a.png"></p>', "selector": ""},
    ).text
    form = BeautifulSoup(page, "html.parser").find("form", class_="image-form")
    assert form.find("input", {"name": "post_url"}).has_attr("required")


def test_images_can_be_processed_again(folder, tmp_path):
    """Reported: a second run said 0 images.

    The step used to substitute placeholders into the source and hand that back,
    so the next run had no <img> tags to find. The cleaner's own rule replaces
    them on every analysis, which made the substitution both redundant and
    destructive.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    out = tmp_path / "out"
    data = {
        "source": '<p><img src="screenshot.png"></p>',
        "history": "[]",
        "folder": str(folder),
        "post_url": "https://www.dyalog.com/blog/2026/01/a-post/",
        "output_folder": str(out),
        "tab": "images",
    }

    first = client.post("/images", data=data)
    assert "Processed 1 image(s)" in first.text

    # Again, over the top of the first run.
    second = client.post("/images", data={**data, "overwrite": "1"})
    assert "Processed 1 image(s)" in second.text
    assert "0 image(s)" not in second.text


def test_the_source_is_not_rewritten_by_processing(folder, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    source = '<p><img src="screenshot.png"></p>'
    page = client.post(
        "/images",
        data={
            "source": source,
            "history": "[]",
            "folder": str(folder),
            "post_url": "a-post",
            "output_folder": str(tmp_path / "out"),
            "tab": "images",
        },
    ).text
    form = BeautifulSoup(page, "html.parser").find("form", class_="image-form")
    # The form still carries the original HTML, so it can be run again.
    assert "img" in form.find("input", {"name": "source"})["value"]


def test_an_image_far_below_the_target_is_flagged(folder, tmp_path):
    """A 250px-wide file is usually a WordPress thumbnail, not the original."""
    small = Image.new("RGB", (250, 300), "white")
    small.save(folder / "thumb.png")

    report = plan_images('<p><img src="thumb.png"></p>', folder, "a-post")
    plan = report.plans[0]
    assert plan.undersize
    assert "250px wide" in plan.note
    assert "1200px target" in plan.note


def test_an_image_at_the_target_is_not_flagged(folder):
    report = plan_images('<p><img src="screenshot.png"></p>', folder, "a-post")
    assert not report.plans[0].undersize


def test_an_undersized_image_is_still_processed_at_its_own_size(folder, tmp_path):
    """Flagged, not dropped: whether to keep it is an editorial decision."""
    Image.new("RGB", (250, 300), "white").save(folder / "thumb.png")
    report = process_images(
        plan_images('<p><img src="thumb.png"></p>', folder, "a-post"), tmp_path / "out"
    )
    written = tmp_path / "out" / "blog_a-post_01.webp"
    assert written.exists()
    with Image.open(written) as result:
        assert result.size == (250, 300)


def test_the_sidecar_records_the_undersize_warning(folder, tmp_path):
    Image.new("RGB", (250, 300), "white").save(folder / "thumb.png")
    report = plan_images('<p><img src="thumb.png"></p>', folder, "a-post")
    text = sidecar_text(report, draft_all(report), "a-post")
    assert "WARNING" in text
    assert "250px wide" in text
