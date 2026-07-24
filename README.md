# SonarQube Report Generator

Enterprise-grade code quality reporting for SonarQube Community Build 25.x.
Replaces the built-in PDF export that was removed in SonarQube Community Edition.

## Features

- **5 report formats**: PDF, DOCX, Excel, HTML, JSON
- **PDF**: Cover page, ToC, Executive Summary, Quality Overview cards, 7 charts, Files Analysis, Issues Table, per-issue Detailed Sections with developer recommendations, Top Files, Top Rules, Technical Debt — all with header/footer and page numbers
- **DOCX**: Equivalent Word document with embedded charts
- **Excel**: 5 sheets — Overview, Issues (with auto-filter), Files, Rules, Metrics
- **HTML**: Dark/light mode toggle, live search, severity/type/status filters, collapsible issue detail cards, all charts embedded as base64
- **JSON**: Full raw API backup for offline/CI use
- **Deterministic recommendations**: Rule-based engine covering 20+ SonarQube rule keys — no AI API required
- **Source context**: Detailed issues include up to five source lines before and after the affected line, when SonarQube source access is available
- **Pagination**: Fetches all issues automatically (handles 10 000+ issues)
- **Retry logic**: Exponential backoff on 429/5xx errors

## Requirements

- Python 3.12+
- A running SonarQube instance (Community Build 25.x or any recent version)
- A SonarQube user token with **Browse** permission on the project
- **See Source Code** permission on the project to include code snippets in reports

## Installation

```bash
cd sonar-report-generator
pip install -r requirements.txt
```

## Usage

### Option 1 — Environment variables (recommended for CI)

```bash
export SONAR_URL=https://sonarqube.example.com
export SONAR_TOKEN=squ_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export PROJECT_KEY=my-project-key

python app.py
```

### Option 2 — `.env` file (recommended for local development)

Create a file named `.env` in the project root with:

```env
SONAR_URL=https://sonarqube.example.com
SONAR_TOKEN=squ_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PROJECT_KEY=my-project-key
OUTPUT_DIR=output
COMPANY_NAME="My Company"
REPORT_TITLE="Code Quality Audit Report"
PAGE_SIZE=500
REQUEST_TIMEOUT=30
MAX_RETRIES=3
```

Then run:

```bash
python app.py
```

The app will automatically load variables from `.env` if they are not already set in the shell.

### Option 3 — Interactive prompts (optional)

```bash
INTERACTIVE_CONFIG=true python app.py
# prompts for SONAR_URL, SONAR_TOKEN, PROJECT_KEY
```

### Optional environment variables

| Variable       | Default                      | Description                        |
|----------------|------------------------------|------------------------------------|
| `OUTPUT_DIR`   | `output/`                    | Where to write report files        |
| `COMPANY_NAME` | `SonarQube Report Generator` | Appears in reports and PDF metadata |
| `REPORT_TITLE` | Project-based title           | Report title override              |
| `PAGE_SIZE` | `500` | Issues requested per API page (1–500) |
| `REQUEST_TIMEOUT` | `30` | HTTP request timeout in seconds |
| `MAX_RETRIES` | `3` | Retries for temporary API failures |
| `ENV_FILE` | `.env` in project root | Optional path to a different env file |
| `INTERACTIVE_CONFIG` | unset | Set to `true` to allow interactive prompts when required values are absent |

## Output

All files are written to `OUTPUT_DIR` (default: `output/`):

```
output/
├── Report.pdf      # Full PDF report
├── Report.docx     # Word document
├── Report.xlsx     # Excel workbook
├── report.html     # Interactive HTML report
└── raw.json        # Full JSON data backup
```

## Project Structure

