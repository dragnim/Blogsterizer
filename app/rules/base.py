from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from bs4 import BeautifulSoup

from app.models import Finding


class Rule(ABC):
    rule_id: str
    description: str
    may_change_copy: bool = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    def apply(self, soup: BeautifulSoup) -> list[Finding]:
        """Apply the rule in-place and return findings."""
