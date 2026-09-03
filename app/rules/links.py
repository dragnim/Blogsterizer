from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.models import Finding, Severity
from app.rules.base import Rule


def _normalise_host(host: str) -> str:
    return host.lower().strip("[]").rstrip(".")


def _is_http_link(href: str) -> bool:
    parsed = urlparse(href)
    # Treat protocol-relative URLs (//example.com/path) as web links too.
    return parsed.scheme in {"http", "https"} or (not parsed.scheme and bool(parsed.netloc))


class LinkPolicyRule(Rule):
    rule_id = "LINK-POLICY-001"
    description = "Apply Dyalog internal/external link conventions."

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        internal_hosts = {_normalise_host(host) for host in self.config.get("internal_hosts", [])}
        external_class = self.config.get("external_class", "ex-link")
        open_external = bool(self.config.get("open_external_in_new_window", True))

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            parsed = urlparse(href)
            host = _normalise_host(parsed.hostname or parsed.netloc)
            is_web_link = _is_http_link(href)
            is_internal = (not is_web_link) or host in internal_hosts
            is_external = is_web_link and not is_internal

            before = str(anchor)
            actions: list[str] = []
            classes = list(anchor.get("class", []))

            if is_external:
                # Core Blogsterizer convention: every external web link receives
                # ex-link, opens in a new window, and has noopener.
                if external_class not in classes:
                    classes.append(external_class)
                    actions.append(f'added class="{external_class}"')
                if classes:
                    anchor["class"] = classes

                if open_external and anchor.get("target") != "_blank":
                    anchor["target"] = "_blank"
                    actions.append('set target="_blank"')

                rel = list(anchor.get("rel", []))
                if "noopener" not in rel:
                    rel.append("noopener")
                    anchor["rel"] = rel
                    actions.append('added rel="noopener"')
            else:
                # Internal links never carry ex-link. Preserve an existing
                # target="_blank" because some downloadable assets were
                # intentionally configured that way in the source content.
                if external_class in classes:
                    classes = [item for item in classes if item != external_class]
                    actions.append(f'removed class="{external_class}"')
                    if classes:
                        anchor["class"] = classes
                    elif anchor.has_attr("class"):
                        del anchor["class"]

                # Any new-window link, internal or external, should have noopener.
                if anchor.get("target") == "_blank":
                    rel = list(anchor.get("rel", []))
                    if "noopener" not in rel:
                        rel.append("noopener")
                        anchor["rel"] = rel
                        actions.append('added rel="noopener"')

            if actions:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title="Link attributes updated",
                        message="Link policy: " + "; ".join(actions) + ".",
                        severity=Severity.SAFE,
                        before_html=before,
                        after_html=str(anchor),
                        applied=True,
                        metadata={
                            "href": href,
                            "host": host,
                            "external": is_external,
                            "target_blank": anchor.get("target") == "_blank",
                            "actions": actions,
                        },
                    )
                )

        return findings
