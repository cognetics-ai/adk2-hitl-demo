from __future__ import annotations

from datetime import date

from valuation.schemas import DCFUserAssumptions
from valuation.schemas import DistributionSpec
from valuation.schemas import FinancialSnapshot
from valuation.schemas import ResolvedCompany
from valuation.schemas import SourceReference


SAMPLE_COMPANY = {
    "query": "CMG",
    "title": "Chipotle Mexican Grill, Inc.",
    "ticker": "CMG",
    "cik": 1058090,
    "cik_padded": "CIK0001058090",
    "data_source": "sample",
    "matches": [
        {
            "ticker": "CMG",
            "title": "Chipotle Mexican Grill, Inc.",
            "cik": 1058090,
            "cik_padded": "CIK0001058090",
        }
    ],
}


def lookup_sample_company(query: str) -> ResolvedCompany:
    q = query.strip().upper()
    if q not in {"CMG", "CHIPOTLE", "CHIPOTLE MEXICAN GRILL"}:
        return ResolvedCompany(
            query=query,
            title="Chipotle Mexican Grill, Inc.",
            ticker="CMG",
            cik=1058090,
            cik_padded="CIK0001058090",
            data_source="sample",
            matches=SAMPLE_COMPANY["matches"],
        )
    return ResolvedCompany.model_validate({**SAMPLE_COMPANY, "query": query})


def build_sample_financial_snapshot(company: ResolvedCompany | None = None) -> FinancialSnapshot:
    company = company or lookup_sample_company("CMG")
    return FinancialSnapshot(
        company_name=company.title,
        ticker=company.ticker,
        cik=company.cik,
        cik_padded=company.cik_padded,
        data_source="sample",
        fiscal_year=2023,
        filing_date=date(2023, 8, 1),
        revenue_base=9.284,
        operating_income=1.3926,
        gross_profit=3.759,
        cost_of_revenue=5.525,
        total_costs_and_expenses=7.8914,
        operating_expenses=2.3664,
        selling_general_and_admin_expense=0.832,
        depreciation_amortization=0.300,
        other_operating_expenses=1.2344,
        income_tax_expense=0.3342,
        current_operating_margin=0.15,
        current_effective_tax_rate=0.24,
        cash_and_non_operating_asset=1.722,
        debt_value_book=3.887,
        current_invested_capital=6.062,
        current_market_equity_value=51.016,
        shares_outstanding=0.0275898,
        notes=[
            "Sample figures mirror the Chipotle worked example in the source notebook.",
            "All monetary values are expressed in USD billions for DCF consistency.",
        ],
        sources=[
            SourceReference(
                metric="revenue_base",
                value=9.284,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Notebook Chipotle point-estimate input.",
            ),
            SourceReference(
                metric="current_operating_margin",
                value=0.15,
                unit="decimal",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Notebook Chipotle point-estimate input.",
            ),
            SourceReference(
                metric="gross_profit",
                value=3.759,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Operating-flow Sankey sample input.",
            ),
            SourceReference(
                metric="cost_of_revenue",
                value=5.525,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="derived",
                fiscal_year=2023,
                notes="Revenue minus gross profit for operating-flow Sankey.",
            ),
            SourceReference(
                metric="operating_expenses",
                value=2.3664,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="derived",
                fiscal_year=2023,
                notes="Gross profit minus operating income for operating-flow Sankey.",
            ),
            SourceReference(
                metric="selling_general_and_admin_expense",
                value=0.832,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Operating-flow Sankey sample input.",
            ),
            SourceReference(
                metric="depreciation_amortization",
                value=0.300,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Operating-flow Sankey sample input.",
            ),
            SourceReference(
                metric="income_tax_expense",
                value=0.3342,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="derived",
                fiscal_year=2023,
                notes="Operating income multiplied by current effective tax rate.",
            ),
            SourceReference(
                metric="current_effective_tax_rate",
                value=0.24,
                unit="decimal",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Notebook Chipotle point-estimate input.",
            ),
            SourceReference(
                metric="cash_and_non_operating_asset",
                value=1.722,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Notebook Chipotle point-estimate input.",
            ),
            SourceReference(
                metric="debt_value_book",
                value=3.887,
                unit="USD billions",
                source="DCF notebook sample",
                confidence="high",
                fiscal_year=2023,
                notes="Notebook Chipotle point-estimate input.",
            ),
        ],
    )


