"""
Interactive HTML report generator with dark mode, search, and filtering.

Produces a single self-contained HTML file (inline CSS + JS, base64-embedded
charts) that can be opened in any browser without a server.

Features
--------
• Dark / light mode toggle
• Live search across all issues
• Filter by severity, type, and status
• Collapsible detailed issue cards
• Sticky navigation bar
• Charts embedded as base64 PNG
• Responsive layout
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from models.issue import IssueType, Severity
from models.metrics import rating_color, rating_letter
from models.project import ReportData
from reports.base_report import BaseReport
from services.chart_service import ChartService
from services.recommendation_engine import RecommendationEngine

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _b64(img_bytes: bytes) -> str:
    return base64.b64encode(img_bytes).decode("ascii")


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


SEV_CSS = {
    "BLOCKER":  "#d32f2f",
    "CRITICAL": "#f44336",
    "MAJOR":    "#ff9800",
    "MINOR":    "#ffc107",
    "INFO":     "#2196f3",
    "UNKNOWN":  "#9e9e9e",
}

TYPE_CSS = {
    "BUG":           "#f44336",
    "VULNERABILITY": "#9c27b0",
    "CODE_SMELL":    "#ff9800",
    "SECURITY_HOTSPOT": "#e91e63",
    "UNKNOWN":       "#9e9e9e",
}


class HtmlReport(BaseReport):
    """Generates a fully interactive, self-contained HTML report."""

    def __init__(self, output_dir: str = "output") -> None:
        super().__init__(output_dir)
        self._chart_svc  = ChartService()
        self._rec_engine = RecommendationEngine()

    def generate(self, data: ReportData) -> str:
        path = self.output_path("report.html")
        logger.info("Generating HTML report → %s", path)

        # Pre-render charts
        charts = {
            "severity_pie":    _b64(self._chart_svc.severity_pie(data)),
            "type_pie":        _b64(self._chart_svc.type_pie(data)),
            "severity_bar":    _b64(self._chart_svc.severity_bar(data)),
            "files_bar":       _b64(self._chart_svc.issues_per_file_bar(data)),
            "rules_bar":       _b64(self._chart_svc.top_rules_bar(data)),
            "security_pie":    _b64(self._chart_svc.security_distribution_pie(data)),
            "maintainability": _b64(self._chart_svc.maintainability_trend(data)),
        }

        html = self._render(data, charts)

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

        import os
        size_kb = os.path.getsize(path) // 1024
        logger.info("HTML report saved – %d KB", size_kb)
        return path

    # ------------------------------------------------------------------
    # Main renderer
    # ------------------------------------------------------------------

    def _render(self, data: ReportData, charts: dict[str, str]) -> str:
        m = data.metrics
        gate_ok = m.quality_gate_status == "OK"
        generated = self.format_datetime(data.generated_at)

        # Pre-build issues JSON for the JS search engine
        issues_json = self._build_issues_json(data)

        # Build sections
        exec_summary_html = self._exec_summary_html(data)
        quality_cards_html = self._quality_cards_html(data)
        charts_html = self._charts_html(charts)
        files_table_html = self._files_table_html(data)
        issues_table_html = self._issues_table_html(data)
        detailed_issues_html = self._detailed_issues_html(data)
        top_files_html = self._top_files_html(data)
        top_rules_html = self._top_rules_html(data)
        tech_debt_html = self._tech_debt_html(data)

        return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{_esc(data.report_title)}</title>
<style>
/* ===================================================================
   CSS Custom Properties – Dark / Light Mode
   =================================================================== */
:root {{
  --bg:          #1e1e2e;
  --bg2:         #181825;
  --bg3:         #313244;
  --fg:          #cdd6f4;
  --fg2:         #a6adc8;
  --primary:     #89b4fa;
  --secondary:   #cba6f7;
  --accent:      #89dceb;
  --success:     #a6e3a1;
  --warning:     #f9e2af;
  --danger:      #f38ba8;
  --border:      #45475a;
  --card-bg:     #1e1e2e;
  --nav-bg:      #11111b;
  --tag-bg:      #313244;
  --sev-blocker: #d32f2f;
  --sev-critical:#f44336;
  --sev-major:   #ff9800;
  --sev-minor:   #ffc107;
  --sev-info:    #2196f3;
  --radius:      8px;
  --shadow:      0 4px 24px rgba(0,0,0,0.4);
  --transition:  0.2s ease;
}}
[data-theme="light"] {{
  --bg:    #f8f9fe;
  --bg2:   #ffffff;
  --bg3:   #e8ecf8;
  --fg:    #1e1e2e;
  --fg2:   #555577;
  --border:#c5cae9;
  --card-bg:#ffffff;
  --nav-bg:#1a237e;
  --tag-bg:#e8ecf8;
  --shadow:0 4px 24px rgba(0,0,0,0.12);
}}

/* ===================================================================
   Base
   =================================================================== */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--fg);
  font-size: 14px;
  line-height: 1.6;
  transition: background var(--transition), color var(--transition);
}}
a {{ color: var(--primary); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{ font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 12px;
        background: var(--bg3); padding: 2px 6px; border-radius: 4px; }}

/* ===================================================================
   Navigation
   =================================================================== */
nav {{
  position: sticky; top: 0; z-index: 1000;
  background: var(--nav-bg);
  padding: 0 24px;
  display: flex; align-items: center; gap: 16px;
  height: 56px;
  box-shadow: 0 2px 16px rgba(0,0,0,0.3);
}}
nav .brand {{
  font-weight: 700; font-size: 16px; color: #fff;
  white-space: nowrap;
}}
nav .nav-links {{
  display: flex; gap: 4px; flex: 1; overflow-x: auto;
  scrollbar-width: none;
}}
nav .nav-links a {{
  color: rgba(255,255,255,0.75); padding: 8px 12px;
  border-radius: var(--radius); font-size: 13px;
  transition: background var(--transition);
  white-space: nowrap;
}}
nav .nav-links a:hover {{ background: rgba(255,255,255,0.12); color: #fff; }}
.theme-btn {{
  background: none; border: 1px solid rgba(255,255,255,0.3);
  color: #fff; padding: 6px 14px; border-radius: 20px;
  cursor: pointer; font-size: 13px; transition: background var(--transition);
  white-space: nowrap;
}}
.theme-btn:hover {{ background: rgba(255,255,255,0.1); }}

/* ===================================================================
   Layout
   =================================================================== */
.container {{ max-width: 1400px; margin: 0 auto; padding: 24px 20px; }}
section {{ margin-bottom: 48px; }}
.section-title {{
  font-size: 22px; font-weight: 700; color: var(--primary);
  margin-bottom: 20px; padding-bottom: 10px;
  border-bottom: 2px solid var(--border);
  display: flex; align-items: center; gap: 10px;
}}
.section-title .icon {{ font-size: 24px; }}

/* ===================================================================
   Hero / Cover
   =================================================================== */
.hero {{
  background: linear-gradient(135deg, #1a237e 0%, #0d47a1 50%, #01579b 100%);
  border-radius: 12px; padding: 48px 40px; margin-bottom: 32px;
  box-shadow: var(--shadow);
  position: relative; overflow: hidden;
}}
.hero::before {{
  content: ''; position: absolute; inset: 0;
  background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.03'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
}}
.hero h1 {{ font-size: 32px; color: #fff; margin-bottom: 8px; font-weight: 800; }}
.hero .subtitle {{ color: rgba(255,255,255,0.8); font-size: 18px; margin-bottom: 24px; }}
.hero-meta {{ display: flex; flex-wrap: wrap; gap: 12px; }}
.meta-chip {{
  background: rgba(255,255,255,0.12); color: #fff;
  padding: 6px 14px; border-radius: 20px; font-size: 12px;
  border: 1px solid rgba(255,255,255,0.2);
}}
.gate-badge {{
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 20px; border-radius: 24px; font-weight: 700;
  font-size: 15px; margin-bottom: 20px;
}}
.gate-passed {{ background: rgba(76,175,80,0.2); color: #a6e3a1; border: 2px solid #4caf50; }}
.gate-failed {{ background: rgba(244,67,54,0.2); color: #f38ba8; border: 2px solid #f44336; }}

/* ===================================================================
   Cards
   =================================================================== */
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }}
.card {{
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
  transition: transform var(--transition), box-shadow var(--transition);
  position: relative; overflow: hidden;
}}
.card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
.card::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px;
}}
.card.reliability::before {{ background: #f44336; }}
.card.maintainability::before {{ background: #ff9800; }}
.card.security::before {{ background: #9c27b0; }}
.card.coverage::before {{ background: #4caf50; }}
.card.duplications::before {{ background: #2196f3; }}
.card.debt::before {{ background: #ff5722; }}
.card-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
               color: var(--fg2); margin-bottom: 8px; font-weight: 600; }}
.card-value {{ font-size: 28px; font-weight: 800; color: var(--primary); line-height: 1; }}
.card-sub {{ font-size: 12px; color: var(--fg2); margin-top: 6px; }}
.rating-badge {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 50%;
  font-weight: 800; font-size: 14px; color: #fff;
}}
.rating-A {{ background: #4caf50; }}
.rating-B {{ background: #8bc34a; }}
.rating-C {{ background: #ff9800; }}
.rating-D {{ background: #f44336; }}
.rating-E {{ background: #d32f2f; }}
.rating-dash {{ background: #9e9e9e; }}

/* ===================================================================
   Tables
   =================================================================== */
.table-wrapper {{ overflow-x: auto; border-radius: var(--radius); box-shadow: var(--shadow); }}
table {{
  width: 100%; border-collapse: collapse;
  background: var(--card-bg);
}}
thead tr {{ background: #1a237e; color: #fff; }}
thead th {{
  padding: 12px 14px; text-align: left;
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
  white-space: nowrap;
}}
tbody tr {{ border-bottom: 1px solid var(--border); transition: background var(--transition); }}
tbody tr:hover {{ background: var(--bg3); }}
tbody tr:nth-child(even) {{ background: var(--bg2); }}
tbody tr:nth-child(even):hover {{ background: var(--bg3); }}
td {{ padding: 10px 14px; font-size: 13px; vertical-align: middle; }}
.file-cell {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.msg-cell {{ max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

/* ===================================================================
   Severity & Type badges
   =================================================================== */
.badge {{
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 700; color: #fff; white-space: nowrap;
}}
.sev-BLOCKER  {{ background: var(--sev-blocker); }}
.sev-CRITICAL {{ background: var(--sev-critical); }}
.sev-MAJOR    {{ background: var(--sev-major); color: #111; }}
.sev-MINOR    {{ background: var(--sev-minor); color: #111; }}
.sev-INFO     {{ background: var(--sev-info); }}
.type-BUG           {{ background: #f44336; }}
.type-VULNERABILITY {{ background: #9c27b0; }}
.type-CODE_SMELL    {{ background: #ff9800; color: #111; }}

/* ===================================================================
   Search & Filter Bar
   =================================================================== */
.filter-bar {{
  display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px;
  align-items: center;
}}
.search-input {{
  flex: 1; min-width: 200px;
  background: var(--bg2); border: 1px solid var(--border);
  color: var(--fg); border-radius: var(--radius);
  padding: 10px 16px; font-size: 14px;
  outline: none; transition: border-color var(--transition);
}}
.search-input:focus {{ border-color: var(--primary); }}
.filter-select {{
  background: var(--bg2); border: 1px solid var(--border);
  color: var(--fg); border-radius: var(--radius);
  padding: 10px 14px; font-size: 13px; outline: none;
  cursor: pointer;
}}
.filter-count {{
  color: var(--fg2); font-size: 13px; white-space: nowrap;
}}

/* ===================================================================
   Detailed Issue Cards (collapsible)
   =================================================================== */
.issue-card {{
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 12px;
  overflow: hidden;
  transition: box-shadow var(--transition);
}}
.issue-card:hover {{ box-shadow: 0 4px 20px rgba(0,0,0,0.25); }}
.issue-header {{
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px; cursor: pointer;
  user-select: none;
  transition: background var(--transition);
}}
.issue-header:hover {{ background: var(--bg3); }}
.issue-num {{
  font-size: 12px; color: var(--fg2);
  min-width: 36px; font-weight: 600;
}}
.issue-rule {{ font-weight: 600; font-size: 13px; flex: 1; }}
.issue-file {{ font-size: 12px; color: var(--fg2); max-width: 300px;
               overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.issue-line {{ font-size: 11px; color: var(--fg2); min-width: 50px; }}
.chevron {{ transition: transform var(--transition); color: var(--fg2); }}
.issue-card.expanded .chevron {{ transform: rotate(180deg); }}
.issue-body {{
  display: none; padding: 18px; border-top: 1px solid var(--border);
}}
.issue-card.expanded .issue-body {{ display: block; }}
.issue-section-title {{
  font-weight: 700; font-size: 13px; color: var(--secondary);
  margin: 14px 0 6px; text-transform: uppercase; letter-spacing: 0.5px;
}}
.issue-text {{ font-size: 13px; color: var(--fg2); line-height: 1.7; }}
.code-snippet {{ margin: 0; padding: 12px; overflow-x: auto; border: 1px solid var(--border); border-radius: 6px; background: var(--bg2); color: var(--fg); font: 12px/1.55 'Cascadia Code', 'Fira Code', monospace; white-space: pre; }}
.meta-grid {{
  display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px;
  margin-bottom: 14px;
}}
.meta-item {{ background: var(--bg3); border-radius: 6px; padding: 10px 14px; }}
.meta-key {{ font-size: 10px; text-transform: uppercase; color: var(--fg2); margin-bottom: 4px; }}
.meta-val {{ font-size: 14px; font-weight: 600; color: var(--fg); }}
.rec-box {{
  background: var(--bg2); border-left: 3px solid var(--accent);
  padding: 12px 16px; border-radius: 0 6px 6px 0;
  margin-top: 10px;
}}
.impact-box {{
  background: var(--bg2); border-left: 3px solid var(--warning);
  padding: 12px 16px; border-radius: 0 6px 6px 0;
  margin-top: 10px;
}}
.pdt-grid {{ display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }}
.pdt-chip {{
  background: var(--bg3); border-radius: 6px; padding: 8px 14px;
  font-size: 12px;
}}
.pdt-chip strong {{ display: block; font-size: 10px; text-transform: uppercase;
                    color: var(--fg2); margin-bottom: 2px; }}
.sonar-link {{ display: inline-block; margin-top: 12px; font-size: 12px; }}

/* ===================================================================
   Charts
   =================================================================== */
.charts-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 20px; }}
.chart-card {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px;
  box-shadow: var(--shadow);
}}
.chart-title {{ font-size: 13px; font-weight: 600; color: var(--fg2);
                text-align: center; margin-bottom: 10px; }}
.chart-card img {{ width: 100%; border-radius: 4px; }}
.chart-full {{ grid-column: 1 / -1; }}

/* ===================================================================
   Summary Stats Row
   =================================================================== */
.stats-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 28px; }}
.stat-box {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 20px; flex: 1; min-width: 130px;
  text-align: center;
}}
.stat-num {{ font-size: 32px; font-weight: 800; color: var(--primary); }}
.stat-label {{ font-size: 11px; text-transform: uppercase; color: var(--fg2);
               letter-spacing: 0.5px; margin-top: 4px; }}

/* ===================================================================
   Utility
   =================================================================== */
.text-muted {{ color: var(--fg2); }}
.mb-4 {{ margin-bottom: 16px; }}
.mt-4 {{ margin-top: 16px; }}
.hidden {{ display: none !important; }}
.tag {{
  display: inline-block; background: var(--tag-bg); color: var(--fg2);
  padding: 2px 8px; border-radius: 10px; font-size: 11px; margin: 2px;
}}
/* Print */
@media print {{ nav {{ display: none; }} .issue-body {{ display: block !important; }} }}
</style>
</head>
<body>

<!-- Navigation -->
<nav>
  <div class="brand">🔍 SonarQube Report</div>
  <div class="nav-links">
    <a href="#summary">Summary</a>
    <a href="#overview">Quality</a>
    <a href="#charts">Charts</a>
    <a href="#files">Files</a>
    <a href="#issues-table">Issues</a>
    <a href="#detailed">Details</a>
    <a href="#top-files">Top Files</a>
    <a href="#top-rules">Top Rules</a>
    <a href="#debt">Debt</a>
  </div>
  <button class="theme-btn" onclick="toggleTheme()">☀️ Light</button>
</nav>

<div class="container">

<!-- Hero -->
<div class="hero">
  <h1>{_esc(data.project_name)}</h1>
  <div class="subtitle">{_esc(data.report_title)} · {_esc(data.company_name)}</div>
  <div class="{"gate-badge gate-passed" if gate_ok else "gate-badge gate-failed"}">
    {"✅ Quality Gate: PASSED" if gate_ok else "❌ Quality Gate: FAILED"}
  </div>
  <div class="hero-meta">
    <span class="meta-chip">📦 {_esc(data.project_key)}</span>
    <span class="meta-chip">📅 {_esc(generated)}</span>
    <span class="meta-chip">🐛 {m.bugs} Bugs</span>
    <span class="meta-chip">🔒 {m.vulnerabilities} Vulnerabilities</span>
    <span class="meta-chip">💨 {m.code_smells} Code Smells</span>
    <span class="meta-chip">📏 {m.ncloc:,} Lines of Code</span>
  </div>
</div>

<!-- Stats Row -->
<div class="stats-row" id="summary">
  <div class="stat-box"><div class="stat-num">{len(data.issues)}</div><div class="stat-label">Total Issues</div></div>
  <div class="stat-box"><div class="stat-num">{m.bugs}</div><div class="stat-label">Bugs</div></div>
  <div class="stat-box"><div class="stat-num">{m.vulnerabilities}</div><div class="stat-label">Vulnerabilities</div></div>
  <div class="stat-box"><div class="stat-num">{m.code_smells}</div><div class="stat-label">Code Smells</div></div>
  <div class="stat-box"><div class="stat-num">{m.coverage:.1f}%</div><div class="stat-label">Coverage</div></div>
  <div class="stat-box"><div class="stat-num">{m.duplicated_lines_density:.1f}%</div><div class="stat-label">Duplications</div></div>
  <div class="stat-box"><div class="stat-num">{m.ncloc:,}</div><div class="stat-label">Lines of Code</div></div>
  <div class="stat-box"><div class="stat-num">{m.files}</div><div class="stat-label">Files</div></div>
</div>

<!-- Executive Summary -->
<section id="exec-summary">
  <div class="section-title"><span class="icon">📋</span> Executive Summary</div>
  {exec_summary_html}
</section>

<!-- Quality Overview -->
<section id="overview">
  <div class="section-title"><span class="icon">🎯</span> Quality Overview</div>
  {quality_cards_html}
</section>

<!-- Charts -->
<section id="charts">
  <div class="section-title"><span class="icon">📊</span> Charts &amp; Visualisations</div>
  {charts_html}
</section>

<!-- Files Analysis -->
<section id="files">
  <div class="section-title"><span class="icon">📁</span> Files Analysis</div>
  {files_table_html}
</section>

<!-- Issues Table -->
<section id="issues-table">
  <div class="section-title"><span class="icon">📋</span> Issues Summary</div>
  <div class="filter-bar">
    <input class="search-input" type="text" id="issueSearch"
           placeholder="🔍  Search issues by rule, file, message…"
           oninput="filterIssues()"/>
    <select class="filter-select" id="sevFilter" onchange="filterIssues()">
      <option value="">All Severities</option>
      <option>BLOCKER</option><option>CRITICAL</option>
      <option>MAJOR</option><option>MINOR</option><option>INFO</option>
    </select>
    <select class="filter-select" id="typeFilter" onchange="filterIssues()">
      <option value="">All Types</option>
      <option value="BUG">Bug</option>
      <option value="VULNERABILITY">Vulnerability</option>
      <option value="CODE_SMELL">Code Smell</option>
    </select>
    <select class="filter-select" id="statusFilter" onchange="filterIssues()">
      <option value="">All Statuses</option>
      <option>OPEN</option><option>CONFIRMED</option>
      <option>RESOLVED</option><option>CLOSED</option>
    </select>
    <span class="filter-count" id="filterCount"></span>
  </div>
  {issues_table_html}
</section>

<!-- Detailed Issues -->
<section id="detailed">
  <div class="section-title"><span class="icon">🔬</span> Detailed Issues</div>
  <div class="mb-4">
    <button onclick="expandAll()" style="margin-right:8px;padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--bg2);color:var(--fg);cursor:pointer;">Expand All</button>
    <button onclick="collapseAll()" style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--bg2);color:var(--fg);cursor:pointer;">Collapse All</button>
  </div>
  {detailed_issues_html}
</section>

<!-- Top Files -->
<section id="top-files">
  <div class="section-title"><span class="icon">🏆</span> Top Files</div>
  {top_files_html}
</section>

<!-- Top Rules -->
<section id="top-rules">
  <div class="section-title"><span class="icon">📏</span> Top Rules</div>
  {top_rules_html}
</section>

<!-- Technical Debt -->
<section id="debt">
  <div class="section-title"><span class="icon">⏱️</span> Technical Debt</div>
  {tech_debt_html}
</section>

</div><!-- /container -->

<script>
// -----------------------------------------------------------------------
// Issues data for JS search engine
// -----------------------------------------------------------------------
const ISSUES = {issues_json};
const rows   = Array.from(document.querySelectorAll('#issuesTableBody tr'));

function filterIssues() {{
  const q      = document.getElementById('issueSearch').value.toLowerCase();
  const sev    = document.getElementById('sevFilter').value;
  const type   = document.getElementById('typeFilter').value;
  const status = document.getElementById('statusFilter').value;
  let count = 0;
  rows.forEach((row, i) => {{
    const issue = ISSUES[i];
    if (!issue) return;
    const match =
      (!q    || (issue.rule + issue.file + issue.msg).toLowerCase().includes(q)) &&
      (!sev  || issue.severity === sev) &&
      (!type || issue.type === type)    &&
      (!status || issue.status === status);
    row.classList.toggle('hidden', !match);
    if (match) count++;
  }});
  document.getElementById('filterCount').textContent =
    count === rows.length ? `${{rows.length}} issues` : `${{count}} of ${{rows.length}} issues`;
}}

// Initialise count
window.addEventListener('DOMContentLoaded', () => {{
  document.getElementById('filterCount').textContent = `${{rows.length}} issues`;
}});

// -----------------------------------------------------------------------
// Collapsible issue cards
// -----------------------------------------------------------------------
function toggleCard(el) {{
  el.closest('.issue-card').classList.toggle('expanded');
}}
function expandAll() {{
  document.querySelectorAll('.issue-card').forEach(c => c.classList.add('expanded'));
}}
function collapseAll() {{
  document.querySelectorAll('.issue-card').forEach(c => c.classList.remove('expanded'));
}}

// -----------------------------------------------------------------------
// Theme toggle
// -----------------------------------------------------------------------
function toggleTheme() {{
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', isDark ? 'light' : 'dark');
  document.querySelector('.theme-btn').textContent = isDark ? '🌙 Dark' : '☀️ Light';
}}
</script>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _exec_summary_html(self, data: ReportData) -> str:
        m = data.metrics
        rows = [
            ("Lines of Code",    f"{m.ncloc:,}",                            "–"),
            ("Bugs",             str(m.bugs),                                m.reliability_rating_letter),
            ("Vulnerabilities",  str(m.vulnerabilities),                     m.security_rating_letter),
            ("Code Smells",      str(m.code_smells),                         m.sqale_rating_letter),
            ("Technical Debt",   m.technical_debt_display,                   "–"),
            ("Coverage",         f"{m.coverage:.1f}%",                       "–"),
            ("Duplicated Lines", f"{m.duplicated_lines_density:.1f}%",        "–"),
            ("Open Issues",      str(m.open_issues),                         "–"),
            ("Accepted Issues",  str(m.accepted_issues),                     "–"),
            ("Resolved Issues",  str(m.resolved_issues),                     "–"),
        ]
        rows_html = ""
        for i, (label, val, rating) in enumerate(rows):
            rating_html = (
                f'<span class="rating-badge rating-{_esc(rating)}">{_esc(rating)}</span>'
                if rating != "–" else "–"
            )
            bg = "background:var(--bg2)" if i % 2 == 0 else ""
            rows_html += f'<tr style="{bg}"><td><strong>{_esc(label)}</strong></td><td>{_esc(val)}</td><td>{rating_html}</td></tr>'

        return f"""
