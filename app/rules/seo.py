"""Report-only SEO and document-structure checks.

Every finding here is a Warning or a Suggestion. Nothing in this module changes
the HTML, because heading levels, link wording and alt text are editorial
decisions (handoff 10). The rule reports; a human decides.
"""
from __future__ import annotations

from collections import Counter

from bs4 import BeautifulSoup, NavigableString, Tag

from app.actions import suggest_unique_id
from app.models import Finding, Severity
from app.rules.base import Rule


HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]

# Link text that tells a reader (and a search engine) nothing about the target.
VAGUE_LINK_TEXT = {
    "click here", "here", "this", "link", "this link", "read more", "more",
    "more info", "more information", "download", "see here", "go", "page",
}


def _level(tag: Tag) -> int:
    return int(tag.name[1])


class SEORule(Rule):
    rule_id = "SEO-001"
    description = "Report SEO and document-structure issues without changing anything."

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []

        if bool(self.config.get("flag_h1", True)):
            findings.extend(self._h1(soup))
        if bool(self.config.get("check_heading_order", True)):
            findings.extend(self._heading_order(soup))
        if bool(self.config.get("check_fake_headings", True)):
            findings.extend(self._fake_headings(soup))
        if bool(self.config.get("check_image_alt", True)):
            findings.extend(self._image_alt(soup))
        if bool(self.config.get("check_link_text", True)):
            findings.extend(self._link_text(soup))
        if bool(self.config.get("check_duplicate_ids", True)):
            findings.extend(self._duplicate_ids(soup))

        return findings

    def _h1(self, soup: BeautifulSoup) -> list[Finding]:
        # WordPress renders the post title as the page's only <h1>, so an <h1>
        # inside the body gives the page a second top-level heading.
        return [
            Finding(
                rule_id="SEO-H1-001",
                title="Heading level 1 in post body",
                message=(
                    f'"{heading.get_text(" ", strip=True)}" is an <h1>. WordPress already '
                    "uses the post title as the page's <h1>, so this gives the page two. "
                    "It is probably meant to be an <h2>. No change was made."
                ),
                severity=Severity.WARNING,
                before_html=str(heading)[:300],
                applied=False,
                metadata={"text": heading.get_text(" ", strip=True)},
                action="demote_heading",
                action_label="Change to <h2>",
                action_params={"tag": "h1", "index": index},
            )
            for index, heading in enumerate(soup.find_all("h1"))
        ]

    def _heading_order(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        previous: Tag | None = None
        for heading in soup.find_all(HEADINGS):
            if previous is not None and _level(heading) > _level(previous) + 1:
                findings.append(
                    Finding(
                        rule_id="SEO-HEADING-ORDER-001",
                        title="Heading level skipped",
                        message=(
                            f"<{heading.name}> follows <{previous.name}>, skipping a level. "
                            "Screen readers and search engines read the heading levels as an "
                            "outline. No change was made."
                        ),
                        severity=Severity.SUGGESTED,
                        before_html=str(heading)[:300],
                        applied=False,
                        metadata={"from": previous.name, "to": heading.name},
                    )
                )
            previous = heading
        return findings

    def _fake_headings(self, soup: BeautifulSoup) -> list[Finding]:
        """A paragraph whose whole content is bold is usually a heading in disguise."""
        findings: list[Finding] = []
        paragraphs = soup.find_all("p")
        for paragraph in paragraphs:
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
            findings.append(
                Finding(
                    rule_id="SEO-FAKE-HEADING-001",
                    title="Bold paragraph used as a heading",
                    message=(
                        f'"{text}" is a paragraph of bold text. If it is a section heading it '
                        "should be a real heading element so it appears in the page outline. "
                        "No change was made."
                    ),
                    severity=Severity.SUGGESTED,
                    before_html=str(paragraph)[:300],
                    applied=False,
                    metadata={"text": text},
                    action="promote_bold_paragraph",
                    action_label="Make this an <h3>",
                    action_params={"index": paragraphs.index(paragraph), "level": 3},
                )
            )
        return findings

    def _image_alt(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        for image in soup.find_all("img"):
            if image.has_attr("alt"):
                # alt="" is the correct marking for a decorative image.
                continue
            findings.append(
                Finding(
                    rule_id="SEO-IMG-ALT-001",
                    title="Image has no alt attribute",
                    message=(
                        "This image has no alt text. Add a description, or alt=\"\" if it is "
                        "purely decorative. No change was made."
                    ),
                    severity=Severity.WARNING,
                    before_html=str(image)[:300],
                    applied=False,
                    metadata={"src": image.get("src", "")},
                )
            )
        return findings

    def _link_text(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        for anchor in soup.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True)
            if not text or text.lower().strip(" .!?:;") not in VAGUE_LINK_TEXT:
                continue
            findings.append(
                Finding(
                    rule_id="SEO-LINK-TEXT-001",
                    title="Link text is not descriptive",
                    message=(
                        f'"{text}" does not describe where the link goes. Descriptive wording '
                        "helps readers and search engines. Changing it is a copy change, so "
                        "nothing was altered."
                    ),
                    severity=Severity.SUGGESTED,
                    before_html=str(anchor)[:300],
                    applied=False,
                    metadata={"text": text, "href": anchor["href"]},
                )
            )
        return findings

    def _duplicate_ids(self, soup: BeautifulSoup) -> list[Finding]:
        counts = Counter(
            element["id"] for element in soup.find_all(id=True) if str(element["id"]).strip()
        )
        findings: list[Finding] = []
        for value, count in sorted(counts.items()):
            if count < 2:
                continue
            duplicates = soup.find_all(id=value)
            # Offer a rename on *every* occurrence, not just the later ones, and
            # show each one what it collides with. Renaming the first is the
            # riskier choice because that is the one existing anchor links
            # currently reach, so it says so.
            for occurrence, element in enumerate(duplicates):
                others = [
                    {
                        "position": str(other_index + 1),
                        "html": str(other)[:300],
                        "text": other.get_text(" ", strip=True)[:120],
                    }
                    for other_index, other in enumerate(duplicates)
                    if other_index != occurrence
                ]
                if occurrence == 0:
                    caution = (
                        " This is the first occurrence, so it is the one existing links to "
                        f"#{value} currently reach. Renaming it will break those links; "
                        "renaming a later one will not."
                    )
                else:
                    caution = (
                        f" This is occurrence {occurrence + 1}, which no link can currently "
                        "reach."
                    )
                findings.append(
                    Finding(
                        rule_id="SEO-DUPLICATE-ID-001",
                        title="Duplicate id",
                        message=(
                            f'id="{value}" is used {count} times and ids must be unique.'
                            + caution
                            + " No change was made."
                        ),
                        severity=Severity.WARNING,
                        before_html=str(element)[:300],
                        applied=False,
                        metadata={"id": value, "count": count, "occurrence": occurrence},
                        action="set_id",
                        action_label="Change id",
                        action_params={"id": value, "occurrence": occurrence},
                        action_input_label="New id",
                        action_input_default=suggest_unique_id(soup, value, element),
                        related=others,
                    )
                )
        return findings
