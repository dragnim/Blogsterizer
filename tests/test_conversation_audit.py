from __future__ import annotations

from app.engine import analyse_html
from app.profiles import DEFAULT_PROFILE_ID, load_profile


PROFILE = load_profile(DEFAULT_PROFILE_ID)


def clean(html: str):
    return analyse_html(html, PROFILE)


def test_raw_apl_parentheses_stay_outside_code_for_single_primitive():
    result = clean('<p>grade up (⍋) and grade down (⍒).</p>')
    assert result.cleaned_html == (
        '<p>grade up (<code class="language-apl">⍋</code>) and '
        'grade down (<code class="language-apl">⍒</code>).</p>'
    )


def test_raw_apl_expression_parentheses_stay_inside_code_when_they_are_expression_syntax():
    result = clean('<p>Use (⊃⍋) or ⊃⍤⍋.</p>')
    assert '<code class="language-apl">(⊃⍋)</code>' in result.cleaned_html
    assert '<code class="language-apl">⊃⍤⍋</code>' in result.cleaned_html


def test_raw_apl_up_down_and_indexing_are_detected():
    result = clean('<p>Use X[↓I], ↑[], and ↑ if needed.</p>')
    assert '<code class="language-apl">X[↓I]</code>' in result.cleaned_html
    assert '<code class="language-apl">↑[]</code>' in result.cleaned_html
    # Handoff 3.5: detection must be conservative. A lone arrow in running prose
    # is ambiguous (it is also an ordinary typographic character), so it is
    # reported for review rather than marked up. A bracketed (↑) is still taken.
    assert '<code class="language-apl">↑</code>' not in result.cleaned_html
    assert any(finding.rule_id == "APL-AMBIGUOUS-001" for finding in result.findings)
    assert '<code class="language-apl">↑</code>' in clean("<p>take (↑) is useful</p>").cleaned_html


def test_raw_apl_user_commands_and_control_structures_are_detected():
    result = clean('<p>The ]LINK group, ]IN command, :Disposable and :For are mentioned.</p>')
    assert '<code class="language-apl">]LINK</code>' in result.cleaned_html
    assert '<code class="language-apl">]IN</code>' in result.cleaned_html
    assert '<code class="language-apl">:Disposable</code>' in result.cleaned_html
    assert '<code class="language-apl">:For</code>' in result.cleaned_html


def test_raw_apl_negative_numbers_with_apl_overbar_are_detected():
    result = clean('<p>Options include 1, ¯1 and ¯3.</p>')
    assert '>1<' not in result.cleaned_html  # plain ASCII 1 is not guessed as code
    assert '<code class="language-apl">¯1</code>' in result.cleaned_html
    assert '<code class="language-apl">¯3</code>' in result.cleaned_html


def test_span_language_apl_is_always_semantic_code():
    html = '<p>Use <span class="language-apl">⎕CSV</span> and <span class="language-apl">1200⌶</span>.</p>'
    result = clean(html)
    assert '<span class="language-apl">' not in result.cleaned_html
    assert '<code class="language-apl">⎕CSV</code>' in result.cleaned_html
    assert '<code class="language-apl">1200⌶</code>' in result.cleaned_html


def test_aplfont_is_always_semantic_code():
    html = '<p>Use <span class="APLFont">≢⍴</span>, <span class="APLFont">⊣/</span>, and <span class="APLFont">⊢/</span>.</p>'
    result = clean(html)
    assert 'APLFont' not in result.cleaned_html
    assert '<code class="language-apl">≢⍴</code>' in result.cleaned_html
    assert '<code class="language-apl">⊣/</code>' in result.cleaned_html
    assert '<code class="language-apl">⊢/</code>' in result.cleaned_html


def test_exact_bare_code_words_example_gets_language_apl_every_time():
    html = "<p>If we want to consider the case where a word in <code>words</code> isn't found in <code>Words</code>, we can append <code>0</code></p>"
    result = clean(html)
    assert result.cleaned_html.count('class="language-apl"') == 3
    assert '<code class="language-apl">words</code>' in result.cleaned_html
    assert '<code class="language-apl">Words</code>' in result.cleaned_html
    assert '<code class="language-apl">0</code>' in result.cleaned_html