<div class="table-wrapper">
<table>
  <thead><tr><th>Metric</th><th>Value</th><th>Rating</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>"""

    def _quality_cards_html(self, data: ReportData) -> str:
        m = data.metrics
        cards = [
            ("reliability",     "Reliability",     f"{m.bugs} Bug(s)",                   m.reliability_rating_letter),
            ("maintainability", "Maintainability", f"{m.code_smells} Code Smell(s)",      m.sqale_rating_letter),
            ("security",        "Security",        f"{m.vulnerabilities} Vuln(s)",        m.security_rating_letter),
            ("coverage",        "Coverage",        f"{m.coverage:.1f}%",                  "–"),
            ("duplications",    "Duplications",    f"{m.duplicated_lines_density:.1f}%",   "–"),
            ("debt",            "Tech Debt",       m.technical_debt_display,               "–"),
        ]
        cards_html = ""
        for css_class, label, value, rating in cards:
            rating_html = (
                f'<span class="rating-badge rating-{_esc(rating)}">{_esc(rating)}</span>'
                if rating not in ("–",) else ""
            )
            cards_html += f"""
<div class="card {_esc(css_class)}">
  <div class="card-label">{_esc(label)}</div>
  <div class="card-value">{_esc(value)}</div>
  <div class="card-sub">{rating_html}</div>