```
sonar-report-generator/
├── app.py                          # Main entry point
├── config.py                       # Configuration loader
├── requirements.txt
│
├── api/
│   ├── client.py                   # HTTP client with retry
│   └── sonar_api.py                # SonarQube REST API wrapper
│
├── models/
│   ├── issue.py                    # Issue, Severity, IssueType enums + dataclasses
│   ├── metrics.py                  # Metrics dataclass
│   └── project.py                  # ReportData, FileAnalysis, RuleAnalysis
│
├── services/
│   ├── data_service.py             # Orchestrates API calls → ReportData
│   ├── chart_service.py            # Generates charts as PNG bytes (matplotlib)
│   └── recommendation_engine.py   # Rule-based fix recommendations
│
├── reports/
│   ├── base_report.py              # ABC base class
│   ├── pdf_report.py               # ReportLab PDF
│   ├── docx_report.py              # python-docx Word
│   ├── excel_report.py             # openpyxl Excel
│   ├── html_report.py              # Self-contained dark-mode HTML
│   └── json_report.py              # JSON backup
│
├── assets/                         # Static assets (logo, fonts)
└── output/                         # Generated reports (git-ignored)
```

## SonarQube APIs Used

All calls use the official REST API — no internal/private endpoints:

| Endpoint                        | Purpose                          |
|---------------------------------|----------------------------------|
| `GET /api/projects/search`      | Project name and metadata        |
| `GET /api/project_branches/list`| Branch list                      |
| `GET /api/measures/component`   | 30+ quality metrics              |
| `GET /api/issues/search`        | All issues (paginated)           |
| `GET /api/sources/show`         | Affected source context per issue |
| `GET /api/rules/show`           | Rule description and remediation |

## Architecture

The project follows SOLID principles:

- **Single Responsibility**: each class does one thing (API client, data models, chart service, report generators)
- **Open/Closed**: add a new report format by subclassing `BaseReport` — no changes to existing code
- **Dependency Inversion**: `DataService` receives a `Config`; report generators receive a typed `ReportData` object — no tight coupling to HTTP or filesystem

Data flow:

```
Config
  └── DataService.collect()
        ├── SonarAPI  →  raw API JSON
        └── ReportData (typed models)
              ├── PDFReport.generate()
              ├── DocxReport.generate()
              ├── ExcelReport.generate()
              ├── HtmlReport.generate()
              └── JsonReport.generate()
```

## Recommendation Engine

The `RecommendationEngine` produces plain-English developer guidance for each issue without calling any AI API. It matches on:

1. **Rule key** (e.g. `typescript:S3776` → "Extract nested logic into named functions to reduce cognitive complexity")
2. **Rule tags** (e.g. `accessibility`, `performance`, `obsolete`)
3. **Issue type fallback** (BUG / VULNERABILITY / CODE_SMELL / SECURITY_HOTSPOT)

Each recommendation includes: priority, fix difficulty, estimated time, developer recommendation, and business impact.

## Troubleshooting

**`401 Unauthorized`** — Check your `SONAR_TOKEN`. Generate a new one in SonarQube → My Account → Security.

**`404 Not Found`** — Verify `PROJECT_KEY` matches exactly (case-sensitive) and the project has been analysed at least once.

**Empty metrics (all zeros)** — The project may not have run a full analysis yet, or your token lacks Browse permission on the project.

**Charts missing in DOCX** — Ensure `matplotlib` and `Pillow` are installed: `pip install matplotlib Pillow`.

**Large projects** — For projects with 10 000+ issues, collection may take a few minutes. Progress is logged to stdout.

## Dependencies

| Package        | Version  | Use                              |
|----------------|----------|----------------------------------|
| requests       | 2.32.3   | HTTP client                      |
| urllib3        | 2.2.3    | Retry adapter                    |
| reportlab      | 4.2.5    | PDF generation                   |
| python-docx    | 1.1.2    | Word document generation         |
| openpyxl       | 3.1.5    | Excel workbook generation        |
| matplotlib     | 3.9.2    | Chart generation (Agg backend)   |
| Pillow         | 10.4.0   | Image handling                   |
| jinja2         | 3.1.4    | (available for template use)     |
| pandas         | 2.2.3    | (available for data processing)  |

## License

MIT
