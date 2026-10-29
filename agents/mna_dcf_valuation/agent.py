from __future__ import annotations

from datetime import date
from typing import Literal

from google.adk import Event
from google.adk import Workflow
from google.adk.agents.context import Context
from google.adk.events import RequestInput
from pydantic import BaseModel
from pydantic import Field

from agents import _logger
from data.sample_data import build_sample_financial_snapshot
from data.sample_data import default_dcf_assumptions
from data.sample_data import lookup_sample_company
from data.sec_normalizer import build_financial_snapshot
from data.sec_tools import fetch_company_facts
from data.sec_tools import fetch_company_submissions
from data.sec_tools import lookup_company
from valuation.dcf_tool import run_dcf_valuation
from valuation.sensitivity import run_dcf_sensitivity
from valuation.schemas import DCFUserAssumptions
from valuation.schemas import DCFValuationParams
from valuation.schemas import FinancialSnapshot
from valuation.schemas import ResolvedCompany


class Banker(BaseModel):
    id: str
    name: str
    title: str
    role: Literal["analyst", "vp", "md"]


BANKERS: dict[str, Banker] = {
    "sarah.lee": Banker(
        id="sarah.lee",
        name="Sarah Lee",
        title="Investment Banking Associate",
        role="analyst",
    ),
    "marcus.kim": Banker(
        id="marcus.kim",
        name="Marcus Kim",
        title="Managing Director",
        role="md",
    ),
}


class DCFWorkflowInput(BaseModel):
    request_id: str = Field(description="Workflow request id assigned by the app.")
    actor_id: str
    company: str = Field(min_length=1)
    scenario_name: str = Field(min_length=2, max_length=80)
    valuation_date: date
    data_source: Literal["sample", "sec"] = "sample"


def _state_set(ctx: Context, key: str, value: BaseModel | dict | list | str | int | float) -> None:
    ctx.state[key] = value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def _resolve_company_from_sec(query: str) -> ResolvedCompany:
    result = lookup_company(query)
    _logger.debug("Resolving company %s via %s", query, result)
    if result.get("status") != "success":
        raise ValueError(result.get("message") or "No SEC company match found.")
    best = result["best_match"]
    return ResolvedCompany(
        query=query,
        title=best["title"],
        ticker=best["ticker"],
        cik=best["cik"],
        cik_padded=best["cik_padded"],
        data_source="sec",
        matches=result.get("matches", []),
    )


def resolve_company_node(ctx: Context, node_input: DCFWorkflowInput) -> Event:
    _logger.info("Resolving company %s via %s", node_input.company, node_input.data_source)
    company = (
        lookup_sample_company(node_input.company)
        if node_input.data_source == "sample"
        else _resolve_company_from_sec(node_input.company)
    )
    _state_set(ctx, "workflow_request", node_input)
    _state_set(ctx, "company", company)
    return Event(
        message=f"Resolved {company.title} ({company.ticker or 'private'}).",
        output=company.model_dump(mode="json"),
    )


def fetch_company_facts_node(ctx: Context, company: ResolvedCompany) -> Event:
    if company.data_source == "sample":
        output = {"company": company.model_dump(mode="json"), "company_facts": None}
        return Event(
            message="Using notebook-backed Chipotle sample financial facts.",
            output=output,
        )

    if company.cik is None:
        raise ValueError("SEC CIK is required to fetch company facts.")
    facts = fetch_company_facts(company.cik)
    submissions = fetch_company_submissions(company.cik)
    output = {
        "company": company.model_dump(mode="json"),
        "company_facts": facts,
        "company_submissions": submissions,
    }
    return Event(
        message=f"Fetched SEC XBRL company facts for {company.title}.",
        output=output,
    )


def normalize_financials_node(ctx: Context, node_input: dict) -> Event:
    company = ResolvedCompany.model_validate(node_input["company"])
    if company.data_source == "sample":
        snapshot = build_sample_financial_snapshot(company)
    else:
        snapshot = build_financial_snapshot(
            company,
            node_input["company_facts"],
            node_input.get("company_submissions"),
        )

    _state_set(ctx, "financial_snapshot", snapshot)
    _state_set(ctx, "snapshot", snapshot)
    return Event(
        message=(
            f"Normalized historical DCF starting point for {snapshot.company_name}."
        ),
        output=snapshot.model_dump(mode="json"),
    )


