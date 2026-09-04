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

from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from app.text import visible_text


class ActionError(ValueError):
    """The action could not be applied to the supplied HTML."""


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u2395\u234b\u235e])")


def _visible_text(html: str) -> str:
    """The words a reader sees. One shared definition (see app.text)."""
    return visible_text(html)


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


def promote_heading_run(soup: BeautifulSoup, params: dict) -> str:
    """Move a whole run of same-level headings up one level.

    Fixing one heading at a time would leave the outline worse than it started:
    the pynapl post has four <h4>s directly under an <h2>, and promoting one
    gives h2 > h3 followed by three h4s that now skip two levels. The run moves
    together.

    The run is every heading at this level from here up to the next heading that
    is shallower, so a later section with its own headings is untouched.
    """
    index = int(params.get("index", 0))
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    if index < 0 or index >= len(headings):
        raise ActionError("That heading is no longer in the document. Re-run the analysis.")

    start = headings[index]
    level = int(start.name[1])
    if level <= 2:
        raise ActionError("That heading is already as high as it can go.")

    run = [start]
    for heading in headings[index + 1:]:
        this_level = int(heading.name[1])
        if this_level < level:
            break
        if this_level == level:
            run.append(heading)

    for heading in run:
        heading.name = f"h{level - 1}"

    count = len(run)
    return (
        f"Promoted {count} heading{'s' if count != 1 else ''} from <h{level}> to "
        f"<h{level - 1}>."
    )


def promote_bold_paragraph_run(soup: BeautifulSoup, params: dict) -> str:
    """Turn every all-bold paragraph in the document into a heading.

    One post had four of them acting as section headings; converting them one at
    a time is tedious and leaves the outline half-done.
    """
    level = int(params.get("level", 3))
    converted = 0

    for paragraph in list(soup.find_all("p")):
        children = [
            child for child in paragraph.children
            if not (isinstance(child, NavigableString) and not str(child).strip())
        ]
        if len(children) != 1:
            continue
        only = children[0]
        if not isinstance(only, Tag) or only.name not in {"strong", "b"}:
            continue
        text = only.get_text(" ", strip=True)
        if not text or len(text) > 100:
            continue
        only.unwrap()
        paragraph.name = f"h{level}"
        converted += 1

    if not converted:
        raise ActionError("No all-bold paragraphs are left. Re-run the analysis.")
    return (
        f"Changed {converted} bold paragraph{'s' if converted != 1 else ''} to "
        f"<h{level}>."
    )


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


def set_code_language(soup: BeautifulSoup, params: dict) -> str:
    """Put a language-* class on one <code> element."""
    index = int(params.get("index", 0))
    value = str(params.get("value", "")).strip()
    element = _nth(soup, "code", index)

    if not value:
        raise ActionError("Enter a class, such as language-bash.")
    if not re.fullmatch(r"language-[a-z0-9][a-z0-9+#-]*", value):
        raise ActionError(
            "A language class looks like language-bash, language-python or language-apl."
        )

    classes = [name for name in element.get("class", []) if not name.startswith("language-")]
    classes.append(value)
    element["class"] = classes
    return f'Set class="{value}" on one code element.'


def convert_to_blockquote(soup: BeautifulSoup, params: dict) -> str:
    """Turn an indented <div> into a real <blockquote>.

    Old posts used <div style="margin: 15px 50px"> to indent a quotation. That
    has no Gutenberg block, so it lands in Custom HTML; a blockquote is what it
    means and maps to core/quote.
    """
    index = int(params.get("index", 0))
    element = _nth(soup, "div", index)
    element.name = "blockquote"
    if element.has_attr("style"):
        del element["style"]
    text = element.get_text(" ", strip=True)[:60]
    return f'Changed a <div> to <blockquote>: "{text}".'


def unlink(soup: BeautifulSoup, params: dict) -> str:
    """Remove a link, keeping the words it wrapped.

    For a broken link where the target is simply gone. The link text stays
    exactly as written: deleting the words would be a copy change, and handoff 2
    reserves that for you.
    """
    href = str(params.get("from_url", ""))
    if not href:
        raise ActionError("No URL was supplied.")

    anchors = soup.find_all("a", href=href)
    if not anchors:
        raise ActionError("That link is no longer in the document. Re-run the analysis.")

    for anchor in anchors:
        anchor.unwrap()

    count = len(anchors)
    return (
        f"Removed {count} link{'s' if count != 1 else ''} to {href}, keeping the "
        "text. Delete the wording yourself if it no longer makes sense."
    )


