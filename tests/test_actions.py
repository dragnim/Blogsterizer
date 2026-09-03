"""Actions the user chooses to apply to individual findings.

Handoff 9: the app proposes and the human decides. Nothing here runs
automatically, and no action is allowed to change a word.
"""
from __future__ import annotations

import json

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.actions import ActionError, apply_action, suggest_split_offset
from app.engine import analyse_html
from app.main import app
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


def text_of(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


# --------------------------------------------------------------------------
# Nothing is automatic
# --------------------------------------------------------------------------

def test_findings_offering_an_action_are_still_not_applied():
    result = clean('<h1>Addendum</h1><p class="code-active-line">Text.</p>')
    actionable = [f for f in result.findings if f.action]
    assert actionable
    for finding in actionable:
        assert not finding.applied
        assert finding.severity.value in {"warning", "suggested"}
    # The document is untouched until the user asks.
    assert "<h1>Addendum</h1>" in result.cleaned_html
    assert "code-active-line" in result.cleaned_html


# --------------------------------------------------------------------------
# Individual actions
# --------------------------------------------------------------------------

def test_remove_class_action():
    html = '<p class="code-active-line">Text.</p>'
    updated, message = apply_action(html, "remove_class", {"class_name": "code-active-line"})
    assert updated == "<p>Text.</p>"
    assert "code-active-line" in message


def test_remove_class_keeps_other_classes():
    html = '<p class="code-active-line keep-me">Text.</p>'
    updated, _ = apply_action(html, "remove_class", {"class_name": "code-active-line"})
    assert 'class="keep-me"' in updated


def test_demote_heading_action():
    updated, message = apply_action(
        '<h1 id="addendum">Addendum</h1>', "demote_heading", {"tag": "h1", "index": 0}
    )
    assert '<h2 id="addendum">Addendum</h2>' in updated
    assert "Addendum" in message


def test_promote_bold_paragraph_action():
    updated, _ = apply_action(
        "<p><strong>Why Hash?</strong></p>", "promote_bold_paragraph", {"index": 0, "level": 3}
    )
    assert updated == "<h3>Why Hash?</h3>"


def test_split_paragraph_keeps_every_word():
    html = (
        "<p>Hashing smooths out this variability. Doing the same search on a hashed "
        "version shows this clearly.</p>"
    )
    updated, message = apply_action(html, "split_paragraph", {"index": 0, "offset": -1})
    assert updated.count("<p>") == 2
    assert text_of(updated) == text_of(html)
    assert "No words were changed" in message


def test_split_paragraph_does_not_cut_through_inline_markup():
    html = (
        "<p>We call these <code>Words</code> and <code>Freqs</code>. "
        "The task is to look up <code>words</code> in <code>Words</code>.</p>"
    )
    updated, _ = apply_action(html, "split_paragraph", {"index": 0, "offset": -1})
    soup = BeautifulSoup(updated, "html.parser")
    assert len(soup.find_all("p")) == 2
    assert len(soup.find_all("code")) == 4
    assert text_of(updated) == text_of(html)


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

def test_action_on_a_stale_index_is_refused():
    with pytest.raises(ActionError):
        apply_action("<p>Only one</p>", "demote_heading", {"tag": "h1", "index": 0})


def test_unknown_action_is_refused():
    with pytest.raises(ActionError):
        apply_action("<p>Text</p>", "delete_everything", {})


def test_promote_refuses_a_paragraph_that_is_not_all_bold():
    with pytest.raises(ActionError):
        apply_action(
            "<p>Some <strong>bold</strong> words</p>",
            "promote_bold_paragraph",
            {"index": 0, "level": 3},
        )


def test_no_action_changes_visible_copy():
    cases = [
        ('<p class="x">Text.</p>', "remove_class", {"class_name": "x"}),
        ("<h1>Title</h1>", "demote_heading", {"tag": "h1", "index": 0}),
        ("<p><strong>Heading</strong></p>", "promote_bold_paragraph", {"index": 0, "level": 3}),
        ("<p>One sentence. Two sentence here.</p>", "split_paragraph", {"index": 0, "offset": -1}),
    ]
    for html, action, params in cases:
        updated, _ = apply_action(html, action, params)
        assert text_of(updated) == text_of(html), action


def test_split_offset_is_minus_one_when_there_is_no_boundary():
    paragraph = BeautifulSoup("<p>one long clause with no sentence end</p>", "html.parser").p
    assert suggest_split_offset(paragraph) == -1


# --------------------------------------------------------------------------
# Through the interface
# --------------------------------------------------------------------------

def test_apply_endpoint_returns_a_refreshed_result():
    client = TestClient(app)
    analysis = client.post(
        "/analyse",
        data={"source_type": "html", "content": "<h1>Addendum</h1><p>Text.</p>", "selector": ""},
    )
    assert "SEO-H1-001" in analysis.text

    applied = client.post(
        "/apply",
        data={
            "source": "<h1>Addendum</h1><p>Text.</p>",
            "history": "[]",
            "action": "demote_heading",
            "params": json.dumps({"tag": "h1", "index": 0}),
        },
    )
    assert applied.status_code == 200
    assert "Applied:" in applied.text
    # The warning is gone because the document was re-analysed, not patched.
    assert "SEO-H1-001" not in applied.text


def test_apply_endpoint_reports_a_refused_action_without_losing_the_document():
    client = TestClient(app)
    response = client.post(
        "/apply",
        data={
            "source": "<p>Untouched text.</p>",
            "history": "[]",
            "action": "demote_heading",
            "params": json.dumps({"tag": "h1", "index": 3}),
        },
    )
    assert response.status_code == 200
    assert "could not be applied" in response.text
    assert "Untouched text." in response.text


def test_apply_buttons_render_for_actionable_findings():
    client = TestClient(app)
    response = client.post(
        "/analyse",
        data={
            "source_type": "html",
            "content": '<h1>Addendum</h1><p class="code-active-line"><strong>Why Hash?</strong></p>',
            "selector": "",
        },
    )
    assert response.text.count("finding-action") >= 2
    assert "Change to &lt;h2&gt;" in response.text


# --------------------------------------------------------------------------
# Duplicate id: proposed value, user override, validation
# --------------------------------------------------------------------------

def test_duplicate_id_offers_a_fix_on_every_occurrence():
    """Either side of the collision can be renamed, so the user picks."""
    result = clean(
        '<h2 id="distraction-1">Tangent #1</h2>'
        '<p id="distraction-1"><strong>Distraction #1</strong></p>'
    )
    findings = [f for f in result.findings if f.rule_id == "SEO-DUPLICATE-ID-001"]
    assert len(findings) == 2
    assert [f.action_params["occurrence"] for f in findings] == [0, 1]
    for finding in findings:
        assert finding.action == "set_id"
        assert finding.action_input_label == "New id"
        assert not finding.applied
    # Each suggestion is a slug of that element's own text.
    assert findings[0].action_input_default == "tangent-1"
    assert findings[1].action_input_default == "distraction-2"


def test_duplicate_id_finding_shows_what_it_collides_with():
    result = clean(
        '<h2 id="distraction-1">Tangent #1</h2>'
        '<p id="distraction-1"><strong>Distraction #1</strong></p>'
    )
    first, second = [f for f in result.findings if f.rule_id == "SEO-DUPLICATE-ID-001"]
    assert [o["position"] for o in first.related] == ["2"]
    assert "Distraction #1" in first.related[0]["text"]
    assert [o["position"] for o in second.related] == ["1"]
    assert "Tangent #1" in second.related[0]["text"]


def test_renaming_the_first_occurrence_is_flagged_as_the_riskier_choice():
    result = clean('<h2 id="dup">A</h2><p id="dup">B</p>')
    first, second = [f for f in result.findings if f.rule_id == "SEO-DUPLICATE-ID-001"]
    assert "break those links" in first.message
    assert "no link can currently reach" in second.message


def test_set_id_renames_only_the_later_occurrence():
    html = '<h2 id="dup">First</h2><p id="dup">Second</p>'
    updated, message = apply_action(
        html, "set_id", {"id": "dup", "occurrence": 1, "value": "second-section"}
    )
    soup = BeautifulSoup(updated, "html.parser")
    # Existing anchors pointing at #dup still reach the original element.
    assert soup.find("h2")["id"] == "dup"
    assert soup.find("p")["id"] == "second-section"
    assert "second-section" in message


def test_set_id_rejects_an_id_that_is_already_used():
    html = '<h2 id="dup">First</h2><p id="dup">Second</p><p id="taken">Third</p>'
    with pytest.raises(ActionError, match="already used"):
        apply_action(html, "set_id", {"id": "dup", "occurrence": 1, "value": "taken"})


def test_set_id_rejects_a_malformed_id():
    html = '<h2 id="dup">First</h2><p id="dup">Second</p>'
    for bad in ("has spaces", "9starts-with-a-digit", ""):
        with pytest.raises(ActionError):
            apply_action(html, "set_id", {"id": "dup", "occurrence": 1, "value": bad})


def test_set_id_changes_no_copy():
    html = '<h2 id="dup">First</h2><p id="dup">Second</p>'
    updated, _ = apply_action(html, "set_id", {"id": "dup", "occurrence": 1, "value": "other"})
    assert text_of(updated) == text_of(html)


def test_three_way_duplicate_offers_a_fix_for_every_occurrence():
    result = clean('<p id="x">A</p><p id="x">B</p><p id="x">C</p>')
    findings = [f for f in result.findings if f.rule_id == "SEO-DUPLICATE-ID-001"]
    assert len(findings) == 3
    assert [f.action_params["occurrence"] for f in findings] == [0, 1, 2]
    # Each one lists the other two.
    for finding in findings:
        assert len(finding.related) == 2


def test_every_warning_in_the_real_post_can_be_resolved():
    """Both warnings this post produces offer a fix."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "hashing-it-out.html"
    result = clean(fixture.read_text(encoding="utf-8"))
    warnings = [f for f in result.findings if f.severity.value == "warning"]
    assert warnings
    for finding in warnings:
        assert finding.action, f"{finding.rule_id} has no way to resolve it"


def test_apply_endpoint_accepts_a_user_supplied_value():
    client = TestClient(app)
    source = '<h2 id="dup">First</h2><p id="dup">Second</p>'
    response = client.post(
        "/apply",
        data={
            "source": source,
            "history": "[]",
            "action": "set_id",
            "params": json.dumps({"id": "dup", "occurrence": 1}),
            "value": "my-own-id",
        },
    )
    assert "Applied:" in response.text
    assert "SEO-DUPLICATE-ID-001" not in response.text
