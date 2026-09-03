"""SEO and structure checks.

Inputs are taken verbatim from the "Hashing It Out: Lookup Performance in
Dyalog APL" post. Every check here is report-only: handoff 10 says editorial
matters are Warnings, never automatic fixes.
"""
from __future__ import annotations

from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


def rule_ids(result, rule_id: str):
    return [f for f in result.findings if f.rule_id == rule_id]


def test_h1_in_the_body_is_flagged():
    result = clean('<h1 id="addendum" class="code-line">Addendum</h1>')
    findings = rule_ids(result, "SEO-H1-001")
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"
    assert "Addendum" in findings[0].message


def test_h1_is_reported_but_never_rewritten():
    """Changing a heading level is an editorial decision, not a safe fix."""
    result = clean("<h1>Addendum</h1>")
    assert "<h1>Addendum</h1>" in result.cleaned_html
    assert "<h2" not in result.cleaned_html
    assert all(not f.applied for f in rule_ids(result, "SEO-H1-001"))


def test_h2_only_document_raises_no_h1_warning():
    result = clean("<h2>Background and Original Goal</h2><p>Text.</p>")
    assert rule_ids(result, "SEO-H1-001") == []


def test_bold_paragraph_used_as_a_heading_is_suggested():
    result = clean('<p id="why-hash" class="code-line"><strong>Why Hash?</strong></p>')
    findings = rule_ids(result, "SEO-FAKE-HEADING-001")
    assert len(findings) == 1
    assert findings[0].severity.value == "suggested"


def test_bold_inside_a_sentence_is_not_a_fake_heading():
    result = clean("<p>Once we have a retained hash table, <strong>all</strong> lookups are faster.</p>")
    assert rule_ids(result, "SEO-FAKE-HEADING-001") == []


def test_duplicate_id_is_flagged_on_each_occurrence():
    result = clean(
        '<h2 id="distraction-1">Tangent #1</h2>'
        '<p id="distraction-1"><strong>Distraction #1</strong></p>'
    )
    findings = rule_ids(result, "SEO-DUPLICATE-ID-001")
    assert len(findings) == 2
    assert all("distraction-1" in f.message for f in findings)


def test_unique_ids_are_not_flagged():
    result = clean('<h2 id="one">A</h2><h2 id="two">B</h2>')
    assert rule_ids(result, "SEO-DUPLICATE-ID-001") == []


def test_skipped_heading_level_is_suggested():
    result = clean("<h2>Section</h2><h4>Subsection</h4>")
    assert len(rule_ids(result, "SEO-HEADING-ORDER-001")) == 1


def test_sequential_heading_levels_are_fine():
    result = clean("<h2>Section</h2><h3>Sub</h3><h2>Next</h2>")
    assert rule_ids(result, "SEO-HEADING-ORDER-001") == []


def test_missing_alt_is_flagged_but_empty_alt_is_not():
    missing = clean('<p><img src="/a.jpg" width="800" height="600"></p>')
    decorative = clean('<p><img src="/a.jpg" alt="" width="800" height="600"></p>')
    assert len(rule_ids(missing, "SEO-IMG-ALT-001")) == 1
    assert rule_ids(decorative, "SEO-IMG-ALT-001") == []


def test_vague_link_text_is_suggested():
    vague = clean('<p>See <a href="https://example.org/">click here</a>.</p>')
    descriptive = clean('<p>See the <a href="https://example.org/">raw data file</a>.</p>')
    assert len(rule_ids(vague, "SEO-LINK-TEXT-001")) == 1
    assert rule_ids(descriptive, "SEO-LINK-TEXT-001") == []


def test_seo_checks_never_change_the_html_or_the_copy():
    source = (
        '<h1 id="addendum">Addendum</h1>'
        '<p id="addendum"><strong>Why Hash?</strong></p>'
        '<h4>Skipped</h4>'
        '<p><img src="/a.jpg"></p>'
        '<p><a href="https://example.org/">click here</a></p>'
    )
    result = clean(source)
    # Every SEO finding is advisory.
    seo = [f for f in result.findings if f.rule_id.startswith("SEO-")]
    assert seo
    assert all(not f.applied for f in seo)
    assert all(f.severity.value in {"warning", "suggested"} for f in seo)
    assert result.copy_preserved
    # The headings and elements themselves are untouched.
    assert "<h1" in result.cleaned_html
    assert "<h4" in result.cleaned_html
    assert "click here" in result.cleaned_html


def test_real_post_structure_reports_the_expected_issues():
    """The structural problems actually present in the Dyalog hashing post."""
    source = (
        '<h2 id="distraction-1" class="code-line">Tangent #1 – ⎕CSV</h2>'
        '<p id="distraction-1" class="code-line"><strong>Distraction #1</strong></p>'
        '<p id="why-hash" class="code-line"><strong>Why Hash?</strong></p>'
        '<h1 id="addendum" class="code-line">Addendum</h1>'
        '<h2 id="lookups-are-complicated" class="code-line">Lookups are Complicated</h2>'
    )
    result = clean(source)
    assert len(rule_ids(result, "SEO-H1-001")) == 1
    assert len(rule_ids(result, "SEO-FAKE-HEADING-001")) == 2
    assert len(rule_ids(result, "SEO-DUPLICATE-ID-001")) == 2
    assert result.copy_preserved
    assert result.counts["error"] == 0
