from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import AliasChoices
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator


DataSource = Literal["sample", "sec"]
SourceConfidence = Literal["high", "medium", "low", "derived"]
DistributionType = Literal["fixed", "normal", "triangular", "uniform"]


class SourceReference(BaseModel):
    metric: str
    value: float | None = None
    unit: str | None = None
    source: str
    confidence: SourceConfidence = "high"
    form: str | None = None
    fiscal_year: int | None = None
    filing_date: date | None = None
    accession_number: str | None = None
    xbrl_tag: str | None = None
    notes: str | None = None


class ResolvedCompany(BaseModel):
    query: str
    title: str
    ticker: str | None = None
    cik: int | None = None
    cik_padded: str | None = None
    data_source: DataSource
    matches: list[dict[str, Any]] = Field(default_factory=list)


class FinancialSnapshot(BaseModel):
    status: Literal["success", "partial"] = "success"
    company_name: str
    ticker: str | None = None
    cik: int | None = None
    cik_padded: str | None = None
    data_source: DataSource
    fiscal_year: int | None = None
    filing_date: date | None = None
    revenue_base: float | None = Field(
        default=None,
        description="Revenue base in billions of USD.",
    )
    operating_income: float | None = Field(
        default=None,
        description="Operating income in billions of USD.",
    )
    gross_profit: float | None = Field(
        default=None,
        description="Gross profit in billions of USD.",
    )
    cost_of_revenue: float | None = Field(
        default=None,
        description="Cost of revenue or cost of sales in billions of USD.",
    )
    total_costs_and_expenses: float | None = Field(
        default=None,
        description="Total costs and operating expenses in billions of USD.",
    )
    operating_expenses: float | None = Field(
        default=None,
        description="Operating expenses below gross profit in billions of USD.",
    )
    selling_general_and_admin_expense: float | None = Field(
        default=None,
        description="Selling, general, and administrative expense in billions of USD.",
    )
    depreciation_amortization: float | None = Field(
        default=None,
        description="Depreciation and amortization expense in billions of USD.",
    )
    other_operating_expenses: float | None = Field(
        default=None,
        description="Residual operating expenses in billions of USD.",
    )
    income_tax_expense: float | None = Field(
        default=None,
        description="Income tax expense in billions of USD.",
    )
    current_operating_margin: float | None = None
    current_effective_tax_rate: float | None = None
    cash_and_non_operating_asset: float | None = Field(
        default=None,
        description="Cash and non-operating assets in billions of USD.",
    )
    debt_value_book: float | None = Field(
        default=None,
        description="Book debt in billions of USD.",
    )
    current_invested_capital: float | None = Field(
        default=None,
        description="Current invested capital in billions of USD.",
    )
    current_market_equity_value: float | None = Field(
        default=None,
        description="Current market equity value in billions of USD.",
    )
    shares_outstanding: float | None = Field(
        default=None,
        description="Shares outstanding in billions.",
    )
    sources: list[SourceReference] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DCFUserAssumptions(BaseModel):
    """Banker-owned forward-looking and market assumptions for the DCF."""

    model_config = ConfigDict(extra="forbid")

    scenario_name: str = Field(min_length=2, max_length=80)
    valuation_date: date
    risk_free_rate: float = Field(ge=-0.02, le=0.20)
    ERP: float = Field(ge=0.0, le=0.25, description="Equity risk premium.")
    equity_value: float = Field(gt=0, description="Current equity value in billions.")
    unlevered_beta: float = Field(gt=0, le=5)
    terminal_unlevered_beta: float = Field(gt=0, le=5)
    current_pretax_cost_of_debt: float = Field(ge=0.0, le=0.30)
    terminal_pretax_cost_of_debt: float = Field(ge=0.0, le=0.30)
    marginal_tax_rate: float = Field(ge=0.0, le=0.60)
    revenue_growth_rate_cycle1_begin: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle1_end: float = Field(ge=-0.90, le=1.00)
    length_of_cycle1: int = Field(
        ge=1,
        le=30,
        validation_alias=AliasChoices("length_of_cycle1", "length_of_cylcle1"),
    )
    revenue_convergence_periods_cycle1: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description=(
            "Optional banker-owned year in cycle 1 when revenue growth begins "
            "converging; defaults to length_of_cycle1."
        ),
    )
    revenue_growth_rate_cycle2_begin: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle2_end: float = Field(ge=-0.90, le=1.00)
    length_of_cycle2: int = Field(
        ge=1,
        le=30,
        validation_alias=AliasChoices("length_of_cycle2", "length_of_cylcle2"),
    )
    revenue_convergence_periods_cycle2: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description=(
            "Optional banker-owned year in cycle 2 when revenue growth begins "
            "converging; defaults to length_of_cycle2."
        ),
    )
    revenue_growth_rate_cycle3_begin: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle3_end: float = Field(ge=-0.10, le=0.12)
    length_of_cycle3: int = Field(
        ge=1,
        le=30,
        validation_alias=AliasChoices("length_of_cycle3", "length_of_cylcle3"),
    )
    revenue_convergence_periods_cycle3: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description=(
            "Optional banker-owned year in cycle 3 when revenue growth begins "
            "converging; defaults to length_of_cycle3."
        ),
    )
    current_sales_to_capital_ratio: float = Field(gt=0, le=20)
    terminal_sales_to_capital_ratio: float = Field(gt=0, le=20)
    terminal_operating_margin: float = Field(ge=-0.50, le=0.80)
    additional_return_on_cost_of_capital_in_perpetuity: float = Field(
        default=0.0,
        ge=-0.10,
        le=0.30,
    )
    debt_value_override: float | None = Field(
        default=None,
        ge=0,
        description="Optional override for debt value in billions.",
    )
    cash_and_non_operating_asset_override: float | None = Field(default=None, ge=0)
    current_operating_margin_override: float | None = Field(
        default=None,
        ge=-0.50,
        le=0.80,
    )
    current_effective_tax_rate_override: float | None = Field(
        default=None,
        ge=0.0,
        le=0.60,
    )
    current_invested_capital_override: float | None = Field(default=None, gt=0)
    asset_liquidation_during_negative_growth: float = Field(default=0.0, ge=0.0, le=1.0)
    provided_by: str | None = None
    provided_by_name: str | None = None
    approved_by: str | None = None
    approval_comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_terminal_policy_and_default_convergence(self) -> "DCFUserAssumptions":
        if self.revenue_growth_rate_cycle3_end > self.risk_free_rate:
            raise ValueError(
                "Terminal growth must not exceed the risk-free rate without "
                "a separate policy override."
            )
        for cycle in (1, 2, 3):
            convergence_field = f"revenue_convergence_periods_cycle{cycle}"
            length = getattr(self, f"length_of_cycle{cycle}")
            convergence = getattr(self, convergence_field)
            if convergence is None:
                setattr(self, convergence_field, length)
                continue
            if convergence > length:
                raise ValueError(
                    f"{convergence_field} cannot exceed length_of_cycle{cycle}."
                )
        return self


