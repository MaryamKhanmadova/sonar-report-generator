"""
JSON raw data backup report.

Serialises all downloaded SonarQube API data to a pretty-printed JSON file.
Useful for debugging, re-running report generation offline, and auditing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from models.project import ReportData
from reports.base_report import BaseReport

logger = logging.getLogger(__name__)


class _DatetimeEncoder(json.JSONEncoder):
    """Extend JSONEncoder to handle datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class JsonReport(BaseReport):
    """Writes all raw API data and typed model summaries to raw.json."""

    def generate(self, data: ReportData) -> str:
        path = self.output_path("raw.json")
        logger.info("Generating JSON backup → %s", path)

        output = {
            "meta": {
                "project_key":  data.project_key,
                "project_name": data.project_name,
                "sonar_url":    data.sonar_url,
                "company_name": data.company_name,
                "report_title": data.report_title,
                "generated_at": data.generated_at.isoformat(),
                "total_issues": len(data.issues),
            },
            "metrics": self._serialise_metrics(data),
            "issues_summary": self._serialise_issues_summary(data),
            "file_stats":     self._serialise_file_stats(data),
            "rule_stats":     self._serialise_rule_stats(data),
            "branches":       [
                {"name": b.name, "is_main": b.is_main, "status": b.status}
                for b in data.branches
            ],
            # Raw API responses for full fidelity
            "raw": data.raw_data,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, cls=_DatetimeEncoder)

        import os
        size_kb = os.path.getsize(path) // 1024
        logger.info("JSON backup saved – %d KB", size_kb)
        return path

    # ------------------------------------------------------------------
    # Private serialisers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialise_metrics(data: ReportData) -> dict[str, Any]:
        m = data.metrics
        return {
            "quality_gate_status":         m.quality_gate_status,
            "bugs":                        m.bugs,
            "reliability_rating":          m.reliability_rating,
            "reliability_rating_letter":   m.reliability_rating_letter,
            "vulnerabilities":             m.vulnerabilities,
            "security_rating":             m.security_rating,
            "security_rating_letter":      m.security_rating_letter,
            "code_smells":                 m.code_smells,
            "sqale_rating":                m.sqale_rating,
            "sqale_rating_letter":         m.sqale_rating_letter,
            "sqale_index_minutes":         m.sqale_index,
            "technical_debt_display":      m.technical_debt_display,
            "sqale_debt_ratio":            m.sqale_debt_ratio,
            "coverage":                    m.coverage,
            "duplicated_lines_density":    m.duplicated_lines_density,
            "duplicated_blocks":           m.duplicated_blocks,
            "lines":                       m.lines,
            "ncloc":                       m.ncloc,
            "files":                       m.files,
            "functions":                   m.functions,
            "classes":                     m.classes,
            "complexity":                  m.complexity,
            "cognitive_complexity":        m.cognitive_complexity,
            "comment_lines_density":       m.comment_lines_density,
            "open_issues":                 m.open_issues,
            "confirmed_issues":            m.confirmed_issues,
            "false_positive_issues":       m.false_positive_issues,
            "wont_fix_issues":             m.wont_fix_issues,
            "accepted_issues":             m.accepted_issues,
        }

    @staticmethod
    def _serialise_issues_summary(data: ReportData) -> list[dict[str, Any]]:
        return [
            {
                "key":        issue.key,
                "rule":       issue.rule,
                "severity":   issue.severity.value,
                "type":       issue.issue_type.value,
                "component":  issue.component,
                "file_path":  issue.file_path,
                "line":       issue.display_line,
                "status":     issue.issue_status.value,
                "message":    issue.message,
                "source_code": issue.source_code or [],
                "source_start_line": issue.source_start_line,
                "highlight_line": issue.highlight_line,
                "effort":     issue.effort,
                "effort_min": issue.effort_minutes,
                "tags":       issue.tags,
                "created_at": issue.creation_date.isoformat(),
            }
            for issue in data.issues
        ]

    @staticmethod
    def _serialise_file_stats(data: ReportData) -> list[dict[str, Any]]:
        return [
            {
                "path":         fa.path,
                "total_issues": fa.total_issues,
                "bugs":         fa.bugs,
                "code_smells":  fa.code_smells,
                "vulnerabilities": fa.vulnerabilities,
                "blocker":      fa.blocker,
                "critical":     fa.critical,
                "major":        fa.major,
                "effort_min":   fa.effort_minutes,
            }
            for fa in sorted(data.file_stats, key=lambda x: x.total_issues, reverse=True)
        ]

    @staticmethod
    def _serialise_rule_stats(data: ReportData) -> list[dict[str, Any]]:
        return [
            {
                "rule_key":       ra.rule_key,
                "count":          ra.count,
                "severity":       ra.severity,
                "issue_type":     ra.issue_type,
                "effort_min":     ra.effort_minutes,
                "message_sample": ra.message_sample,
            }
            for ra in sorted(data.rule_stats, key=lambda x: x.count, reverse=True)
        ]
