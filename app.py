"""
SonarQube Report Generator – main entry point.

Usage
-----
    python app.py

Environment variables (or interactive prompt fallback):
    SONAR_URL      – e.g. https://sonarqube.example.com
    SONAR_TOKEN    – SonarQube user/project token
    PROJECT_KEY    – e.g. my-project
    OUTPUT_DIR     – (optional) output directory, default: output/
    COMPANY_NAME   – (optional) company name shown in report cover
    REPORT_TITLE   – (optional) report title override

Outputs written to OUTPUT_DIR:
    Report.pdf   – Full enterprise-grade PDF report
    Report.docx  – Word document
    Report.xlsx  – Excel workbook (5 sheets)
    report.html  – Interactive dark-mode HTML report
    raw.json     – Full JSON data backup
"""

from __future__ import annotations

import logging
import os
import sys
import time
import warnings
from pathlib import Path

# macOS Command Line Tools Python is linked with LibreSSL and urllib3 v2 emits
# this compatibility warning even though HTTP requests still work. It is not a
# report-generation error, so keep normal runs focused on actionable output.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")

# ---------------------------------------------------------------------------
# Logging setup – do this before any local imports so all loggers inherit it
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------
from api import APIClient, SonarAPI
from api.client import SonarHTTPError
from requests import RequestException
from config import load_config
from services.data_service import DataService
from reports.pdf_report import PDFReport
from reports.docx_report import DocxReport
from reports.excel_report import ExcelReport
from reports.html_report import HtmlReport
from reports.json_report import JsonReport


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║          SonarQube Report Generator  v1.0.0                 ║
║          Enterprise Code Quality Reporting Suite             ║
╚══════════════════════════════════════════════════════════════╝
"""


def _print_summary(paths: dict[str, str], elapsed: float) -> None:
    """Print a post-run summary table."""
    print("\n" + "═" * 62)
    print("  ✅  All reports generated successfully!")
    print("═" * 62)
    labels = {"PDF": "📄", "DOCX": "📝", "Excel": "📊", "HTML": "🌐", "JSON": "💾"}
    for fmt, path in paths.items():
        icon = labels.get(fmt, "📁")
        size = Path(path).stat().st_size // 1024 if Path(path).exists() else 0
        print(f"  {icon}  {fmt:<6}  {path}  ({size} KB)")
    print("═" * 62)
    print(f"  ⏱️  Total time: {elapsed:.1f}s")
    print("═" * 62 + "\n")


def main() -> int:
    """
    Orchestrate the full report generation pipeline.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on error.
    """
    print(BANNER)
    start = time.monotonic()

    # ------------------------------------------------------------------
    # 1. Load configuration
    # ------------------------------------------------------------------
    try:
        config = load_config()
    except KeyboardInterrupt:
        print("\n[Aborted]")
        return 1
    except ValueError as exc:
        logger.error("Invalid configuration: %s", exc)
        return 1

    logger.info(
        "Configuration loaded – project=%s  url=%s  output=%s",
        config.project_key,
        config.sonar_url,
        config.output_dir,
    )

    # ------------------------------------------------------------------
    # 2. Ensure output directory exists
    # ------------------------------------------------------------------
    os.makedirs(config.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 3. Fetch data from SonarQube
    # ------------------------------------------------------------------
    logger.info("Connecting to SonarQube …")
    try:
        client = APIClient(
            base_url=config.sonar_url,
            token=config.sonar_token,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
        )
        api = SonarAPI(client, config.project_key)
        data_service = DataService(
            api,
            page_size=config.page_size,
            company_name=config.company_name,
            report_title=config.report_title,
        )
        report_data = data_service.collect()
    except SonarHTTPError as exc:
        if exc.status_code in (401, 403):
            logger.error(
                "SonarQube access denied (%s). Generate a valid token for this server "
                "and grant its user Browse permission on project '%s'.",
                exc.status_code,
                config.project_key,
            )
        else:
            logger.error("SonarQube API request failed: %s", exc)
        return 1
    except RequestException as exc:
        logger.error(
            "Cannot connect to SonarQube at %s: %s. Check SONAR_URL and make sure the server is running.",
            config.sonar_url,
            exc,
        )
        return 1
    except Exception as exc:
        logger.error("Failed to collect data from SonarQube: %s", exc, exc_info=True)
        return 1

    logger.info(
        "Data collected – %d issues | %d files | %d rules",
        len(report_data.issues),
        len(report_data.file_stats),
        len(report_data.rules),
    )

    # ------------------------------------------------------------------
    # 4. Generate reports
    # ------------------------------------------------------------------
    generators = [
        ("JSON",  JsonReport(config.output_dir)),   # JSON first – fast, no deps
        ("PDF",   PDFReport(config.output_dir)),
        ("DOCX",  DocxReport(config.output_dir)),
        ("Excel", ExcelReport(config.output_dir)),
        ("HTML",  HtmlReport(config.output_dir)),
    ]

    output_paths: dict[str, str] = {}
    errors: list[str] = []

    for fmt, generator in generators:
        try:
            logger.info("Generating %s report …", fmt)
            t0 = time.monotonic()
            path = generator.generate(report_data)
            elapsed = time.monotonic() - t0
            output_paths[fmt] = path
            logger.info("%s report done in %.1fs  →  %s", fmt, elapsed, path)
        except Exception as exc:  # noqa: BLE001
            msg = f"{fmt} report failed: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

    # ------------------------------------------------------------------
    # 5. Summary
    # ------------------------------------------------------------------
    total_elapsed = time.monotonic() - start
    _print_summary(output_paths, total_elapsed)

    if errors:
        print("⚠️  Some reports had errors:")
        for err in errors:
            print(f"   • {err}")
        print()

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
