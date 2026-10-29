from __future__ import annotations

from datetime import date
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator


PeerCategory = Literal["core", "secondary", "broader_reference"]
VALID_PEER_CATEGORIES = {"core", "secondary", "broader_reference"}
PEER_CATEGORY_ALIASES: dict[str, PeerCategory] = {
    "primary": "core",
    "direct": "core",
    "direct_peer": "core",
    "direct_comparable": "core",
    "selected": "core",
    "second_tier": "secondary",
    "secondary_peer": "secondary",
    "indirect": "secondary",
    "broad": "broader_reference",
    "broader": "broader_reference",
    "broad_reference": "broader_reference",
    "reference": "broader_reference",
    "excluded": "broader_reference",
    "exclude": "broader_reference",
    "not_comparable": "broader_reference",
    "not_a_peer": "broader_reference",
    "non_comparable": "broader_reference",
    "non_peer": "broader_reference",
    "n_a": "broader_reference",
    "na": "broader_reference",
    "none": "broader_reference",
    "not_applicable": "broader_reference",
    "not_available": "broader_reference",
}


def _normalize_peer_category_value(
    value: Any,
    *,
    default: PeerCategory = "core",
) -> str:
    if value is None:
        return default
    normalized = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace(".", "")
    )
    if not normalized:
        return default
    return PEER_CATEGORY_ALIASES.get(normalized, normalized)


class PeerCandidate(BaseModel):
    company_name: str = Field(min_length=1)
    ticker: str | None = Field(
        default=None,
        description="Public ticker if known. Company name is acceptable when ticker is unknown.",
    )
    exchange: str | None = None
    country: str | None = None
    peer_category: PeerCategory = "core"
    rationale: str = Field(min_length=1)
    key_differences: str | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @field_validator("peer_category", mode="before")
    @classmethod
    def normalize_peer_category(cls, value: Any) -> PeerCategory:
        return _normalize_peer_category_value(value)  # type: ignore[return-value]


class PeerProposal(BaseModel):
    target_company: str
    target_ticker: str | None = None
    as_of_date: date = Field(default_factory=date.today)
    selection_methodology: str
    suggested_peers: list[PeerCandidate] = Field(min_length=1, max_length=12)
    excluded_peers: list[PeerCandidate] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)

    @field_validator("excluded_peers", mode="before")
    @classmethod
    def normalize_excluded_peers(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            return []
        if isinstance(value, list):
            normalized_peers = []
            for peer in value:
                if not isinstance(peer, dict):
                    normalized_peers.append(peer)
                    continue
                normalized_peer = dict(peer)
                normalized_category = _normalize_peer_category_value(
                    normalized_peer.get("peer_category"),
                    default="broader_reference",
                )
                if normalized_category not in VALID_PEER_CATEGORIES:
                    normalized_category = "broader_reference"
                normalized_peer["peer_category"] = normalized_category
                normalized_peers.append(normalized_peer)
            return normalized_peers
        return value

    @field_validator("data_limitations", mode="before")
    @classmethod
    def normalize_data_limitations(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]


class PeerReviewDecision(BaseModel):
    approved: bool = True
    selected_peers: list[PeerCandidate] = Field(min_length=1, max_length=15)
    comment: str | None = None
    decided_by: str | None = None
    decided_by_name: str | None = None

    @model_validator(mode="after")
    def require_peers_when_approved(self) -> "PeerReviewDecision":
        if self.approved and not self.selected_peers:
            raise ValueError("At least one selected peer is required when approved.")
        return self


class CompsCompanyRecord(BaseModel):
    query: str
    company_name: str
    ticker: str | None = None
    cik: int | None = None
    peer_category: PeerCategory | Literal["target"] = "core"
    status: Literal["success", "partial", "not_found", "failed"] = "success"
    fiscal_year: int | None = None
    filing_date: date | None = None
    revenue_mm: float | None = None
    gross_profit_mm: float | None = None
    operating_income_mm: float | None = None
    depreciation_amortization_mm: float | None = None
    cash_mm: float | None = None
    debt_mm: float | None = None
    shares_outstanding_mm: float | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CompsExcelArtifact(BaseModel):
    path: str
    filename: str
    mime_type: str
    generated_at: str
    source: str = "SEC XBRL companyfacts"
