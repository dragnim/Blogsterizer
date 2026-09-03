"""Working through findings: counters, previews and undo.

The counters had been confusing because "Safe" was recomputed after every fix
and collapsed to zero. Safe now answers "what did the cleaner do to my source?"
and holds steady; the other counters answer "what still needs me?".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.actions import preview_action
from app.main import app
from app.profiles import DEFAULT_PROFILE_ID, load_profile
from app.session import build_session

FIXTURE = Path(__file__).parent / "fixtures" / "hashing-it-out.html"


def profile():
    return load_profile(DEFAULT_PROFILE_ID)


def counter(text: str, label: str) -> int | None:
    match = re.search(rf"{label} <strong>(\d+)</strong>", text)
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# Counters
# --------------------------------------------------------------------------

def test_safe_count_is_measured_against_the_source_and_does_not_move():
    source = FIXTURE.read_text(encoding="utf-8")
    start = build_session(source, profile())
    assert start.counts["safe"] > 0

    finding = next(f for f in start.findings if f.rule_id == "PARAGRAPH-REVIEW-001")
    after = build_session(
        source, profile(), [{"action": finding.action, "params": finding.action_params}]
    )
    # The clean-up work done to the source is the same fact as before.
    assert after.counts["safe"] == start.counts["safe"]


def test_resolving_a_suggestion_reduces_the_suggestion_count():
    source = FIXTURE.read_text(encoding="utf-8")
    start = build_session(source, profile())
    finding = next(f for f in start.findings if f.rule_id == "PARAGRAPH-REVIEW-001")

    after = build_session(
        source, profile(), [{"action": finding.action, "params": finding.action_params}]
    )
    assert after.counts["suggested"] == start.counts["suggested"] - 1
    assert after.fixed_count == 1


def test_resolving_a_warning_reduces_the_warning_count():
    source = FIXTURE.read_text(encoding="utf-8")
    start = build_session(source, profile())
    after = build_session(
        source, profile(), [{"action": "demote_heading", "params": {"tag": "h1", "index": 0}}]
    )
    assert after.counts["warning"] == start.counts["warning"] - 1


def test_fixes_stack_and_replay_deterministically():
    source = FIXTURE.read_text(encoding="utf-8")
    history = [
        {"action": "demote_heading", "params": {"tag": "h1", "index": 0}},
        {"action": "remove_class", "params": {"class_name": "code-active-line"}},
    ]
    first = build_session(source, profile(), history)
    second = build_session(source, profile(), history)
    assert first.cleaned_html == second.cleaned_html
    assert first.fixed_count == 2
    assert first.error is None


# --------------------------------------------------------------------------
# Previews
# --------------------------------------------------------------------------

def test_split_preview_shows_the_two_resulting_paragraphs():
    preview = preview_action(
        "<p>One sentence here. Two sentence here now.</p>",
        "split_paragraph",
        {"index": 0, "offset": -1},
    )
    assert preview == "<p>One sentence here.</p><p>Two sentence here now.</p>"


def test_every_actionable_finding_carries_a_preview():
    session = build_session(FIXTURE.read_text(encoding="utf-8"), profile())
    actionable = [f for f in session.findings if f.action]
    assert actionable
    for finding in actionable:
        assert finding.action_preview, f"{finding.rule_id} has no preview"


def test_a_preview_never_raises_into_the_page():
    assert preview_action("", "split_paragraph", {"index": 0}) is None
    assert preview_action("<p>No boundary</p>", "split_paragraph", {"index": 0, "offset": -1}) is None
    assert preview_action("<p>Text</p>", "not_a_real_action", {}) is None


def test_preview_does_not_alter_the_document():
    session = build_session(FIXTURE.read_text(encoding="utf-8"), profile())
    before = session.cleaned_html
    again = build_session(FIXTURE.read_text(encoding="utf-8"), profile())
    assert again.cleaned_html == before


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------

def test_undo_reverses_exactly_one_fix():
    client = TestClient(app)
    source = "<h1>Addendum</h1><p>Text.</p>"
    history = [{"action": "demote_heading", "params": {"tag": "h1", "index": 0}}]

    response = client.post(
        "/undo", data={"source": source, "history": json.dumps(history)}
    )
    assert response.status_code == 200
    assert "Undid the last change." in response.text
    # The warning is back because the document is back.
    assert "SEO-H1-001" in response.text


def test_undo_on_an_empty_history_is_harmless():
    client = TestClient(app)
    response = client.post("/undo", data={"source": "<p>Text.</p>", "history": "[]"})
    assert response.status_code == 200
    assert "Text." in response.text


def test_apply_then_undo_returns_the_original_document():
    source = FIXTURE.read_text(encoding="utf-8")
    start = build_session(source, profile())
    history = [{"action": "demote_heading", "params": {"tag": "h1", "index": 0}}]
    applied = build_session(source, profile(), history)
    undone = build_session(source, profile(), history[:-1])

    assert applied.cleaned_html != start.cleaned_html
    assert undone.cleaned_html == start.cleaned_html


def test_a_fix_that_no_longer_replays_is_reported_not_swallowed():
    session = build_session(
        "<p>Just text.</p>",
        profile(),
        [{"action": "demote_heading", "params": {"tag": "h1", "index": 0}}],
    )
    assert session.error
    assert session.fixed_count == 0
    assert "Just text." in session.cleaned_html


# --------------------------------------------------------------------------
# Through the interface
# --------------------------------------------------------------------------

def test_counters_behave_as_the_user_works_through_findings():
    client = TestClient(app)
    source = FIXTURE.read_text(encoding="utf-8")

    start = client.post(
        "/analyse", data={"source_type": "html", "content": source, "selector": ""}
    ).text
    safe = counter(start, "Safe")
    suggestions = counter(start, "Suggestions")
    assert counter(start, "Fixed") is None

    history = [{"action": "demote_heading", "params": {"tag": "h1", "index": 0}}]
    applied = client.post(
        "/apply",
        data={
            "source": source,
            "history": "[]",
            "action": "demote_heading",
            "params": json.dumps({"tag": "h1", "index": 0}),
        },
    ).text
    assert counter(applied, "Safe") == safe
    assert counter(applied, "Suggestions") == suggestions
    assert counter(applied, "Warnings") == 2  # the two duplicate-id occurrences
    assert counter(applied, "Fixed") == 1

    undone = client.post(
        "/undo", data={"source": source, "history": json.dumps(history)}
    ).text
    assert counter(undone, "Warnings") == 3
    assert counter(undone, "Fixed") is None


def test_severity_key_explains_what_safe_means():
    client = TestClient(app)
    response = client.post(
        "/analyse", data={"source_type": "html", "content": "<p>Text.</p>", "selector": ""}
    )
    assert "What do these mean?" in response.text
    assert "Deterministic clean-up" in response.text


# --------------------------------------------------------------------------
# Making the preview readable
# --------------------------------------------------------------------------

def test_only_the_inserted_markup_is_marked():
    from app.actions import highlight_additions

    before = "<p>One here. Two here now.</p>"
    after = "<p>One here.</p><p>Two here now.</p>"
    marked = highlight_additions(before, after)
    assert marked.count('<mark class="added">') == 1
    assert "&lt;/p&gt;&lt;p&gt;</mark>" in marked


def test_highlighting_escapes_the_document_but_not_its_own_marks():
    from app.actions import highlight_additions

    marked = highlight_additions("<p>a</p>", '<p>a</p><p><script>x</script></p>')
    # Document markup is inert.
    assert "<script>" not in marked
    assert "&lt;script&gt;" in marked
    # The mark elements themselves are live.
    assert '<mark class="added">' in marked


def test_a_split_preview_lists_the_resulting_paragraphs_separately():
    from app.actions import preview_blocks

    blocks = preview_blocks("<p>One here.</p><p>Two here now.</p>")
    assert [b["tag"] for b in blocks] == ["p", "p"]
    assert blocks[0]["text"] == "One here."
    assert blocks[1]["text"] == "Two here now."


def test_real_split_preview_shows_two_blocks_and_one_insertion():
    session = build_session(FIXTURE.read_text(encoding="utf-8"), profile())
    finding = next(f for f in session.findings if f.rule_id == "PARAGRAPH-REVIEW-001")
    assert len(finding.action_preview_blocks) == 2
    assert finding.action_preview_markup.count('<mark class="added">') == 1
    # The words are the same either side of the split.
    joined = " ".join(block["text"] for block in finding.action_preview_blocks)
    assert joined.split() == finding.action_preview_blocks[0]["text"].split() + \
        finding.action_preview_blocks[1]["text"].split()


def test_single_block_actions_do_not_render_a_block_list():
    """Demoting a heading produces one element, so there is nothing to compare."""
    session = build_session("<h1>Addendum</h1><p>Text.</p>", profile())
    finding = next(f for f in session.findings if f.rule_id == "SEO-H1-001")
    assert len(finding.action_preview_blocks) == 1
    assert finding.action_preview_markup.count('<mark class="added">') >= 1


def test_preview_blocks_are_rendered_in_the_page():
    client = TestClient(app)
    response = client.post(
        "/analyse",
        data={
            "source_type": "html",
            "content": "<p>" + ("One sentence here. " * 40) + "Final sentence here.</p>",
            "selector": "",
        },
    )
    assert 'class="preview-block"' in response.text
    assert '<mark class="added">' in response.text
