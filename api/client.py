"""
Low-level HTTP client for SonarQube REST API.

Wraps *requests* with:
  • Token-based authentication
  • Exponential-backoff retry (urllib3 Retry)
  • Consistent error handling and logging
  • Pagination helper

All higher-level API calls live in ``sonar_api.py``; this module only knows
about HTTP mechanics.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SonarHTTPError(Exception):
    """Raised when the SonarQube API returns a non-2xx status."""

    def __init__(self, status_code: int, url: str, body: str) -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status_code} from {url}: {body[:200]}")


class APIClient:
    """
    Thread-safe HTTP client with retry and auth baked in.

    Parameters
    ----------
    base_url:
        Root URL of the SonarQube instance (no trailing slash).
    token:
        SonarQube user/project token used as HTTP Basic Auth username.
    timeout:
        Per-request timeout in seconds.
    max_retries:
        Total retry attempts on connection errors or 5xx responses.
    """

    _RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
    _RETRY_METHODS = ("GET", "HEAD", "OPTIONS")

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = self._build_session(token, max_retries)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Perform a GET request and return the parsed JSON body.

        Parameters
        ----------
        path:
            API path, e.g. ``/api/issues/search``.
        params:
            Query-string parameters.

        Returns
        -------
        dict
            Parsed JSON response.

        Raises
        ------
        SonarHTTPError
            On non-2xx HTTP status codes.
        """
        url = f"{self.base_url}{path}"
        logger.debug("GET %s params=%s", url, params)

        resp = self._session.get(url, params=params, timeout=self.timeout)

        if not resp.ok:
            raise SonarHTTPError(resp.status_code, url, resp.text)

        data: dict[str, Any] = resp.json()
        logger.debug("GET %s → %d bytes", url, len(resp.content))
        return data

    def get_paginated(
        self,
        path: str,
        result_key: str,
        params: Optional[dict[str, Any]] = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Collect all pages of a paginated SonarQube endpoint.

        SonarQube uses ``p`` (page index, 1-based) and ``ps`` (page size).
        Pagination stops when the collected items equal the reported total or
        the last page returns fewer items than requested.

        Parameters
        ----------
        path:
            API path.
        result_key:
            JSON key that holds the list of items (e.g. ``"issues"``).
        params:
            Additional query parameters (do not include ``p`` or ``ps``).
        page_size:
            Number of items per page (max 500 for most endpoints).

        Returns
        -------
        list
            All collected items across all pages.
        """
        params = dict(params or {})
        params["ps"] = page_size
        params["p"] = 1

        all_items: list[dict[str, Any]] = []

        while True:
            data = self.get(path, params)
            items: list[dict[str, Any]] = data.get(result_key, [])
            all_items.extend(items)

            # Determine total from paging info
            paging = data.get("paging", {})
            total = paging.get("total", data.get("total", len(all_items)))
            page_index = paging.get("pageIndex", params["p"])
            page_size_returned = paging.get("pageSize", page_size)

            logger.debug(
                "Page %d/%d – collected %d/%d items",
                page_index,
                -(-total // page_size),
                len(all_items),
                total,
            )

            # Stop when we have everything
            if len(all_items) >= total or len(items) < page_size_returned:
                break

            params["p"] = page_index + 1
            # Be a polite client – small back-off between pages
            time.sleep(0.05)

        logger.info("Fetched %d items from %s", len(all_items), path)
        return all_items

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _build_session(cls, token: str, max_retries: int) -> requests.Session:
        """Create a *requests* session with retry adapter and auth."""
        session = requests.Session()
        session.auth = (token, "")
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

        retry = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=cls._RETRY_STATUS_CODES,
            allowed_methods=cls._RETRY_METHODS,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session
