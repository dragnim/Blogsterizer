"""A working session: one source document plus the fixes the user has applied.

The counters were confusing because two different questions shared one row of
numbers. They are now separated:

* **Safe** answers "what did the cleaner do to my source?". It is measured once,
  against the original source, and does not move as you work.
* **Suggestions / Warnings / Errors** answer "what still needs me?". They are
  measured against the current state and go down as you resolve them.
* **Fixed** counts the changes you chose to apply, and can be undone.

Nothing is stored on the server. The source and the list of applied fixes are
carried in the form, and the whole state is rebuilt by replaying the fixes from
the original each time. Replay is deterministic because each fix was recorded
against the document as it stood after the previous one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.actions import (
    ActionError,
    apply_action,
    highlight_additions,
    preview_action,
    preview_blocks,
)
from app.engine import analyse_html
from app.images import ImageReport, basename_of
from app.models import AnalysisResult, Finding, Severity


@dataclass
class AppliedFix:
    action: str
    params: dict[str, Any]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "params": self.params, "message": self.message}


@dataclass
class Session:
    """Everything the results page needs to render."""

    source: str
    baseline: AnalysisResult
    current: AnalysisResult
    fixes: list[AppliedFix] = field(default_factory=list)
    error: str | None = None
    images: ImageReport | None = None
    image_slug: str = ""
    sidecar: str = ""

    @property
    def cleaned_html(self) -> str:
        return self.current.cleaned_html

    @property
    def block_markup(self) -> str:
        return self.current.block_markup

    @property
    def diff(self) -> str:
        return self.current.diff

    @property
    def copy_preserved(self) -> bool:
        return self.baseline.copy_preserved and self.current.copy_preserved

    @property
    def copy_guard_message(self) -> str:
        if not self.baseline.copy_preserved:
            return self.baseline.copy_guard_message
        return self.current.copy_guard_message

    @property
    def export_safe(self) -> bool:
        return self.copy_preserved and self.counts["error"] == 0

    @property
    def safe_findings(self) -> list[Finding]:
        """What the cleaner did, measured once against the original source."""
        return [f for f in self.baseline.findings if f.severity == Severity.SAFE]

    @property
    def open_findings(self) -> list[Finding]:
        """What still needs a human, measured against the current state."""
        return [f for f in self.current.findings if f.severity != Severity.SAFE]

    @property
    def findings(self) -> list[Finding]:
        return self.open_findings + self.safe_findings

    @property
    def counts(self) -> dict[str, int]:
        open_counts = {severity.value: 0 for severity in Severity}
        for finding in self.open_findings:
            open_counts[finding.severity.value] += 1
        open_counts[Severity.SAFE.value] = len(self.safe_findings)
        return open_counts

    @property
    def fixed_count(self) -> int:
        return len(self.fixes)

    @property
    def finding_groups(self) -> list[dict[str, Any]]:
        """Findings gathered by rule, most urgent first.

        A real post produces hundreds of findings, most of them repeats of the
        same handful of rules — seven long paragraphs, four bold paragraphs. A
        flat list buries that; one accordion per rule makes the shape obvious.
        """
        order = {
            Severity.ERROR.value: 0,
            Severity.WARNING.value: 1,
            Severity.SUGGESTED.value: 2,
            Severity.SAFE.value: 3,
        }
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for finding in self.findings:
            key = (finding.rule_id, finding.severity.value)
            group = grouped.setdefault(
                key,
                {
                    "rule_id": finding.rule_id,
                    "severity": finding.severity.value,
                    "title": finding.title,
                    "findings": [],
                },
            )
            group["findings"].append(finding)

        groups = list(grouped.values())
        for group in groups:
            group["count"] = len(group["findings"])
            group["actionable"] = sum(1 for f in group["findings"] if f.action)
            # Anything still open is worth opening on arrival; the long tail of
            # completed clean-up is not.
            group["open"] = group["severity"] in {Severity.ERROR.value, Severity.WARNING.value}
        groups.sort(key=lambda group: (order[group["severity"]], -group["count"], group["rule_id"]))
        return groups


def _attach_previews(findings: list[Finding]) -> None:
    for finding in findings:
        if not finding.action:
            continue
        params = dict(finding.action_params)
        # Actions that take a value preview using the value the app proposes.
        if finding.action_input_default and "value" not in params:
            params["value"] = finding.action_input_default
        preview = preview_action(finding.before_html or "", finding.action, params)
        finding.action_preview = preview
        if preview:
            finding.action_preview_markup = highlight_additions(finding.before_html or "", preview)
            finding.action_preview_blocks = preview_blocks(preview)


def image_findings(report: ImageReport) -> list[Finding]:
    """Turn an image-processing report into findings.

    The report has its own table in the Images tab, but the Changes tab is where
    the work gets done, so anything needing a decision has to appear there too.
    """
    findings: list[Finding] = []

    for plan in report.plans:
        if not plan.matched:
            findings.append(
                Finding(
                    rule_id="IMAGE-NOT-FOUND-001",
                    title="No file for this image",
                    message=(
                        f"{plan.src_attribute} has no matching file in the folder, so "
                        "nothing was processed for it. Nothing was guessed. "
                        f"{plan.note}"
                    ),
                    severity=Severity.WARNING,
                    before_html=plan.src_attribute,
                    applied=False,
                    metadata={"src": plan.src_attribute},
                    action="remove_image_placeholder",
                    action_label="Remove the placeholder",
                    action_params={"file": basename_of(plan.src_attribute)},
                )
            )
        elif plan.undersize:
            findings.append(
                Finding(
                    rule_id="IMAGE-TOO-SMALL-001",
                    title="Image is much smaller than the target",
                    message=(
                        f"{plan.source.name if plan.source else plan.output_name} is "
                        f"{plan.width}×{plan.height}px. {plan.note}"
                    ),
                    severity=Severity.WARNING,
                    before_html=f"{plan.output_name} ← {plan.src_attribute}",
                    applied=False,
                    metadata={
                        "file": plan.output_name,
                        "width": plan.width,
                        "height": plan.height,
                    },
                    action="remove_image_placeholder",
                    action_label="Remove the placeholder",
                    action_params={"file": basename_of(plan.src_attribute)},
                )
            )

    for name in report.unreferenced:
        findings.append(
            Finding(
                rule_id="IMAGE-UNUSED-001",
                title="File in the folder that the post does not use",
                message=(
                    f"{name} is in the folder but no <img> in the post refers to it. "
                    "It was not processed. If the post should show it, add the image; "
                    "if not, it does not belong in this folder."
                ),
                severity=Severity.SUGGESTED,
                before_html=name,
                applied=False,
                metadata={"file": name},
            )
        )

    return findings


def build_session(
    source: str,
    profile: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> Session:
    """Analyse the source, then replay the user's fixes on top of it."""
    baseline = analyse_html(source, profile)

    html = baseline.cleaned_html
    fixes: list[AppliedFix] = []
    error: str | None = None

    for entry in history or []:
        action = str(entry.get("action", ""))
        params = dict(entry.get("params", {}))
        try:
            html, message = apply_action(html, action, params)
        except (ActionError, ValueError) as exc:
            # A recorded fix no longer fits. Keep the fixes that did apply and
            # say so, rather than silently dropping the rest.
            error = f"A previously applied change could no longer be replayed: {exc}"
            break
        fixes.append(AppliedFix(action=action, params=params, message=message))

    current = analyse_html(html, profile) if fixes or history else baseline
    _attach_previews(current.findings)

    return Session(source=source, baseline=baseline, current=current, fixes=fixes, error=error)
