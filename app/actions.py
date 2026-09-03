"""Actions a user can choose to apply to an individual finding.

Nothing in this module runs automatically. Each action corresponds to a
Suggestion or Warning the user has read and explicitly accepted, which is what
handoff 9 describes for paragraph splitting: the app proposes, the human
decides, and only then does the structure change.

Every action here is structural. None of them changes a word: `_visible_text`
is compared before and after and the action is refused if the copy moves.
"""
from __future__ import annotations

import difflib
import html as html_module
import re
from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup, NavigableString, Tag


class ActionError(ValueError):
    """The action could not be applied to the supplied HTML."""


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u2395\u234b\u235e])")


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True).replace("\xa0", " ")


def _nth(soup: BeautifulSoup, name: str, index: int) -> Tag:
    elements = soup.find_all(name)
    if index < 0 or index >= len(elements):
        raise ActionError(f"That {name} is no longer in the document. Re-run the analysis.")
    return elements[index]


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

def remove_class(soup: BeautifulSoup, params: dict) -> str:
    """Remove one class name wherever it appears."""
    name = params.get("class_name", "")
    if not name:
        raise ActionError("No class name was supplied.")
    removed = 0
    for element in soup.find_all(class_=True):
        classes = list(element.get("class", []))
        if name not in classes:
            continue
        kept = [item for item in classes if item != name]
        if kept:
            element["class"] = kept
        else:
            del element["class"]
        removed += 1
    if not removed:
        raise ActionError(f'class="{name}" is no longer in the document.')
    return f'Removed class="{name}" from {removed} element{"s" if removed != 1 else ""}.'


def demote_heading(soup: BeautifulSoup, params: dict) -> str:
    """Turn an <h1> into an <h2> (or any heading down one level)."""
    index = int(params.get("index", 0))
    name = params.get("tag", "h1")
    heading = _nth(soup, name, index)
    level = int(heading.name[1])
    if level >= 6:
        raise ActionError("That heading is already at the lowest level.")
    heading.name = f"h{level + 1}"
    text = heading.get_text(" ", strip=True)
    return f'Changed "{text}" from <{name}> to <{heading.name}>.'


def promote_bold_paragraph(soup: BeautifulSoup, params: dict) -> str:
    """Turn a paragraph that is entirely bold into a real heading."""
    index = int(params.get("index", 0))
    level = int(params.get("level", 3))
    paragraph = _nth(soup, "p", index)
    children = [
        child for child in paragraph.children
        if not (isinstance(child, NavigableString) and not str(child).strip())
    ]
    if len(children) != 1 or not isinstance(children[0], Tag) or children[0].name not in {"strong", "b"}:
        raise ActionError("That paragraph is no longer a single run of bold text.")
    inner = children[0]
    inner.unwrap()
    paragraph.name = f"h{level}"
    text = paragraph.get_text(" ", strip=True)
    return f'Changed "{text}" from a bold paragraph to <h{level}>.'


def suggest_unique_id(soup: BeautifulSoup, value: str, element: Tag | None = None) -> str:
    """Propose an unused id, preferring one derived from the element's own text."""
    taken = {str(tag["id"]) for tag in soup.find_all(id=True)}

    if element is not None:
        text = element.get_text(" ", strip=True).lower()
        slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60].rstrip("-")
        if slug and slug not in taken and not slug[0].isdigit():
            return slug

    stem = re.sub(r"-\d+$", "", value) or "section"
    counter = 2
    while f"{stem}-{counter}" in taken:
        counter += 1
    return f"{stem}-{counter}"


def set_id(soup: BeautifulSoup, params: dict) -> str:
    """Give one element a different id.

    Used to resolve a duplicate id. The new value is supplied by the user; the
    app proposes one but never imposes it.
    """
    value = str(params.get("id", ""))
    occurrence = int(params.get("occurrence", 1))
    new_id = str(params.get("value", "")).strip()

    matches = soup.find_all(id=value)
    if occurrence < 0 or occurrence >= len(matches):
        raise ActionError(f'id="{value}" is no longer duplicated. Re-run the analysis.')

    if not new_id:
        raise ActionError("Enter an id.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_:.-]*", new_id):
        raise ActionError(
            "An id must start with a letter and contain no spaces "
            "(letters, digits, hyphens, underscores, colons and full stops are allowed)."
        )
    if new_id == value:
        raise ActionError("That is the id it already has.")
    if soup.find(id=new_id) is not None:
        raise ActionError(f'id="{new_id}" is already used elsewhere in the document.')

    matches[occurrence]["id"] = new_id
    return f'Changed id="{value}" to id="{new_id}".'


def rewrite_url(soup: BeautifulSoup, params: dict) -> str:
    """Repoint every link with a given href at a new URL.

    The new URL is supplied by the user; the app proposes the same path on the
    new host but will not invent one (handoff 6.3).
    """
    old = str(params.get("from_url", ""))
    new = str(params.get("value", "")).strip()

    if not old:
        raise ActionError("No URL was supplied.")
    if not new:
        raise ActionError("Enter a URL.")
    if not re.match(r"^(https?://|/|#)", new):
        raise ActionError("A URL must start with http://, https://, / or #.")

    anchors = soup.find_all("a", href=old)
    if not anchors:
        raise ActionError("That link is no longer in the document. Re-run the analysis.")
    for anchor in anchors:
        anchor["href"] = new
    count = len(anchors)
    return f"Repointed {count} link{'s' if count != 1 else ''} to {new}."


