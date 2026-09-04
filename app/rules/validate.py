from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString

from app.models import Finding, Severity
from app.rules.base import Rule
from app.rules.apl_markup import APL_SIGNAL_RE, _inside_code_like, _raw_candidates
from app.rules.links import _is_http_link, _normalise_host
from app.rules.structure import _looks_like_legacy_resource_icon, _resource_kind


def _contains_apl(text: str) -> bool:
    """Whether this code contains APL.

    Both tiers count here, unlike raw-token detection in prose: inside a <code>
    element an arrow or a multiplication sign is strong evidence, where in a
    sentence it is not.
    """
    return bool(APL_SIGNAL_RE.search(text))


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

        # A YouTube video id is 11 characters of [A-Za-z0-9_-]. One corpus post
        # had ?v=https:aIqDxwlcoVU in the source, which the dyalog.tv migration
        # faithfully carried into a youtube.com URL that cannot work. Handoff 6.3
        # forbids repairing it, so it is reported instead.
        for anchor_tag in soup.find_all("a", href=True):
            href = str(anchor_tag["href"])
            match = re.search(r"youtube\.com/watch\?v=([^&]+)", href)
            if not match:
                continue
            video_id = match.group(1)
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            findings.append(
                Finding(
                    rule_id="VIDEO-ID-001",
                    title="Video id does not look valid",
                    message=(
                        f'The video id "{video_id}" is not 11 characters of letters, '
                        "digits, hyphen or underscore, so this link will not play. The id "
                        "was taken from the source exactly as written and has not been "
                        "altered — find the right one and correct it by hand."
                    ),
                    severity=Severity.WARNING,
                    before_html=str(anchor_tag)[:300],
                    applied=False,
                    metadata={"video_id": video_id},
                )
            )

        # Malformed source can nest one <code> inside another.
        for code in soup.find_all("code"):
            if code.find("code") is not None:
                findings.append(
                    Finding(
                        rule_id="NESTED-CODE-001",
                        title="Code element nested inside another",
                        message=(
                            "A <code> element contains another <code>. This came from the "
                            "source and is almost certainly a stray tag there; it will not "
                            "render as intended. Fix it in the source or by hand."
                        ),
                        severity=Severity.WARNING,
                        before_html=str(code)[:300],
                        applied=False,
                    )
                )

        for code in soup.find_all("code"):
            language_classes = [name for name in code.get("class", []) if name.startswith("language-")]
            if language_classes:
                continue
            # Code the APL rule deliberately left alone, because it is evidently
            # another language, is a Suggestion for the user to label. Only
            # unlabelled *APL* is a rule failure.
            if _contains_apl(code.get_text()):
                findings.append(
                    self._error(
                        "Unclassified APL code remains",
                        "This code contains APL glyphs but has no language-* class.",
                        str(code),
                        code="OUTPUT-CODE-CLASS-001",
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id="OUTPUT-CODE-CLASS-002",
                        title="Code has no language",
                        message=(
                            "This code has no language-* class. It does not look like APL, "
                            "so nothing was assumed; set the language so the site "
                            "highlights it correctly."
                        ),
                        severity=Severity.SUGGESTED,
                        before_html=str(code)[:300],
                        applied=False,
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
