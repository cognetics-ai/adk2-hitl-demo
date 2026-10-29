from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from typing import Iterable

from agents import _logger
from valuation.schemas import FinancialSnapshot
from valuation.schemas import ResolvedCompany
from valuation.schemas import SourceReference


USD_BILLION = 1_000_000_000

REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]

COST_OF_REVENUE_TAGS = [
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "CostOfGoodsSold",
    "CostOfRevenueExcludingDepreciationDepletionAndAmortization",
    "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
]


@dataclass(frozen=True)
class FactValue:
    metric: str
    value: float
    raw_value: float
    unit: str
    tag: str
    form: str | None
    fiscal_year: int | None
    filing_date: date | None
    period_start: date | None
    period_end: date | None
    accession_number: str | None


@dataclass(frozen=True)
class AnnualFiling:
    accession_number: str | None
    form: str | None
    fiscal_year: int | None
    filing_date: date | None
    report_date: date | None
    primary_document: str | None = None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _latest_annual_fact(
    company_facts: dict[str, Any],
    *,
    metric: str,
    tag_candidates: Iterable[str],
    units: Iterable[str],
) -> FactValue | None:
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for tag in tag_candidates:
        concept = us_gaap.get(tag)
        if not concept:
            continue
        for unit in units:
            facts = concept.get("units", {}).get(unit, [])
            annual = [
                item
                for item in facts
                if item.get("form") in {"10-K", "20-F", "40-F"}
                and item.get("fp") == "FY"
                and item.get("val") is not None
            ]
            if not annual:
                continue
            annual = sorted(
                annual,
                key=lambda item: (
                    _parse_date(item.get("end")) or date.min,
                    item.get("fy") or 0,
                    _parse_date(item.get("filed")) or date.min,
                ),
                reverse=True,
            )
            latest = annual[0]
            raw_value = float(latest["val"])
            value = raw_value / USD_BILLION if unit == "USD" else raw_value / USD_BILLION
            return FactValue(
                metric=metric,
                value=value,
                raw_value=raw_value,
                unit="USD billions" if unit == "USD" else "shares billions",
                tag=tag,
                form=latest.get("form"),
                fiscal_year=latest.get("fy"),
                filing_date=_parse_date(latest.get("filed")),
                period_start=_parse_date(latest.get("start")),
                period_end=_parse_date(latest.get("end")),
                accession_number=latest.get("accn"),
            )
    return None


def _latest_annual_filing_from_submissions(
    company_submissions: dict[str, Any] | None,
) -> AnnualFiling | None:
    if not company_submissions:
        return None

    recent = company_submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    annual_filings: list[AnnualFiling] = []
    for index, form in enumerate(forms):
        if form not in {"10-K", "20-F", "40-F"}:
            continue
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_documents = recent.get("primaryDocument", [])
        annual_filings.append(
            AnnualFiling(
                accession_number=(
                    accession_numbers[index]
                    if index < len(accession_numbers)
                    else None
                ),
                form=form,
                fiscal_year=None,
                filing_date=_parse_date(
                    filing_dates[index] if index < len(filing_dates) else None
                ),
                report_date=_parse_date(
                    report_dates[index] if index < len(report_dates) else None
                ),
                primary_document=(
                    primary_documents[index]
                    if index < len(primary_documents)
                    else None
                ),
            )
        )

    if not annual_filings:
        return None
    return max(
        annual_filings,
        key=lambda filing: (
            filing.report_date or date.min,
            filing.filing_date or date.min,
        ),
    )


def _latest_annual_filing_from_company_facts(
    company_facts: dict[str, Any],
) -> AnnualFiling | None:
    anchor = _latest_annual_fact(
        company_facts,
        metric="revenue_base",
        tag_candidates=REVENUE_TAGS,
        units=["USD"],
    )
    if anchor is None:
        return None
    return AnnualFiling(
        accession_number=anchor.accession_number,
        form=anchor.form,
        fiscal_year=anchor.fiscal_year,
        filing_date=anchor.filing_date,
        report_date=anchor.period_end,
    )


def _fact_matches_annual_filing(
    item: dict[str, Any],
    annual_filing: AnnualFiling,
) -> bool:
    if annual_filing.accession_number and item.get("accn") != annual_filing.accession_number:
        return False
    if annual_filing.report_date and _parse_date(item.get("end")) != annual_filing.report_date:
        return False
    return True


