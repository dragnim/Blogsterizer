from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from app.models import Finding, Severity
from app.rules.base import Rule


# Strong APL signals. These characters are distinctive enough to identify an
# unwrapped APL token in prose without trying to infer arbitrary ASCII code.
# ASCII-only code is handled when it is already inside <code>...</code>.
UNAMBIGUOUS_APL_CHARS = (
    "∆∇⋄⍙⍝⍞⍠⍤⍥⍨⍣⍢⍛⍫⍀⌿⌸⌺⌷⌹⌶"
    "⎕⍺⍵⍬⍳⍴⍷⍸⍋⍒⍉⍎⍕⍟⍪⍱⍲"
    "⊆⊣⊢⊥⊤⌽⊖≡≢¯"
)

# Handoff 2 and 3.5: these are APL primitives, but they are also ordinary
# mathematical and typographic characters. "The grid is 3 × 4" and
# "Choose File → Save" are prose, not code. A character from this tier only
# counts as APL when it sits inside a larger token (A←1 2 3) or is quoted in
# brackets as a glyph (grade up (⍋)). On its own in running prose it is left
# alone and reported as a Suggestion instead.
AMBIGUOUS_APL_CHARS = "←→↑↓⊂⊃⌈⌊∊∪∩≠≤≥×÷○∘¨"

APL_SIGNAL_CHARS = UNAMBIGUOUS_APL_CHARS + AMBIGUOUS_APL_CHARS
APL_SIGNAL_RE = re.compile("[" + re.escape(APL_SIGNAL_CHARS) + "]")
UNAMBIGUOUS_RE = re.compile("[" + re.escape(UNAMBIGUOUS_APL_CHARS) + "]")
AMBIGUOUS_RE = re.compile("[" + re.escape(AMBIGUOUS_APL_CHARS) + "]")
TOKEN_WITH_APL_RE = re.compile(r"\S*[" + re.escape(APL_SIGNAL_CHARS) + r"]\S*")


def _qualifies_as_apl(core: str, *, bracketed: bool) -> bool:
    """Decide whether a detected token is confidently APL."""
    if UNAMBIGUOUS_RE.search(core):
        return True
    if not AMBIGUOUS_RE.search(core):
        return False
    # A lone shared character in prose is not evidence of code, unless the
    # writer quoted it in brackets the way the handoff's own examples do.
    return bracketed or len(core) > 1

USER_COMMAND_RE = re.compile(r"(?<![\w\]])\][A-Za-z][A-Za-z0-9_-]*")
CONTROL_WORDS = {
    "Access", "AndIf", "Attribute", "Case", "CaseList", "Class", "Disposable",
    "Else", "ElseCase", "ElseIf", "End", "EndAccess", "EndAttribute", "EndClass",
    "EndDisposable", "EndFor", "EndHold", "EndIf", "EndInterface", "EndNamespace",
    "EndProperty", "EndRepeat", "EndSection", "EndSelect", "EndTrap", "EndWhile",
    "EndWith", "Field", "For", "Hold", "If", "Implements", "In", "Interface",
    "Namespace", "OrIf", "Property", "Repeat", "Section", "Select", "Trap", "Until",
    "Using", "While", "With",
}
CONTROL_RE = re.compile(r"(?<!\w):([A-Za-z][A-Za-z0-9]*)")

TRAILING_PROSE = ",;:.!?\"'’”"
LEADING_PROSE = "\"'‘“"
PAIR_DELIMS = {"(": ")", "[": "]", "{": "}"}


def _inside_code_like(node: NavigableString) -> bool:
    parent = node.parent
    while isinstance(parent, Tag):
        if parent.name in {"code", "pre", "script", "style", "textarea", "template", "noscript"}:
            return True
        parent = parent.parent
    return False


