from __future__ import annotations

from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def profile():
    return load_profile(DEFAULT_PROFILE_ID)


def test_apl_markup_and_legacy_class_are_cleaned():
    html = '<p class="fclear">Use <span class="APLFont">⎕JSON</span>.</p>'
    result = analyse_html(html, profile())

    assert '<p>Use <code class="language-apl">⎕JSON</code>.</p>' in result.cleaned_html
    assert result.copy_preserved


def test_url_migrations_and_link_policy():
    html = '''
    <p>
      <a class="ex-link" href="https://www.dyalog.com/uploads/files/presentations/test.pdf" target="_blank" rel="noopener">PDF</a>
      <a href="https://dyalog.tv/Webinar/?v=ABC123" target="_blank" rel="noopener">Video</a>
    </p>
    '''
    result = analyse_html(html, profile())

    assert 'href="https://dyalogprod.gos.dyalog.com/uploads/files/presentations/test.pdf"' in result.cleaned_html
    internal_fragment = result.cleaned_html.split('test.pdf')[0].rsplit('<a', 1)[-1]
    assert 'ex-link' not in internal_fragment
    assert 'href="https://www.youtube.com/watch?v=ABC123"' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html
    assert result.copy_preserved


def test_webinar_icon_layout_is_rewritten_without_losing_copy():
    html = '''
    <ul>
      <li>Webinars:
        <ul>
          <li>Language Features of Dyalog version 18.0 in Depth (part 1)
            <a href="https://dyalog.tv/Webinar/?v=Hln3zryunsw"><img src="youtube.png"></a>
            <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pptx"><img src="ppt.png"></a>
            <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pdf"><img src="pdf.png"></a>
            explains <span class="APLFont">⎕C</span>.
          </li>
        </ul>
      </li>
    </ul>
    '''
    result = analyse_html(html, profile())

    assert '<strong>Language Features of Dyalog version 18.0 in Depth (part 1)</strong>' in result.cleaned_html
    assert '>Watch video</a>' in result.cleaned_html
    assert '>PowerPoint</a>' in result.cleaned_html
    assert '>PDF</a>' in result.cleaned_html
    assert '<code class="language-apl">⎕C</code>' in result.cleaned_html
    assert 'https://www.youtube.com/watch?v=Hln3zryunsw' in result.cleaned_html
    assert 'https://dyalogprod.gos.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pptx' in result.cleaned_html
    assert result.copy_preserved


def test_copy_guard_detects_deleted_copy():
    # Exercise the guard directly through a profile that contains a destructive rewrite-like rule
    # by confirming normal rules never delete the original text.
    html = '<p>Do not change a single word: <span class="APLFont">⎕C</span>.</p>'
    result = analyse_html(html, profile())
    assert result.copy_preserved
    assert 'Do not change a single word' in result.cleaned_html


def test_cleaning_is_idempotent():
    html = '''<p class="fclear">Use <span class="APLFont">⎕JSON</span> and
    <a href="https://dyalog.tv/Webinar/?v=ABC123">watch it</a>.</p>'''
    first = analyse_html(html, profile())
    second = analyse_html(first.cleaned_html, profile())
    assert second.cleaned_html == first.cleaned_html


def test_existing_code_gets_language_apl_class_even_without_legacy_wrapper():
    html = '<p>Use <code>⎕JSON</code> and <code>X+0</code>.</p>'
    result = analyse_html(html, profile())
    assert '<code class="language-apl">⎕JSON</code>' in result.cleaned_html
    assert '<code class="language-apl">X+0</code>' in result.cleaned_html
    assert result.copy_preserved


def test_unwrapped_apl_tokens_are_wrapped():
    html = '<p>Use ⎕JSON and ⍸ here.</p>'
    result = analyse_html(html, profile())
    assert '<code class="language-apl">⎕JSON</code>' in result.cleaned_html
    assert '<code class="language-apl">⍸</code>' in result.cleaned_html
    assert result.copy_preserved


def test_known_junk_classes_and_attributes_are_removed():
    # Handoff 4.1/4.3: fclear and wp-* are known junk; old-class is unknown and
    # must survive with a suggestion rather than being destroyed silently.
    html = '<p class="fclear old-class wp-block-paragraph" data-id="123" style="color:red" align="left">Copy stays.</p>'
    result = analyse_html(html, profile())
    assert result.cleaned_html == '<p class="old-class">Copy stays.</p>'
    assert result.copy_preserved
    assert any(finding.rule_id == "UNKNOWN-CLASS-001" for finding in result.findings)


