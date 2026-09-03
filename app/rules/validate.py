from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString

from app.models import Finding, Severity
from app.rules.base import Rule
from app.rules.apl_markup import _inside_code_like, _raw_candidates
from app.rules.links import _is_http_link, _normalise_host
from app.rules.structure import _looks_like_legacy_resource_icon, _resource_kind


class OutputValidationRule(Rule):
    """Read-only invariant checks for the final Dyalog HTML.

    These checks exist because the Blogsterizer's core conventions are important
    enough that a future regression should appear as an ERROR in the interface,
    not merely as a failed unit test noticed later.
    """

    rule_id = "OUTPUT-VALIDATION-001"
    description = "Verify the final output against the core Dyalog migration invariants."

    def _error(self, title: str, message: str, html: str, *, code: str) -> Finding:
        return Finding(
            rule_id=code,
            title=title,
            message=message,
            severity=Severity.ERROR,
            before_html=html,
            applied=False,
        )

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        link_config = self.config.get("link_policy", {})
        internal_hosts = {
            _normalise_host(host)
            for host in link_config.get("internal_hosts", [])
        }
        external_class = link_config.get("external_class", "ex-link")

        # APL markup invariants.
        for element in soup.find_all(["span", "font"]):
            classes = set(element.get("class", []))
            if classes.intersection({"APLFont", "language-apl"}):
                findings.append(
                    self._error(
                        "Legacy APL wrapper remains",
                        "APL markup should use <code class=\"language-apl\">, not a span/font wrapper.",
                        str(element),
                        code="OUTPUT-APL-WRAPPER-001",
                    )
                )

        for code in soup.find_all("code"):
            language_classes = [name for name in code.get("class", []) if name.startswith("language-")]
            if not language_classes:
                findings.append(
                    self._error(
                        "Unclassified code remains",
                        "Every code element in a Dyalog profile must have an explicit language-* class.",
                        str(code),
                        code="OUTPUT-CODE-CLASS-001",
                    )
                )

        for text_node in soup.find_all(string=True):
            if not isinstance(text_node, NavigableString) or _inside_code_like(text_node):
                continue
            if _raw_candidates(str(text_node)):
                findings.append(
                    self._error(
                        "Unwrapped APL remains",
                        "Unmistakable APL text remains outside code.language-apl.",
                        str(text_node),
                        code="OUTPUT-RAW-APL-001",
                    )
                )

        # Known editor cruft must not survive.
        for element in soup.find_all(True):
            classes = set(element.get("class", []))
            leftovers = classes.intersection({"fclear", "APLFont", "code-line"})
            if leftovers:
                findings.append(
                    self._error(
                        "Legacy class remains",
                        f"Known obsolete class(es) remain: {', '.join(sorted(leftovers))}.",
                        str(element),
                        code="OUTPUT-LEGACY-CLASS-001",
                    )
                )
            if str(element.get("dir", "")).lower() == "auto":
                findings.append(
                    self._error(
                        'dir="auto" remains',
                        'Editor-generated dir="auto" should have been removed.',
                        str(element),
                        code="OUTPUT-DIR-AUTO-001",
                    )
                )

        # Link policy and URL-migration invariants.
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            classes = set(anchor.get("class", []))

            if href.startswith("https://www.dyalog.com/uploads/files/presentations/"):
                findings.append(
                    self._error(
                        "Old presentation URL remains",
                        "This presentation URL should have been migrated to dyalogprod.gos.dyalog.com.",
                        str(anchor),
                        code="OUTPUT-PRESENTATION-URL-001",
                    )
                )
            if href.startswith("https://dyalog.tv/"):
                findings.append(
                    self._error(
                        "dyalog.tv URL remains",
                        "Configured dyalog.tv video links should have been converted to direct YouTube links.",
                        str(anchor),
                        code="OUTPUT-DYALOG-TV-001",
                    )
                )

            if _is_http_link(href):
                parsed = urlparse(href)
                host = _normalise_host(parsed.hostname or parsed.netloc)
                is_internal = host in internal_hosts
                if is_internal:
                    if external_class in classes:
                        findings.append(
                            self._error(
                                "Internal link has ex-link",
                                "Current Dyalog-site links must not carry the external-link class.",
                                str(anchor),
                                code="OUTPUT-INTERNAL-EXLINK-001",
                            )
                        )
                else:
                    rel = set(anchor.get("rel", []))
                    missing: list[str] = []
                    if external_class not in classes:
                        missing.append(f'class="{external_class}"')
                    if anchor.get("target") != "_blank":
                        missing.append('target="_blank"')
                    if "noopener" not in rel:
                        missing.append('rel="noopener"')
                    if missing:
                        findings.append(
                            self._error(
                                "External-link policy incomplete",
                                "External link is missing: " + ", ".join(missing) + ".",
                                str(anchor),
                                code="OUTPUT-EXTERNAL-LINK-001",
                            )
                        )

            # A recognised legacy resource icon should have been converted to a
            # readable text link. Normal image links/logos are not flagged.
            image = anchor.find("img")
            if (
                image is not None
                and _looks_like_legacy_resource_icon(image)
                and _resource_kind(href) != "resource"
            ):
                findings.append(
                    self._error(
                        "Legacy resource icon remains",
                        "A recognised PDF/PPT/ZIP/video/GitHub resource link still contains an image icon.",
                        str(anchor),
                        code="OUTPUT-RESOURCE-ICON-001",
                    )
                )

        return findings