# Evidence that a piece of code is *not* APL. Handoff 3.2 makes unclassified
# code APL, which was right for the old release pages where it always was. Newer
# posts mix in shell, CLI flags and other languages, and labelling those
# language-apl makes the site's highlighter render bash as APL.
#
# These patterns are deliberately narrow: strong evidence of something else,
# rather than an attempt to identify the language. Anything without such
# evidence is still treated as APL.
NON_APL_PATTERNS = (
    (re.compile(r"(?m)^\s*[~/][\w./-]*\s*\$\s"), "a shell prompt"),
    (re.compile(r"(?m)^\s*[$>❯#]\s+\w"), "a shell prompt"),
    (re.compile(r"^#!/"), "a shebang line"),
    (re.compile(r"(?<![\w⍨])--[a-z][a-z0-9-]{2,}"), "a long command-line flag"),
    (re.compile(r"\b(?:git|npm|pip|pip3|sudo|apt-get|brew|curl|wget|docker|kubectl|"
                r"cd|mkdir|cp|mv|chmod|ssh|scp|tar|make|cmake|systemctl)\s+[\w./-]"),
     "a shell command"),
    (re.compile(r"\b(?:def|class|import|from|lambda)\s+\w+.*:"), "Python syntax"),
    (re.compile(r"\bprint\s*\("), "a print() call"),
    (re.compile(r"\b(?:function|const|let|var)\s+\w+\s*[=(]"), "JavaScript syntax"),
    (re.compile(r"=>|\+\+|&&|\|\||==="), "operators APL does not have"),
    (re.compile(r"</?[a-z][a-z0-9]*(?:\s[^>]*)?>"), "HTML markup"),
    (re.compile(r"^\s*[{\[].*[}\]]\s*$", re.DOTALL), "a JSON or object literal"),
    (re.compile(r"\.(?:py|js|ts|sh|json|yaml|yml|cs|go|rs|java|html|css)\b"),
     "a filename from another language"),
)


def non_apl_evidence(text: str) -> str | None:
    """Why this code is evidently not APL, or None if there is no such evidence.

    An APL glyph settles it the other way: a shell transcript that prints APL
    output still contains APL, and mislabelling that is the lesser error.
    """
    if UNAMBIGUOUS_RE.search(text):
        return None
    for pattern, description in NON_APL_PATTERNS:
        if pattern.search(text):
            return description
    return None


def guess_language(text: str) -> str:
    """A starting suggestion for the user to correct. Never applied on its own."""
    if (
        text.startswith("#!/")
        or re.search(r"^\s*[$>\u276f#]\s+\w", text, re.MULTILINE)
        or re.search(r"\b(?:git|npm|pip|sudo|docker|curl|cd|mkdir|chmod)\s", text)
        or re.search(r"(?<![\w\u2368])--[a-z][a-z0-9-]{2,}", text)
    ):
        return "language-bash"
    if re.search(r"\b(?:def|import|lambda)\s|\bprint\s*\(", text):
        return "language-python"
    if re.search(r"=>|\b(?:function|const|let)\s", text):
        return "language-javascript"
    if re.search(r"^\s*[{\[].*[}\]]\s*$", text, re.DOTALL):
        return "language-json"
    if re.search(r"</?[a-z][a-z0-9]*(?:\s[^>]*)?>", text):
        return "language-html"
    return "language-plaintext"


def _merge_code_class(element: Tag) -> bool:
    classes = list(element.get("class", []))
    # Respect an explicit non-APL language already present. Unclassified code on
    # Dyalog profiles is treated as APL.
    explicit_languages = [name for name in classes if name.startswith("language-")]
    if explicit_languages and "language-apl" not in explicit_languages:
        return False
    if "language-apl" in classes:
        return False
    classes.append("language-apl")
    element["class"] = classes
    return True


def _single_apl_atom(text: str) -> bool:
    """Return True for a single primitive/system name inside prose brackets.

    This lets raw prose such as ``grade up (⍋)`` become
    ``grade up (<code ...>⍋</code>)`` rather than putting the prose parentheses
    inside the code element. Multi-symbol expressions such as ``(⊃⍋)`` keep
    their parentheses because those parentheses are part of the APL expression.
    """
    if len(text) == 1 and APL_SIGNAL_RE.search(text):
        return True
    if re.fullmatch(r"⎕[A-Za-z][A-Za-z0-9]*", text):
        return True
    if re.fullmatch(r"\][A-Za-z][A-Za-z0-9_-]*", text):
        return True
    if text.startswith(":") and text[1:] in CONTROL_WORDS:
        return True
    return False