</div>"""
        return f'<div class="cards">{cards_html}</div>'

    def _charts_html(self, charts: dict[str, str]) -> str:
        pairs = [
            ("severity_pie",    "Severity Distribution"),
            ("type_pie",        "Issue Type Distribution"),
            ("severity_bar",    "Issues by Severity"),
            ("security_pie",    "Security Distribution"),
            ("maintainability", "Maintainability Trend"),
        ]
        html = '<div class="charts-grid">'
        for key, title in pairs:
            img_src = f"data:image/png;base64,{charts.get(key, '')}"
            html += f"""
<div class="chart-card">
  <div class="chart-title">{_esc(title)}</div>
  <img src="{img_src}" alt="{_esc(title)}" loading="lazy"/>
</div>"""

        # Full-width charts
        for key, title in [("files_bar", "Top Files by Issue Count"), ("rules_bar", "Top Violated Rules")]:
            img_src = f"data:image/png;base64,{charts.get(key, '')}"
            html += f"""
<div class="chart-card chart-full">
  <div class="chart-title">{_esc(title)}</div>
  <img src="{img_src}" alt="{_esc(title)}" loading="lazy"/>
</div>"""
        html += "</div>"
        return html

    def _files_table_html(self, data: ReportData) -> str:
        rows_html = ""
        for rank, fa in enumerate(data.top_files, start=1):
            rows_html += f"""
