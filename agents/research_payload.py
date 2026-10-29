from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agents import _logger
from data.sample_data import lookup_sample_company
from data.sec_tools import SecClientError
from data.sec_tools import lookup_company


SAMPLE_COMPANY_QUERIES = {"CMG", "CHIPOTLE", "CHIPOTLE MEXICAN GRILL"}


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _initial_ticker(company: str) -> str | None:
    normalized = company.strip().upper()
    normalized_symbol = normalized.replace(".", "").replace("-", "")
    if 1 <= len(normalized) <= 8 and normalized_symbol.isalnum():
        return normalized
    return None


def _parse_text_payload(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"company": text}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        return {"company": parsed}
    return {"company": str(parsed)}


def _parse_content_parts(parts: Any) -> dict[str, Any] | None:
    if not isinstance(parts, list):
        return None
    for part in parts:
        text = None
        if isinstance(part, dict):
            text = part.get("text")
        else:
            text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            return _parse_text_payload(text)
    return None


def _parse_payload(node_input: Any) -> dict[str, Any]:
    parts = getattr(node_input, "parts", None)
    parsed_from_parts = _parse_content_parts(parts)
    if parsed_from_parts is not None:
        return parsed_from_parts

    if isinstance(node_input, dict):
        parsed_from_parts = _parse_content_parts(node_input.get("parts"))
        if parsed_from_parts is not None:
            return parsed_from_parts
        return dict(node_input)

    if isinstance(node_input, BaseModel):
        payload = node_input.model_dump(mode="json")
        parsed_from_parts = _parse_content_parts(payload.get("parts"))
        if parsed_from_parts is not None:
            return parsed_from_parts
        return payload

    if isinstance(node_input, str):
        return _parse_text_payload(node_input)

    return {"company": str(node_input)}


def _submitted_company(payload: dict[str, Any]) -> str | None:
    return (
        _clean_string(payload.get("company"))
        or _clean_string(payload.get("ticker"))
        or _clean_string(payload.get("client_name"))
        or _clean_string(payload.get("title"))
    )


def _lookup_company_identity(query: str) -> dict[str, Any] | None:
    if query.strip().upper() in SAMPLE_COMPANY_QUERIES:
        company = lookup_sample_company(query)
        return company.model_dump(mode="json")

    try:
        result = lookup_company(query)
    except SecClientError as exc:
        _logger.warning(
            "SEC title resolution failed for %s; using submitted company. Error: %s",
            query,
            exc,
        )
        return None

    if result.get("status") != "success":
        return None
    return result["best_match"]


def build_research_payload(node_input: Any) -> dict[str, Any]:
    _logger.debug(f"Node Input: {node_input}")
    payload = _parse_payload(node_input)
    _logger.debug(f"Payload Input: {payload}")
    submitted = _submitted_company(payload)
    _logger.debug(f"Submitted Company: {submitted}")
    if not submitted:
        return payload

    payload["company"] = _clean_string(payload.get("company")) or submitted

    title = _clean_string(payload.get("title")) or _clean_string(
        payload.get("company_title")
    )
    _logger.debug(f"Title Input: {title}")
    ticker = _clean_string(payload.get("ticker"))

    if title is None:
        identity = _lookup_company_identity(submitted)
        if identity is not None:
            title = _clean_string(identity.get("title"))
            ticker = ticker or _clean_string(identity.get("ticker"))

    title = title or submitted
    ticker = ticker or _initial_ticker(submitted)

    payload["title"] = title
    payload["client_name"] = _clean_string(payload.get("client_name")) or title
    if ticker:
        payload["ticker"] = ticker
    return payload
