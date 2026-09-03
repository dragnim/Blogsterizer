from __future__ import annotations

from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


def profile():
    return load_profile(DEFAULT_PROFILE_ID)


def clean(html: str):
    return analyse_html(html, profile())


def test_external_target_blank_gets_ex_link_even_if_class_missing():
    result = clean('<a href="http://docs.dyalog.com/14.0/test.pdf" target="_blank" rel="noopener">PDF</a>')
    assert 'class="ex-link"' in result.cleaned_html
    assert result.copy_preserved


def test_external_link_without_target_gets_full_external_policy():
    result = clean('<a href="https://github.com/Dyalog/ride">RIDE</a>')
    assert 'class="ex-link"' in result.cleaned_html
    assert 'target="_blank"' in result.cleaned_html
    assert 'rel="noopener"' in result.cleaned_html
    assert result.copy_preserved


def test_protocol_relative_external_link_is_external():
    result = clean('<a href="//example.com/resource">Example</a>')
    assert 'class="ex-link"' in result.cleaned_html
    assert 'target="_blank"' in result.cleaned_html


def test_internal_dyalogprod_link_never_gets_ex_link_even_when_target_blank():
    result = clean('<a class="ex-link old" href="https://dyalogprod.gos.dyalog.com/file.pdf" target="_blank">File</a>')
    assert 'ex-link' not in result.cleaned_html
    assert 'old' in result.cleaned_html  # handoff 5.1: keep the existing class
    assert 'target="_blank"' in result.cleaned_html
    assert 'rel="noopener"' in result.cleaned_html


def test_internal_www_dyalog_page_does_not_get_external_class():
    result = clean('<a href="https://www.dyalog.com/products/test/">Dyalog page</a>')
    assert 'ex-link' not in result.cleaned_html
    assert 'target="_blank"' not in result.cleaned_html


def test_presentation_asset_is_rewritten_and_ex_link_removed():
    result = clean('''<a class="ex-link" href="https://www.dyalog.com/uploads/files/presentations/Test.pdf" target="_blank" rel="noopener">PDF</a>''')
    assert 'https://dyalogprod.gos.dyalog.com/uploads/files/presentations/Test.pdf' in result.cleaned_html
    assert 'ex-link' not in result.cleaned_html
    assert 'target="_blank"' in result.cleaned_html


def test_dyalog_tv_is_rewritten_to_youtube_and_gets_ex_link():
    result = clean('<a href="https://dyalog.tv/Webinar/?v=BSQr203sbWc">Video</a>')
    assert 'href="https://www.youtube.com/watch?v=BSQr203sbWc"' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html
    assert 'target="_blank"' in result.cleaned_html
    assert 'rel="noopener"' in result.cleaned_html


def test_fclear_and_editor_cruft_are_removed():
    # Handoff 4.1/4.3: known junk goes, the unrecognised "junk" class stays.
    result = clean('<p class="fclear code-line junk" dir="auto" style="color:red" align="left" data-id="123">Text</p>')
    assert result.cleaned_html == '<p class="junk">Text</p>'
    assert 'fclear' not in result.cleaned_html
    assert 'code-line' not in result.cleaned_html


def test_legacy_aplfont_becomes_inline_language_apl_code():
    result = clean('<p>Use <span class="APLFont">⍳</span>.</p>')
    assert result.cleaned_html == '<p>Use <code class="language-apl">⍳</code>.</p>'


def test_legacy_language_apl_span_becomes_code_not_span():
    result = clean('<p>Use <span class="language-apl">⎕JSON</span>.</p>')
    assert result.cleaned_html == '<p>Use <code class="language-apl">⎕JSON</code>.</p>'


def test_existing_unclassified_code_becomes_apl_code():
    result = clean('<p><code>X+0</code></p>')
    assert result.cleaned_html == '<p><code class="language-apl">X+0</code></p>'


def test_explicit_other_code_language_is_not_changed_to_apl():
    result = clean('<p><code class="language-python old">print(1)</code></p>')
    assert 'language-python' in result.cleaned_html
    assert 'language-apl' not in result.cleaned_html
    assert 'old' in result.cleaned_html  # handoff 4.3: unknown classes survive


def test_parenthesised_release_note_resource_gets_clean_layout_without_rewording_title():
    result = clean('''<ul><li>the release notes for Dyalog v19.0 (<a href="http://docs.dyalog.com/19.0/test.pdf" target="_blank" rel="noopener">PDF</a>)</li></ul>''')
    assert '<strong>the release notes for Dyalog v19.0</strong> – ' in result.cleaned_html
    assert '>Release notes (PDF)</a>' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html
    assert result.copy_preserved


def test_parenthesised_github_resource_gets_clean_layout():
    result = clean('''<ul><li>the release notes for Link v4.0 (<a href="https://dyalog.github.io/link/4.0/ReleaseNotes40/" target="_blank" rel="noopener">GitHub</a>)</li></ul>''')
    assert '<strong>the release notes for Link v4.0</strong> – ' in result.cleaned_html
    assert '>View on GitHub</a>' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html
    assert result.copy_preserved