def _split_candidate(token: str) -> tuple[str, str, str, bool]:
    """Split a raw token into prose prefix, code core and prose suffix.

    The fourth value records whether prose brackets were peeled off the core.
    """
    prefix = ""
    suffix = ""
    core = token
    bracketed = False

    while core and core[0] in LEADING_PROSE:
        prefix += core[0]
        core = core[1:]
    while core and core[-1] in TRAILING_PROSE:
        suffix = core[-1] + suffix
        core = core[:-1]

    if len(core) >= 3 and core[0] in PAIR_DELIMS and core[-1] == PAIR_DELIMS[core[0]]:
        inner = core[1:-1]
        if _single_apl_atom(inner):
            prefix += core[0]
            suffix = core[-1] + suffix
            core = inner
            bracketed = True

    return prefix, core, suffix, bracketed


def _raw_candidates(text: str) -> list[tuple[int, int, str, str, str]]:
    candidates: list[tuple[int, int, str, str, str]] = []

    for match in TOKEN_WITH_APL_RE.finditer(text):
        token = match.group(0)
        prefix, core, suffix, bracketed = _split_candidate(token)
        if not core or not _qualifies_as_apl(core, bracketed=bracketed):
            continue
        start = match.start() + len(prefix)
        end = match.end() - len(suffix)
        # If brackets were moved out of the core, adjust for those too. The
        # lengths above already account for them because they were added to
        # prefix/suffix by _split_candidate().
        candidates.append((start, end, prefix, core, suffix))

    # User commands and control words can be APL without an APL-only glyph.
    for match in USER_COMMAND_RE.finditer(text):
        candidates.append((match.start(), match.end(), "", match.group(0), ""))

    for match in CONTROL_RE.finditer(text):
        if match.group(1) in CONTROL_WORDS:
            candidates.append((match.start(), match.end(), "", match.group(0), ""))

    # Keep deterministic, non-overlapping candidates. A strong-glyph candidate
    # takes precedence over command/control patterns at the same location.
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    result: list[tuple[int, int, str, str, str]] = []
    last_end = -1
    for item in candidates:
        if item[0] < last_end:
            continue
        result.append(item)
        last_end = item[1]
    return result


def _unwrapped_ambiguous_glyphs(text: str) -> set[str]:
    """Shared maths/APL characters left in prose because they are ambiguous."""
    claimed: set[int] = set()
    for start, end, _prefix, _core, _suffix in _raw_candidates(text):
        claimed.update(range(start, end))
    return {
        char
        for index, char in enumerate(text)
        if index not in claimed and AMBIGUOUS_RE.match(char)
    }