def rewrite_host(soup: BeautifulSoup, params: dict) -> str:
    """Repoint every link on one host at another host.

    Only the host changes: the path, query and fragment are preserved exactly,
    because handoff 6.3 forbids inventing or altering a URL beyond a configured
    migration. This does not check that anything exists at the new host — the
    Links tab does that.
    """
    from_host = str(params.get("from_host", "")).strip().lower()
    to_host = str(params.get("value", "")).strip()

    if not from_host:
        raise ActionError("No host was supplied.")
    if not to_host:
        raise ActionError("Enter a host, such as dyalogprod.gos.dyalog.com.")
    to_host = re.sub(r"^https?://", "", to_host).strip("/")
    if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d+)?", to_host, re.IGNORECASE):
        raise ActionError(f"{to_host!r} does not look like a host name.")
    if to_host.lower() == from_host:
        raise ActionError("That is the host they already use.")

    changed = 0
    for anchor in soup.find_all("a", href=True):
        parsed = urlparse(str(anchor["href"]))
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != from_host:
            continue
        anchor["href"] = parsed._replace(netloc=to_host).geturl()
        changed += 1

    if not changed:
        raise ActionError(f"No links on {from_host} are left. Re-run the analysis.")
    return (
        f"Repointed {changed} link{'s' if changed != 1 else ''} from {from_host} "
        f"to {to_host}. Paths were preserved exactly."
    )


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


def split_paragraph_lines(soup: BeautifulSoup, params: dict) -> str:
    """Split one paragraph into several, at every internal line break.

    Some old posts arrive as a single <p> holding the whole article, with the
    paragraph breaks surviving only as newlines. Splitting at every line break
    changes only <p> structure; the words stay exactly as written (handoff 9).
    """
    index = int(params.get("index", 0))
    paragraph = _nth(soup, "p", index)

    # Only split on breaks that fall in the paragraph's own text nodes, so
    # inline markup is never cut in half.
    parts: list[list[Any]] = [[]]
    for child in list(paragraph.contents):
        if isinstance(child, NavigableString):
            pieces = re.split(r"\n+", str(child))
            parts[-1].append(NavigableString(pieces[0]))
            for piece in pieces[1:]:
                parts.append([NavigableString(piece)])
        else:
            parts[-1].append(child.extract())

    kept = [group for group in parts if "".join(
        item.get_text() if isinstance(item, Tag) else str(item) for item in group
    ).strip()]
    if len(kept) < 2:
        raise ActionError("That paragraph has no line breaks to split on.")

    new_paragraphs: list[Tag] = []
    for group in kept:
        fresh = soup.new_tag("p")
        for name, value in paragraph.attrs.items():
            fresh[name] = value
        for item in group:
            fresh.append(item)
        # Trim the whitespace the break used to occupy.
        if fresh.contents and isinstance(fresh.contents[0], NavigableString):
            fresh.contents[0].replace_with(NavigableString(str(fresh.contents[0]).lstrip()))
        if fresh.contents and isinstance(fresh.contents[-1], NavigableString):
            fresh.contents[-1].replace_with(NavigableString(str(fresh.contents[-1]).rstrip()))
        new_paragraphs.append(fresh)

    anchor = paragraph
    for fresh in new_paragraphs:
        anchor.insert_after(fresh)
        anchor = fresh
    paragraph.decompose()

    return f"Split one paragraph into {len(new_paragraphs)}. No words were changed."


def line_break_count(paragraph: Tag) -> int:
    """How many of the paragraph's own text nodes contain a line break."""
    total = 0
    for child in paragraph.contents:
        if isinstance(child, NavigableString):
            total += len(re.findall(r"\n+", str(child)))
    return total


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
        Action("promote_heading_run", "Promote these headings", promote_heading_run),
        Action(
            "promote_bold_paragraph_run",
            "Make all the bold paragraphs headings",
            promote_bold_paragraph_run,
        ),
        Action("promote_bold_paragraph", "Make this a heading", promote_bold_paragraph),
        Action("split_paragraph", "Split this paragraph", split_paragraph),
        Action("set_id", "Change this id", set_id),
        Action("rewrite_url", "Repoint this link", rewrite_url),
        Action("unlink", "Remove this link, keeping the text", unlink),
        Action("rewrite_host", "Repoint every link on this host", rewrite_host),
        Action("convert_to_blockquote", "Make this a blockquote", convert_to_blockquote),
        Action("set_code_language", "Set the code language", set_code_language),
        Action("split_paragraph_lines", "Split at the line breaks", split_paragraph_lines),
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