<tr>
  <td>{rank}</td>
  <td class="file-cell" title="{_esc(fa.path)}">{_esc(fa.file_name)}</td>
  <td><strong>{fa.total_issues}</strong></td>
  <td>{fa.bugs}</td>
  <td>{fa.code_smells}</td>
  <td>{fa.vulnerabilities}</td>
  <td>{fa.effort_minutes}</td>
</tr>"""
        return f"""
<div class="table-wrapper">
<table>
  <thead><tr><th>#</th><th>File</th><th>Total</th><th>Bugs</th>
    <th>Code Smells</th><th>Vulns</th><th>Effort (min)</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>"""

    def _issues_table_html(self, data: ReportData) -> str:
        rows_html = ""
        for idx, issue in enumerate(data.issues_sorted_by_severity, start=1):
            sev_badge = f'<span class="badge sev-{_esc(issue.severity.value)}">{_esc(issue.severity.value)}</span>'
            type_badge = f'<span class="badge type-{_esc(issue.issue_type.value)}">{_esc(issue.issue_type.label)}</span>'
            rows_html += f"""
<tr>
  <td>{idx}</td>
  <td>{sev_badge}</td>
  <td>{type_badge}</td>
  <td><code>{_esc(issue.rule.split(":")[-1])}</code></td>
  <td class="file-cell" title="{_esc(issue.file_path)}">{_esc(issue.file_name)}</td>
  <td>{issue.display_line or "–"}</td>
  <td>{_esc(issue.issue_status.value)}</td>
  <td class="msg-cell" title="{_esc(issue.message)}">{_esc(issue.message[:80])}</td>
