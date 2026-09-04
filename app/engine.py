from __future__ import annotations

import difflib
import html as html_module
import re
from typing import Any, Iterable

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, ProcessingInstruction, Tag

from app.blocks import INLINE_TAGS, to_block_markup
from app.models import AnalysisResult, Finding, Severity
from app.rules import (
    APLMarkupRule,
    CleanupRule,
    LegacyClassRule,
    ImagePlaceholderRule,
    LinkPolicyRule,
    SEORule,
    StructureRule,
    URLRewriteRule,
    WebinarLayoutRule,
    OutputValidationRule,
)


TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
PRESENTATIONAL_TOKENS = {"(", ")", "[", "]", "{", "}", "|", "–", "—", "-", ",", ".", ";", ":", "!", "?", "\"", "’", "‘", "“", "”"}


def _plain_block_to_html(block: str) -> str:
    # Plain-text input can use Markdown-style backticks to identify ASCII-only
    # inline code that cannot be inferred safely from prose. The APL rule later
    # adds class="language-apl" to these <code> elements.
    parts = re.split(r"(`[^`\n]+`)", block.strip())
    rendered: list[str] = []
    for part in parts:
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            rendered.append(f"<code>{html_module.escape(part[1:-1])}</code>")
        else:
            rendered.append(html_module.escape(part))
    return "".join(rendered)


def plain_text_to_html(text: str) -> str:
    blocks = re.split(r"\n\s*\n", text.strip())
    return "\n\n".join(
        f"<p>{_plain_block_to_html(block)}</p>"
        for block in blocks
        if block.strip()
    )


def _node_text(node: Any) -> str:
    """Text of one node, inserting a break only at a block boundary."""
    # A comment is not visible copy. This matters because block markup carries
    # its structure in comments, so treating them as text made re-importing the
    # block output look like a copy change.
    if isinstance(node, (Comment, Doctype, ProcessingInstruction)):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in {"script", "style", "template", "noscript"}:
        return ""
    if node.name == "br":
        return "\n"
    inner = "".join(_node_text(child) for child in node.children)
    # An inline element contributes no whitespace of its own; a block one does.
    return inner if node.name in INLINE_TAGS else f"\n{inner}\n"