def test_old_prefix_plus_icon_release_link_gets_title_action_layout():
    result = clean('''<ul><li>the <a href="http://docs.dyalog.com/18.2/test.pdf" target="_blank" rel="noopener">release notes for Dyalog v18.2 <img style="margin:0" src="pdf.svg" width="24" height="24"></a></li></ul>''')
    assert '<strong>the release notes for Dyalog v18.2</strong> – ' in result.cleaned_html
    assert '>Release notes (PDF)</a>' in result.cleaned_html
    assert '<img' not in result.cleaned_html
    assert result.copy_preserved


def test_standalone_pdf_icon_link_loses_icon_and_align_but_keeps_title():
    result = clean('''<p align="left"><a href="http://docs.dyalog.com/14.0/Compiler.pdf" target="_blank" rel="noopener"><img src="pdf.png" alt="" width="24" height="24"> Dyalog Experimental Functionality – Compiler</a></p>''')
    assert '<p><a class="ex-link"' in result.cleaned_html
    assert 'Dyalog Experimental Functionality – Compiler (PDF)</a></p>' in result.cleaned_html
    assert '<img' not in result.cleaned_html


def test_webinar_title_is_bold_resources_are_text_and_apl_is_code():
    html = '''
    <ul><li>Webinars:<ul>
      <li>Language Features of Dyalog version 18.0 in Depth (part 1)
        <a href="https://dyalog.tv/Webinar/?v=Hln3zryunsw"><img src="youtube.png"></a>
        <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pptx"><img src="ppt.png"></a>
        <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pdf"><img src="pdf.png"></a>
        explains <span class="APLFont">⎕C</span>.
      </li>
    </ul></li></ul>
    '''
    result = clean(html)
    assert '<strong>Language Features of Dyalog version 18.0 in Depth (part 1)</strong>' in result.cleaned_html
    assert '>Watch video</a>' in result.cleaned_html
    assert '>PowerPoint</a>' in result.cleaned_html
    assert '>PDF</a>' in result.cleaned_html
    assert 'https://www.youtube.com/watch?v=Hln3zryunsw' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html.split('watch?v=Hln3zryunsw')[0].rsplit('<a', 1)[-1]
    ppt_anchor = result.cleaned_html.split('Webinar_LangFeaturesV18.pptx')[0].rsplit('<a', 1)[-1]
    assert 'ex-link' not in ppt_anchor
    assert '<code class="language-apl">⎕C</code>' in result.cleaned_html
    assert result.copy_preserved


def test_internal_link_stays_plain_and_external_wikipedia_gets_ex_link():
    html = '''<p><a href="https://dyalogprod.gos.dyalog.com/products/dyalog-versions/16-0/">Dyalog v16.0</a> and <a href="https://en.wikipedia.org/wiki/Timsort">Timsort</a>.</p>'''
    result = clean(html)
    internal = result.cleaned_html.split('Dyalog v16.0')[0].rsplit('<a', 1)[-1]
    external = result.cleaned_html.split('Timsort')[0].rsplit('<a', 1)[-1]
    assert 'ex-link' not in internal
    assert 'ex-link' in external


def test_long_paragraph_is_flagged_not_rewritten():
    text = 'Sentence one. ' + ('A long paragraph sentence. ' * 40)
    html = f'<p>{text}</p>'
    result = clean(html)
    assert result.cleaned_html == html
    assert any(f.rule_id == 'PARAGRAPH-REVIEW-001' and not f.applied for f in result.findings)


def test_dyalog_profile_is_idempotent_across_thread_patterns():
    html = '''<p class="fclear code-line" dir="auto">Use <span class="APLFont">⎕JSON</span> and <a href="https://dyalog.tv/Webinar/?v=ABC123">watch it</a>.</p>'''
    first = clean(html)
    second = clean(first.cleaned_html)
    assert second.cleaned_html == first.cleaned_html


def test_profile_also_strips_code_line_and_dir_auto():
    from app.profiles import DEFAULT_PROFILE_ID, load_profile
    result = analyse_html('<p class="code-line" dir="auto"><span>Hello</span>, world</p>', load_profile(DEFAULT_PROFILE_ID))
    assert result.cleaned_html == '<p>Hello, world</p>'
    assert result.copy_preserved


def test_exact_blog_inline_code_example_is_apl_is_apl():
    html = '''<p>If we want to consider the case where a word in <code>words</code> isn't found in <code>Words</code>, we can append <code>0</code></p>'''
    result = clean(html)
    assert result.cleaned_html == '''<p>If we want to consider the case where a word in <code class="language-apl">words</code> isn't found in <code class="language-apl">Words</code>, we can append <code class="language-apl">0</code></p>'''
    assert result.copy_preserved


def test_blog_profile_removes_editor_code_line_and_marks_code_as_apl():
    from app.profiles import DEFAULT_PROFILE_ID, load_profile
    html = '<p class="code-line" dir="auto">Use <code class="code-line">words</code>.</p>'
    result = analyse_html(html, load_profile(DEFAULT_PROFILE_ID))
    assert result.cleaned_html == '<p>Use <code class="language-apl">words</code>.</p>'
    assert result.copy_preserved