</tr>"""
        return f"""
<div class="table-wrapper">
<table id="issuesTable">
  <thead><tr>
    <th>#</th><th>Severity</th><th>Type</th><th>Rule</th>
    <th>File</th><th>Line</th><th>Status</th><th>Message</th>
  </tr></thead>
  <tbody id="issuesTableBody">{rows_html}</tbody>
</table>
</div>"""

    def _detailed_issues_html(self, data: ReportData) -> str:
        html_parts = []
        for idx, issue in enumerate(data.issues_sorted_by_severity, start=1):
            rec  = self._rec_engine.recommend(issue, data.sonar_url)
            rule = data.rules.get(issue.rule, {})
            rule_desc  = self._strip_html(rule.get("mdDesc", rule.get("htmlDesc", "")))[:600]
            rule_fix   = self._strip_html(rule.get("mdNote", ""))[:400]

            sev_badge = f'<span class="badge sev-{_esc(issue.severity.value)}">{_esc(issue.severity.value)}</span>'
            type_badge = f'<span class="badge type-{_esc(issue.issue_type.value)}">{_esc(issue.issue_type.label)}</span>'
            tags_html = " ".join(f'<span class="tag">{_esc(t)}</span>' for t in issue.tags)

            rule_desc_section = ""
            if rule_desc:
                rule_desc_section = f"""
