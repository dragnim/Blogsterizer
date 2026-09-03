from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    SAFE = "safe"
    SUGGESTED = "suggested"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class Finding:
    rule_id: str
    title: str
    message: str
    severity: Severity
    before_html: str | None = None
    after_html: str | None = None
    applied: bool = False
    changes_copy: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    # An action the user may choose to apply to this finding. Never automatic.
    action: str | None = None
    action_label: str | None = None
    action_params: dict[str, Any] = field(default_factory=dict)
    # Some actions need a value from the user; the app proposes a default.
    action_input_label: str | None = None
    action_input_default: str | None = None
    # What the document would look like if this action were applied.
    action_preview: str | None = None
    # The same preview prepared for display: markup with insertions marked, and
    # the resulting top-level elements listed so a split reads as two blocks.
    action_preview_markup: str | None = None
    action_preview_blocks: list[dict[str, str]] = field(default_factory=list)
    # Other elements this finding is about, e.g. the id it collides with.
    related: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "before_html": self.before_html,
            "after_html": self.after_html,
            "applied": self.applied,
            "changes_copy": self.changes_copy,
            "metadata": self.metadata,
            "action": self.action,
            "action_label": self.action_label,
            "action_params": self.action_params,
            "action_input_label": self.action_input_label,
            "action_input_default": self.action_input_default,
            "action_preview": self.action_preview,
            "action_preview_blocks": self.action_preview_blocks,
            "related": self.related,
        }


@dataclass(slots=True)
class AnalysisResult:
    source_html: str
    cleaned_html: str
    findings: list[Finding]
    copy_preserved: bool
    copy_guard_message: str
    diff: str
    block_markup: str = ""

    @property
    def counts(self) -> dict[str, int]:
        values = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            values[finding.severity.value] += 1
        return values

    @property
    def export_safe(self) -> bool:
        return self.copy_preserved and self.counts[Severity.ERROR.value] == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_html": self.source_html,
            "cleaned_html": self.cleaned_html,
            "findings": [item.to_dict() for item in self.findings],
            "copy_preserved": self.copy_preserved,
            "copy_guard_message": self.copy_guard_message,
            "export_safe": self.export_safe,
            "diff": self.diff,
            "block_markup": self.block_markup,
            "counts": self.counts,
        }
