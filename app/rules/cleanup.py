from __future__ import annotations

from bs4 import BeautifulSoup, Comment, Tag

from app.models import Finding, Severity
from app.rules.base import Rule


class CleanupRule(Rule):
    rule_id = "HTML-CLEANUP-001"
    description = "Remove legacy classes, data attributes, presentational attributes, and empty wrappers."

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []

        strip_data = bool(self.config.get("strip_data_attributes", True))
        remove_attributes = set(self.config.get("remove_attributes", ["style", "align"]))
        remove_attribute_values = {
            str(attr).lower(): {str(value).lower() for value in values}
            for attr, values in self.config.get("remove_attribute_values", {}).items()
        }
        # Handoff 4.3: known junk is removed automatically, an explicitly
        # required class is preserved, and an unrecognised class is reported
        # rather than destroyed. "allowlist" remains available for a profile
        # that genuinely wants to strip everything it does not name.
        class_mode = self.config.get("class_mode", "known")
        removable_classes = set(self.config.get("remove_classes", ["fclear", "APLFont", "code-line"]))
        removable_prefixes = tuple(self.config.get(
            "remove_class_prefixes",
            ["wp-", "has-", "is-style-", "align", "attachment-", "size-"],
        ))
        allowed_by_tag = {
            tag: set(values)
            for tag, values in self.config.get("allowed_classes", {}).items()
        }
        allowed_prefixes_by_tag = {
            tag: tuple(values)
            for tag, values in self.config.get("allowed_class_prefixes", {}).items()
        }
        global_allowed = set(self.config.get("global_allowed_classes", []))

        for element in list(soup.find_all(True)):
            before = str(element)
            removed_attrs: list[str] = []
            removed_classes: list[str] = []

            # data-* is editing/plugin cruft in the content we are migrating.
            if strip_data:
                for attr in list(element.attrs):
                    if attr.lower().startswith("data-"):
                        del element.attrs[attr]
                        removed_attrs.append(attr)

            for attr in list(remove_attributes):
                if element.has_attr(attr):
                    del element.attrs[attr]
                    removed_attrs.append(attr)

            for attr, blocked_values in remove_attribute_values.items():
                if not element.has_attr(attr):
                    continue
                current = str(element.get(attr, "")).lower()
                if current in blocked_values:
                    del element.attrs[attr]
                    removed_attrs.append(attr)

            classes = list(element.get("class", []))
            if classes:
                if class_mode == "allowlist":
                    allowed = global_allowed | allowed_by_tag.get(element.name, set())
                    allowed_prefixes = allowed_prefixes_by_tag.get(element.name, ())
                    kept = [
                        name for name in classes
                        if name in allowed or any(name.startswith(prefix) for prefix in allowed_prefixes)
                    ]
                    removed_classes = [name for name in classes if name not in kept]
                else:
                    kept = []
                    for name in classes:
                        if name in removable_classes or any(name.startswith(prefix) for prefix in removable_prefixes):
                            removed_classes.append(name)
                        else:
                            kept.append(name)

                if kept:
                    element["class"] = kept
                elif element.has_attr("class"):
                    del element["class"]

            if removed_attrs or removed_classes:
                details: list[str] = []
                if removed_classes:
                    details.append("classes: " + ", ".join(removed_classes))
                if removed_attrs:
                    details.append("attributes: " + ", ".join(removed_attrs))
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="Legacy HTML cleaned",
                        message="Removed " + "; ".join(details) + ".",
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html=str(element),
                        applied=True,
                    )
                )


        # Handoff 4.1: syntax highlighters (Prism, highlight.js) wrap every token
        # in a <span> of their own. That markup is generated at render time by
        # whatever highlighter the old site used, so it is editor cruft in the
        # same family as code-line, and the new site's highlighter will produce
        # its own. Unwrapping keeps the text exactly.
        markers = set(self.config.get("highlighter_classes", ["token"]))
        marker_prefixes = tuple(self.config.get("highlighter_class_prefixes", ["hljs-"]))
        if markers or marker_prefixes:
            for span in soup.find_all("span", class_=True):
                classes = span.get("class", [])
                if not any(
                    name in markers or name.startswith(marker_prefixes) for name in classes
                ):
                    continue
                before = str(span)
                span.unwrap()
                findings.append(
                    Finding(
                        rule_id="HIGHLIGHTER-SPAN-001",
                        title="Highlighter span removed",
                        message=(
                            "Removed a syntax-highlighter <span> "
                            f'(class="{" ".join(classes)}"), keeping its text. The new site '
                            "highlights code itself."
                        ),
                        severity=Severity.SAFE,
                        before_html=before,
                        applied=True,
                        metadata={"classes": classes},
                    )
                )

        # Legacy presentational attributes on table cells. Seen as
        # <td width="200px"> in the corpus: layout markup that the site's own
        # CSS should decide, in the same family as align= (handoff 4.1).
        for attribute in self.config.get("remove_table_attributes", ["width", "height"]):
            for cell in soup.find_all(["td", "th", "table"]):
                if not cell.has_attr(attribute):
                    continue
                before = str(cell)[:200]
                del cell[attribute]
                findings.append(
                    Finding(
                        rule_id="TABLE-ATTR-001",
                        title="Legacy table attribute removed",
                        message=(
                            f'Removed {attribute}="..." from a <{cell.name}>. Table sizing '
                            "belongs to the site's stylesheet."
                        ),
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html=str(cell)[:200],
                        applied=True,
                    )
                )

        # An empty paragraph, usually a lone &nbsp; left by the classic editor,
        # renders as a stray gap and becomes an empty Gutenberg block.
        if bool(self.config.get("remove_empty_paragraphs", True)):
            for paragraph in soup.find_all("p"):
                if paragraph.find(["img", "br", "hr", "iframe", "input"]):
                    continue
                text = paragraph.get_text().replace("\xa0", " ").strip()
                if text:
                    continue
                before = str(paragraph)
                paragraph.decompose()
                findings.append(
                    Finding(
                        rule_id="EMPTY-PARAGRAPH-001",
                        title="Empty paragraph removed",
                        message=(
                            "Removed a paragraph containing nothing but whitespace. The "
                            "classic editor left these behind; in Gutenberg it becomes an "
                            "empty block."
                        ),
                        severity=Severity.SAFE,
                        before_html=before,
                        applied=True,
                    )
                )

        # Handoff 4.3: an unknown class might carry intentional styling or
        # semantics, so it survives and is reported once for human review.
        if class_mode != "allowlist" and bool(self.config.get("report_unknown_classes", True)):
            known_good = set(self.config.get("known_classes", ["ex-link"]))
            known_good_prefixes = tuple(self.config.get("known_class_prefixes", ["language-"]))
            unknown: dict[str, str] = {}
            for element in soup.find_all(class_=True):
                for name in element.get("class", []):
                    if name in known_good or name.startswith(known_good_prefixes):
                        continue
                    unknown.setdefault(name, str(element))
            for name, example in sorted(unknown.items()):
                findings.append(
                    Finding(
                        rule_id="UNKNOWN-CLASS-001",
                        title="Unrecognised class kept",
                        message=(
                            f'class="{name}" is not a known junk class, so it was kept. '
                            "Remove it by hand if it is editor cruft."
                        ),
                        severity=Severity.SUGGESTED,
                        before_html=example,
                        applied=False,
                        metadata={"class": name},
                        action="remove_class",
                        action_label=f'Remove class="{name}"',
                        action_params={"class_name": name},
                    )
                )

        # Replace non-breaking spaces used as layout glue in legacy HTML with
        # ordinary spaces, but never touch code/preformatted content.
        if bool(self.config.get("normalize_nbsp", True)):
            for text_node in list(soup.find_all(string=True)):
                if "\xa0" not in str(text_node):
                    continue
                parent = text_node.parent
                if parent and parent.name in {"code", "pre", "script", "style", "textarea"}:
                    continue
                before = str(text_node)
                text_node.replace_with(before.replace("\xa0", " "))
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="Legacy spacing normalised",
                        message="Replaced a non-breaking space used as layout spacing with a normal space.",
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html=before.replace("\xa0", " "),
                        applied=True,
                    )
                )

        # Comments from page builders/editors are not useful in pasted content.
        if bool(self.config.get("remove_comments", True)):
            for comment in list(soup.find_all(string=lambda text: isinstance(text, Comment))):
                before = str(comment)
                comment.extract()
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="HTML comment removed",
                        message="Removed an HTML comment.",
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html="",
                        applied=True,
                    )
                )

        # Once legacy classes/attributes are gone, plain spans add no semantics.
        if bool(self.config.get("unwrap_empty_spans", True)):
            for span in list(soup.find_all("span")):
                if span.attrs:
                    continue
                before = str(span)
                span.unwrap()
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="Redundant span removed",
                        message="Removed an attribute-free <span> wrapper without changing its text.",
                        severity=Severity.SAFE,
                        before_html=before,
                        applied=True,
                    )
                )

        return findings