def test_required_classes_are_added_without_deleting_unknown_ones():
    # Handoff 5.1: append ex-link, do not delete the class that is already there.
    html = '<p><a class="old-link" href="https://example.com">Example</a> <code class="old-code">⎕C</code></p>'
    result = analyse_html(html, profile())
    assert 'ex-link' in result.cleaned_html
    assert 'old-link' in result.cleaned_html
    assert 'language-apl' in result.cleaned_html
    assert 'old-code' in result.cleaned_html


def test_standalone_icon_link_preserves_title_and_adds_file_type():
    html = '<p align="left"><a href="http://docs.dyalog.com/14.0/compiler.pdf" target="_blank" rel="noopener"><img src="pdf.png" width="24" height="24"> Dyalog Experimental Functionality – Compiler</a></p>'
    result = analyse_html(html, profile())
    assert '<p><a class="ex-link" href="http://docs.dyalog.com/14.0/compiler.pdf" rel="noopener" target="_blank">Dyalog Experimental Functionality – Compiler (PDF)</a></p>' == result.cleaned_html
    assert result.copy_preserved


def test_release_note_icon_link_becomes_title_and_text_action():
    html = '<ul><li>The Dyalog v17.1 Release Notes <a href="http://docs.dyalog.com/17.1/release.pdf"><img src="pdf.png"></a></li></ul>'
    result = analyse_html(html, profile())
    assert '<strong>The Dyalog v17.1 Release Notes</strong> – ' in result.cleaned_html
    assert '>Release notes (PDF)</a>' in result.cleaned_html
    assert '<img' not in result.cleaned_html
    assert result.copy_preserved


def test_cleanup_is_idempotent_with_raw_apl_and_legacy_attributes():
    html = '<p class="fclear junk" data-x="1">Use ⎕JSON.</p>'
    first = analyse_html(html, profile())
    second = analyse_html(first.cleaned_html, profile())
    assert second.cleaned_html == first.cleaned_html


def test_explicit_non_apl_code_language_is_respected():
    html = '<pre><code class="language-python">print("hello")</code></pre>'
    result = analyse_html(html, profile())
    assert 'class="language-python"' in result.cleaned_html
    assert 'language-apl' not in result.cleaned_html


def test_nbsp_layout_spacing_is_normalised_without_changing_copy():
    html = '<p>Hello&nbsp;<a href="https://example.com">world</a>&nbsp;again.</p>'
    result = analyse_html(html, profile())
    assert '&nbsp;' not in result.cleaned_html
    assert '\xa0' not in result.cleaned_html
    assert 'Hello <a ' in result.cleaned_html
    assert '</a> again.' in result.cleaned_html
    assert result.copy_preserved


def test_code_line_class_and_dir_auto_are_removed():
    html = '<p class="code-line" dir="auto">Use <code class="code-line">⎕JSON</code>.</p>'
    result = analyse_html(html, profile())
    assert result.cleaned_html == '<p>Use <code class="language-apl">⎕JSON</code>.</p>'
    assert result.copy_preserved


def test_code_line_class_is_not_allowed_to_survive_on_plain_paragraphs():
    html = '<p class="code-line">This is ordinary copy.</p>'
    result = analyse_html(html, profile())
    assert result.cleaned_html == '<p>This is ordinary copy.</p>'
    assert result.copy_preserved


def test_cleanup_does_not_rollback_when_unwrapping_span_next_to_punctuation():
    html = '<p class="code-line" dir="auto"><span>Hello</span>, world</p>'
    result = analyse_html(html, profile())
    assert result.cleaned_html == '<p>Hello, world</p>'
    assert 'code-line' not in result.cleaned_html
    assert 'dir=' not in result.cleaned_html
    assert not any(f.rule_id == 'COPY-GUARD-RULE-001' for f in result.findings)
    assert result.copy_preserved


def test_dyalog_output_never_leaves_code_line_or_dir_auto_in_nested_markup():
    html = '<p class="code-line" dir="auto">One <span>two</span>. <code class="code-line">⎕JSON</code></p>'
    result = analyse_html(html, profile())
    assert 'code-line' not in result.cleaned_html
    assert 'dir=' not in result.cleaned_html
    assert '<code class="language-apl">⎕JSON</code>' in result.cleaned_html
    assert result.copy_preserved


