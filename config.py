"""
Configuration module for SonarQube Report Generator.

Reads connection parameters from environment variables.  An interactive prompt
is available only when explicitly enabled for a local terminal session.
All settings are centralized here following the Single Responsibility Principle.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the root application logger."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("sonar_report")


def _load_dotenv(path: Path) -> dict[str, str]:
    """Parse the subset of dotenv syntax used by this project.

    Shell variables have priority over values in the file.  Supporting
    ``export KEY=value`` and quoted values makes the local configuration work
    consistently in both a terminal and common dotenv editors.
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
                logger.warning("Ignoring invalid key in %s: %s", path, key)
                continue
            if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            env[key] = value
    return env


def _apply_dotenv() -> None:
    """Load environment variables from .env if they are not already set.

    This also treats an existing empty environment variable as unset so
    a valid value from .env can still be applied.
    """
    env_path = Path(os.environ.get("ENV_FILE", Path(__file__).resolve().parent / ".env")).expanduser()
    for key, value in _load_dotenv(env_path).items():
        if not os.environ.get(key):
            os.environ[key] = value


logger = setup_logging()


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """
    Immutable configuration object for the report generator.

    Attributes:
        sonar_url:       Base URL of the SonarQube instance (no trailing slash).
        sonar_token:     Authentication token (sqp_… or sqa_…).
        project_key:     SonarQube project key to analyse.
        output_dir:      Directory where generated reports will be saved.
        page_size:       Number of issues to fetch per API page (max 500).
        request_timeout: HTTP request timeout in seconds.
        max_retries:     Number of retry attempts on transient failures.
        company_name:    Company name shown in report headers/footer.
        report_title:    Custom title override (defaults to project name).
    """

    sonar_url: str
    sonar_token: str
    project_key: str
    output_dir: str = "output"
    page_size: int = 500
    request_timeout: int = 30
    max_retries: int = 3
    company_name: str = "SonarQube Report Generator"
    report_title: Optional[str] = None

    # Internal derived fields (set post-init)
    _base_url: str = field(init=False, repr=False, default="")

    def __post_init__(self) -> None:
        self.sonar_url = self.sonar_url.rstrip("/")
        if not self.sonar_url.startswith(("http://", "https://")):
            raise ValueError("SONAR_URL must start with http:// or https://")
        if not 1 <= self.page_size <= 500:
            raise ValueError("PAGE_SIZE must be between 1 and 500")
        if self.request_timeout <= 0:
            raise ValueError("REQUEST_TIMEOUT must be greater than 0")
        if self.max_retries < 0:
            raise ValueError("MAX_RETRIES cannot be negative")
        self._base_url = self.sonar_url
        self.output_dir = str(Path(self.output_dir).expanduser())

    @property
    def base_url(self) -> str:
        """Normalized base URL without trailing slash."""
        return self._base_url

    @property
    def auth(self) -> tuple[str, str]:
        """HTTP Basic Auth tuple expected by requests."""
        return (self.sonar_token, "")


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------

def load_config() -> Config:
    """
    Load configuration from environment variables.

    Environment variables:
        SONAR_URL       – required
        SONAR_TOKEN     – required
        PROJECT_KEY     – required
        OUTPUT_DIR      – optional, default "output"
        PAGE_SIZE       – optional, 1–500, default 500
        REQUEST_TIMEOUT – optional seconds, default 30
        MAX_RETRIES     – optional, default 3
        COMPANY_NAME    – optional
        REPORT_TITLE    – optional

    Set ``INTERACTIVE_CONFIG=true`` only when prompts are desired.  Otherwise,
    missing required values result in a clear error instead of blocking CI or
    a normal ``python app.py`` run.
    """
    _apply_dotenv()

    sonar_url = os.environ.get("SONAR_URL", "").strip()
    sonar_token = os.environ.get("SONAR_TOKEN", "").strip()
    project_key = os.environ.get("PROJECT_KEY", "").strip()

    # Prompts are opt-in so a missing .env never leaves automated runs waiting
    # for terminal input.
    interactive = os.environ.get("INTERACTIVE_CONFIG", "").strip().lower() in {"1", "true", "yes"}
    if interactive:
        if not sonar_url:
            sonar_url = input("Enter SonarQube URL (e.g. http://localhost:9000): ").strip()
        if not sonar_token:
            sonar_token = input("Enter SonarQube Token (sqp_…): ").strip()
        if not project_key:
            project_key = input("Enter Project Key (e.g. bm-admin-fe): ").strip()

    missing = []
    if not sonar_url:
        missing.append("SONAR_URL")
    if not sonar_token:
        missing.append("SONAR_TOKEN")
    if not project_key:
        missing.append("PROJECT_KEY")

    if missing:
        env_path = Path(os.environ.get("ENV_FILE", Path(__file__).resolve().parent / ".env")).expanduser()
        logger.error("Missing required configuration: %s", ", ".join(missing))
        raise ValueError(
            f"Missing required configuration: {', '.join(missing)}. "
            f"Add them to {env_path} or set ENV_FILE to the correct file."
        )

    def optional_int(name: str, default: int) -> int:
        raw_value = os.environ.get(name, "").strip()
        if not raw_value:
            return default
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer; received {raw_value!r}") from exc

    cfg = Config(
        sonar_url=sonar_url,
        sonar_token=sonar_token,
        project_key=project_key,
        output_dir=os.environ.get("OUTPUT_DIR", "output").strip() or "output",
        page_size=optional_int("PAGE_SIZE", 500),
        request_timeout=optional_int("REQUEST_TIMEOUT", 30),
        max_retries=optional_int("MAX_RETRIES", 3),
        company_name=os.environ.get("COMPANY_NAME", "SonarQube Report Generator").strip() or "SonarQube Report Generator",
        report_title=os.environ.get("REPORT_TITLE") or None,
    )

    logger.info("Configuration loaded – project: %s, url: %s", cfg.project_key, cfg.sonar_url)
    return cfg