def _latest_annual_filing_fact(
    company_facts: dict[str, Any],
    *,
    metric: str,
    tag_candidates: Iterable[str],
    units: Iterable[str],
    annual_filing: AnnualFiling | None,
) -> FactValue | None:
    if annual_filing is None:
        return _latest_annual_fact(
            company_facts,
            metric=metric,
            tag_candidates=tag_candidates,
            units=units,
        )

    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for tag in tag_candidates:
        concept = us_gaap.get(tag)
        if not concept:
            continue
        for unit in units:
            facts = concept.get("units", {}).get(unit, [])
            annual = [
                item
                for item in facts
                if item.get("form") in {"10-K", "20-F", "40-F"}
                and item.get("fp") == "FY"
                and item.get("val") is not None
                and _fact_matches_annual_filing(item, annual_filing)
            ]
            if not annual:
                continue
            annual = sorted(
                annual,
                key=lambda item: (
                    _parse_date(item.get("end")) or date.min,
                    _parse_date(item.get("start")) or date.min,
                    _parse_date(item.get("filed")) or date.min,
                ),
                reverse=True,
            )
            latest = annual[0]
            raw_value = float(latest["val"])
            value = raw_value / USD_BILLION
            return FactValue(
                metric=metric,
                value=value,
                raw_value=raw_value,
                unit="USD billions" if unit == "USD" else "shares billions",
                tag=tag,
                form=latest.get("form"),
                fiscal_year=latest.get("fy") or annual_filing.fiscal_year,
                filing_date=_parse_date(latest.get("filed")) or annual_filing.filing_date,
                period_start=_parse_date(latest.get("start")),
                period_end=_parse_date(latest.get("end")),
                accession_number=latest.get("accn") or annual_filing.accession_number,
            )
    return None


def _source_from_fact(fact: FactValue) -> SourceReference:
    period_note = (
        f"Period ended {fact.period_end.isoformat()}."
        if fact.period_end is not None
        else None
    )
    return SourceReference(
        metric=fact.metric,
        value=fact.value,
        unit=fact.unit,
        source="SEC XBRL companyfacts",
        confidence="high",
        form=fact.form,
        fiscal_year=fact.fiscal_year,
        filing_date=fact.filing_date,
        accession_number=fact.accession_number,
        xbrl_tag=fact.tag,
        notes=period_note,
    )


def _derived_source(
    *,
    metric: str,
    value: float | None,
    fiscal_year: int | None,
    filing_date: date | None,
    notes: str,
) -> SourceReference:
    return SourceReference(
        metric=metric,
        value=value,
        unit="USD billions",
        source="Derived from SEC XBRL companyfacts",
        confidence="derived",
        fiscal_year=fiscal_year,
        filing_date=filing_date,
        notes=notes,
    )


def _ratio(numerator: FactValue | None, denominator: FactValue | None) -> float | None:
    if numerator is None or denominator is None or denominator.raw_value == 0:
        return None
    return numerator.raw_value / denominator.raw_value


def _non_negative(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, value)