<div class="issue-section-title">❓ Why Is This an Issue?</div>
<p class="issue-text">{_esc(rule_desc)}</p>"""

            rule_fix_section = ""
            if rule_fix:
                rule_fix_section = f"""
<div class="issue-section-title">🔧 Remediation</div>
<p class="issue-text">{_esc(rule_fix)}</p>"""

            source_section = ""
            if issue.code_snippet:
                source_section = f"""
<div class="issue-section-title">💻 Code</div>
<pre class="code-snippet">{_esc(issue.code_snippet)}</pre>"""

            sonar_link = ""
            if rec.sonar_url:
                sonar_link = f'<a href="{_esc(rec.sonar_url)}" class="sonar-link" target="_blank">🔗 Open in SonarQube</a>'

            html_parts.append(f"""
<div class="issue-card" id="issue-{idx}" data-sev="{_esc(issue.severity.value)}"
     data-type="{_esc(issue.issue_type.value)}" data-status="{_esc(issue.issue_status.value)}">
  <div class="issue-header" onclick="toggleCard(this)">
    <span class="issue-num">#{idx}</span>
    {sev_badge}
    {type_badge}
    <span class="issue-rule">{_esc(issue.rule)}</span>
    <span class="issue-file" title="{_esc(issue.file_path)}">{_esc(issue.file_name)}</span>
    <span class="issue-line">L{issue.display_line or '–'}</span>
    <span class="chevron">▼</span>
  </div>
  <div class="issue-body">
    <div class="meta-grid">
      <div class="meta-item"><div class="meta-key">Severity</div><div class="meta-val">{sev_badge}</div></div>
      <div class="meta-item"><div class="meta-key">Type</div><div class="meta-val">{type_badge}</div></div>
      <div class="meta-item"><div class="meta-key">File</div><div class="meta-val" title="{_esc(issue.file_path)}" style="font-size:11px">{_esc(self.truncate(issue.file_path, 45))}</div></div>
      <div class="meta-item"><div class="meta-key">Line</div><div class="meta-val">{issue.display_line or '–'}</div></div>
      <div class="meta-item"><div class="meta-key">Status</div><div class="meta-val">{_esc(issue.issue_status.value)}</div></div>
      <div class="meta-item"><div class="meta-key">Effort</div><div class="meta-val">{_esc(issue.effort)}</div></div>
    </div>

    <div class="issue-section-title">📌 Problem</div>
    <p class="issue-text">{_esc(issue.message)}</p>
    {source_section}
    {rule_desc_section}
    {rule_fix_section}

    <div class="issue-section-title">💡 Developer Recommendation</div>
    <div class="rec-box issue-text">{_esc(rec.developer_recommendation)}</div>

    <div class="issue-section-title">📈 Business Impact</div>
    <div class="impact-box issue-text">{_esc(rec.business_impact)}</div>

    <div class="pdt-grid">
      <div class="pdt-chip"><strong>Priority</strong>{_esc(rec.priority.value)}</div>
      <div class="pdt-chip"><strong>Difficulty</strong>{_esc(rec.difficulty.value)}</div>
      <div class="pdt-chip"><strong>Est. Time</strong>{_esc(rec.estimated_time)}</div>
    </div>

    {f'<div class="mt-4">{tags_html}</div>' if tags_html else ''}
    {sonar_link}
  </div>
