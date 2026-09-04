"""Wrap cleaned HTML in WordPress block delimiters.

Pasting plain HTML into a Paragraph block sends it through Gutenberg's paste
sanitiser, which strips class="language-apl" and class="ex-link". Pasting
block-delimited markup into the Code Editor sends it through the block parser
instead, which leaves the inner HTML alone.

This module changes no copy and applies no clean-up rules. It runs after the
rule engine and only adds the HTML comments that mark block boundaries.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, ProcessingInstruction, Tag

from app.models import Finding, Severity


HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Elements that belong inside a paragraph rather than standing on their own.
# Old page fragments often leave these loose at the top level; each one must
# join the surrounding prose instead of becoming its own block, or a single
# sentence gets torn into several blocks.
INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "del", "dfn",
    "em", "i", "ins", "kbd", "mark", "q", "s", "samp", "small", "span", "strong",
    "sub", "sup", "time", "u", "var", "wbr",
}

# Blocks whose saved markup carries a wp-block-* class. Gutenberg regenerates
# this markup when it validates a block, so omitting the class it expects
# produces an "unexpected or invalid content" warning in the editor.
BLOCK_CLASSES = {
    "code": "wp-block-code",
    "image": "wp-block-image",
    "quote": "wp-block-quote",
    "table": "wp-block-table",
    "preformatted": "wp-block-preformatted",
}


def _delimiters(name: str, attributes: dict[str, Any] | None = None) -> tuple[str, str]:
    if attributes:
        payload = json.dumps(attributes, separators=(",", ":"), ensure_ascii=False)
        return f"<!-- wp:{name} {payload} -->", f"<!-- /wp:{name} -->"
    return f"<!-- wp:{name} -->", f"<!-- /wp:{name} -->"


def _add_class(element: Tag, name: str) -> None:
    classes = list(element.get("class", []))
    if name not in classes:
        classes.insert(0, name)
    element["class"] = classes


def _wrap(soup: BeautifulSoup, element: Tag, tag_name: str, class_name: str) -> Tag:
    """Put an element inside the wrapper Gutenberg expects, if it isn't already."""
    if element.name == tag_name:
        _add_class(element, class_name)
        return element
    wrapper = soup.new_tag(tag_name)
    _add_class(wrapper, class_name)
    element.wrap(wrapper)
    return wrapper


def _quote_markup(soup: BeautifulSoup, element: Tag) -> str:
    """A quote block, with its paragraphs as nested blocks.

    core/quote holds paragraph *blocks*, not loose text: a <blockquote> with
    bare text inside it fails block validation with "unexpected or invalid
    content". Loose text is therefore wrapped in a <p> first, and each paragraph
    gets its own wp:paragraph delimiters.
    """
    # Wrap any loose text in a paragraph, so the blockquote holds only blocks.
    for child in list(element.contents):
        if isinstance(child, NavigableString) and str(child).strip():
            paragraph = soup.new_tag("p")
            child.wrap(paragraph)

    inner: list[str] = []
    for child in element.contents:
        if isinstance(child, IGNORED_NODES):
            continue
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "p":
            open_tag, close_tag = _delimiters("paragraph")
            inner.append(f"{open_tag}\n{child.decode(formatter='minimal')}\n{close_tag}")
        elif child.name == "cite":
            # A citation belongs to the block, not to its paragraphs.
            inner.append(child.decode(formatter="minimal"))
        else:
            inner.append(child.decode(formatter="minimal"))

    _add_class(element, BLOCK_CLASSES["quote"])
    classes = " ".join(element.get("class", []))
    body = "\n".join(inner)
    open_tag, close_tag = _delimiters("quote")
    return f'{open_tag}\n<blockquote class="{classes}">\n{body}\n</blockquote>\n{close_tag}'


def _classify(element: Tag) -> tuple[str, dict[str, Any] | None]:
    """Map a top-level element to a core block name and its attributes."""
    name = element.name

    if name == "p":
        return "paragraph", None
    if name in HEADINGS:
        level = int(name[1])
        # core/heading defaults to level 2, so only other levels need the attribute.
        return "heading", None if level == 2 else {"level": level}
    if name == "ul":
        return "list", None
    if name == "ol":
        return "list", {"ordered": True}
    if name == "pre":
        # <pre><code> is a code block; a bare <pre> is preformatted text.
        return ("code", None) if element.find("code") is not None else ("preformatted", None)
    if name == "blockquote":
        return "quote", None
    if name == "table":
        return "table", None
    if name == "hr":
        return "separator", None
    if name == "img":
        return "image", None
    if name == "figure":
        return ("image", None) if element.find("img") is not None else ("html", None)
    return "html", None