def default_dcf_assumptions(
    snapshot: FinancialSnapshot | None = None,
    *,
    scenario_name: str = "Base Case",
) -> DCFUserAssumptions:
    snapshot = snapshot or build_sample_financial_snapshot()
    return DCFUserAssumptions(
        scenario_name=scenario_name,
        valuation_date=date(2026, 5, 11),
        risk_free_rate=0.04,
        ERP=0.048,
        equity_value=snapshot.current_market_equity_value or 51.016,
        unlevered_beta=0.90,
        terminal_unlevered_beta=0.90,
        current_pretax_cost_of_debt=0.06,
        terminal_pretax_cost_of_debt=0.055,
        marginal_tax_rate=0.25,
        revenue_growth_rate_cycle1_begin=0.11,
        revenue_growth_rate_cycle1_end=0.16,
        length_of_cycle1=6,
        revenue_growth_rate_cycle2_begin=0.14,
        revenue_growth_rate_cycle2_end=0.09,
        length_of_cycle2=6,
        revenue_growth_rate_cycle3_begin=0.08,
        revenue_growth_rate_cycle3_end=0.04,
        length_of_cycle3=6,
        current_sales_to_capital_ratio=1.7,
        terminal_sales_to_capital_ratio=1.3,
        terminal_operating_margin=0.175,
        additional_return_on_cost_of_capital_in_perpetuity=0.02,
        current_invested_capital_override=snapshot.current_invested_capital,
        asset_liquidation_during_negative_growth=0.0,
    )


def default_monte_carlo_distributions(
    assumptions: DCFUserAssumptions | None = None,
) -> list[DistributionSpec]:
    assumptions = assumptions or default_dcf_assumptions()
    return [
        DistributionSpec(
            variable="risk_free_rate",
            distribution="normal",
            mean=assumptions.risk_free_rate,
            stdev=0.002,
            min_value=0.0,
            max_value=0.10,
        ),
        DistributionSpec(
            variable="ERP",
            distribution="normal",
            mean=assumptions.ERP,
            stdev=0.001,
            min_value=0.0,
            max_value=0.15,
        ),
        DistributionSpec(
            variable="revenue_growth_rate_cycle1_begin",
            distribution="triangular",
            low=0.09,
            mode=assumptions.revenue_growth_rate_cycle1_begin,
            high=0.15,
        ),
        DistributionSpec(
            variable="revenue_growth_rate_cycle1_end",
            distribution="triangular",
            low=0.12,
            mode=assumptions.revenue_growth_rate_cycle1_end,
            high=0.19,
        ),
        DistributionSpec(
            variable="revenue_growth_rate_cycle2_end",
            distribution="triangular",
            low=0.06,
            mode=assumptions.revenue_growth_rate_cycle2_end,
            high=0.12,
        ),
        DistributionSpec(
            variable="revenue_growth_rate_cycle3_end",
            distribution="triangular",
            low=0.025,
            mode=assumptions.revenue_growth_rate_cycle3_end,
            high=0.04,
            max_value=assumptions.risk_free_rate,
        ),
        DistributionSpec(
            variable="terminal_operating_margin",
            distribution="triangular",
            low=0.12,
            mode=assumptions.terminal_operating_margin,
            high=0.22,
        ),
        DistributionSpec(
            variable="current_sales_to_capital_ratio",
            distribution="triangular",
            low=1.5,
            mode=assumptions.current_sales_to_capital_ratio,
            high=1.9,
        ),
        DistributionSpec(
            variable="terminal_sales_to_capital_ratio",
            distribution="triangular",
            low=1.1,
            mode=assumptions.terminal_sales_to_capital_ratio,
            high=1.6,
        ),
        DistributionSpec(
            variable="additional_return_on_cost_of_capital_in_perpetuity",
            distribution="triangular",
            low=0.0,
            mode=assumptions.additional_return_on_cost_of_capital_in_perpetuity,
            high=0.035,
        ),
    ]