def _visible_text(html: str) -> str:
    """The text a reader would see.

    Inline elements do not introduce whitespace when a browser renders them:
    `<span>x</span>y` reads as "xy", not "x y". Extracting with a separator at
    every element boundary made the guard see a copy change whenever an inline
    wrapper was added or removed mid-word — which is exactly what a syntax
    highlighter does. Only block boundaries separate words here.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = "".join(_node_text(node) for node in soup.contents)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _tokens(html: str) -> list[str]:
    return TOKEN_PATTERN.findall(_visible_text(html))


def _is_subsequence(needles: Iterable[str], haystack: Iterable[str]) -> bool:
    iterator = iter(haystack)
    return all(any(candidate == needle for candidate in iterator) for needle in needles)


def _semantic_tokens(html: str) -> list[str]:
    # For approved resource-layout changes we allow presentational punctuation
    # such as brackets, separators and dashes to change, while still requiring
    # every original word, number and APL token to survive in order.
    return [token for token in _tokens(html) if token not in PRESENTATIONAL_TOKENS]


def _copy_guard(source_html: str, cleaned_html: str, findings: list[Finding]) -> tuple[bool, str]:
    source_tokens = _tokens(source_html)
    cleaned_tokens = _tokens(cleaned_html)
    authorised_copy_changes = any(item.applied and item.changes_copy for item in findings)

    if source_tokens == cleaned_tokens:
        return True, "Visible copy is unchanged."

    if authorised_copy_changes:
        semantic_source = _semantic_tokens(source_html)
        semantic_cleaned = _semantic_tokens(cleaned_html)
        if _is_subsequence(semantic_source, semantic_cleaned):
            return True, (
                "All original words, numbers and APL tokens are preserved; "
                "approved resource labels or separators were changed."
            )
        return False, (
            "An approved resource-layout rule changed more than presentation labels or separators. "
            "Review the output before using it."
        )

    if _is_subsequence(source_tokens, cleaned_tokens):
        return False, "Visible text was added by a rule that was not authorised to change copy."
    return False, "Original visible copy was removed, reordered or changed. Review the output before using it."


def _make_diff(source_html: str, cleaned_html: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            source_html.splitlines(),
            cleaned_html.splitlines(),
            fromfile="original.html",
            tofile="blogsterized.html",
            lineterm="",
        )
    )


def _build_rules(profile: dict[str, Any]):
    rules_config = profile.get("rules", {})
    rule_map = {
        "url_rewrites": URLRewriteRule(profile.get("url_rewrites", {})),
        "webinar_layout": WebinarLayoutRule(rules_config.get("webinar_layout", {})),
        "structure": StructureRule(rules_config.get("structure", {})),
        "apl_markup": APLMarkupRule(profile.get("apl_markup", {})),
        "legacy_classes": LegacyClassRule(profile.get("legacy_classes", {})),
        "link_policy": LinkPolicyRule(profile.get("link_policy", {})),
        "cleanup": CleanupRule(profile.get("cleanup", {})),
        "image_placeholder": ImagePlaceholderRule(
            rules_config.get("image_placeholder", {})
            if isinstance(rules_config.get("image_placeholder"), dict) else {}
        ),
        "seo": SEORule(rules_config.get("seo", {}) if isinstance(rules_config.get("seo"), dict) else {}),
        "output_validation": OutputValidationRule(profile),
    }
    order = profile.get(
        "rule_order",
        ["url_rewrites", "webinar_layout", "structure", "apl_markup", "legacy_classes", "link_policy", "cleanup", "seo", "image_placeholder", "output_validation"],
    )
    return [rule_map[name] for name in order if name in rule_map and rules_config.get(name, True) is not False]


def extract_body_html(source_html: str) -> str:
    """Reduce a full HTML document to the content inside <body>.

    Exported pages arrive wrapped in <html><head>…</head><body>. That wrapper is
    page furniture, not post content: left in place it survives into the output
    and the block serialiser turns the whole document into one Custom HTML
    block. Fragments without a wrapper are returned untouched.
    """
    lowered = source_html.lower()
    if "<body" not in lowered and "<html" not in lowered:
        return source_html
    soup = BeautifulSoup(source_html, "html.parser")
    body = soup.find("body")
    if body is not None:
        return body.decode_contents()
    html_element = soup.find("html")
    if html_element is not None:
        for head in html_element.find_all("head"):
            head.decompose()
        return html_element.decode_contents()
    return source_html


CAPTION_OPEN = re.compile(r"\[caption\b[^\]]*\]")
CAPTION_CLOSE = re.compile(r"\[/caption\]")

# [embedyt] https://www.youtube.com/watch?v=... [/embedyt] wraps a video embed.
# Gutenberg does not interpret it, so the brackets would show as literal text.
# The URL inside is real content and is kept as a link for you to turn into an
# embed block by hand.
EMBEDYT = re.compile(r"\[embedyt\]\s*(\S+?)\s*\[/embedyt\]")


def strip_embed_shortcodes(source_html: str) -> tuple[str, int]:
    """Turn [embedyt]URL[/embedyt] into a plain link to the same URL.

    The video is content, so the URL survives; only the shortcode wrapper goes.
    Making it an anchor rather than bare text means the link policy then applies
    to it like any other external link.
    """
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        url = match.group(1)
        return f'<a href="{url}">{url}</a>'

    return EMBEDYT.sub(replace, source_html), count


def strip_caption_shortcodes(source_html: str) -> tuple[str, int]:
    """Remove classic [caption ...] wrappers, keeping the caption wording.

    Gutenberg does not interpret shortcodes, so these would render as literal
    text in the post. The brackets and their attributes are markup, so they are
    removed here, before the copy guard takes its baseline — the guard would
    otherwise see `attachment_9685` and `aligncenter` as words being deleted.
    The caption itself is the author's copy and is left exactly as written.
    """
    stripped, opened = CAPTION_OPEN.subn("", source_html)
    stripped, closed = CAPTION_CLOSE.subn("", stripped)
    return stripped, opened + closed


def analyse_html(source_html: str, profile: dict[str, Any]) -> AnalysisResult:
    source_html = extract_body_html(source_html)
    source_html, captions_removed = strip_caption_shortcodes(source_html)
    source_html, embeds_removed = strip_embed_shortcodes(source_html)
    # Old exports carry class=" language-apl" with a leading space. The parser
    # normalises it, so the class ends up correct, but nothing said so: one
    # corpus post had 58 such elements and produced almost no findings.
    untidy_classes = len(re.findall(r'class="\s+language-\w+"', source_html))
    soup = BeautifulSoup(source_html, "html.parser")
    findings: list[Finding] = []

    if untidy_classes:
        findings.append(
            Finding(
                rule_id="APL-CLASS-WHITESPACE-001",
                title="Untidy language class normalised",
                message=(
                    f'{untidy_classes} element(s) had a language class with a leading '
                    'space, such as class=" language-apl". The class itself is correct '
                    "and was tidied; nothing else about the markup changed."
                ),
                severity=Severity.SAFE,
                applied=True,
                metadata={"count": untidy_classes},
            )
        )

    if embeds_removed:
        findings.append(
            Finding(
                rule_id="EMBED-SHORTCODE-001",
                title="Video embed shortcode converted",
                message=(
                    f"Converted {embeds_removed} [embedyt] shortcode(s) to a plain link. "
                    "Gutenberg does not interpret the shortcode, so it would have shown "
                    "as literal text. Replace the link with an Embed block if you want the "
                    "video to play in the post."
                ),
                severity=Severity.SAFE,
                applied=True,
                metadata={"count": embeds_removed},
            )
        )

    if captions_removed:
        findings.append(
            Finding(
                rule_id="CAPTION-SHORTCODE-001",
                title="Caption shortcodes removed",
                message=(
                    f"Removed {captions_removed} classic [caption] shortcode marker(s). "
                    "Gutenberg does not interpret them, so they would have shown as "
                    "literal text. The caption wording was left as written."
                ),
                severity=Severity.SAFE,
                applied=True,
                metadata={"count": captions_removed},
            )
        )

    for rule in _build_rules(profile):
        before_html = soup.decode(formatter="minimal")
        before_tokens = _tokens(before_html)
        before_text = _visible_text(before_html)
        rule_findings = rule.apply(soup)
        after_html = soup.decode(formatter="minimal")
        after_tokens = _tokens(after_html)
        after_text = _visible_text(after_html)

        # Hard safety rail: ordinary clean-up rules are never allowed to change
        # the actual visible tokens. Rules that intentionally replace resource
        # labels/separators may add presentational words, but they still may not
        # remove or reorder any original semantic word, number or APL token.
        may_change_copy = bool(getattr(rule, "may_change_copy", False))
        blocked = False
        block_message = ""

        if not may_change_copy and before_tokens != after_tokens:
            blocked = True
            block_message = f"{rule.rule_id} attempted to change visible copy, so its changes were rolled back."
        elif may_change_copy:
            before_semantic = _semantic_tokens(before_html)
            after_semantic = _semantic_tokens(after_html)
            if not _is_subsequence(before_semantic, after_semantic):
                blocked = True
                block_message = (
                    f"{rule.rule_id} removed or reordered original visible copy, so its changes were rolled back."
                )

        if blocked:
            soup = BeautifulSoup(before_html, "html.parser")
            findings.append(
                Finding(
                    rule_id="COPY-GUARD-RULE-001",
                    title="Rule blocked by copy guard",
                    message=block_message,
                    severity=Severity.ERROR,
                    before_html=before_text,
                    after_html=after_text,
                    applied=False,
                    metadata={"blocked_rule": rule.rule_id},
                )
            )
            continue

        findings.extend(rule_findings)

    cleaned_html = soup.decode(formatter="minimal")

    # Block markup is a second view of the same cleaned HTML for pasting into the
    # WordPress Code Editor. It applies no rules and changes no copy.
    block_markup, block_findings = to_block_markup(cleaned_html)
    findings.extend(block_findings)

    copy_preserved, copy_guard_message = _copy_guard(source_html, cleaned_html, findings)
    if not copy_preserved:
        findings.append(
            Finding(
                rule_id="COPY-GUARD-001",
                title="Copy guard failed",
                message=copy_guard_message,
                severity=Severity.ERROR,
                before_html=_visible_text(source_html),
                after_html=_visible_text(cleaned_html),
                applied=False,
            )
        )

    return AnalysisResult(
        source_html=source_html,
        cleaned_html=cleaned_html,
        findings=findings,
        copy_preserved=copy_preserved,
        copy_guard_message=copy_guard_message,
        diff=_make_diff(source_html, cleaned_html),
        block_markup=block_markup,
    )
