"""
Data orchestration service.

Pulls data from the SonarQube API, assembles typed models, and returns
a fully populated :class:`ReportData` object ready for all report generators.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from api.sonar_api import SonarAPI
from models.issue import Issue, IssueType, Severity
from models.metrics import Metrics
from models.project import Branch, FileAnalysis, ReportData, RuleAnalysis

logger = logging.getLogger(__name__)


class DataService:
    """
    Orchestrates all SonarQube API calls and assembles the :class:`ReportData`.

    Parameters
    ----------
    api:
        Configured :class:`SonarAPI` instance.
    page_size:
        Number of issues per page (≤500).
    """

    def __init__(
        self,
        api: SonarAPI,
        page_size: int = 500,
        company_name: str = "SonarQube Report Generator",
        report_title: str | None = None,
    ) -> None:
        self._api = api
        self._page_size = page_size
        self._company_name = company_name
        self._report_title = report_title

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def collect(self) -> ReportData:
        """
        Fetch all required data from SonarQube and return a :class:`ReportData`.

        Steps
        -----
        1. Fetch project info (name, key).
        2. Fetch branches.
        3. Fetch measures/metrics.
        4. Fetch all issues (paginated).
        5. Fetch rule details for unique rules found in issues.
        6. Compute per-file and per-rule aggregates.
        7. Bundle into :class:`ReportData`.
        """
        logger.info("Starting data collection for project '%s'", self._api.project_key)

        # 1 – Project info
        project_info = self._api.get_project_info()
        project_name = project_info.get("name", self._api.project_key)
        logger.info("Project name: %s", project_name)

        # 2 – Branches
        raw_branches = self._api.get_branches()
        branches = [Branch.from_dict(b) for b in raw_branches]
        logger.info("Branches found: %d", len(branches))

        # 3 – Metrics
        raw_measures = self._api.get_measures()
        metrics = Metrics.from_api_response(raw_measures)
        logger.info(
            "Quality gate: %s | Bugs: %d | Vulnerabilities: %d | Code Smells: %d",
            metrics.quality_gate_status,
            metrics.bugs,
            metrics.vulnerabilities,
            metrics.code_smells,
        )

        # 4 – Issues
        raw_issues = self._api.get_all_issues(page_size=self._page_size)
        issues = [Issue.from_dict(i) for i in raw_issues]
        logger.info("Total issues fetched: %d", len(issues))

        # 5 – Source context. Cache by location because multiple issues can
        # point to the same line. Source access is best-effort in SonarAPI.
        source_cache: dict[tuple[str, int], tuple[int, list[str]] | None] = {}
        sources_fetched = 0
        for issue in issues:
            if not issue.component or issue.highlight_line is None:
                continue
            location = (issue.component, issue.highlight_line)
            if location not in source_cache:
                lines = self._api.get_source_code(issue.component, issue.highlight_line)
                source_cache[location] = (
                    (lines[0][0], [code for _, code in lines]) if lines else None
                )
            source_context = source_cache[location]
            if source_context:
                issue.source_start_line, issue.source_code = source_context
            if issue.source_code:
                sources_fetched += 1
        logger.info("Source context fetched for %d/%d issues", sources_fetched, len(issues))

        # 6 – Rule details
        rule_keys = [i.rule for i in issues]
        rules = self._api.get_rules_batch(rule_keys)
        logger.info("Rule details fetched: %d", len(rules))

        # Enrich issues with rule data
        for issue in issues:
            if issue.rule in rules:
                issue.rule_detail = rules[issue.rule]

        # 7 – Aggregates
        file_stats = self._compute_file_stats(issues)
        rule_stats = self._compute_rule_stats(issues)

        # 8 – Bundle raw data for JSON export
        raw_data: dict[str, Any] = {
            "project_info": project_info,
            "branches": raw_branches,
            "measures": raw_measures,
            "issues": raw_issues,
            "rules": rules,
        }

        report = ReportData(
            project_key=self._api.project_key,
            project_name=project_name,
            sonar_url=self._api._client.base_url,
            company_name=self._company_name,
            custom_report_title=self._report_title,
            generated_at=datetime.now(),
            metrics=metrics,
            issues=issues,
            branches=branches,
            rules=rules,
            file_stats=file_stats,
            rule_stats=rule_stats,
            raw_data=raw_data,
        )

        logger.info("Data collection complete – %d issues across %d files",
                    len(issues), len(file_stats))
        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_file_stats(issues: list[Issue]) -> list[FileAnalysis]:
        """Aggregate issue counts and effort per file."""
        agg: dict[str, FileAnalysis] = defaultdict(lambda: FileAnalysis(path=""))

        for issue in issues:
            path = issue.file_path
            if path not in agg:
                agg[path] = FileAnalysis(path=path)

            fa = agg[path]
            fa.total_issues += 1
            fa.effort_minutes += issue.effort_minutes

            t = issue.issue_type
            if t == IssueType.BUG:
                fa.bugs += 1
            elif t == IssueType.VULNERABILITY:
                fa.vulnerabilities += 1
            elif t == IssueType.CODE_SMELL:
                fa.code_smells += 1

            s = issue.severity
            if s == Severity.BLOCKER:
                fa.blocker += 1
            elif s == Severity.CRITICAL:
                fa.critical += 1
            elif s == Severity.MAJOR:
                fa.major += 1
            elif s == Severity.MINOR:
                fa.minor += 1
            elif s == Severity.INFO:
                fa.info += 1

        return list(agg.values())

    @staticmethod
    def _compute_rule_stats(issues: list[Issue]) -> list[RuleAnalysis]:
        """Aggregate violation counts per rule."""
        agg: dict[str, RuleAnalysis] = {}

        for issue in issues:
            key = issue.rule
            if key not in agg:
                agg[key] = RuleAnalysis(
                    rule_key=key,
                    severity=issue.severity.value,
                    issue_type=issue.issue_type.value,
                    message_sample=issue.message[:120],
                )
            ra = agg[key]
            ra.count += 1
            ra.effort_minutes += issue.effort_minutes

        return list(agg.values())