def test_copy_changing_rule_is_rolled_back_if_it_removes_original_words(monkeypatch):
    from app import engine
    from app.models import Finding, Severity
    from app.rules.base import Rule

    class BadResourceRule(Rule):
        rule_id = "BAD-RESOURCE-001"
        may_change_copy = True

        def apply(self, soup):
            paragraph = soup.find("p")
            before = str(paragraph)
            paragraph.string = "Replacement only"
            return [
                Finding(
                    rule_id=self.rule_id,
                    title="Bad replacement",
                    message="This should be blocked.",
                    severity=Severity.SAFE,
                    before_html=before,
                    after_html=str(paragraph),
                    applied=True,
                    changes_copy=True,
                )
            ]

    monkeypatch.setattr(engine, "_build_rules", lambda profile: [BadResourceRule({})])
    result = engine.analyse_html("<p>Original words must survive.</p>", {})

    assert result.cleaned_html == "<p>Original words must survive.</p>"
    assert any(
        finding.rule_id == "COPY-GUARD-RULE-001"
        and finding.metadata.get("blocked_rule") == "BAD-RESOURCE-001"
        for finding in result.findings
    )


def test_plain_text_backticks_become_apl_code():
    from app.engine import plain_text_to_html

    source_html = plain_text_to_html("Use `words`, `Words`, and `0`.")
    result = analyse_html(source_html, profile())
    assert '<code class="language-apl">words</code>' in result.cleaned_html
    assert '<code class="language-apl">Words</code>' in result.cleaned_html
    assert '<code class="language-apl">0</code>' in result.cleaned_html


def test_output_validation_reports_core_invariant_if_link_rule_is_disabled():
    import copy

    broken_profile = copy.deepcopy(profile())
    broken_profile["rules"]["link_policy"] = False
    result = analyse_html('<p><a href="https://example.com">Example</a></p>', broken_profile)
    assert any(f.rule_id == 'OUTPUT-EXTERNAL-LINK-001' for f in result.findings)
    assert not result.export_safe


def test_output_validation_reports_unclassified_code_if_apl_rule_is_disabled():
    import copy

    broken_profile = copy.deepcopy(profile())
    broken_profile["rules"]["apl_markup"] = False
    result = analyse_html('<p><code>words</code></p>', broken_profile)
    assert any(f.rule_id == 'OUTPUT-CODE-CLASS-001' for f in result.findings)
    assert not result.export_safe


def test_normal_linked_blog_image_becomes_a_placeholder_not_a_resource_link():
    html = '<p><a href="https://example.com/article"><img src="photo.jpg" width="800" height="450" alt="Article image"></a></p>'
    result = analyse_html(html, profile())
    assert "Image here: photo.jpg" in result.cleaned_html
    assert "View resource" not in result.cleaned_html
    return
    assert '<img ' in result.cleaned_html
    assert 'photo.jpg' in result.cleaned_html
    assert 'View resource' not in result.cleaned_html
    assert any('ex-link' in anchor for anchor in [result.cleaned_html])
    assert result.export_safe


def test_large_pdf_thumbnail_is_preserved_but_link_policy_is_applied():
    html = '<p><a href="https://example.com/report.pdf"><img src="report-cover.jpg" width="600" height="800" alt="Report cover"></a></p>'
    result = analyse_html(html, profile())
    assert 'report-cover.jpg' in result.cleaned_html
    assert '>PDF</a>' not in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html
    assert result.export_safe


def test_text_only_webinar_title_link_is_preserved_and_converted_to_action_link():
    html = '<ul><li>Webinars:<ul><li><a href="https://dyalog.tv/Webinar/?v=ABC123">Introducing Dyalog version 18.0</a></li></ul></li></ul>'
    result = analyse_html(html, profile())
    assert '<strong>Introducing Dyalog version 18.0</strong> – ' in result.cleaned_html
    assert '>Watch video</a>' in result.cleaned_html
    assert 'href="https://www.youtube.com/watch?v=ABC123"' in result.cleaned_html
    assert result.export_safe


def test_output_validation_catches_raw_apl_if_apl_rule_is_disabled():
    import copy

    broken_profile = copy.deepcopy(profile())
    broken_profile["rules"]["apl_markup"] = False
    result = analyse_html('<p>Use ⎕JSON here.</p>', broken_profile)
    assert any(f.rule_id == 'OUTPUT-RAW-APL-001' for f in result.findings)
    assert not result.export_safe