def split_paragraph(soup: BeautifulSoup, params: dict) -> str:
    """Split one paragraph in two at a sentence boundary.

    Handoff 9: only the <p> structure changes, the words stay identical.
    """
    index = int(params.get("index", 0))
    offset = int(params.get("offset", -1))
    paragraph = _nth(soup, "p", index)

    if offset < 0:
        offset = suggest_split_offset(paragraph)
    if offset <= 0:
        raise ActionError("No sentence boundary was found in that paragraph.")

    # Walk the paragraph's own nodes, moving everything past the boundary into a
    # second paragraph. The boundary always falls inside a direct text node so
    # that inline markup is never cut in half.
    second = soup.new_tag("p")
    seen = 0
    moving = False
    for child in list(paragraph.contents):
        if moving:
            second.append(child.extract())
            continue
        length = len(child.get_text() if isinstance(child, Tag) else str(child))
        if not moving and seen + length >= offset and isinstance(child, NavigableString):
            cut = offset - seen
            head, tail = str(child)[:cut], str(child)[cut:]
            child.replace_with(NavigableString(head))
            if tail.strip():
                second.append(NavigableString(tail.lstrip()))
            moving = True
        seen += length

    if not second.get_text(strip=True):
        raise ActionError("Splitting there would leave an empty paragraph.")

    # Tidy the trailing space left at the end of the first paragraph.
    if paragraph.contents and isinstance(paragraph.contents[-1], NavigableString):
        paragraph.contents[-1].replace_with(NavigableString(str(paragraph.contents[-1]).rstrip()))

    paragraph.insert_after(second)
    return "Split one paragraph into two. No words were changed."


def suggest_split_offset(paragraph: Tag) -> int:
    """Character offset of the sentence boundary nearest the paragraph's middle.

    Only boundaries that fall inside the paragraph's own text nodes are offered,
    so applying the split can never cut through inline markup.
    """
    text = paragraph.get_text()
    middle = len(text) / 2
    candidates = [match.start() for match in SENTENCE_END.finditer(text)]
    if not candidates:
        return -1

    # Map each candidate to a position inside a direct text child.
    safe: list[int] = []
    position = 0
    for child in paragraph.contents:
        length = len(child.get_text() if isinstance(child, Tag) else str(child))
        if isinstance(child, NavigableString):
            safe.extend(
                candidate for candidate in candidates
                if position < candidate < position + length
            )
        position += length
    if not safe:
        return -1
    return min(safe, key=lambda candidate: abs(candidate - middle))


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    run: Callable[[BeautifulSoup, dict], str]


ACTIONS: dict[str, Action] = {
    action.id: action
    for action in (
        Action("remove_class", "Remove this class", remove_class),
        Action("demote_heading", "Demote to the next level", demote_heading),
        Action("promote_bold_paragraph", "Make this a heading", promote_bold_paragraph),
        Action("split_paragraph", "Split this paragraph", split_paragraph),
        Action("set_id", "Change this id", set_id),
        Action("rewrite_url", "Repoint this link", rewrite_url),
    )
}


def apply_action(html: str, action_id: str, params: dict) -> tuple[str, str]:
    """Apply one action and return (updated HTML, description).

    Raises ActionError if the action does not fit the document, or if it would
    change any visible copy.
    """
    action = ACTIONS.get(action_id)
    if action is None:
        raise ActionError(f"Unknown action: {action_id}")

    soup = BeautifulSoup(html, "html.parser")
    before = _visible_text(html)
    message = action.run(soup, params)
    updated = soup.decode(formatter="minimal")

    if _visible_text(updated) != before:
        raise ActionError(
            f"{action.label} would have changed the visible copy, so it was not applied."
        )
    return updated, message


def preview_action(fragment_html: str, action_id: str, params: dict) -> str | None:
    """Show what an action would do, applied to the finding's own fragment.

    The finding stores the affected element on its own, so the action is run
    against that in isolation with the locators normalised to the first (and
    only) match. Returns None if a preview cannot be produced; a preview is
    never allowed to raise into the page.
    """
    if not fragment_html:
        return None
    isolated = dict(params)
    if "index" in isolated:
        isolated["index"] = 0
    if "occurrence" in isolated:
        isolated["occurrence"] = 0
    try:
        updated, _ = apply_action(fragment_html, action_id, isolated)
    except (ActionError, ValueError):
        return None
    return updated


def highlight_additions(before: str, after: str) -> str:
    """Escape `after` for display, wrapping anything newly inserted in <mark>.

    Returns HTML that is safe to render: every character of the document is
    escaped, and the only live tags are the <mark> elements added here. This is
    what makes a one-tag change visible in a wall of markup.
    """
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    pieces: list[str] = []
    for opcode, _i1, _i2, j1, j2 in matcher.get_opcodes():
        segment = after[j1:j2]
        if not segment:
            continue
        escaped = html_module.escape(segment)
        if opcode in {"insert", "replace"}:
            pieces.append(f'<mark class="added">{escaped}</mark>')
        else:
            pieces.append(escaped)
    return "".join(pieces)


def preview_blocks(after: str) -> list[dict[str, str]]:
    """Break preview HTML into its top-level elements, for readable display.

    This is what makes a paragraph split legible: two <p> elements shown as two
    separate blocks of prose, rather than one run of markup with a tag buried
    somewhere in the middle of it.
    """
    soup = BeautifulSoup(after, "html.parser")
    blocks: list[dict[str, str]] = []
    for node in soup.contents:
        if isinstance(node, Tag):
            text = node.get_text(" ", strip=True)
            if text:
                blocks.append({"tag": node.name, "text": text})
        elif isinstance(node, NavigableString) and str(node).strip():
            blocks.append({"tag": "", "text": str(node).strip()})
    return blocks
