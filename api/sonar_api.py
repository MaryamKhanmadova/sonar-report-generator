"""
SonarQube REST API wrapper.

Exposes high-level methods that correspond to the official endpoints:
  • /api/measures/component
  • /api/issues/search
  • /api/rules/show
  • /api/project_branches/list
  • /api/projects/search  (used to validate project key)

All raw JSON is returned; translation into typed models happens in the
service layer.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Optional

from api.client import APIClient

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]*>")


def sanitize_source_line(html_line: str) -> str:
    """Convert SonarQube's syntax-highlighted source HTML to plain code.

    Tags are removed before entities are decoded so encoded source fragments
    such as ``&lt;Component&gt;`` remain source code rather than being treated
    as HTML tags.
    """
    return html.unescape(_HTML_TAG_RE.sub("", html_line))


class SonarAPI:
    """
    Facade over SonarQube Community Build REST API (v9+/25.x).

    Parameters
    ----------
    client:
        Configured :class:`APIClient` instance.
    project_key:
        Key of the project being analysed.
    """

    # Metrics fetched for the executive summary
    SUMMARY_METRICS: list[str] = [
        "alert_status",
        "quality_gate_details",
        "bugs",
        "reliability_rating",
        "vulnerabilities",
        "security_rating",
        "code_smells",
        "sqale_rating",
        "sqale_index",
        "sqale_debt_ratio",
        "coverage",
        "duplicated_lines_density",
        "duplicated_blocks",
        "lines",
        "ncloc",
        "functions",
        "classes",
        "files",
        "complexity",
        "cognitive_complexity",
        "comment_lines_density",
        "accepted_issues",
        "new_bugs",
        "new_vulnerabilities",
        "new_code_smells",
        "new_coverage",
        "new_duplicated_lines_density",
        "confirmed_issues",
        "false_positive_issues",
        "wont_fix_issues",
        "open_issues",
        "reopened_issues",
    ]

    def __init__(self, client: APIClient, project_key: str) -> None:
        self._client = client
        self.project_key = project_key

    # ------------------------------------------------------------------
    # Project & branch
    # ------------------------------------------------------------------

    def get_project_info(self) -> dict[str, Any]:
        """
        Get project information without requiring projects/search permission.
        Uses component data available from measures endpoint.
        """
        data = self.get_measures(["bugs"])

        return data.get("component", {
            "key": self.project_key,
            "name": self.project_key,
        })

    def get_branches(self) -> list[dict[str, Any]]:
        """
        Return all branches for the project.

        Endpoint: GET /api/project_branches/list
        """
        data = self._client.get(
            "/api/project_branches/list",
            params={"project": self.project_key},
        )
        return data.get("branches", [])

    # ------------------------------------------------------------------
    # Metrics / measures
    # ------------------------------------------------------------------

    def get_measures(
        self,
        metric_keys: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        Fetch component measures.

        Endpoint: GET /api/measures/component

        Parameters
        ----------
        metric_keys:
            List of metric keys to retrieve. Defaults to
            :attr:`SUMMARY_METRICS`.

        Returns
        -------
        dict
            Raw response from the API.
        """
        keys = metric_keys or self.SUMMARY_METRICS
        data = self._client.get(
            "/api/measures/component",
            params={
                "component": self.project_key,
                "metricKeys": ",".join(keys),
                "additionalFields": "metrics,period",
            },
        )
        return data

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def get_all_issues(
        self,
        statuses: Optional[list[str]] = None,
        types: Optional[list[str]] = None,
        severities: Optional[list[str]] = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Fetch ALL issues for the project, with automatic pagination.

        Endpoint: GET /api/issues/search

        Parameters
        ----------
        statuses:
            Filter by status list, e.g. ``["OPEN","CONFIRMED"]``.
            ``None`` → all statuses.
        types:
            Filter by type, e.g. ``["BUG","CODE_SMELL","VULNERABILITY"]``.
        severities:
            Filter by severity, e.g. ``["CRITICAL","MAJOR"]``.
        page_size:
            Items per page (max 500).

        Returns
        -------
        list
            All issue dicts across all pages.
        """
        params: dict[str, Any] = {
            "componentKeys": self.project_key,
            "additionalFields": "rules,comments",
        }
        if statuses:
            params["statuses"] = ",".join(statuses)
        if types:
            params["types"] = ",".join(types)
        if severities:
            params["severities"] = ",".join(severities)

        logger.info("Fetching issues for project '%s' …", self.project_key)

        # Try a single-request fetch when possible to avoid multiple
        # paginated round-trips. SonarQube commonly caps page size at 500
        # items; if the total number of issues is <= that cap we can request
        # them all in one call which is faster for small projects.
        try:
            probe = dict(params)
            probe.update({"ps": 1, "p": 1})
            first = self._client.get("/api/issues/search", params=probe)
            paging = first.get("paging", {})
            total = paging.get("total", first.get("total", 0))
        except Exception:
            total = 0

        server_limit = min(500, page_size)
        if total and total <= server_limit:
            single = dict(params)
            single.update({"ps": total, "p": 1})
            data = self._client.get("/api/issues/search", params=single)
            return data.get("issues", [])

        # Fallback to existing paginated collector
        return self._client.get_paginated(
            "/api/issues/search",
            result_key="issues",
            params=params,
            page_size=page_size,
        )

    # ------------------------------------------------------------------
    # Source code
    # ------------------------------------------------------------------

    def get_source_code(
        self,
        component_key: str,
        line: int,
        context: int = 5,
    ) -> list[tuple[int, str]]:
        """Return source lines around an issue, or an empty list on failure.

        ``/api/sources/show`` requires SonarQube's *See Source Code*
        permission, which may be absent even when issue metadata is available.
        Source retrieval is intentionally best-effort so an inaccessible file
        never prevents the rest of a report from being generated.
        """
        if not component_key or line < 1:
            return []

        try:
            data = self._client.get(
                "/api/sources/show",
                params={
                    "key": component_key,
                    "from": max(1, line - max(0, context)),
                    "to": line + max(0, context),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not fetch source for %s:%d: %s", component_key, line, exc
            )
            return []

        source_lines: list[tuple[int, str]] = []
        for source_line in data.get("sources", []):
            # SonarQube versions return either {"line": N, "code": "..."}
            # or the compact [N, "..."] representation.
            if isinstance(source_line, dict):
                number_value = source_line.get("line")
                code = source_line.get("code", "")
            elif isinstance(source_line, (list, tuple)) and len(source_line) >= 2:
                number_value, code = source_line[0], source_line[1]
            else:
                continue
            try:
                number = int(number_value)
            except (TypeError, ValueError):
                continue
            source_lines.append((number, sanitize_source_line(str(code))))
        return source_lines

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def get_rule(self, rule_key: str) -> dict[str, Any]:
        """
        Fetch detailed rule information including description and remediation.

        Endpoint: GET /api/rules/show

        Parameters
        ----------
        rule_key:
            Full rule key, e.g. ``typescript:S3776``.

        Returns
        -------
        dict
            Raw rule dict, or empty dict on error.
        """
        try:
            data = self._client.get(
                "/api/rules/show",
                params={"key": rule_key, "actives": "false"},
            )
            return data.get("rule", {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch rule '%s': %s", rule_key, exc)
            return {}

    def get_rules_batch(self, rule_keys: list[str]) -> dict[str, dict[str, Any]]:
        """
        Fetch multiple rules, returning a mapping of key → rule dict.

        Deduplicates keys and skips failed lookups silently.

        Parameters
        ----------
        rule_keys:
            List of rule keys (may contain duplicates).

        Returns
        -------
        dict
            ``{rule_key: rule_dict}`` for every successfully fetched rule.
        """
        unique_keys = list(dict.fromkeys(rule_keys))  # preserve order, dedupe
        logger.info("Fetching %d unique rules …", len(unique_keys))
        result: dict[str, dict[str, Any]] = {}
        for key in unique_keys:
            rule = self.get_rule(key)
            if rule:
                result[key] = rule
        logger.info("Fetched %d rules", len(result))
        return result