IGNORED_NODES = (Comment, Doctype, ProcessingInstruction)


def _is_inline(node: Any) -> bool:
    if isinstance(node, IGNORED_NODES):
        return False
    if isinstance(node, NavigableString):
        return bool(str(node).strip())
    return isinstance(node, Tag) and node.name in INLINE_TAGS


# Classic WordPress content has no <p> tags: paragraphs are separated by a blank
# line and wpautop supplies the markup at render time. A run of loose inline
# content therefore ends at a blank line, or the whole post collapses into one
# enormous paragraph.
BLANK_LINE = re.compile(r"\n[ \t]*\n")


def _split_on_blank_lines(text: str) -> list[str]:
    return BLANK_LINE.split(text)


def _render_run(run: list[Any]) -> str:
    return "".join(
        item.decode(formatter="minimal") if isinstance(item, Tag) else str(item)
        for item in run
    )


def to_block_markup(html: str) -> tuple[str, list[Finding]]:
    """Return (block-delimited markup, findings).

    Anything with no obvious core-block equivalent falls back to a Custom HTML
    block, which preserves the markup exactly and is reported as a Suggestion so
    it can be reviewed rather than silently accepted.
    """
    soup = BeautifulSoup(html, "html.parser")
    findings: list[Finding] = []
    pieces: list[str] = []

    # Collect consecutive inline nodes so a run of prose becomes one paragraph.
    nodes = list(soup.contents)
    index = 0
    while index < len(nodes):
        node = nodes[index]

        if _is_inline(node):
            # Accumulate consecutive inline content, starting a new paragraph
            # wherever a blank line appears inside a text node.
            runs: list[list[Any]] = [[]]
            while index < len(nodes) and (
                _is_inline(nodes[index])
                or (isinstance(nodes[index], NavigableString) and not str(nodes[index]).strip())
            ):
                item = nodes[index]
                index += 1
                if isinstance(item, IGNORED_NODES):
                    continue
                if isinstance(item, NavigableString):
                    parts = _split_on_blank_lines(str(item))
                    runs[-1].append(NavigableString(parts[0]))
                    for part in parts[1:]:
                        runs.append([NavigableString(part)])
                else:
                    runs[-1].append(item)

            for run in runs:
                inner = _render_run(run).strip()
                if not inner:
                    continue
                open_tag, close_tag = _delimiters("paragraph")
                pieces.append(f"{open_tag}\n<p>{inner}</p>\n{close_tag}")
            continue

        index += 1
        if isinstance(node, IGNORED_NODES) or isinstance(node, NavigableString):
            continue
        if not isinstance(node, Tag):
            continue

        block_name, attributes = _classify(node)
        element = node

        if block_name == "quote":
            pieces.append(_quote_markup(soup, element))
            continue

        if block_name == "code":
            # core/code stores its content through the <code> selector, so a class
            # on that element is dropped when the block is validated and every code
            # block reports "unexpected or invalid content". The class has to ride
            # on the <pre> as the block's own className attribute instead.
            inner_code = node.find("code")
            languages = [
                name for name in (inner_code.get("class", []) if inner_code else [])
                if name.startswith("language-")
            ]
            if languages:
                del inner_code["class"]
                for language in languages:
                    _add_class(node, language)
                attributes = {"className": " ".join(languages)}
            _add_class(element, BLOCK_CLASSES["code"])
        elif block_name in BLOCK_CLASSES:
            if block_name in {"image", "table"}:
                element = _wrap(soup, node, "figure", BLOCK_CLASSES[block_name])
            else:
                _add_class(element, BLOCK_CLASSES[block_name])

        if block_name == "html":
            findings.append(
                Finding(
                    rule_id="BLOCK-MARKUP-001",
                    title="No matching core block",
                    message=(
                        f"<{node.name}> has no obvious core block, so it became a Custom HTML "
                        "block. The markup is preserved exactly; check it suits the post."
                    ),
                    severity=Severity.SUGGESTED,
                    before_html=str(node)[:300],
                    applied=False,
                    metadata={"tag": node.name},
                )
            )

        open_tag, close_tag = _delimiters(block_name, attributes)
        pieces.append(f"{open_tag}\n{element.decode(formatter='minimal')}\n{close_tag}")

    return "\n\n".join(pieces), findings