def request_dcf_assumptions(ctx: Context, snapshot: FinancialSnapshot):
    suggested = (
        default_dcf_assumptions(snapshot).model_dump(mode="json")
        if snapshot.data_source == "sample"
        else None
    )
    message = (
        "I found the historical starting point. Please provide banker-owned "
        "forward-looking assumptions before the DCF can run. Revenue "
        "convergence periods are optional and default to the matching cycle "
        "length when omitted."
    )
    workflow_request = ctx.state.get("workflow_request") or {}
    request_id = workflow_request.get("request_id", snapshot.ticker or snapshot.company_name)
    yield RequestInput(
        interrupt_id=f"dcf_assumptions:{request_id}",
        message=message,
        payload={
            "snapshot": snapshot.model_dump(mode="json"),
            "suggested_assumptions": suggested,
            "required_controls": [
                "Do not invent forward-looking assumptions.",
                "Percentages must be expressed as decimals.",
                "Terminal growth must not exceed the risk-free rate.",
                "Revenue convergence periods may be supplied per phase or omitted.",
                "Assumption ownership and scenario name are captured.",
            ],
        },
        response_schema=DCFUserAssumptions,
    )


def _required_snapshot_value(snapshot: FinancialSnapshot, field_name: str) -> float:
    value = getattr(snapshot, field_name)
    if value is None:
        raise ValueError(
            f"{field_name} is missing from historical facts and must be supplied "
            "as an override before valuation can run."
        )
    return float(value)


def merge_inputs_node(
    ctx: Context,
    snapshot: FinancialSnapshot,
    node_input: DCFUserAssumptions,
) -> Event:
    _logger.info(
        "Merging DCF assumptions for %s scenario %s",
        snapshot.company_name,
        node_input.scenario_name,
    )
    params = DCFValuationParams(
        risk_free_rate=node_input.risk_free_rate,
        ERP=node_input.ERP,
        equity_value=node_input.equity_value,
        debt_value=(
            node_input.debt_value_override
            if node_input.debt_value_override is not None
            else _required_snapshot_value(snapshot, "debt_value_book")
        ),
        unlevered_beta=node_input.unlevered_beta,
        terminal_unlevered_beta=node_input.terminal_unlevered_beta,
        year_beta_begins_to_converge_to_terminal_beta=1,
        current_pretax_cost_of_debt=node_input.current_pretax_cost_of_debt,
        terminal_pretax_cost_of_debt=node_input.terminal_pretax_cost_of_debt,
        year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt=3,
        current_effective_tax_rate=(
            node_input.current_effective_tax_rate_override
            if node_input.current_effective_tax_rate_override is not None
            else _required_snapshot_value(snapshot, "current_effective_tax_rate")
        ),
        marginal_tax_rate=node_input.marginal_tax_rate,
        year_effective_tax_rate_begin_to_converge_marginal_tax_rate=1,
        revenue_base=_required_snapshot_value(snapshot, "revenue_base"),
        revenue_growth_rate_cycle1_begin=node_input.revenue_growth_rate_cycle1_begin,
        revenue_growth_rate_cycle1_end=node_input.revenue_growth_rate_cycle1_end,
        revenue_growth_rate_cycle2_begin=node_input.revenue_growth_rate_cycle2_begin,
        revenue_growth_rate_cycle2_end=node_input.revenue_growth_rate_cycle2_end,
        revenue_growth_rate_cycle3_begin=node_input.revenue_growth_rate_cycle3_begin,
        revenue_growth_rate_cycle3_end=node_input.revenue_growth_rate_cycle3_end,
        revenue_convergence_periods_cycle1=(
            node_input.revenue_convergence_periods_cycle1
            or node_input.length_of_cycle1
        ),
        revenue_convergence_periods_cycle2=(
            node_input.revenue_convergence_periods_cycle2
            or node_input.length_of_cycle2
        ),
        revenue_convergence_periods_cycle3=(
            node_input.revenue_convergence_periods_cycle3
            or node_input.length_of_cycle3
        ),
        length_of_cycle1=node_input.length_of_cycle1,
        length_of_cycle2=node_input.length_of_cycle2,
        length_of_cycle3=node_input.length_of_cycle3,
        current_sales_to_capital_ratio=node_input.current_sales_to_capital_ratio,
        terminal_sales_to_capital_ratio=node_input.terminal_sales_to_capital_ratio,
        year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital=1,
        current_operating_margin=(
            node_input.current_operating_margin_override
            if node_input.current_operating_margin_override is not None
            else _required_snapshot_value(snapshot, "current_operating_margin")
        ),
        terminal_operating_margin=node_input.terminal_operating_margin,
        year_operating_margin_begins_to_converge_to_terminal_operating_margin=1,
        additional_return_on_cost_of_capital_in_perpetuity=(
            node_input.additional_return_on_cost_of_capital_in_perpetuity
        ),
        cash_and_non_operating_asset=(
            node_input.cash_and_non_operating_asset_override
            if node_input.cash_and_non_operating_asset_override is not None
            else _required_snapshot_value(snapshot, "cash_and_non_operating_asset")
        ),
        asset_liquidation_during_negative_growth=(
            node_input.asset_liquidation_during_negative_growth
        ),
        current_invested_capital=(
            node_input.current_invested_capital_override
            if node_input.current_invested_capital_override is not None
            else snapshot.current_invested_capital
            if snapshot.current_invested_capital is not None
            else "implicit"
        ),
    )
    _state_set(ctx, "assumptions", node_input)
    _state_set(ctx, "dcf_params", params)
    _state_set(
        ctx,
        "assumption_lineage",
        {
            "scenario_name": node_input.scenario_name,
            "valuation_date": node_input.valuation_date.isoformat(),
            "provided_by": node_input.provided_by,
            "provided_by_name": node_input.provided_by_name,
            "approved_by": node_input.approved_by,
            "approval_comment": node_input.approval_comment,
            "source": "human_provided",
        },
    )
    return Event(
        message="Merged historical facts with banker-approved assumptions.",
        output=params.model_dump(mode="json"),
    )


