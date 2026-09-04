"""Not every code sample in a Dyalog post is APL.

Handoff section 3.2 makes unclassified `<code>` APL, which was right for the old
release pages. Newer posts mix in shell, CLI flags and other languages, and
labelling those `language-apl` makes the site's highlighter render bash as APL.

The detection is evidence-based: strong evidence of something else, not an
attempt to identify the language. Without such evidence, code is still APL.
"""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.actions import ActionError, apply_action
from app.engine import analyse_html, strip_caption_shortcodes
from app.profiles import DEFAULT_PROFILE_ID, load_profile
from app.rules.apl_markup import guess_language, non_apl_evidence


def clean(html: str):
    return analyse_html(html, load_profile(DEFAULT_PROFILE_ID))


def classes_of(html: str) -> list[list[str] | None]:
    soup = BeautifulSoup(html, "html.parser")
    return [code.get("class") for code in soup.find_all("code")]


# --------------------------------------------------------------------------
# What counts as evidence
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "~/work/tmp  $ git clone git@github.com:dyalog-labs/agent-dev-container.git",
        "$ npm install",
        "#!/usr/local/bin/dyalogscript",
        "--dangerously-skip-permissions",
        "docker run -it ubuntu",
        "def main(argv):",
        'print("hello")',
        "const x = () => 1",
        "if (a && b) { return 1; }",
        '<div class="x">text</div>',
        "script.py",
    ],
)
def test_these_are_recognised_as_not_apl(text):
    assert non_apl_evidence(text) is not None, text


@pytest.mark.parametrize(
    "text",
    [
        "Words",
        "Freqs[Words \u2373 words]",
        "A\u21901 2 3",
        "\u2395JSON",
        "1500\u2336",
        "]RunTime -c \"Words\u2373'the'\"",   # a user command, despite the flag
        "0",
    ],
)
def test_these_are_still_treated_as_apl(text):
    assert non_apl_evidence(text) is None, text


def test_an_apl_glyph_settles_it_even_alongside_shell():
    """A shell transcript that prints APL output still contains APL."""
    assert non_apl_evidence("dyalogscript /dev/stdin <<'APL'\n\u2395\u21902+2\nAPL") is None


def test_the_suggested_language_is_a_starting_point():
    assert guess_language("$ git clone x") == "language-bash"
    assert guess_language("--dangerously-skip-permissions") == "language-bash"
    assert guess_language("def main():") == "language-python"
    assert guess_language("const x = () => 1") == "language-javascript"
    assert guess_language('<div class="x">t</div>') == "language-html"


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

def test_a_shell_block_is_not_labelled_apl():
    result = clean(
        "<pre><code>~/work/tmp  $ git clone git@github.com:dyalog-labs/x.git\n"
        "Cloning into 'x'...</code></pre>"
    )
    assert "language-apl" not in result.cleaned_html
    finding = next(f for f in result.findings if f.rule_id == "APL-NOT-APL-001")
    assert finding.severity.value == "suggested"
    assert finding.metadata["suggested"] == "language-bash"


def test_a_cli_flag_is_not_labelled_apl():
    result = clean("<p>Enable <code>--dangerously-skip-permissions</code> mode.</p>")
    assert "language-apl" not in result.cleaned_html
    assert any(f.rule_id == "APL-NOT-APL-001" for f in result.findings)


def test_ordinary_apl_is_still_labelled():
    result = clean("<p>Use <code>Words</code> and <code>Freqs</code>.</p>")
    assert classes_of(result.cleaned_html) == [["language-apl"], ["language-apl"]]
    assert not [f for f in result.findings if f.rule_id == "APL-NOT-APL-001"]


def test_unlabelled_non_apl_is_a_suggestion_not_an_error():
    result = clean("<pre><code>$ git status</code></pre>")
    assert result.counts["error"] == 0
    assert result.export_safe


def test_unlabelled_apl_is_still_an_error():
    """The invariant that matters: APL must not lose its class."""
    import copy

    broken = copy.deepcopy(load_profile(DEFAULT_PROFILE_ID))
    broken["rules"]["apl_markup"] = False
    result = analyse_html("<pre><code>A\u21901 2 3</code></pre>", broken)
    assert any(f.rule_id == "OUTPUT-CODE-CLASS-001" for f in result.findings)
    assert not result.export_safe


def test_the_language_can_be_set_from_the_finding():
    html = "<pre><code>$ git status</code></pre>"
    result = clean(html)
    finding = next(f for f in result.findings if f.rule_id == "APL-NOT-APL-001")
    updated, message = apply_action(
        result.cleaned_html, finding.action, {**finding.action_params, "value": "language-bash"}
    )
    assert 'class="language-bash"' in updated
    assert "language-bash" in message


def test_a_nonsense_language_class_is_refused():
    for bad in ("bash", "language-", "Language-Bash!", ""):
        with pytest.raises(ActionError):
            apply_action("<pre><code>x</code></pre>", "set_code_language",
                         {"index": 0, "value": bad})


def test_the_detection_can_be_switched_off():
    import copy

    old_behaviour = copy.deepcopy(load_profile(DEFAULT_PROFILE_ID))
    old_behaviour["apl_markup"]["flag_non_apl_code"] = False
    result = analyse_html("<pre><code>$ git status</code></pre>", old_behaviour)
    assert "language-apl" in result.cleaned_html


# --------------------------------------------------------------------------
# Caption shortcodes
# --------------------------------------------------------------------------

def test_caption_shortcodes_are_removed_but_the_caption_is_kept():
    result = clean(
        '[caption id="attachment_9685" align="aligncenter" width="2802"]'
        '<img src="shot.png" alt="Claude Code"/> Claude Code showing the skills[/caption]'
    )
    assert "[caption" not in result.cleaned_html
    assert "[/caption]" not in result.cleaned_html
    assert "Claude Code showing the skills" in result.cleaned_html
    assert any(f.rule_id == "CAPTION-SHORTCODE-001" for f in result.findings)


def test_the_shortcode_attributes_do_not_trip_the_copy_guard():
    """attachment_9685 and aligncenter are markup, not words the author wrote."""
    result = clean(
        '[caption id="attachment_9685" align="aligncenter" width="2802"]'
        '<img src="shot.png"/> The caption[/caption]'
    )
    assert result.copy_preserved
    assert result.counts["error"] == 0


def test_stripping_is_a_no_op_when_there_are_no_shortcodes():
    html = "<p>Ordinary text.</p>"
    stripped, count = strip_caption_shortcodes(html)
    assert stripped == html
    assert count == 0
