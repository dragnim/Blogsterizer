"""What a reader actually sees.

There is one definition of this, used by both copy guards — the per-rule guard in
the engine and the per-action guard in `actions` — because two definitions meant
two behaviours. The engine's was fixed in 0.14.1 to stop treating inline element
boundaries as whitespace; the actions one was not, and it refused to unlink an
anchor sitting before a full stop on the grounds that the copy had changed.

Inline elements contribute no whitespace when a browser renders them:
`<span>x</span>y` reads as "xy", and `<a>notes</a>.` reads as "notes.". Only a
block boundary separates words.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import (
    BeautifulSoup,
    Comment,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    Tag,
)

# Elements that sit within a line of text rather than forming their own block.
INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "del", "dfn",
    "em", "i", "ins", "kbd", "mark", "q", "s", "samp", "small", "span", "strong",
    "sub", "sup", "time", "u", "var", "wbr",
}

IGNORED_NODES = (Comment, Doctype, ProcessingInstruction)
INVISIBLE_TAGS = {"script", "style", "template", "noscript"}


def node_text(node: Any) -> str:
    """Text of one node, breaking only at a block boundary."""
    # A comment is not visible copy. This matters because block markup carries
    # its structure in comments.
    if isinstance(node, IGNORED_NODES):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in INVISIBLE_TAGS:
        return ""
    if node.name == "br":
        return "\n"
    inner = "".join(node_text(child) for child in node.children)
    return inner if node.name in INLINE_TAGS else f"\n{inner}\n"


def visible_text(html: str) -> str:
    """The words a reader sees, with whitespace normalised.

    A run of spaces, a newline and a single space all render the same, so they
    must compare the same: otherwise splitting a paragraph at a newline looks
    like a copy change when the words are untouched.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = "".join(node_text(node) for node in soup.contents)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