class DCFValuationParams(BaseModel):
    """Notebook-compatible parameters for the deterministic DCF engine."""

    model_config = ConfigDict(extra="forbid")

    risk_free_rate: float = Field(ge=-0.02, le=0.20)
    ERP: float = Field(ge=0.0, le=0.25)
    equity_value: float = Field(gt=0)
    debt_value: float = Field(ge=0)
    unlevered_beta: float = Field(gt=0, le=5)
    terminal_unlevered_beta: float = Field(gt=0, le=5)
    year_beta_begins_to_converge_to_terminal_beta: int = Field(ge=1)
    current_pretax_cost_of_debt: float = Field(ge=0.0, le=0.30)
    terminal_pretax_cost_of_debt: float = Field(ge=0.0, le=0.30)
    year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt: int = Field(ge=1)
    current_effective_tax_rate: float = Field(ge=0.0, le=0.60)
    marginal_tax_rate: float = Field(ge=0.0, le=0.60)
    year_effective_tax_rate_begin_to_converge_marginal_tax_rate: int = Field(ge=1)
    revenue_base: float = Field(gt=0)
    revenue_growth_rate_cycle1_begin: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle1_end: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle2_begin: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle2_end: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle3_begin: float = Field(ge=-0.90, le=1.00)
    revenue_growth_rate_cycle3_end: float = Field(ge=-0.10, le=0.12)
    revenue_convergence_periods_cycle1: int = Field(ge=1)
    revenue_convergence_periods_cycle2: int = Field(ge=1)
    revenue_convergence_periods_cycle3: int = Field(ge=1)
    length_of_cycle1: int = Field(
        ge=1,
        validation_alias=AliasChoices("length_of_cycle1", "length_of_cylcle1"),
    )
    length_of_cycle2: int = Field(
        ge=1,
        validation_alias=AliasChoices("length_of_cycle2", "length_of_cylcle2"),
    )
    length_of_cycle3: int = Field(
        ge=1,
        validation_alias=AliasChoices("length_of_cycle3", "length_of_cylcle3"),
    )
    current_sales_to_capital_ratio: float = Field(gt=0)
    terminal_sales_to_capital_ratio: float = Field(gt=0)
    year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital: int = Field(
        ge=1,
    )
    current_operating_margin: float = Field(ge=-0.50, le=0.80)
    terminal_operating_margin: float = Field(ge=-0.50, le=0.80)
    year_operating_margin_begins_to_converge_to_terminal_operating_margin: int = Field(
        ge=1,
    )
    additional_return_on_cost_of_capital_in_perpetuity: float = Field(
        default=0.0,
        ge=-0.10,
        le=0.30,
    )
    cash_and_non_operating_asset: float = Field(default=0.0, ge=0)
    asset_liquidation_during_negative_growth: float = Field(default=0.0, ge=0, le=1)
    current_invested_capital: float | Literal["implicit"] = "implicit"

    @field_validator("current_invested_capital")
    @classmethod
    def validate_current_invested_capital(
        cls,
        value: float | Literal["implicit"],
    ) -> float | Literal["implicit"]:
        if value == "implicit":
            return value
        if value <= 0:
            raise ValueError("current_invested_capital must be positive or 'implicit'.")
        return value

    @model_validator(mode="after")
    def validate_terminal_spread_and_convergence(self) -> "DCFValuationParams":
        if self.revenue_growth_rate_cycle3_end > self.risk_free_rate:
            raise ValueError("Terminal growth cannot exceed the risk-free rate.")
        for cycle in (1, 2, 3):
            convergence = getattr(self, f"revenue_convergence_periods_cycle{cycle}")
            length = getattr(self, f"length_of_cycle{cycle}")
            if convergence > length:
                raise ValueError(
                    f"revenue_convergence_periods_cycle{cycle} cannot exceed "
                    f"length_of_cycle{cycle}."
                )
        return self


