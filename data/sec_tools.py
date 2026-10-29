from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests

from agents import _logger


SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/{cik}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/{cik}.json"
DEFAULT_SEC_USER_AGENT = (
    "EverCore_AgenticWorkflow_IB/0.1 "
    "contact: valuation-platform@example.com"
)


class SecClientError(RuntimeError):
    pass


class SecRateLimiter:
    """Small process-local limiter aligned to the SEC fair-access ceiling."""

    def __init__(self, requests_per_second: float = 8.0) -> None:
        self._interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                time.sleep(self._next_allowed - now)
            self._next_allowed = time.monotonic() + self._interval


_RATE_LIMITER = SecRateLimiter()


def sec_headers() -> dict[str, str]:
    return {
        "User-Agent": os.getenv("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }


def format_cik(cik: int | str) -> str:
    return f"CIK{int(cik):010d}"


def _sec_get_json(url: str) -> dict[str, Any]:
    _RATE_LIMITER.wait()
    _logger.info("Fetching SEC JSON from %s", url)
    try:
        response = requests.get(url, headers=sec_headers(), timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise SecClientError(f"SEC request failed for {url}: {exc}") from exc
    except ValueError as exc:
        raise SecClientError(f"SEC response was not valid JSON for {url}: {exc}") from exc


def lookup_company(query: str) -> dict[str, Any]:
    """Resolve a ticker or company name to SEC company metadata."""
    data = _sec_get_json(SEC_COMPANY_TICKERS_URL)
    _logger.debug(f"lookup_company: query: {query};")
    q = query.strip().upper()
    matches: list[dict[str, Any]] = []
    for item in data.values():
        ticker = item.get("ticker", "").upper()
        title = item.get("title", "").upper()
        if q == ticker or q in title:
            _logger.debug(f"Entity/Item: {item}")
            cik = int(item["cik_str"])
            matches.append(
                {
                    "ticker": item["ticker"],
                    "title": item["title"],
                    "cik": cik,
                    "cik_padded": format_cik(cik),
                    "data_source": "sec",
                }
            )

    if not matches:
        return {
            "status": "not_found",
            "query": query,
            "message": "No SEC company match found.",
            "matches": [],
        }

    return {
        "status": "success",
        "query": query,
        "best_match": matches[0],
        "matches": matches[:10],
    }


def fetch_company_facts(cik: int | str) -> dict[str, Any]:
    """Fetch SEC XBRL company facts."""
    cik_padded = format_cik(cik)
    co_facts = _sec_get_json(SEC_COMPANY_FACTS_URL.format(cik=cik_padded))
    _logger.debug(
        "Fetched company facts for %s with namespaces %s",
        cik_padded,
        list(co_facts.get("facts", {}).keys()),
    )
    return co_facts


def fetch_company_submissions(cik: int | str) -> dict[str, Any]:
    """Fetch SEC submissions metadata for a company."""
    cik_padded = format_cik(cik)
    return _sec_get_json(SEC_SUBMISSIONS_URL.format(cik=cik_padded))
