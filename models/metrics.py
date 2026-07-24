"""
Domain model for SonarQube quality metrics.

Translates the raw /api/measures/component response into a clean dataclass.
Ratings are stored both as numeric values (1-5) and as letter grades (A-E).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Rating helpers
# ---------------------------------------------------------------------------

def rating_letter(value: Optional[float]) -> str:
    """Convert a numeric SonarQube rating (1–5) to a letter grade."""
    if value is None:
        return "–"
    try:
        v = int(float(value))
    except (ValueError, TypeError):
        return "–"
    return {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}.get(v, "–")


def rating_color(letter: str) -> str:
    """Return a hex colour for a rating letter, matching the SonarQube palette."""
    return {
        "A": "#4caf50",
        "B": "#8bc34a",
        "C": "#ff9800",
        "D": "#f44336",
        "E": "#d32f2f",
        "–": "#9e9e9e",
    }.get(letter, "#9e9e9e")


def gate_color(status: str) -> str:
    return "#4caf50" if status.upper() == "OK" else "#f44336"


# ---------------------------------------------------------------------------
# Metrics dataclass
# ---------------------------------------------------------------------------

@dataclass
class Metrics:
    """
    Aggregated quality metrics for a single SonarQube project/component.

    All counts default to 0 and all ratings default to ``None`` so callers
    can safely format them without guarding for missing keys.
    """

    # Quality gate
    quality_gate_status: str = "UNKNOWN"   # "OK" | "WARN" | "ERROR"
    quality_gate_details: str = ""

    # Reliability
    bugs: int = 0
    reliability_rating: Optional[float] = None

    # Security
    vulnerabilities: int = 0
    security_rating: Optional[float] = None

    # Maintainability
    code_smells: int = 0
    sqale_rating: Optional[float] = None
    sqale_index: int = 0                  # technical debt in minutes
    sqale_debt_ratio: float = 0.0

    # Coverage
    coverage: float = 0.0

    # Duplications
    duplicated_lines_density: float = 0.0
    duplicated_blocks: int = 0

    # Size
    lines: int = 0
    ncloc: int = 0
    functions: int = 0
    classes: int = 0
    files: int = 0
    complexity: int = 0
    cognitive_complexity: int = 0
    comment_lines_density: float = 0.0

    # Issue counts by status
    open_issues: int = 0
    confirmed_issues: int = 0
    false_positive_issues: int = 0
    wont_fix_issues: int = 0
    accepted_issues: int = 0
    reopened_issues: int = 0

    # New code (branch comparison)
    new_bugs: int = 0
    new_vulnerabilities: int = 0
    new_code_smells: int = 0
    new_coverage: float = 0.0
    new_duplicated_lines_density: float = 0.0

    # ---------------------------------------------------------------------------
    # Derived properties
    # ---------------------------------------------------------------------------

    @property
    def reliability_rating_letter(self) -> str:
        return rating_letter(self.reliability_rating)

    @property
    def security_rating_letter(self) -> str:
        return rating_letter(self.security_rating)

    @property
    def sqale_rating_letter(self) -> str:
        return rating_letter(self.sqale_rating)

    @property
    def technical_debt_display(self) -> str:
        """Human-readable technical debt string (e.g. '2h 30min')."""
        minutes = self.sqale_index
        if minutes == 0:
            return "0min"
        h, m = divmod(minutes, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}min")
        return " ".join(parts)

    @property
    def resolved_issues(self) -> int:
        return self.false_positive_issues + self.wont_fix_issues + self.accepted_issues

    @property
    def total_issues(self) -> int:
        return self.bugs + self.vulnerabilities + self.code_smells

    # ---------------------------------------------------------------------------
    # Factory
    # ---------------------------------------------------------------------------

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Metrics":
        """
        Build a :class:`Metrics` instance from the raw
        /api/measures/component API response.

        Parameters
        ----------
        data:
            Full response dict (contains ``component.measures`` list).
        """
        component = data.get("component", {})
        measures_list: list[dict[str, Any]] = component.get("measures", [])

        # Build a flat metric_key → value map
        mv: dict[str, Any] = {}
        for m in measures_list:
            key = m.get("metric", "")
            val = m.get("value")
            if val is not None:
                mv[key] = val

        def _int(key: str, default: int = 0) -> int:
            try:
                return int(float(mv.get(key, default)))
            except (ValueError, TypeError):
                return default

        def _float(key: str, default: float = 0.0) -> float:
            try:
                return float(mv.get(key, default))
            except (ValueError, TypeError):
                return default

        def _str(key: str, default: str = "") -> str:
            return str(mv.get(key, default))

        def _optional_float(key: str) -> Optional[float]:
            val = mv.get(key)
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        # Parse quality gate from alert_status
        gate_raw = _str("alert_status", "UNKNOWN").upper()

        return cls(
            quality_gate_status=gate_raw,
            quality_gate_details=_str("quality_gate_details"),
            bugs=_int("bugs"),
            reliability_rating=_optional_float("reliability_rating"),
            vulnerabilities=_int("vulnerabilities"),
            security_rating=_optional_float("security_rating"),
            code_smells=_int("code_smells"),
            sqale_rating=_optional_float("sqale_rating"),
            sqale_index=_int("sqale_index"),
            sqale_debt_ratio=_float("sqale_debt_ratio"),
            coverage=_float("coverage"),
            duplicated_lines_density=_float("duplicated_lines_density"),
            duplicated_blocks=_int("duplicated_blocks"),
            lines=_int("lines"),
            ncloc=_int("ncloc"),
            functions=_int("functions"),
            classes=_int("classes"),
            files=_int("files"),
            complexity=_int("complexity"),
            cognitive_complexity=_int("cognitive_complexity"),
            comment_lines_density=_float("comment_lines_density"),
            open_issues=_int("open_issues"),
            confirmed_issues=_int("confirmed_issues"),
            false_positive_issues=_int("false_positive_issues"),
            wont_fix_issues=_int("wont_fix_issues"),
            accepted_issues=_int("accepted_issues"),
            reopened_issues=_int("reopened_issues"),
            new_bugs=_int("new_bugs"),
            new_vulnerabilities=_int("new_vulnerabilities"),
            new_code_smells=_int("new_code_smells"),
            new_coverage=_float("new_coverage"),
            new_duplicated_lines_density=_float("new_duplicated_lines_density"),
        )
