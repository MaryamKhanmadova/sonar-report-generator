"""
Chart generation service.

Produces matplotlib charts as in-memory PNG bytes (no files written to disk
by this module — the report generators decide where to place them).

Charts generated:
  • Severity distribution (pie)
  • Issue type distribution (pie)
  • Issues per file (bar, top 20)
  • Top violated rules (bar, top 20)
  • Issues by severity (horizontal bar)
  • Security distribution (pie)
  • Maintainability trend placeholder (line)
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")  # non-interactive backend – must be set before pyplot import
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from models.project import ReportData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------

SEVERITY_COLORS = {
    "BLOCKER":  "#d32f2f",
    "CRITICAL": "#f44336",
    "MAJOR":    "#ff9800",
    "MINOR":    "#ffc107",
    "INFO":     "#2196f3",
    "UNKNOWN":  "#9e9e9e",
}

TYPE_COLORS = {
    "BUG":           "#f44336",
    "VULNERABILITY": "#9c27b0",
    "CODE_SMELL":    "#ff9800",
    "SECURITY_HOTSPOT": "#e91e63",
    "UNKNOWN":       "#9e9e9e",
}

CHART_BG      = "#1e1e2e"
CHART_FG      = "#cdd6f4"
ACCENT_BLUE   = "#89b4fa"
ACCENT_GREEN  = "#a6e3a1"
ACCENT_PEACH  = "#fab387"
ACCENT_RED    = "#f38ba8"
ACCENT_YELLOW = "#f9e2af"
ACCENT_PURPLE = "#cba6f7"


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class ChartService:
    """
    Generates all charts required by the report generators.

    Returns bytes (PNG) for each chart so they can be embedded directly
    into PDF, DOCX, and HTML reports without touching the filesystem.
    """

    def __init__(self, dark_mode: bool = False) -> None:
        self._dark = dark_mode
        self._style = "dark_background" if dark_mode else "seaborn-v0_8-whitegrid"

    # ------------------------------------------------------------------
    # Public chart generators
    # ------------------------------------------------------------------

    def severity_pie(self, data: "ReportData") -> bytes:
        """Pie chart: issues by severity."""
        from collections import Counter
        counts = Counter(i.severity.value for i in data.issues)
        if not counts:
            return self._empty_chart("No issues found")

        labels = list(counts.keys())
        sizes  = list(counts.values())
        colors = [SEVERITY_COLORS.get(l, "#9e9e9e") for l in labels]

        fig, ax = self._fig(6, 5)
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=None,
            colors=colors,
            autopct="%1.1f%%",
            startangle=140,
            pctdistance=0.75,
            wedgeprops={"linewidth": 2, "edgecolor": "white"},
        )
        for at in autotexts:
            at.set_fontsize(9)
            at.set_color("white")

        legend = [mpatches.Patch(color=c, label=f"{l} ({counts[l]})") for l, c in zip(labels, colors)]
        ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.15),
                  ncol=3, frameon=False, fontsize=9)
        ax.set_title("Issues by Severity", fontsize=13, fontweight="bold", pad=15)
        return self._to_bytes(fig)

    def type_pie(self, data: "ReportData") -> bytes:
        """Pie chart: issues by type."""
        from collections import Counter
        counts = Counter(i.issue_type.value for i in data.issues)
        if not counts:
            return self._empty_chart("No issues found")

        labels = list(counts.keys())
        sizes  = list(counts.values())
        colors = [TYPE_COLORS.get(l, "#9e9e9e") for l in labels]
        display = [t.replace("_", " ").title() for t in labels]

        fig, ax = self._fig(6, 5)
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=None,
            colors=colors,
            autopct="%1.1f%%",
            startangle=90,
            pctdistance=0.78,
            wedgeprops={"linewidth": 2, "edgecolor": "white"},
        )
        for at in autotexts:
            at.set_fontsize(9)
            at.set_color("white")

        legend = [mpatches.Patch(color=c, label=f"{d} ({counts[l]})") for l, d, c in zip(labels, display, colors)]
        ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.12),
                  ncol=2, frameon=False, fontsize=9)
        ax.set_title("Issues by Type", fontsize=13, fontweight="bold", pad=15)
        return self._to_bytes(fig)

    def issues_per_file_bar(self, data: "ReportData") -> bytes:
        """Horizontal bar chart: top 20 files by issue count."""
        top = data.top_files[:20]
        if not top:
            return self._empty_chart("No file data available")

        names = [f.file_name[:40] for f in reversed(top)]
        counts = [f.total_issues for f in reversed(top)]
        bugs_  = [f.bugs for f in reversed(top)]
        smells = [f.code_smells for f in reversed(top)]
        vulns  = [f.vulnerabilities for f in reversed(top)]

        fig, ax = self._fig(10, max(5, len(names) * 0.45))
        y = range(len(names))

        ax.barh(y, counts,  color=ACCENT_BLUE,   label="Total",         height=0.6)
        ax.barh(y, bugs_,   color=ACCENT_RED,    label="Bugs",          height=0.6)
        ax.barh(y, smells,  color=ACCENT_PEACH,  label="Code Smells",   height=0.6)
        ax.barh(y, vulns,   color=ACCENT_PURPLE, label="Vulnerabilities", height=0.6)

        ax.set_yticks(list(y))
        ax.set_yticklabels(names, fontsize=8)
        ax.set_xlabel("Number of Issues", fontsize=10)
        ax.set_title("Top Files by Issue Count", fontsize=13, fontweight="bold")
        ax.legend(loc="lower right", fontsize=8, frameon=False)
        ax.xaxis.grid(True, linestyle="--", alpha=0.5)
        ax.set_axisbelow(True)

        # Annotate totals
        for i, c in enumerate(counts):
            ax.text(c + 0.2, i, str(c), va="center", fontsize=7)

        fig.tight_layout()
        return self._to_bytes(fig)

    def top_rules_bar(self, data: "ReportData") -> bytes:
        """Horizontal bar chart: top 20 most violated rules."""
        top = data.top_rules[:20]
        if not top:
            return self._empty_chart("No rule data available")

        names  = [r.rule_key[:45] for r in reversed(top)]
        counts = [r.count for r in reversed(top)]

        fig, ax = self._fig(10, max(5, len(names) * 0.45))
        y = range(len(names))

        bars = ax.barh(y, counts, color=ACCENT_BLUE, height=0.6)
        ax.set_yticks(list(y))
        ax.set_yticklabels(names, fontsize=8)
        ax.set_xlabel("Violations", fontsize=10)
        ax.set_title("Top Violated Rules", fontsize=13, fontweight="bold")
        ax.xaxis.grid(True, linestyle="--", alpha=0.5)
        ax.set_axisbelow(True)

        for i, c in enumerate(counts):
            ax.text(c + 0.1, i, str(c), va="center", fontsize=7)

        fig.tight_layout()
        return self._to_bytes(fig)

    def severity_bar(self, data: "ReportData") -> bytes:
        """Vertical bar chart: issue count per severity."""
        from collections import Counter
        counts = Counter(i.severity.value for i in data.issues)
        order = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
        labels = [s for s in order if s in counts]
        values = [counts[s] for s in labels]
        colors = [SEVERITY_COLORS[s] for s in labels]

        if not labels:
            return self._empty_chart("No severity data")

        fig, ax = self._fig(7, 4)
        bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.8, width=0.6)

        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                    str(val), ha="center", va="bottom", fontsize=10, fontweight="bold")

        ax.set_ylabel("Issues", fontsize=10)
        ax.set_title("Issues by Severity", fontsize=13, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", alpha=0.5)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return self._to_bytes(fig)

    def security_distribution_pie(self, data: "ReportData") -> bytes:
        """Pie chart: security-related issues vs total."""
        vulns = len(data.vulnerabilities)
        other = len(data.issues) - vulns
        if vulns == 0:
            return self._empty_chart("No vulnerabilities found ✓")

        fig, ax = self._fig(5, 4)
        ax.pie(
            [vulns, other],
            labels=[f"Vulnerabilities\n({vulns})", f"Other Issues\n({other})"],
            colors=[ACCENT_RED, ACCENT_BLUE],
            autopct="%1.1f%%",
            startangle=90,
            wedgeprops={"linewidth": 2, "edgecolor": "white"},
        )
        ax.set_title("Security Distribution", fontsize=13, fontweight="bold")
        return self._to_bytes(fig)

    def maintainability_trend(self, data: "ReportData") -> bytes:
        """
        Placeholder maintainability trend chart.

        In a real deployment this would query historical analysis data
        via /api/measures/search_history. For now it generates a descriptive
        placeholder showing the current snapshot value.
        """
        fig, ax = self._fig(8, 3)

        debt_h = data.metrics.sqale_index // 60
        ax.axhline(y=debt_h, color=ACCENT_PEACH, linewidth=2, linestyle="--", label=f"Current: {debt_h}h")
        ax.fill_between([0, 1], [0, 0], [debt_h, debt_h], alpha=0.15, color=ACCENT_PEACH)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, max(debt_h * 1.5, 10))
        ax.set_xticks([])
        ax.set_ylabel("Technical Debt (hours)", fontsize=10)
        ax.set_title("Maintainability Trend (current snapshot)", fontsize=13, fontweight="bold")
        ax.legend(fontsize=9)
        ax.text(
            0.5, debt_h / 2 if debt_h > 5 else debt_h + 2,
            "Connect /api/measures/search_history for\nhistorical trend data",
            ha="center", va="center", fontsize=8,
            color="#888888", style="italic",
        )
        ax.yaxis.grid(True, linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        fig.tight_layout()
        return self._to_bytes(fig)

    def overview_summary_bar(self, data: "ReportData") -> bytes:
        """Summary bar: Bugs, Vulnerabilities, Code Smells side by side."""
        categories = ["Bugs", "Vulnerabilities", "Code Smells"]
        values     = [
            data.metrics.bugs,
            data.metrics.vulnerabilities,
            data.metrics.code_smells,
        ]
        colors = [ACCENT_RED, ACCENT_PURPLE, ACCENT_PEACH]

        fig, ax = self._fig(6, 4)
        bars = ax.bar(categories, values, color=colors, edgecolor="white", linewidth=0.8, width=0.5)

        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                    str(val), ha="center", va="bottom", fontsize=13, fontweight="bold")

        ax.set_ylabel("Count", fontsize=10)
        ax.set_title("Issue Overview", fontsize=14, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", alpha=0.5)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return self._to_bytes(fig)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fig(self, w: float, h: float) -> tuple[Figure, plt.Axes]:
        """Create a styled figure."""
        with plt.style.context(self._style if self._style in plt.style.available else "seaborn-v0_8-whitegrid"):
            fig, ax = plt.subplots(figsize=(w, h))
            fig.patch.set_facecolor("white")
            ax.set_facecolor("#fafafa")
        return fig, ax

    @staticmethod
    def _to_bytes(fig: Figure) -> bytes:
        """Render figure to PNG bytes and close it."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    @staticmethod
    def _empty_chart(message: str) -> bytes:
        """Render a simple placeholder chart with a message."""
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.text(0.5, 0.5, message, ha="center", va="center",
                fontsize=12, color="#888888", transform=ax.transAxes)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
