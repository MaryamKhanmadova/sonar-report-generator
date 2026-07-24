"""
Domain model for a SonarQube project and its analysis snapshot.

Bundles together all data needed to generate the full report so that
each report generator receives one clean object rather than several
loosely coupled dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from models.issue import Issue
from models.metrics import Metrics


@dataclass
class Branch:
    """Represents a single SonarQube project branch."""

    name: str
    is_main: bool
    status: str          # "OK" | "ERROR" | "NONE"
    analysis_date: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Branch":
        return cls(
            name=d.get("name", ""),
            is_main=d.get("isMain", False),
            status=d.get("status", {}).get("qualityGateStatus", "NONE"),
            analysis_date=d.get("analysisDate", ""),
        )


@dataclass
class FileAnalysis:
    """Aggregated per-file statistics derived from the issues list."""

    path: str
    total_issues: int = 0
    bugs: int = 0
    vulnerabilities: int = 0
    code_smells: int = 0
    blocker: int = 0
    critical: int = 0
    major: int = 0
    minor: int = 0
    info: int = 0
    effort_minutes: int = 0

    @property
    def file_name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class RuleAnalysis:
    """Aggregated per-rule violation statistics."""

    rule_key: str
    count: int = 0
    severity: str = ""
    issue_type: str = ""
    message_sample: str = ""
    effort_minutes: int = 0


@dataclass
class ReportData:
    """
    Complete data bundle passed to every report generator.

    Attributes
    ----------
    project_key:
        SonarQube project identifier.
    project_name:
        Human-readable project name.
    sonar_url:
        Base URL of the SonarQube server.
    generated_at:
        Timestamp when the report was generated.
    metrics:
        Aggregated quality metrics.
    issues:
        Full list of typed Issue objects.
    branches:
        All branches for the project.
    rules:
        Mapping of rule key → raw rule API dict (with description).
    file_stats:
        Per-file aggregated statistics (top files).
    rule_stats:
        Per-rule aggregated statistics (top rules).
    raw_data:
        Raw API responses for the JSON backup.
    """

    project_key: str
    project_name: str
    sonar_url: str
    company_name: str
    custom_report_title: str | None
    generated_at: datetime
    metrics: Metrics
    issues: list[Issue]
    branches: list[Branch]
    rules: dict[str, dict[str, Any]]
    file_stats: list[FileAnalysis] = field(default_factory=list)
    rule_stats: list[RuleAnalysis] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Derived helpers
    # ---------------------------------------------------------------------------

    @property
    def open_issues(self) -> list[Issue]:
        from models.issue import IssueStatus
        return [i for i in self.issues if i.issue_status == IssueStatus.OPEN]

    @property
    def bugs(self) -> list[Issue]:
        from models.issue import IssueType
        return [i for i in self.issues if i.issue_type == IssueType.BUG]

    @property
    def vulnerabilities(self) -> list[Issue]:
        from models.issue import IssueType
        return [i for i in self.issues if i.issue_type == IssueType.VULNERABILITY]

    @property
    def code_smells(self) -> list[Issue]:
        from models.issue import IssueType
        return [i for i in self.issues if i.issue_type == IssueType.CODE_SMELL]

    @property
    def issues_sorted_by_severity(self) -> list[Issue]:
        return sorted(self.issues, key=lambda i: (i.severity.order, i.file_path, i.line or 0))

    @property
    def top_files(self) -> list[FileAnalysis]:
        return sorted(self.file_stats, key=lambda f: f.total_issues, reverse=True)[:20]

    @property
    def top_rules(self) -> list[RuleAnalysis]:
        return sorted(self.rule_stats, key=lambda r: r.count, reverse=True)[:20]

    @property
    def total_effort_minutes(self) -> int:
        return sum(i.effort_minutes for i in self.issues)

    @property
    def total_effort_display(self) -> str:
        minutes = self.total_effort_minutes
        h, m = divmod(minutes, 60)
        d, h = divmod(h, 8)
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}min")
        return " ".join(parts) or "0min"

    @property
    def report_title(self) -> str:
        return self.custom_report_title or f"Code Quality Report – {self.project_name}"
