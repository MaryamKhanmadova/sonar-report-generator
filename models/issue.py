"""
Domain model for a SonarQube issue.

Translates the raw JSON payload returned by /api/issues/search into a clean,
typed Python dataclass.  All string → enum coercions happen here so the rest
of the codebase can work with strong types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """SonarQube legacy severity levels (still present in 25.x API)."""
    BLOCKER = "BLOCKER"
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_str(cls, value: str) -> "Severity":
        try:
            return cls(value.upper())
        except ValueError:
            return cls.UNKNOWN

    @property
    def order(self) -> int:
        """Lower = more severe."""
        return {
            "BLOCKER": 0,
            "CRITICAL": 1,
            "MAJOR": 2,
            "MINOR": 3,
            "INFO": 4,
            "UNKNOWN": 5,
        }.get(self.value, 5)

    @property
    def color_hex(self) -> str:
        return {
            "BLOCKER": "#d32f2f",
            "CRITICAL": "#f44336",
            "MAJOR": "#ff9800",
            "MINOR": "#ffc107",
            "INFO": "#2196f3",
            "UNKNOWN": "#9e9e9e",
        }.get(self.value, "#9e9e9e")


class IssueType(str, Enum):
    BUG = "BUG"
    VULNERABILITY = "VULNERABILITY"
    CODE_SMELL = "CODE_SMELL"
    SECURITY_HOTSPOT = "SECURITY_HOTSPOT"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_str(cls, value: str) -> "IssueType":
        try:
            return cls(value.upper())
        except ValueError:
            return cls.UNKNOWN

    @property
    def label(self) -> str:
        return {
            "BUG": "Bug",
            "VULNERABILITY": "Vulnerability",
            "CODE_SMELL": "Code Smell",
            "SECURITY_HOTSPOT": "Security Hotspot",
            "UNKNOWN": "Unknown",
        }.get(self.value, self.value)

    @property
    def icon(self) -> str:
        return {
            "BUG": "🐛",
            "VULNERABILITY": "🔒",
            "CODE_SMELL": "💨",
            "SECURITY_HOTSPOT": "🔥",
            "UNKNOWN": "❓",
        }.get(self.value, "❓")


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    TO_REVIEW = "TO_REVIEW"
    REVIEWED = "REVIEWED"
    ACCEPTED = "ACCEPTED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_str(cls, value: str) -> "IssueStatus":
        try:
            return cls(value.upper())
        except ValueError:
            return cls.UNKNOWN


class SoftwareQuality(str, Enum):
    MAINTAINABILITY = "MAINTAINABILITY"
    RELIABILITY = "RELIABILITY"
    SECURITY = "SECURITY"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_str(cls, value: str) -> "SoftwareQuality":
        try:
            return cls(value.upper())
        except ValueError:
            return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Impact model (Clean Code / MQR mode)
# ---------------------------------------------------------------------------

@dataclass
class Impact:
    """Represents the impact of an issue on a software quality attribute."""
    software_quality: SoftwareQuality
    severity: str  # HIGH / MEDIUM / LOW

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Impact":
        return cls(
            software_quality=SoftwareQuality.from_str(d.get("softwareQuality", "")),
            severity=d.get("severity", "UNKNOWN"),
        )


# ---------------------------------------------------------------------------
# Main Issue dataclass
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """
    A single SonarQube code quality issue.

    Attributes are named after the SonarQube API fields, converted to
    snake_case.  Only fields useful for reporting are included.
    """

    key: str
    rule: str
    severity: Severity
    component: str
    project: str
    line: Optional[int]
    status: IssueStatus
    issue_status: IssueStatus        # "issueStatus" from API (MQR mode)
    message: str
    issue_type: IssueType
    effort: str                       # e.g. "5min"
    debt: str                         # e.g. "5min"
    effort_minutes: int               # parsed from effort
    tags: list[str]
    author: str
    creation_date: datetime
    update_date: datetime
    impacts: list[Impact]
    quick_fix_available: bool
    clean_code_attribute: str
    clean_code_attribute_category: str
    prioritized_rule: bool

    # Enriched later
    rule_detail: dict[str, Any] = field(default_factory=dict)
    source_code: list[str] | None = None
    source_start_line: Optional[int] = None
    highlight_line: Optional[int] = None

    # ---------------------------------------------------------------------------
    # Derived properties
    # ---------------------------------------------------------------------------

    @property
    def file_path(self) -> str:
        """Return the file path without the project prefix."""
        if ":" in self.component:
            return self.component.split(":", 1)[1]
        return self.component

    @property
    def file_name(self) -> str:
        """Return just the filename."""
        return self.file_path.rsplit("/", 1)[-1]

    @property
    def sonar_url(self) -> str:
        """Placeholder – filled in by analysis service with real base URL."""
        return ""

    @property
    def primary_impact(self) -> Optional[Impact]:
        """Return the highest-severity impact, or None."""
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        return min(self.impacts, key=lambda i: order.get(i.severity, 99), default=None)

    @property
    def primary_software_quality(self) -> str:
        pi = self.primary_impact
        return pi.software_quality.value if pi else "UNKNOWN"

    @property
    def code_snippet(self) -> str:
        """Format fetched source with line numbers and the issue line marked."""
        if not self.source_code or self.source_start_line is None:
            return ""
        return "\n".join(
            f"{self.source_start_line + index:>4} {code}"
            f"{'  <--' if self.source_start_line + index == self.highlight_line else ''}"
            for index, code in enumerate(self.source_code)
        )

    @property
    def display_line(self) -> Optional[int]:
        """Line shown in reports, preferring SonarQube's precise text range."""
        return self.highlight_line or self.line

    # ---------------------------------------------------------------------------
    # Factories
    # ---------------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Issue":
        """
        Construct an :class:`Issue` from a raw API response dict.

        Parameters
        ----------
        d:
            Raw issue dict from /api/issues/search.
        """
        return cls(
            key=d.get("key", ""),
            rule=d.get("rule", ""),
            severity=Severity.from_str(d.get("severity", "UNKNOWN")),
            component=d.get("component", ""),
            project=d.get("project", ""),
            line=_parse_optional_int(d.get("line")),
            status=IssueStatus.from_str(d.get("status", "UNKNOWN")),
            issue_status=IssueStatus.from_str(d.get("issueStatus", d.get("status", "UNKNOWN"))),
            message=d.get("message", ""),
            issue_type=IssueType.from_str(d.get("type", "UNKNOWN")),
            effort=d.get("effort", "0min"),
            debt=d.get("debt", "0min"),
            effort_minutes=_parse_minutes(d.get("effort", "0min")),
            tags=d.get("tags", []),
            author=d.get("author", ""),
            creation_date=_parse_date(d.get("creationDate", "")),
            update_date=_parse_date(d.get("updateDate", "")),
            impacts=[Impact.from_dict(i) for i in d.get("impacts", [])],
            quick_fix_available=d.get("quickFixAvailable", False),
            clean_code_attribute=d.get("cleanCodeAttribute", ""),
            clean_code_attribute_category=d.get("cleanCodeAttributeCategory", ""),
            prioritized_rule=d.get("prioritizedRule", False),
            highlight_line=_parse_optional_int(
                (d.get("textRange") or {}).get("startLine")
            ) or _parse_optional_int(d.get("line")),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_minutes(effort: str) -> int:
    """
    Convert SonarQube effort string to total minutes.

    Examples: ``"5min"`` → 5, ``"1h30min"`` → 90, ``"2h"`` → 120.
    """
    if not effort:
        return 0
    total = 0
    import re
    for match in re.finditer(r"(\d+)(h|min)", effort):
        value, unit = int(match.group(1)), match.group(2)
        total += value * 60 if unit == "h" else value
    return total


def _parse_optional_int(value: Any) -> Optional[int]:
    """Convert a possible API numeric field to ``int`` without raising."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_date(date_str: str) -> datetime:
    """Parse ISO-8601 date string returned by SonarQube."""
    if not date_str:
        return datetime.now()
    # SonarQube format: 2026-07-22T14:16:36+0000
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.now()
