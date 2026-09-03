from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from app.models import Finding, Severity
from app.rules.base import Rule
from app.rules.structure import _looks_like_legacy_resource_icon


def _resource_label(href: str) -> str:
    parsed = urlparse(href)
    host = parsed.netloc.lower()
    suffix = PurePosixPath(parsed.path).suffix.lower()
    if "youtube.com" in host or "youtu.be" in host or "dyalog.tv" in host:
        return "Watch video"
    if suffix in {".ppt", ".pptx"}:
        return "PowerPoint"
    if suffix == ".pdf":
        return "PDF"
    if suffix == ".zip":
        return "Materials (ZIP)"
    if "github.com" in host:
        return "View on GitHub"
    return "View resource"


def _meaningful_direct_text_before(tag: Tag, stop: Tag) -> str:
    parts: list[str] = []
    for child in tag.children:
        if child is stop:
            break
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            parts.append(child.get_text(" ", strip=False))
    return "".join(parts).strip()


def _is_webinar_container(item: Tag) -> bool:
    direct_text = "".join(
        str(child) for child in item.children if isinstance(child, NavigableString)
    ).strip().lower()
    return direct_text.startswith("webinars:") or direct_text.startswith("webinar:")


class WebinarLayoutRule(Rule):
    rule_id = "WEBINAR-LAYOUT-001"
    description = "Turn icon-based webinar resources into clear text links."
    may_change_copy = True

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []

        webinar_lists: list[Tag] = []
        for item in soup.find_all("li"):
            nested = item.find("ul", recursive=False)
            if nested and _is_webinar_container(item):
                webinar_lists.append(nested)

        for webinar_list in webinar_lists:
            for item in webinar_list.find_all("li", recursive=False):
                before = str(item)
                changed = False
                anchors = item.find_all("a", recursive=False)
                if not anchors:
                    continue

                first_anchor = anchors[0]
                title_before = _meaningful_direct_text_before(item, first_anchor)
                first_anchor_text = first_anchor.get_text(" ", strip=True)

                # Old pages sometimes put the webinar title inside the video
                # link, with or without an icon. Move that title out before
                # replacing the link text with the action label.
                first_label = _resource_label(first_anchor.get("href", ""))
                title_inside_video_link = (
                    not title_before
                    and bool(first_anchor_text)
                    and first_label == "Watch video"
                    and first_anchor_text not in {"Watch video", "Watch on YouTube"}
                )
                if title_inside_video_link:
                    title = first_anchor_text
                    strong = soup.new_tag("strong")
                    strong.string = title
                    first_anchor.insert_before(strong)
                    first_anchor.insert_before(NavigableString(" – "))
                    changed = True
                elif title_before:
                    existing_strong = item.find("strong", recursive=False)
                    if existing_strong is None:
                        # Replace the direct text before the first link with a strong title.
                        for child in list(item.children):
                            if child is first_anchor:
                                break
                            if isinstance(child, NavigableString) and child.strip():
                                raw = str(child)
                                stripped = raw.strip()
                                strong = soup.new_tag("strong")
                                strong.string = stripped
                                child.replace_with(strong)
                                strong.insert_after(NavigableString(" – "))
                                changed = True
                                break

                # Replace icon links and title-bearing video links with action labels.
                anchors = item.find_all("a", recursive=False)
                for anchor in anchors:
                    label = _resource_label(anchor.get("href", ""))
                    image = anchor.find("img")
                    has_icon = image is not None and _looks_like_legacy_resource_icon(image)
                    current = anchor.get_text(" ", strip=True)
                    if has_icon or (label == "Watch video" and current not in {"Watch video", "Watch on YouTube"}):
                        anchor.clear()
                        anchor.string = label
                        changed = True

                # Add readable separators between resource links.
                anchors = item.find_all("a", recursive=False)
                for anchor in anchors[1:]:
                    previous = anchor.previous_sibling
                    previous_text = str(previous) if isinstance(previous, NavigableString) else ""
                    if "|" not in previous_text:
                        if isinstance(previous, NavigableString) and not previous.strip():
                            previous.replace_with(NavigableString(" | "))
                        else:
                            anchor.insert_before(NavigableString(" | "))
                        changed = True

                # Add a separator between the final resource and an existing description.
                last_anchor = anchors[-1]
                later_text = "".join(
                    child.get_text(" ", strip=False) if isinstance(child, Tag) else str(child)
                    for child in list(last_anchor.next_siblings)
                ).strip()
                immediate = last_anchor.next_sibling
                immediate_text = str(immediate) if isinstance(immediate, NavigableString) else ""
                if later_text and not immediate_text.lstrip().startswith(("–", "-", "|", ".", ",", ";", ":")):
                    if isinstance(immediate, NavigableString):
                        immediate.replace_with(NavigableString(" – " + immediate_text.lstrip()))
                    else:
                        last_anchor.insert_after(NavigableString(" – "))
                    changed = True

                if changed:
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            title="Webinar links clarified",
                            message="Bolded the webinar title and replaced icon-only resources with descriptive text links.",
                            severity=Severity.SAFE,
                            before_html=before,
                            after_html=str(item),
                            applied=True,
                            changes_copy=True,
                        )
                    )

        return findings