</div>""")
        return "\n".join(html_parts)

    def _top_files_html(self, data: ReportData) -> str:
        rows_html = ""
        for rank, fa in enumerate(data.top_files, start=1):
            rows_html += f"""
<tr>
  <td>{rank}</td>
  <td class="file-cell" title="{_esc(fa.path)}">{_esc(fa.path)}</td>
  <td><strong>{fa.total_issues}</strong></td>
  <td>{fa.bugs}</td><td>{fa.code_smells}</td>
  <td>{fa.vulnerabilities}</td><td>{fa.blocker}</td><td>{fa.critical}</td>
</tr>"""
        return f"""
<div class="table-wrapper">
<table>
  <thead><tr><th>#</th><th>File</th><th>Total</th><th>Bugs</th>
    <th>Code Smells</th><th>Vulns</th><th>Blocker</th><th>Critical</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>"""

    def _top_rules_html(self, data: ReportData) -> str:
        rows_html = ""
        for rank, ra in enumerate(data.top_rules, start=1):
            sev_badge = f'<span class="badge sev-{_esc(ra.severity)}">{_esc(ra.severity)}</span>'
            rows_html += f"""
<tr>
  <td>{rank}</td>
  <td><code>{_esc(ra.rule_key)}</code></td>
  <td><strong>{ra.count}</strong></td>
  <td>{sev_badge}</td>
  <td>{_esc(ra.issue_type.replace("_", " ").title())}</td>
  <td class="msg-cell">{_esc(ra.message_sample)}</td>