def test_release_18_webinar_resources_follow_established_layout_and_link_policy():
    html = '''
    <ul><li>Webinars:<ul>
      <li>Introducing Dyalog version 18.0 <a href="https://dyalog.tv/Webinar/?v=BSQr203sbWc"><img src="youtube.png"></a> <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_IntroducingDyalogV18.zip"><img src="zip.png"></a></li>
      <li>Language Features of Dyalog version 18.0 in Depth (part 1) <a href="https://dyalog.tv/Webinar/?v=Hln3zryunsw"><img src="youtube.png"></a> <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pptx"><img src="ppt.png"></a> <a href="https://www.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pdf"><img src="pdf.png"></a> explains <span class="APLFont">⎕C</span>.</li>
    </ul></li></ul>
    '''
    result = clean(html)
    assert '<strong>Introducing Dyalog version 18.0</strong> – ' in result.cleaned_html
    assert 'href="https://www.youtube.com/watch?v=BSQr203sbWc"' in result.cleaned_html
    assert '>Watch video</a> | <a href="https://dyalogprod.gos.dyalog.com/uploads/files/presentations/Webinar_IntroducingDyalogV18.zip"' in result.cleaned_html
    assert '>Materials (ZIP)</a>' in result.cleaned_html
    assert '<strong>Language Features of Dyalog version 18.0 in Depth (part 1)</strong> – ' in result.cleaned_html
    assert '>Watch video</a> | <a href="https://dyalogprod.gos.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pptx"' in result.cleaned_html
    assert '>PowerPoint</a> | <a href="https://dyalogprod.gos.dyalog.com/uploads/files/presentations/Webinar_LangFeaturesV18.pdf"' in result.cleaned_html
    assert '>PDF</a> – explains <code class="language-apl">⎕C</code>.' in result.cleaned_html


def test_release_18_2_old_link_wrapped_icon_becomes_title_and_action():
    html = '''<ul><li>the <a href="http://docs.dyalog.com/18.2/Dyalog Version 18.2 Release Notes.pdf" target="_blank" rel="noopener">release notes for Dyalog v18.2 <img style="margin:0" title="PDF" src="pdf.svg" width="24" height="24"></a></li></ul>'''
    result = clean(html)
    assert '<strong>the release notes for Dyalog v18.2</strong> – ' in result.cleaned_html
    assert '>Release notes (PDF)</a>' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html
    assert '<img' not in result.cleaned_html


def test_release_17_1_icon_only_pdf_link_becomes_bold_title_and_action():
    html = '''<ul><li>The Dyalog v17.1 Release Notes <a href="http://docs.dyalog.com/17.1/Dyalog Version 17.1 Release Notes.pdf" target="_blank" rel="noopener"><img src="pdf.png" alt="" width="24" height="24"></a></li></ul>'''
    result = clean(html)
    assert '<strong>The Dyalog v17.1 Release Notes</strong> – ' in result.cleaned_html
    assert '>Release notes (PDF)</a>' in result.cleaned_html
    assert 'class="ex-link"' in result.cleaned_html


def test_release_17_link_user_command_converts_to_apl_code():
    html = '''<ul><li>The <span class="APLFont">]LINK</span> user command project can be found in <a href="https://github.com/Dyalog/link" target="_blank" rel="noopener">Dyalog's GitHub project</a></li></ul>'''
    result = clean(html)
    assert '<code class="language-apl">]LINK</code>' in result.cleaned_html
    assert '<a class="ex-link" href="https://github.com/Dyalog/link"' in result.cleaned_html


def test_internal_dyalog_link_stays_internal_but_wikipedia_becomes_external():
    html = '''<p><a href="https://dyalogprod.gos.dyalog.com/products/dyalog-versions/16-0/">Dyalog v16.0</a> and <a href="https://en.wikipedia.org/wiki/Timsort" target="_blank" rel="noopener">Timsort</a>.</p>'''
    result = clean(html)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(result.cleaned_html, "html.parser")
    anchors = soup.find_all("a")
    internal, external = anchors
    assert "ex-link" not in internal.get("class", [])
    assert internal.get("target") is None
    assert "ex-link" in external.get("class", [])
    assert external.get("target") == "_blank"


def test_old_editor_markup_is_stripped_from_paragraph_and_code():
    result = clean('<p class="code-line" dir="auto">Use <code class="code-line">words</code>.</p>')
    assert result.cleaned_html == '<p>Use <code class="language-apl">words</code>.</p>'


def test_dir_rtl_is_not_removed_as_editor_cruft():
    result = clean('<p dir="rtl">Text</p>')
    assert 'dir="rtl"' in result.cleaned_html