def build_financial_snapshot(
    company: ResolvedCompany,
    company_facts: dict[str, Any],
    company_submissions: dict[str, Any] | None = None,
) -> FinancialSnapshot:
    """Convert SEC companyfacts into a conservative DCF starting point."""
    _logger.debug(f"company: {company}")
    _logger.debug(
        "company_facts namespaces: %s",
        list(company_facts.get("facts", {}).keys()),
    )
    annual_filing = (
        _latest_annual_filing_from_submissions(company_submissions)
        or _latest_annual_filing_from_company_facts(company_facts)
    )
    _logger.debug("latest annual filing anchor: %s", annual_filing)
    revenue = _latest_annual_filing_fact(
        company_facts,
        metric="revenue_base",
        tag_candidates=REVENUE_TAGS,
        units=["USD"],
        annual_filing=annual_filing,
    )
    _logger.debug(f"revenue: {revenue}")
    operating_income = _latest_annual_filing_fact(
        company_facts,
        metric="operating_income",
        tag_candidates=["OperatingIncomeLoss"],
        units=["USD"],
        annual_filing=annual_filing,
    )
    _logger.debug(f"operating_income: {operating_income}")
    gross_profit = _latest_annual_filing_fact(
        company_facts,
        metric="gross_profit",
        tag_candidates=["GrossProfit"],
        units=["USD"],
        annual_filing=annual_filing,
    )
    cost_of_revenue = _latest_annual_filing_fact(
        company_facts,
        metric="cost_of_revenue",
        tag_candidates=COST_OF_REVENUE_TAGS,
        units=["USD"],
        annual_filing=annual_filing,
    )
    total_costs_and_expenses = _latest_annual_filing_fact(
        company_facts,
        metric="total_costs_and_expenses",
        tag_candidates=["CostsAndExpenses"],
        units=["USD"],
        annual_filing=annual_filing,
    )
    selling_general_and_admin = _latest_annual_filing_fact(
        company_facts,
        metric="selling_general_and_admin_expense",
        tag_candidates=[
            "SellingGeneralAndAdministrativeExpense",
            "SellingAndMarketingExpense",
            "GeneralAndAdministrativeExpense",
        ],
        units=["USD"],
        annual_filing=annual_filing,
    )
    depreciation_amortization = _latest_annual_filing_fact(
        company_facts,
        metric="depreciation_amortization",
        tag_candidates=[
            "DepreciationDepletionAndAmortization",
            "DepreciationDepletionAndAmortizationExpense",
            "DepreciationAndAmortization",
            "DepreciationAndAmortizationExpense",
        ],
        units=["USD"],
        annual_filing=annual_filing,
    )

    tax_expense = _latest_annual_filing_fact(
        company_facts,
        metric="income_tax_expense",
        tag_candidates=["IncomeTaxExpenseBenefit"],
        units=["USD"],
        annual_filing=annual_filing,
    )
    _logger.debug(f"tax_expense: {tax_expense}")
    pretax_income = _latest_annual_filing_fact(
        company_facts,
        metric="pretax_income",
        tag_candidates=[
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ],
        units=["USD"],
        annual_filing=annual_filing,
    )
    _logger.debug(f"pretax_income: {pretax_income}")
    cash = _latest_annual_filing_fact(
        company_facts,
        metric="cash_and_non_operating_asset",
        tag_candidates=[
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
        units=["USD"],
        annual_filing=annual_filing,
    )
    debt = _latest_annual_filing_fact(
        company_facts,
        metric="debt_value_book",
        tag_candidates=[
            "LongTermDebtAndFinanceLeaseObligationsCurrentAndNoncurrent",
            "DebtAndFinanceLeaseObligationsCurrentAndNoncurrent",
            "LongTermDebtAndFinanceLeaseObligations",
            "DebtInstrumentCarryingAmount",
            "LongTermDebtNoncurrent",
            "LongTermDebt",
            "DebtCurrent",
        ],
        units=["USD"],
        annual_filing=annual_filing,
    )
    invested_capital = _latest_annual_filing_fact(
        company_facts,
        metric="current_invested_capital",
        tag_candidates=["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        units=["USD"],
        annual_filing=annual_filing,
    )
    shares = _latest_annual_filing_fact(
        company_facts,
        metric="shares_outstanding",
        tag_candidates=[
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingBasic",
            "CommonStocksIncludingAdditionalPaidInCapitalMember",
        ],
        units=["shares", "pure"],
        annual_filing=annual_filing,
    )

    sources = [
        _source_from_fact(fact)
        for fact in [
            revenue,
            gross_profit,
            cost_of_revenue,
            total_costs_and_expenses,
            operating_income,
            selling_general_and_admin,
            depreciation_amortization,
            tax_expense,
            pretax_income,
            cash,
            debt,
            invested_capital,
            shares,
        ]
        if fact is not None
    ]
    gross_profit_value = gross_profit.value if gross_profit else None
    cost_of_revenue_value = cost_of_revenue.value if cost_of_revenue else None
    total_costs_and_expenses_value = (
        total_costs_and_expenses.value if total_costs_and_expenses else None
    )
    revenue_value = revenue.value if revenue else None
    operating_income_value = operating_income.value if operating_income else None
    if (
        total_costs_and_expenses_value is None
        and revenue_value is not None
        and operating_income_value is not None
    ):
        total_costs_and_expenses_value = _non_negative(
            revenue_value - operating_income_value
        )
        sources.append(
            _derived_source(
                metric="total_costs_and_expenses",
                value=total_costs_and_expenses_value,
                fiscal_year=revenue.fiscal_year if revenue else None,
                filing_date=revenue.filing_date if revenue else None,
                notes="Revenue minus operating income.",
            )
        )
    if gross_profit_value is None and revenue_value is not None and cost_of_revenue_value is not None:
        gross_profit_value = _non_negative(revenue_value - cost_of_revenue_value)
        sources.append(
            _derived_source(
                metric="gross_profit",
                value=gross_profit_value,
                fiscal_year=revenue.fiscal_year if revenue else None,
                filing_date=revenue.filing_date if revenue else None,
                notes="Revenue minus cost_of_revenue.",
            )
        )
    if cost_of_revenue_value is None and revenue_value is not None and gross_profit_value is not None:
        cost_of_revenue_value = _non_negative(revenue_value - gross_profit_value)
        sources.append(
            _derived_source(
                metric="cost_of_revenue",
                value=cost_of_revenue_value,
                fiscal_year=revenue.fiscal_year if revenue else None,
                filing_date=revenue.filing_date if revenue else None,
                notes="Revenue minus gross_profit.",
            )
        )
    operating_expenses_value = (
        _non_negative(gross_profit_value - operating_income_value)
        if gross_profit_value is not None and operating_income_value is not None
        else None
    )
    if operating_expenses_value is not None:
        sources.append(
            _derived_source(
                metric="operating_expenses",
                value=operating_expenses_value,
                fiscal_year=revenue.fiscal_year if revenue else None,
                filing_date=revenue.filing_date if revenue else None,
                notes="Gross profit minus operating income.",
            )
        )
    other_operating_expenses_value = None
    if operating_expenses_value is not None:
        classified_expenses = sum(
            value
            for value in [
                selling_general_and_admin.value if selling_general_and_admin else None,
                depreciation_amortization.value if depreciation_amortization else None,
            ]
            if value is not None
        )
        other_operating_expenses_value = _non_negative(
            operating_expenses_value - classified_expenses
        )
        sources.append(
            _derived_source(
                metric="other_operating_expenses",
                value=other_operating_expenses_value,
                fiscal_year=revenue.fiscal_year if revenue else None,
                filing_date=revenue.filing_date if revenue else None,
                notes="Operating expenses minus classified SG&A and D&A where available.",
            )
        )
    current_operating_margin = _ratio(operating_income, revenue)
    current_effective_tax_rate = (
        _ratio(tax_expense, pretax_income)
        if pretax_income is not None and pretax_income.raw_value > 0
        else None
    )
    notes = [
        "SEC companyfacts supply historical starting points only.",
        "Forward-looking DCF assumptions must be supplied and approved by a banker.",
    ]
    if annual_filing is not None:
        notes.append(
            "Historical facts are anchored to the latest annual filing"
            f" {annual_filing.form or ''}"
            f" accession {annual_filing.accession_number or 'unknown'}"
            f" for period ended {annual_filing.report_date or 'unknown'}."
        )
    else:
        notes.append("Latest annual filing metadata could not be identified.")
    if revenue is None:
        notes.append("Revenue was not found in the configured SEC XBRL tag candidates.")
    if debt is None:
        notes.append("Debt was not found in the configured SEC XBRL tag candidates.")
    if current_operating_margin is None:
        notes.append("Operating margin could not be calculated from SEC facts.")
    if gross_profit_value is None:
        notes.append(
            "Gross profit / cost of revenue detail was not found in configured SEC tags "
            "for the latest annual filing period."
        )

    _logger.info(
        "Built SEC financial snapshot for %s with %s sources",
        company.title,
        len(sources),
    )
    return FinancialSnapshot(
        status="success" if revenue and operating_income else "partial",
        company_name=company.title,
        ticker=company.ticker,
        cik=company.cik,
        cik_padded=company.cik_padded,
        data_source="sec",
        fiscal_year=revenue.fiscal_year if revenue else None,
        filing_date=revenue.filing_date if revenue else None,
        revenue_base=revenue.value if revenue else None,
        operating_income=operating_income.value if operating_income else None,
        gross_profit=gross_profit_value,
        cost_of_revenue=cost_of_revenue_value,
        total_costs_and_expenses=total_costs_and_expenses_value,
        operating_expenses=operating_expenses_value,
        selling_general_and_admin_expense=(
            selling_general_and_admin.value if selling_general_and_admin else None
        ),
        depreciation_amortization=(
            depreciation_amortization.value if depreciation_amortization else None
        ),
        other_operating_expenses=other_operating_expenses_value,
        income_tax_expense=tax_expense.value if tax_expense else None,
        current_operating_margin=current_operating_margin,
        current_effective_tax_rate=current_effective_tax_rate,
        cash_and_non_operating_asset=cash.value if cash else None,
        debt_value_book=debt.value if debt else None,
        current_invested_capital=invested_capital.value if invested_capital else None,
        current_market_equity_value=None,
        shares_outstanding=shares.value if shares else None,
        sources=sources,
        notes=notes,
    )