</tr>"""
        return f"""
<div class="table-wrapper">
<table>
  <thead><tr><th>#</th><th>Rule Key</th><th>Violations</th>
    <th>Severity</th><th>Type</th><th>Sample Message</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>"""

    def _tech_debt_html(self, data: ReportData) -> str:
        m = data.metrics
        rows = [
            ("Total Technical Debt",        m.technical_debt_display),
            ("Debt Ratio",                  f"{m.sqale_debt_ratio:.2f}%"),
            ("Total Estimated Effort",       data.total_effort_display),
            ("Files Analysed",               str(m.files)),
            ("Cyclomatic Complexity",        str(m.complexity)),
            ("Cognitive Complexity",         str(m.cognitive_complexity)),
            ("Comment Density",              f"{m.comment_lines_density:.1f}%"),
        ]
        rows_html = ""
        for i, (label, val) in enumerate(rows):
            bg = "background:var(--bg2)" if i % 2 == 0 else ""
            rows_html += f'<tr style="{bg}"><td><strong>{_esc(label)}</strong></td><td>{_esc(val)}</td></tr>'

        return f"""
<p class="text-muted mb-4">
  The project carries a total technical debt of <strong>{_esc(m.technical_debt_display)}</strong>
  (debt ratio: <strong>{m.sqale_debt_ratio:.2f}%</strong>).
  The estimated total remediation effort for all {len(data.issues)} issues is
  <strong>{_esc(data.total_effort_display)}</strong>.
</p>
<div class="table-wrapper">
<table>
  <thead><tr><th>Metric</th><th>Value</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_issues_json(self, data: ReportData) -> str:
        issues = [
            {
                "rule":     i.rule,
                "severity": i.severity.value,
                "type":     i.issue_type.value,
                "file":     i.file_path,
                "msg":      i.message,
                "status":   i.issue_status.value,
            }
            for i in data.issues_sorted_by_severity
        ]
        return json.dumps(issues, ensure_ascii=False)

    @staticmethod
    def _strip_html(html: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html or "")
        return re.sub(r"\s+", " ", text).strip()
