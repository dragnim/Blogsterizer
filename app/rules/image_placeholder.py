"""Replace every `<img>` with a placeholder.

Images are not carried into the new markup. The old `src` points at the site
being migrated away from, so passing it through would publish a hotlink to
`www.dyalog.com` — and the images themselves are processed separately, into
renamed WebP files, then placed by hand.

So every `<img>` becomes a conspicuous placeholder naming the file it stood for.
This deliberately overrides handoff section 11 ("normal images must survive"),
which was written when the app was destroying images silently. Nothing is
destroyed here: the filename is preserved in the placeholder, and the image
itself is in your folder.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, Tag

from app.models import Finding, Severity
from app.rules.base import Rule


def source_name(tag: Tag) -> str:
    src = str(tag.get("src", "")).strip()
    if not src:
        return ""
    path = urlparse(src).path if "://" in src else src
    return unquote(Path(path).name)


def placeholder_text(tag: Tag, position: int) -> str:
    name = source_name(tag)
    return f"Image here: {name}" if name else f"Image here: image {position:02d}"


class ImagePlaceholderRule(Rule):
    rule_id = "IMAGE-PLACEHOLDER-001"
    description = "Replace each <img> with a placeholder naming the file it stood for."
    # The placeholder text is new visible copy, so the per-rule guard has to be
    # told this rule is allowed to add it. The words it adds are its own, not a
    # rewrite of anything the author wrote.
    may_change_copy = True

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        if not bool(self.config.get("replace_images", True)):
            return []

        findings: list[Finding] = []

        for position, tag in enumerate(soup.find_all("img"), start=1):
            # An image already replaced by the Images step is left alone.
            before = str(tag)
            text = placeholder_text(tag, position)
            alt = str(tag.get("alt", "")).strip()

            # A thumbnail that links somewhere carries information the
            # placeholder must not swallow: <a href="report.pdf"><img></a> is a
            # link to the report. Keep the anchor and put the placeholder inside
            # it, so the href survives for you to deal with.
            parent = tag.parent
            linked = (
                isinstance(parent, Tag)
                and parent.name == "a"
                and bool(parent.get("href"))
            )

            target = tag
            if not linked:
                # A wrapper whose only content is this image goes too: a block
                # placeholder inside a <p> is invalid, and an empty wrapper is
                # pointless.
                for _ in range(3):
                    holder = target.parent
                    if holder is None or holder.name not in {"a", "p", "figure", "span", "div"}:
                        break
                    if holder.get_text(strip=True):
                        break
                    if any(
                        child is not target and getattr(child, "name", None) is not None
                        for child in holder.children
                    ):
                        break
                    target = holder

            inline = linked or (
                target is tag
                and bool(tag.parent is not None and tag.parent.get_text(strip=True))
            )

            if inline:
                marker = soup.new_tag("strong")
                marker["class"] = ["image-placeholder"]
                marker.string = f"[{text}]"
            else:
                marker = soup.new_tag("p")
                marker["class"] = ["image-placeholder"]
                strong = soup.new_tag("strong")
                strong.string = text
                marker.append(strong)

            target.replace_with(marker)

            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title="Image replaced with a placeholder",
                    message=(
                        f"Replaced an <img> with \u201c{text}\u201d. Images are not carried "
                        "into the new markup: the old src points at the site being migrated "
                        "away from. Add the processed image here by hand."
                        + (f' The original alt text was "{alt}".' if alt else "")
                    ),
                    severity=Severity.SAFE,
                    before_html=before,
                    after_html=str(marker),
                    applied=True,
                    changes_copy=True,
                    metadata={"file": source_name(tag), "alt": alt},
                )
            )

        return findings