def run_dcf_valuation_node(ctx: Context, node_input: DCFValuationParams) -> Event:
    result = run_dcf_valuation(node_input)
    if result["status"] != "success":
        raise ValueError(result.get("message") or "DCF valuation failed.")
    _state_set(ctx, "valuation_result", result)
    return Event(
        message=(
            "DCF complete: intrinsic equity value "
            f"${result['intrinsic_equity_value']:.2f}bn."
        ),
        output=result,
    )


def run_sensitivity_node(ctx: Context, node_input: dict) -> Event:
    params = DCFValuationParams.model_validate(ctx.state["dcf_params"])
    valuation_result = ctx.state.get("valuation_result")
    sensitivity = run_dcf_sensitivity(params, valuation_result)
    _state_set(ctx, "sensitivity_result", sensitivity)
    top_driver = sensitivity["top_value_drivers"][0]["label"]
    return Event(
        message=f"Sensitivity complete: largest observed driver is {top_driver}.",
        output=sensitivity,
    )


def explain_result_node(ctx: Context, node_input: dict) -> Event:
    snapshot = FinancialSnapshot.model_validate(ctx.state["financial_snapshot"])
    assumptions = DCFUserAssumptions.model_validate(ctx.state["assumptions"])
    valuation_result = ctx.state["valuation_result"]
    sensitivity = ctx.state.get("sensitivity_result") or {}
    premium = valuation_result.get("implied_premium_discount")
    top_drivers = [
        driver.get("label")
        for driver in sensitivity.get("top_value_drivers", [])[:3]
        if driver.get("label")
    ]
    explanation = {
        "company": snapshot.company_name,
        "ticker": snapshot.ticker,
        "scenario_name": assumptions.scenario_name,
        "valuation_date": assumptions.valuation_date.isoformat(),
        "headline": (
            f"Intrinsic equity value is ${valuation_result['intrinsic_equity_value']:.2f}bn "
            f"versus current equity value of ${valuation_result['current_market_equity_value']:.2f}bn."
        ),
        "premium_discount": premium,
        "key_assumptions": {
            "risk_free_rate": assumptions.risk_free_rate,
            "ERP": assumptions.ERP,
            "terminal_growth": assumptions.revenue_growth_rate_cycle3_end,
            "terminal_operating_margin": assumptions.terminal_operating_margin,
            "terminal_sales_to_capital_ratio": assumptions.terminal_sales_to_capital_ratio,
        },
        "largest_value_drivers": [
            "terminal operating margin",
            "mature-phase growth",
            "sales-to-capital ratio",
            "cost of capital",
        ],
        "sensitivity_drivers": top_drivers,
        "limitations": [
            "This is a model output, not investment advice.",
            "Forward-looking assumptions were provided by the user.",
            "SEC/sample facts and human assumptions are stored separately for review.",
            "Sensitivity analysis changes one input at a time and does not replace scenario analysis.",
        ],
        "source_count": len(snapshot.sources),
    }
    _state_set(ctx, "valuation_explanation", explanation)
    return Event(
        message="Prepared banker-readable valuation explanation and limitations.",
        output=explanation,
    )


root_agent = Workflow(
    name="mna_dcf_valuation_workflow",
    edges=[
        (
            "START",
            resolve_company_node,
            fetch_company_facts_node,
            normalize_financials_node,
            request_dcf_assumptions,
            merge_inputs_node,
            run_dcf_valuation_node,
            run_sensitivity_node,
            explain_result_node,
        ),
    ],
)
