from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from app.models import Finding, Severity
from app.actions import line_break_count, suggest_split_offset
from app.rules.base import Rule




ICON_WORDS = ("pdf", "ppt", "powerpoint", "zip", "youtube", "github", "acrobat")

# Old Dyalog icon assets are named like pdf_24.png, youtube-play_24.png,
# ppt.gif or github-icon.png. A screenshot called pdf-export-dialog.png is not
# an icon, so the whole filename must look like an icon name, not merely
# contain a resource word somewhere.
ICON_FILENAME_RE = re.compile(
    r"^(?:"
    + "|".join(ICON_WORDS)
    + r"|youtube-play|youtube_play"
    + r")"
    r"(?:[-_](?:icon|play|logo|small|button))?"
    r"(?:[-_]?\d{1,3})?$"
)

# Handoff 11: a real content image is never a 24px icon. Anything meaningfully
# larger than an icon is protected regardless of what its filename says.
MAX_ICON_DIMENSION = 40


def _pixel_dimension(image: Tag, name: str) -> float | None:
    raw = str(image.get(name, "")).strip().lower().replace("px", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _looks_like_legacy_resource_icon(image: Tag) -> bool:
    """Recognise the small file/service icons used by the old Dyalog pages.

    Do not treat every linked image as a resource icon: blog posts can contain
    screenshots/thumbnails inside links and those must survive untouched
    (handoff 11). Declared dimensions win over filename guesswork, so a large
    image is never removed even if its name mentions PDF or GitHub.
    """
    width = _pixel_dimension(image, "width")
    height = _pixel_dimension(image, "height")

    # A declared size larger than an icon settles it: this is content.
    if (width is not None and width > MAX_ICON_DIMENSION) or (
        height is not None and height > MAX_ICON_DIMENSION
    ):
        return False

    if width is not None and height is not None:
        return True

    filename = PurePosixPath(urlparse(str(image.get("src", ""))).path).stem.lower()
    if filename and ICON_FILENAME_RE.match(filename):
        return True

    alt = str(image.get("alt", "")).strip().lower()
    title = str(image.get("title", "")).strip().lower()
    return alt in ICON_WORDS or title in ICON_WORDS

def _resource_kind(href: str) -> str:
    parsed = urlparse(href)
    host = parsed.netloc.lower()
    suffix = PurePosixPath(parsed.path).suffix.lower()
    if "youtube.com" in host or "youtu.be" in host or "dyalog.tv" in host:
        return "video"
    if suffix in {".ppt", ".pptx"}:
        return "powerpoint"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".zip":
        return "zip"
    if "github.com" in host or "github.io" in host:
        return "github"
    return "resource"


def _label_for_link(href: str, context: str = "") -> str:
    kind = _resource_kind(href)
    context_lower = context.lower()
    if kind == "video":
        return "Watch video"
    if kind == "powerpoint":
        return "PowerPoint"
    if kind == "pdf":
        return "Release notes (PDF)" if "release notes" in context_lower else "PDF"
    if kind == "zip":
        return "Materials (ZIP)"
    if kind == "github":
        return "View on GitHub"
    return "View resource"


def _suffix_for_link(href: str) -> str:
    return {
        "video": "",
        "powerpoint": " (PowerPoint)",
        "pdf": " (PDF)",
        "zip": " (ZIP)",
        "github": "",
        "resource": "",
    }[_resource_kind(href)]


def _is_webinar_container(item: Tag) -> bool:
    direct_text = "".join(
        str(child) for child in item.children if isinstance(child, NavigableString)
    ).strip().lower()
    return direct_text.startswith("webinars:") or direct_text.startswith("webinar:")


def _inside_webinar_list(anchor: Tag) -> bool:
    for parent in anchor.parents:
        if parent.name == "li":
            direct_text = "".join(
                str(child) for child in parent.children if isinstance(child, NavigableString)
            ).strip().lower()
            if direct_text.startswith("webinars:") or direct_text.startswith("webinar:"):
                return True
    return False


def _li_is_effectively_only_anchor(li: Tag, anchor: Tag) -> bool:
    for child in li.children:
        if child is anchor:
            continue
        if isinstance(child, NavigableString) and not child.strip():
            continue
        return False
    return True


def _replace_anchor_contents_with_text(anchor: Tag, text: str) -> None:
    anchor.clear()
    anchor.string = text


def _normalise_parenthesised_resource_item(soup: BeautifulSoup, li: Tag) -> tuple[bool, str | None]:
    """Normalise simple legacy list items such as:

    the release notes for Dyalog v19.0 (<a>PDF</a>)

    The surrounding prose is preserved word-for-word; only the resource label
    and presentational brackets/separator are changed.
    """
    direct_anchors = [child for child in li.children if isinstance(child, Tag) and child.name == "a"]
    other_tags = [
        child for child in li.children
        if isinstance(child, Tag) and child.name != "a"
    ]
    if len(direct_anchors) != 1 or other_tags:
        return False, None

    anchor = direct_anchors[0]
    current_label = anchor.get_text(" ", strip=True).lower()
    if current_label not in {"pdf", "github", "youtube"}:
        return False, None

    before_text_parts: list[NavigableString] = []
    after_text_parts: list[NavigableString] = []
    seen_anchor = False
    for child in list(li.children):
        if child is anchor:
            seen_anchor = True
            continue
        if not isinstance(child, NavigableString):
            return False, None
        (after_text_parts if seen_anchor else before_text_parts).append(child)

    before_text = "".join(str(node) for node in before_text_parts)
    after_text = "".join(str(node) for node in after_text_parts)
    if not before_text.rstrip().endswith("(") or not after_text.lstrip().startswith(")"):
        return False, None

    title = before_text.rstrip()[:-1].rstrip()
    remainder = after_text.lstrip()[1:]
    if not title:
        return False, None

    original = str(li)
    label = _label_for_link(anchor.get("href", ""), title)
    anchor.clear()
    anchor.string = label

    li.clear()
    strong = soup.new_tag("strong")
    strong.string = title
    li.append(strong)
    li.append(NavigableString(" – "))
    li.append(anchor)
    if remainder:
        li.append(NavigableString(remainder))
    return True, original


def _normalise_prefix_plus_icon_anchor(soup: BeautifulSoup, li: Tag, anchor: Tag) -> tuple[bool, str | None]:
    """Handle items such as ``the <a>release notes … <img></a>``.

    This pattern appears repeatedly in the old release pages. The words are
    preserved in the same order and the resource link becomes a separate action.
    """
    if anchor.find("img") is None:
        return False, None
    direct_tags = [child for child in li.children if isinstance(child, Tag)]
    if direct_tags != [anchor]:
        return False, None

    before = "".join(
        str(child) for child in li.children
        if isinstance(child, NavigableString) and child is not anchor.next_sibling
    )
    # We only support a simple text prefix followed by the single link.
    children = list(li.children)
    try:
        idx = children.index(anchor)
    except ValueError:
        return False, None
    prefix = "".join(str(child) for child in children[:idx] if isinstance(child, NavigableString))
    suffix = "".join(str(child) for child in children[idx + 1:] if isinstance(child, NavigableString))
    if any(isinstance(child, Tag) for child in children[:idx] + children[idx + 1:]):
        return False, None
    if suffix.strip():
        return False, None

    anchor_text = anchor.get_text(" ", strip=True).replace("\xa0", " ")
    title = (prefix + anchor_text).strip()
    if not title:
        return False, None

    original = str(li)
    label = _label_for_link(anchor.get("href", ""), title)
    anchor.clear()
    anchor.string = label
    li.clear()
    strong = soup.new_tag("strong")
    strong.string = title
    li.append(strong)
    li.append(NavigableString(" – "))
    li.append(anchor)
    return True, original


class StructureRule(Rule):
    rule_id = "STRUCTURE-001"
    description = "Replace legacy icon resource links and flag structural review items."
    may_change_copy = True

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []

        # First handle the non-icon ``(PDF)`` / ``(GitHub)`` resource-list
        # layout used on several release pages. Webinar lists have their own rule.
        for li in list(soup.find_all("li")):
            if any(_is_webinar_container(parent) for parent in li.parents if isinstance(parent, Tag) and parent.name == "li"):
                continue
            changed, original = _normalise_parenthesised_resource_item(soup, li)
            if changed:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="Resource list item clarified",
                        message="Replaced a bracketed resource type with the title – action-link layout.",
                        severity=Severity.SAFE,
                        before_html=original,
                        after_html=str(li),
                        applied=True,
                        changes_copy=True,
                    )
                )

        for anchor in list(soup.find_all("a", href=True)):
            image = anchor.find("img")
            if (
                image is None
                or not _looks_like_legacy_resource_icon(image)
                or _inside_webinar_list(anchor)
            ):
                continue

            parent_li = anchor.parent if anchor.parent and anchor.parent.name == "li" else None

            if parent_li is not None:
                changed_prefix, original_prefix = _normalise_prefix_plus_icon_anchor(soup, parent_li, anchor)
                if changed_prefix:
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            title="Legacy resource list item cleaned",
                            message="Separated the resource title from its legacy icon link.",
                            severity=Severity.SAFE,
                            before_html=original_prefix,
                            after_html=str(parent_li),
                            applied=True,
                            changes_copy=True,
                        )
                    )
                    continue

            before = str(parent_li if parent_li else anchor.parent if anchor.parent else anchor)
            anchor_text = anchor.get_text(" ", strip=True).replace("\xa0", " ")
            context = parent_li.get_text(" ", strip=True) if parent_li else anchor_text
            label = _label_for_link(anchor["href"], context)
            changed_copy = False

            # Old pages often have one link containing both a PDF/GitHub icon and
            # a useful title. Preserve that title. For a list item made solely of
            # that link, use the cleaner title – action-link layout used throughout
            # the migration work. For paragraphs/inline links, simply remove the
            # icon and append the file type.
            if anchor_text:
                if parent_li is not None and _li_is_effectively_only_anchor(parent_li, anchor):
                    strong = soup.new_tag("strong")
                    strong.string = anchor_text
                    anchor.insert_before(strong)
                    anchor.insert_before(NavigableString(" – "))
                    _replace_anchor_contents_with_text(anchor, label)
                    changed_copy = True
                else:
                    image.decompose()
                    # Remove the NBSP/whitespace the icon used to sit against,
                    # so the label does not end up with a doubled space.
                    text_children = [
                        child for child in anchor.children if isinstance(child, NavigableString)
                    ]
                    for index, child in enumerate(text_children):
                        cleaned = str(child).replace("\xa0", " ")
                        if index == 0:
                            cleaned = cleaned.lstrip()
                        if index == len(text_children) - 1:
                            cleaned = cleaned.rstrip()
                        child.replace_with(NavigableString(cleaned))
                    suffix = _suffix_for_link(anchor["href"])
                    current = anchor.get_text(" ", strip=True)
                    if suffix and not current.lower().endswith(suffix.lower()):
                        anchor.append(NavigableString(suffix))
                        changed_copy = True
            else:
                # Icon-only resource link. When it follows plain text in a list
                # item, keep that text as the title and turn the icon into an action
                # link. Otherwise just use a descriptive resource label.
                image.decompose()
                _replace_anchor_contents_with_text(anchor, label)
                changed_copy = True

                if parent_li is not None:
                    preceding = []
                    for child in list(parent_li.children):
                        if child is anchor:
                            break
                        preceding.append(child)
                    text_nodes = [
                        child for child in preceding
                        if isinstance(child, NavigableString) and child.strip()
                    ]
                    if len(text_nodes) == 1:
                        node = text_nodes[0]
                        title = str(node).strip()
                        strong = soup.new_tag("strong")
                        strong.string = title
                        node.replace_with(strong)
                        strong.insert_after(NavigableString(" – "))

            after_target = parent_li if parent_li else anchor.parent if anchor.parent else anchor
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title="Legacy resource icon removed",
                    message="Removed a legacy resource icon and replaced it with readable text where needed.",
                    severity=Severity.SAFE,
                    before_html=before,
                    after_html=str(after_target),
                    applied=True,
                    changes_copy=changed_copy,
                )
            )

        long_paragraph_threshold = int(self.config.get("long_paragraph_threshold", 650))
        paragraphs = soup.find_all("p")

        # A single <p> holding the whole article, with the paragraph breaks
        # surviving only as newlines. Splitting at every break changes only <p>
        # structure, so it is offered as one action rather than a long paragraph
        # suggestion the user would have to apply repeatedly.
        for index, paragraph in enumerate(paragraphs):
            breaks = line_break_count(paragraph)
            if breaks < 2:
                continue
            findings.append(
                Finding(
                    rule_id="PARAGRAPH-LINES-001",
                    title="One paragraph holding several",
                    message=(
                        f"This paragraph contains {breaks} line breaks, so it is probably "
                        f"{breaks + 1} paragraphs that lost their markup. Splitting at the "
                        "breaks changes only the paragraph structure; the words stay as "
                        "written. No change was made."
                    ),
                    severity=Severity.SUGGESTED,
                    before_html=str(paragraph)[:600],
                    applied=False,
                    metadata={"breaks": breaks},
                    action="split_paragraph_lines",
                    action_label=f"Split into {breaks + 1} paragraphs",
                    action_params={"index": index},
                )
            )

        for index, paragraph in enumerate(paragraphs):
            text = paragraph.get_text(" ", strip=True)
            if len(text) < long_paragraph_threshold:
                continue
            offset = suggest_split_offset(paragraph)
            if offset > 0:
                raw = paragraph.get_text()
                preview = raw[max(0, offset - 45):offset].strip()
                following = raw[offset:offset + 45].strip()
                message = (
                    f"This paragraph is {len(text)} characters. A sentence boundary sits "
                    f"after \u201c…{preview}\u201d, before \u201c{following}…\u201d. "
                    "No copy or HTML was changed."
                )
            else:
                message = (
                    f"This paragraph is {len(text)} characters and may benefit from a "
                    "logical split, but no safe sentence boundary was found. "
                    "No copy or HTML was changed."
                )
            findings.append(
                Finding(
                    rule_id="PARAGRAPH-REVIEW-001",
                    title="Long paragraph",
                    message=message,
                    severity=Severity.SUGGESTED,
                    before_html=str(paragraph),
                    applied=False,
                    metadata={"characters": len(text), "offset": offset},
                    action="split_paragraph" if offset > 0 else None,
                    action_label="Split here" if offset > 0 else None,
                    action_params={"index": index, "offset": offset} if offset > 0 else {},
                )
            )

        for anchor in soup.find_all("a", href=True):
            if not anchor.get_text(" ", strip=True) and anchor.find("img") is None:
                findings.append(
                    Finding(
                        rule_id="EMPTY-LINK-001",
                        title="Empty link",
                        message="This link has no readable text and needs manual review.",
                        severity=Severity.WARNING,
                        before_html=str(anchor),
                        applied=False,
                    )
                )

        return findings
