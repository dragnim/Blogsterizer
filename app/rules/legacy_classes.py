from __future__ import annotations

from bs4 import BeautifulSoup

from app.models import Finding, Severity
from app.rules.base import Rule


class LegacyClassRule(Rule):
    rule_id = "LEGACY-CLASS-001"
    description = "Remove configured obsolete CSS classes without disturbing other classes."

    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        findings: list[Finding] = []
        remove_classes = set(self.config.get("remove", ["fclear"]))

        for element in soup.find_all(class_=True):
            current = list(element.get("class", []))
            kept = [name for name in current if name not in remove_classes]
            removed = [name for name in current if name in remove_classes]
            if not removed:
                continue

            before = str(element)
            if kept:
                element["class"] = kept
            else:
                del element["class"]

            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title="Obsolete class removed",
                    message=f"Removed obsolete class{'es' if len(removed) > 1 else ''}: {', '.join(removed)}.",
                    severity=Severity.SAFE,
                    before_html=before,
                    after_html=str(element),
                    applied=True,
                )
            )

        return findings