class DistributionSpec(BaseModel):
    variable: str
    distribution: DistributionType
    value: float | None = None
    mean: float | None = None
    stdev: float | None = Field(default=None, ge=0)
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    approved_by: str | None = None
    approval_comment: str | None = None

    @model_validator(mode="after")
    def validate_distribution_fields(self) -> "DistributionSpec":
        if self.distribution == "fixed" and self.value is None:
            raise ValueError("fixed distributions require value.")
        if self.distribution == "normal" and self.stdev is None:
            raise ValueError("normal distributions require stdev.")
        if self.distribution == "triangular":
            if self.low is None or self.mode is None or self.high is None:
                raise ValueError("triangular distributions require low, mode, and high.")
            if not self.low <= self.mode <= self.high:
                raise ValueError("triangular distribution must satisfy low <= mode <= high.")
        if self.distribution == "uniform":
            if self.low is None or self.high is None:
                raise ValueError("uniform distributions require low and high.")
            if self.low > self.high:
                raise ValueError("uniform distribution must satisfy low <= high.")
        return self


class MonteCarloRunRecord(BaseModel):
    run_id: str
    requested_by: str
    requested_by_name: str | None = None
    sample_size: int
    seed: int
    distributions: list[DistributionSpec]
    result: dict[str, Any]
    created_at: datetime