def test_copy_is_unchanged_for_normal_apl_markup_conversion():
    html = '<p>The functions <em>unique</em> (<span class="APLFont">∪</span>) and <em>unique mask</em> (<span class="APLFont">≠</span>) are related.</p>'
    result = clean(html)
    assert result.copy_preserved
    assert 'The functions' in result.cleaned_html
    assert 'are related.' in result.cleaned_html


def test_raw_apl_diamond_is_detected():
    result = clean('<p>Use A←B⋄C←D.</p>')
    assert '<code class="language-apl">A←B⋄C←D</code>' in result.cleaned_html


def test_mixed_thread_corpus_satisfies_core_output_invariants():
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    html = '''
    <div class="old-wrapper" data-builder="x">
      <p class="fclear code-line" dir="auto">Use <span class="APLFont">⎕JSON</span>, <code>words</code>, and <code>0</code>.</p>
      <p>Raw APL: grade up (⍋), <span class="language-apl">⎕DT</span>, ]LINK and :For.</p>
      <p><a href="https://github.com/Dyalog/ride">RIDE</a> <a class="ex-link" href="https://dyalogprod.gos.dyalog.com/products/test/">Internal</a></p>
      <p><a class="ex-link" href="https://www.dyalog.com/uploads/files/presentations/Test.pdf" target="_blank" rel="noopener">PDF</a></p>
      <ul><li>Webinars:<ul><li>Test webinar <a href="https://dyalog.tv/Webinar/?v=ABC123"><img src="youtube.png"></a></li></ul></li></ul>
    </div>
    '''
    result = clean(html)
    soup = BeautifulSoup(result.cleaned_html, "html.parser")

    assert "APLFont" not in result.cleaned_html
    assert "code-line" not in result.cleaned_html
    assert 'dir="auto"' not in result.cleaned_html
    assert "dyalog.tv" not in result.cleaned_html
    assert "https://www.dyalog.com/uploads/files/presentations/" not in result.cleaned_html

    for code in soup.find_all("code"):
        explicit = [name for name in code.get("class", []) if name.startswith("language-")]
        assert explicit, str(code)
        if explicit == ["language-apl"]:
            assert "language-apl" in code.get("class", [])

    internal_hosts = {"dyalogprod.gos.dyalog.com", "www.dyalog.com", "dyalog.com"}
    for anchor in soup.find_all("a", href=True):
        parsed = urlparse(anchor["href"])
        if parsed.scheme not in {"http", "https"}:
            continue
        is_internal = parsed.hostname in internal_hosts
        classes = anchor.get("class", [])
        if is_internal:
            assert "ex-link" not in classes, str(anchor)
        else:
            assert "ex-link" in classes, str(anchor)
            assert anchor.get("target") == "_blank", str(anchor)
            assert "noopener" in anchor.get("rel", []), str(anchor)

    assert result.copy_preserved


def test_bare_preformatted_code_block_is_wrapped_as_apl_code():
    result = clean('<pre>R←A+B\nR</pre>')
    assert result.cleaned_html == '<pre><code class="language-apl">R←A+B\nR</code></pre>'
    assert result.copy_preserved


def test_paragraph_length_threshold_catches_ride_example_that_was_manually_split():
    html = '''<p>Synchronised with the release of Dyalog v14.1 for Mac OS, the Remote Integrated Development Environment (RIDE) is now generally available under Microsoft Windows, Linux, and Mac OS. The RIDE can connect to Dyalog running on any supported execution platform and is the IDE of choice for Dyalog on Mac OS and Linux. The "classical" IDE remains the tool of choice for the development of Microsoft Windows applications, but the RIDE is also available for Windows for use as a front end for AIX or Linux servers – or as a remote debugger for Windows services.</p>'''
    result = clean(html)
    assert any(f.rule_id == 'PARAGRAPH-REVIEW-001' for f in result.findings)
    assert result.cleaned_html == html


def test_jarvis_external_link_gets_external_link_policy_without_changing_text():
    html = '<p>the <a href="https://github.com/Dyalog/Jarvis/wiki">Jarvis Framework</a>.</p>'
    result = clean(html)
    assert '<a class="ex-link" href="https://github.com/Dyalog/Jarvis/wiki" rel="noopener" target="_blank">Jarvis Framework</a>' in result.cleaned_html
    assert result.export_safe