class APLMarkupRule(Rule):
    rule_id = "APL-MARKUP-001"
    description = 'Normalise APL markup and ensure APL code uses <code class="language-apl">.'

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        legacy_classes = set(self.config.get("legacy_classes", ["APLFont", "language-apl"]))
        mark_all_code = bool(self.config.get("mark_all_code_as_apl", True))
        # Report code that is evidently another language rather than claiming it
        # as APL. Set false to restore the older behaviour from handoff 3.2.
        flag_non_apl = bool(self.config.get("flag_non_apl_code", True))
        wrap_raw_tokens = bool(self.config.get("wrap_raw_apl_tokens", True))

        # 1. Convert legacy span/font wrappers to semantic code while preserving
        # unrelated attributes/classes. Only the known legacy APL class is replaced.
        for element in list(soup.find_all(["span", "font"])):
            classes = list(element.get("class", []))
            if not set(classes).intersection(legacy_classes):
                continue

            before = str(element)
            preserved_classes = [name for name in classes if name not in legacy_classes]
            element.name = "code"
            if preserved_classes:
                element["class"] = preserved_classes
            elif element.has_attr("class"):
                del element["class"]
            _merge_code_class(element)
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title="APL wrapper converted",
                    message='Converted legacy APL markup to <code class="language-apl">.',
                    severity=Severity.SAFE,
                    before_html=before,
                    after_html=str(element),
                    applied=True,
                )
            )

        # 2. Existing inline/block code on Dyalog pages is APL unless it carries
        # an explicit non-APL language-* class, or is evidently something else.
        if mark_all_code:
            for index, element in enumerate(soup.find_all("code")):
                before = str(element)
                text = element.get_text()
                evidence = non_apl_evidence(text) if flag_non_apl else None

                if evidence:
                    suggested = guess_language(text)
                    findings.append(
                        Finding(
                            rule_id="APL-NOT-APL-001",
                            title="Code that is probably not APL",
                            message=(
                                f"This code contains {evidence} and no APL glyph, so it was "
                                "left unclassified rather than labelled as APL. Set the right "
                                "language, or apply APL if it is APL after all."
                            ),
                            severity=Severity.SUGGESTED,
                            before_html=before[:400],
                            applied=False,
                            metadata={"evidence": evidence, "suggested": suggested},
                            action="set_code_language",
                            action_label="Set the language",
                            action_params={"index": index},
                            action_input_label="Class",
                            action_input_default=suggested,
                        )
                    )
                    continue

                if _merge_code_class(element):
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            title="APL code class added",
                            message='Added class="language-apl" to an existing <code> element.',
                            severity=Severity.SAFE,
                            before_html=before,
                            after_html=str(element),
                            applied=True,
                        )
                    )

            # Some older pages use a bare <pre> for code. If the <pre> contains
            # only text (no nested markup), wrap that text in semantic APL code.
            # Mixed-markup <pre> blocks are left alone because guessing there
            # could destroy intentional structure.
            for pre in soup.find_all("pre"):
                if pre.find("code") is not None or pre.find(True) is not None:
                    continue
                before = str(pre)
                text = pre.get_text()
                evidence = non_apl_evidence(text) if flag_non_apl else None
                code = soup.new_tag("code")
                if evidence:
                    # Still made semantic, but not claimed as APL.
                    findings.append(
                        Finding(
                            rule_id="APL-NOT-APL-001",
                            title="Code block that is probably not APL",
                            message=(
                                f"This block contains {evidence} and no APL glyph, so it was "
                                "wrapped in <code> without a language. Set the right language."
                            ),
                            severity=Severity.SUGGESTED,
                            before_html=before[:400],
                            applied=False,
                            metadata={"evidence": evidence, "suggested": guess_language(text)},
                        )
                    )
                else:
                    code["class"] = ["language-apl"]
                code.string = text
                pre.clear()
                pre.append(code)
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="APL code block normalised",
                        message=(
                            "Wrapped a bare <pre> block in a semantic <code> element"
                            + ("." if evidence else ' with class="language-apl".')
                        ),
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html=str(pre),
                        applied=True,
                    )
                )

        # 3. Catch unmistakable unwrapped APL tokens in ordinary text. This is
        # intentionally conservative: arbitrary ASCII words/numbers are not guessed.
        if wrap_raw_tokens:
            # Handoff 3.5/12: a character that is APL in code but ordinary in
            # prose is reported for a human, never marked up automatically.
            if bool(self.config.get("suggest_ambiguous_glyphs", True)):
                ambiguous: dict[str, str] = {}
                for text_node in soup.find_all(string=True):
                    if not isinstance(text_node, NavigableString) or _inside_code_like(text_node):
                        continue
                    text = str(text_node)
                    for glyph in _unwrapped_ambiguous_glyphs(text):
                        ambiguous.setdefault(glyph, text.strip())
                for glyph, context in sorted(ambiguous.items()):
                    findings.append(
                        Finding(
                            rule_id="APL-AMBIGUOUS-001",
                            title="Possible APL glyph in prose",
                            message=(
                                f"'{glyph}' is an APL primitive but also an ordinary "
                                "typographic character, so it was left as written. "
                                "Wrap it by hand if it is meant to be code."
                            ),
                            severity=Severity.SUGGESTED,
                            before_html=context[:300],
                            applied=False,
                            metadata={"glyph": glyph},
                        )
                    )

            for text_node in list(soup.find_all(string=True)):
                if not isinstance(text_node, NavigableString) or _inside_code_like(text_node):
                    continue
                text = str(text_node)
                candidates = _raw_candidates(text)
                if not candidates:
                    continue

                pieces: list[object] = []
                cursor = 0
                for start, end, _prefix, core, _suffix in candidates:
                    if start < cursor:
                        continue
                    pieces.append(text[cursor:start])
                    code = soup.new_tag("code")
                    code["class"] = ["language-apl"]
                    code.string = core
                    pieces.append(code)
                    cursor = end
                pieces.append(text[cursor:])

                before = text
                parent = text_node.parent
                replacement_nodes = [
                    NavigableString(piece) if isinstance(piece, str) else piece
                    for piece in pieces
                    if piece != ""
                ]
                text_node.replace_with(*replacement_nodes)

                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="Unwrapped APL detected",
                        message='Wrapped unmistakable APL text in <code class="language-apl">.',
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html=str(parent) if parent else None,
                        applied=True,
                    )
                )

        return findings
