from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.models import Finding, Severity
from app.rules.base import Rule


class URLRewriteRule(Rule):
    rule_id = "URL-REWRITE-001"
    description = "Apply explicit, profile-defined URL migrations."

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        rewrites: list[dict[str, Any]] = self.config.get("rewrites", [])

        for anchor in soup.find_all("a", href=True):
            original = anchor["href"]
            updated = original
            matched_rule: dict[str, Any] | None = None

            for rewrite in rewrites:
                if "from" in rewrite and updated.startswith(rewrite["from"]):
                    updated = rewrite["to"] + updated[len(rewrite["from"]):]
                    matched_rule = rewrite
                    break
                if "pattern" in rewrite:
                    candidate = re.sub(rewrite["pattern"], rewrite["replacement"], updated)
                    if candidate != updated:
                        updated = candidate
                        matched_rule = rewrite
                        break

            if updated == original:
                continue

            anchor["href"] = updated
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title="URL migrated",
                    message=matched_rule.get("description", "Rewrote a URL using the active profile.") if matched_rule else "Rewrote a URL using the active profile.",
                    severity=Severity.SAFE,
                    before_html=original,
                    after_html=updated,
                    applied=True,
                    metadata={"old_url": original, "new_url": updated},
                )
            )

        findings.extend(self._suggest_host_moves(soup))
        return findings

    def _suggest_host_moves(self, soup: BeautifulSoup) -> list[Finding]:
        """Flag links still pointing at a host that is being moved.

        These are *not* rewritten automatically. Only the specific paths named in
        `rewrites` above are established migrations (handoff 6.1); everything
        else on the old host may or may not exist at the new one, and 6.3 forbids
        guessing. So each distinct URL is offered as a suggestion the user can
        apply. The mapping is configuration, so reversing it at go-live is a
        config change rather than a code change.
        """
        moves: list[dict[str, str]] = self.config.get("host_suggestions", [])
        if not moves:
            return []

        seen: dict[str, tuple[str, str]] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            for move in moves:
                if parsed.netloc.lower() != str(move["from"]).lower():
                    continue
                target = parsed._replace(netloc=move["to"]).geturl()
                seen.setdefault(href, (target, str(anchor)[:300]))
                break

        findings: list[Finding] = []

        # One action per host, so 40 links across a post can be repointed in a
        # single press. The per-URL suggestions below remain for anything that
        # needs handling individually.
        for move in moves:
            host = str(move["from"])
            target_host = str(move["to"])
            matching = [
                href for href in seen
                if urlparse(href).netloc.lower() == host.lower()
            ]
            if len(matching) < 2:
                continue
            findings.append(
                Finding(
                    rule_id="URL-HOST-ALL-001",
                    title=f"{len(matching)} links still on {host}",
                    message=(
                        f"{len(matching)} links point at {host}. Repointing them all at "
                        f"{target_host} changes only the host; every path, query and "
                        "fragment is preserved exactly. Check the files exist there first "
                        "\u2014 the Links tab can do that for you."
                    ),
                    severity=Severity.SUGGESTED,
                    before_html="<br>".join(sorted(matching)[:12]),
                    applied=False,
                    metadata={"host": host, "target_host": target_host, "count": len(matching)},
                    action="rewrite_host",
                    action_label=f"Repoint all {len(matching)}",
                    action_params={"from_host": host},
                    action_input_label="New host",
                    action_input_default=target_host,
                )
            )

        for href, (target, anchor_html) in sorted(seen.items()):
            count = len(soup.find_all("a", href=href))
            findings.append(
                Finding(
                    rule_id="URL-HOST-001",
                    title="Link still points at the old site",
                    message=(
                        f"{href} is on a host that is being moved. "
                        + (f"It appears {count} times. " if count > 1 else "")
                        + "Only the configured presentation paths are migrated "
                        "automatically, because the app must never guess whether a "
                        "URL exists at the new host. No change was made."
                    ),
                    severity=Severity.SUGGESTED,
                    before_html=anchor_html,
                    applied=False,
                    metadata={"old_url": href, "new_url": target, "count": count},
                    action="rewrite_url",
                    action_label="Point at the new site",
                    action_params={"from_url": href},
                    action_input_label="New URL",
                    action_input_default=target,
                )
            )
        return findings
