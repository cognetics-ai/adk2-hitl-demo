from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _to_int(value: float | int, *, name: str) -> int:
    result = int(round(float(value)))
    if result < 1:
        raise ValueError(f"{name} must be at least 1.")
    return result


def _scalar(value: Any) -> float:
    array = np.asarray(value)
    return float(array.reshape(-1)[0])


def _append(series: pd.Series, value: float) -> pd.Series:
    return pd.concat([series.reset_index(drop=True), pd.Series([value])], ignore_index=True)


def dynamic_converger(
    current: float,
    expected: float,
    number_of_steps: int,
    period_to_begin_to_converge: int,
) -> pd.Series:
    """Project a value that stays flat, then converges linearly to a target."""
    number_of_steps = _to_int(number_of_steps, name="number_of_steps")
    period_to_begin_to_converge = _to_int(
        period_to_begin_to_converge,
        name="period_to_begin_to_converge",
    )
    period_to_begin_to_converge = min(period_to_begin_to_converge, number_of_steps)

    flat_periods = max(period_to_begin_to_converge - 1, 0)
    convergence_periods = number_of_steps - flat_periods
    phase_1 = np.array([float(current)] * flat_periods)
    phase_2 = np.linspace(float(current), float(expected), convergence_periods)
    return pd.Series(np.concatenate((phase_1, phase_2)))


def dynamic_converger_multiple_phase(
    growth_rates_for_each_cycle: list[list[float]],
    length_of_each_cycle: list[int],
    convergence_periods: list[int],
) -> pd.Series:
    results: list[pd.Series] = []
    for cycle in range(len(length_of_each_cycle)):
        results.append(
            dynamic_converger(
                current=growth_rates_for_each_cycle[cycle][0],
                expected=growth_rates_for_each_cycle[cycle][1],
                number_of_steps=length_of_each_cycle[cycle],
                period_to_begin_to_converge=convergence_periods[cycle],
            )
        )
    return pd.concat(results, ignore_index=True)


def revenue_projector_multi_phase(
    revenue_base: float,
    revenue_growth_rate_cycle1_begin: float,
    revenue_growth_rate_cycle1_end: float,
    revenue_growth_rate_cycle2_begin: float,
    revenue_growth_rate_cycle2_end: float,
    revenue_growth_rate_cycle3_begin: float,
    revenue_growth_rate_cycle3_end: float = 0.028,
    length_of_cycle1: int = 3,
    length_of_cycle2: int = 4,
    length_of_cycle3: int = 3,
    revenue_convergence_periods_cycle1: int = 1,
    revenue_convergence_periods_cycle2: int = 1,
    revenue_convergence_periods_cycle3: int = 1,
) -> tuple[pd.Series, pd.Series]:
    projected_revenue_growth = dynamic_converger_multiple_phase(
        growth_rates_for_each_cycle=[
            [revenue_growth_rate_cycle1_begin, revenue_growth_rate_cycle1_end],
            [revenue_growth_rate_cycle2_begin, revenue_growth_rate_cycle2_end],
            [revenue_growth_rate_cycle3_begin, revenue_growth_rate_cycle3_end],
        ],
        length_of_each_cycle=[
            _to_int(length_of_cycle1, name="length_of_cycle1"),
            _to_int(length_of_cycle2, name="length_of_cycle2"),
            _to_int(length_of_cycle3, name="length_of_cycle3"),
        ],
        convergence_periods=[
            _to_int(
                revenue_convergence_periods_cycle1,
                name="revenue_convergence_periods_cycle1",
            ),
            _to_int(
                revenue_convergence_periods_cycle2,
                name="revenue_convergence_periods_cycle2",
            ),
            _to_int(
                revenue_convergence_periods_cycle3,
                name="revenue_convergence_periods_cycle3",
            ),
        ],
    )
    projected_revenue_growth_cumulative = (1 + projected_revenue_growth).cumprod()
    projected_revenues = float(revenue_base) * projected_revenue_growth_cumulative
    return projected_revenues, projected_revenue_growth


def operating_margin_projector(
    current_operating_margin: float,
    terminal_operating_margin: float,
    valuation_interval_in_years: int = 10,
    year_operating_margin_begins_to_converge_to_terminal_operating_margin: int = 5,
) -> pd.Series:
    return dynamic_converger(
        current_operating_margin,
        terminal_operating_margin,
        valuation_interval_in_years,
        year_operating_margin_begins_to_converge_to_terminal_operating_margin,
    )


def tax_rate_projector(
    current_effective_tax_rate: float,
    marginal_tax_rate: float,
    valuation_interval_in_years: int = 10,
    year_effective_tax_rate_begin_to_converge_marginal_tax_rate: int = 5,
) -> pd.Series:
    return dynamic_converger(
        current_effective_tax_rate,
        marginal_tax_rate,
        valuation_interval_in_years,
        year_effective_tax_rate_begin_to_converge_marginal_tax_rate,
    )


def cost_of_capital_projector(
    unlevered_beta: float,
    terminal_unlevered_beta: float,
    current_pretax_cost_of_debt: float,
    terminal_pretax_cost_of_debt: float,
    equity_value: float,
    debt_value: float,
    marginal_tax_rate: float = 0.21,
    risk_free_rate: float = 0.015,
    ERP: float = 0.055,
    valuation_interval_in_years: int = 10,
    year_beta_begins_to_converge_to_terminal_beta: int = 5,
    year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt: int = 5,
) -> tuple[pd.Series, pd.Series, float, pd.Series, pd.Series]:
    if equity_value <= 0:
        raise ValueError("equity_value must be positive.")
    total_capital = equity_value + debt_value
    if total_capital <= 0:
        raise ValueError("total capital must be positive.")

    company_beta = unlevered_beta * (1 + (1 - marginal_tax_rate) * (debt_value / equity_value))
    terminal_beta = terminal_unlevered_beta * (
        1 + (1 - marginal_tax_rate) * (debt_value / equity_value)
    )
    beta_during_valuation_cycle = dynamic_converger(
        company_beta,
        terminal_beta,
        valuation_interval_in_years,
        year_beta_begins_to_converge_to_terminal_beta,
    )
    pre_tax_cost_of_debt = dynamic_converger(
        current_pretax_cost_of_debt,
        terminal_pretax_cost_of_debt,
        valuation_interval_in_years,
        year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt,
    )

    equity_to_capital = equity_value / total_capital
    debt_to_capital = debt_value / total_capital
    after_tax_cost_of_debt = pre_tax_cost_of_debt * (1 - marginal_tax_rate)
    cost_of_equity = risk_free_rate + (beta_during_valuation_cycle * ERP)
    cost_of_capital = (
        equity_to_capital * cost_of_equity
    ) + (debt_to_capital * after_tax_cost_of_debt)
    return (
        cost_of_capital,
        beta_during_valuation_cycle,
        float(terminal_beta),
        cost_of_equity,
        after_tax_cost_of_debt,
    )


def sales_to_capital_projector(
    current_sales_to_capital_ratio: float,
    terminal_sales_to_capital_ratio: float,
    valuation_interval_in_years: int = 10,
    year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital: int = 3,
) -> pd.Series:
    return dynamic_converger(
        current_sales_to_capital_ratio,
        terminal_sales_to_capital_ratio,
        valuation_interval_in_years,
        year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital,
    )


def reinvestment_projector(
    revenue_base: float,
    projected_revenues: pd.Series,
    sales_to_capital_ratios: pd.Series,
    asset_liquidation_during_negative_growth: float = 0,
) -> pd.Series:
    revenue_series = pd.concat(
        [pd.Series([float(revenue_base)]), projected_revenues.reset_index(drop=True)],
        ignore_index=True,
    )
    reinvestment = revenue_series.diff().dropna().reset_index(drop=True) / sales_to_capital_ratios
    return reinvestment.where(
        reinvestment > 0,
        reinvestment * asset_liquidation_during_negative_growth,
    )


def valuator_multi_phase(
    risk_free_rate: float,
    ERP: float,
    equity_value: float,
    debt_value: float,
    unlevered_beta: float,
    terminal_unlevered_beta: float,
    year_beta_begins_to_converge_to_terminal_beta: int,
    current_pretax_cost_of_debt: float,
    terminal_pretax_cost_of_debt: float,
    year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt: int,
    current_effective_tax_rate: float,
    marginal_tax_rate: float,
    year_effective_tax_rate_begin_to_converge_marginal_tax_rate: int,
    revenue_base: float,
    revenue_growth_rate_cycle1_begin: float,
    revenue_growth_rate_cycle1_end: float,
    revenue_growth_rate_cycle2_begin: float,
    revenue_growth_rate_cycle2_end: float,
    revenue_growth_rate_cycle3_begin: float,
    revenue_growth_rate_cycle3_end: float,
    revenue_convergence_periods_cycle1: int,
    revenue_convergence_periods_cycle2: int,
    revenue_convergence_periods_cycle3: int,
    length_of_cycle1: int,
    length_of_cycle2: int,
    length_of_cycle3: int,
    current_sales_to_capital_ratio: float,
    terminal_sales_to_capital_ratio: float,
    year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital: int,
    current_operating_margin: float,
    terminal_operating_margin: float,
    year_operating_margin_begins_to_converge_to_terminal_operating_margin: int,
    additional_return_on_cost_of_capital_in_perpetuity: float = 0.0,
    cash_and_non_operating_asset: float = 0.0,
    asset_liquidation_during_negative_growth: float = 0.0,
    current_invested_capital: float | str = "implicit",
) -> dict[str, Any]:
    """Run the deterministic three-cycle DCF engine refactored from the notebook."""
    valuation_interval_in_years = (
        _to_int(length_of_cycle1, name="length_of_cycle1")
        + _to_int(length_of_cycle2, name="length_of_cycle2")
        + _to_int(length_of_cycle3, name="length_of_cycle3")
    )
    terminal_growth_rate = float(revenue_growth_rate_cycle3_end)

    (
        projected_cost_of_capital,
        projected_beta,
        terminal_beta,
        projected_cost_of_equity,
        projected_after_tax_cost_of_debt,
    ) = cost_of_capital_projector(
        unlevered_beta=unlevered_beta,
        terminal_unlevered_beta=terminal_unlevered_beta,
        current_pretax_cost_of_debt=current_pretax_cost_of_debt,
        terminal_pretax_cost_of_debt=terminal_pretax_cost_of_debt,
        equity_value=equity_value,
        debt_value=debt_value,
        marginal_tax_rate=marginal_tax_rate,
        risk_free_rate=risk_free_rate,
        ERP=ERP,
        valuation_interval_in_years=valuation_interval_in_years,
        year_beta_begins_to_converge_to_terminal_beta=(
            year_beta_begins_to_converge_to_terminal_beta
        ),
        year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt=(
            year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt
        ),
    )
    projected_cost_of_capital_cumulative = (1 + projected_cost_of_capital).cumprod()
    projected_cost_of_equity_cumulative = (1 + projected_cost_of_equity).cumprod()

    projected_revenues, projected_revenue_growth = revenue_projector_multi_phase(
        revenue_base=revenue_base,
        revenue_growth_rate_cycle1_begin=revenue_growth_rate_cycle1_begin,
        revenue_growth_rate_cycle1_end=revenue_growth_rate_cycle1_end,
        revenue_growth_rate_cycle2_begin=revenue_growth_rate_cycle2_begin,
        revenue_growth_rate_cycle2_end=revenue_growth_rate_cycle2_end,
        revenue_growth_rate_cycle3_begin=revenue_growth_rate_cycle3_begin,
        revenue_growth_rate_cycle3_end=revenue_growth_rate_cycle3_end,
        length_of_cycle1=length_of_cycle1,
        length_of_cycle2=length_of_cycle2,
        length_of_cycle3=length_of_cycle3,
        revenue_convergence_periods_cycle1=revenue_convergence_periods_cycle1,
        revenue_convergence_periods_cycle2=revenue_convergence_periods_cycle2,
        revenue_convergence_periods_cycle3=revenue_convergence_periods_cycle3,
    )
    projected_tax_rates = tax_rate_projector(
        current_effective_tax_rate=current_effective_tax_rate,
        marginal_tax_rate=marginal_tax_rate,
        valuation_interval_in_years=valuation_interval_in_years,
        year_effective_tax_rate_begin_to_converge_marginal_tax_rate=(
            year_effective_tax_rate_begin_to_converge_marginal_tax_rate
        ),
    )
    sales_to_capital_ratios = sales_to_capital_projector(
        current_sales_to_capital_ratio,
        terminal_sales_to_capital_ratio,
        valuation_interval_in_years=valuation_interval_in_years,
        year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital=(
            year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital
        ),
    )
    projected_reinvestment = reinvestment_projector(
        revenue_base=revenue_base,
        projected_revenues=projected_revenues,
        sales_to_capital_ratios=sales_to_capital_ratios,
        asset_liquidation_during_negative_growth=asset_liquidation_during_negative_growth,
    )

    invested_capital = projected_reinvestment.copy()
    if current_invested_capital == "implicit":
        current_invested_capital = revenue_base / current_sales_to_capital_ratio
    current_invested_capital = float(current_invested_capital)
    invested_capital.iloc[0] = invested_capital.iloc[0] + current_invested_capital
    invested_capital = invested_capital.cumsum()

    projected_operating_margins = operating_margin_projector(
        current_operating_margin,
        terminal_operating_margin,
        valuation_interval_in_years=valuation_interval_in_years,
        year_operating_margin_begins_to_converge_to_terminal_operating_margin=(
            year_operating_margin_begins_to_converge_to_terminal_operating_margin
        ),
    )
    projected_operating_income = projected_revenues * projected_operating_margins
    projected_operating_income_after_tax = projected_operating_income * (
        1 - projected_tax_rates
    )
    projected_fcff = projected_operating_income_after_tax - projected_reinvestment
    roic = projected_operating_income_after_tax / invested_capital

    terminal_cost_of_capital = float(projected_cost_of_capital.iloc[-1])
    terminal_cost_of_equity = float(projected_cost_of_equity.iloc[-1])
    if terminal_cost_of_capital <= terminal_growth_rate:
        raise ValueError(
            "Terminal cost of capital must be greater than terminal growth rate.",
        )
    if terminal_cost_of_equity <= terminal_growth_rate:
        raise ValueError(
            "Terminal cost of equity must be greater than terminal growth rate.",
        )

    if terminal_growth_rate < 0:
        terminal_reinvestment_rate = 0.0
    else:
        terminal_reinvestment_rate = terminal_growth_rate / (
            terminal_cost_of_capital + additional_return_on_cost_of_capital_in_perpetuity
        )

    terminal_revenue = float(projected_revenues.iloc[-1]) * (1 + terminal_growth_rate)
    terminal_operating_income = terminal_revenue * terminal_operating_margin
    terminal_operating_income_after_tax = terminal_operating_income * (1 - marginal_tax_rate)
    terminal_reinvestment = terminal_operating_income_after_tax * terminal_reinvestment_rate
    terminal_fcff = terminal_operating_income_after_tax - terminal_reinvestment
    terminal_value = terminal_fcff / (terminal_cost_of_capital - terminal_growth_rate)
    terminal_discount_rate = float(projected_cost_of_capital_cumulative.iloc[-1])
    terminal_equity_discount_rate = float(projected_cost_of_equity_cumulative.iloc[-1])

    projected_cost_of_capital_cumulative_with_terminal_rate = _append(
        projected_cost_of_capital_cumulative,
        terminal_discount_rate,
    )
    projected_cost_of_equity_cumulative_with_terminal_rate = _append(
        projected_cost_of_equity_cumulative,
        terminal_equity_discount_rate,
    )
    projected_revenue_growth = _append(projected_revenue_growth, terminal_growth_rate)
    projected_revenues = _append(projected_revenues, terminal_revenue)
    projected_tax_rates = _append(projected_tax_rates, marginal_tax_rate)
    projected_reinvestment = _append(projected_reinvestment, terminal_reinvestment)
    invested_capital = _append(invested_capital, np.nan)
    terminal_roic = terminal_cost_of_capital + additional_return_on_cost_of_capital_in_perpetuity
    roic = _append(roic, terminal_roic)
    projected_operating_margins = _append(
        projected_operating_margins,
        terminal_operating_margin,
    )
    projected_operating_income = _append(
        projected_operating_income,
        terminal_operating_income,
    )
    projected_operating_income_after_tax = _append(
        projected_operating_income_after_tax,
        terminal_operating_income_after_tax,
    )
    projected_fcff_value = _append(projected_fcff, terminal_value)
    projected_fcff = _append(projected_fcff, terminal_fcff)
    projected_beta = _append(projected_beta, terminal_beta)
    sales_to_capital_ratios = _append(
        sales_to_capital_ratios,
        terminal_sales_to_capital_ratio,
    )
    projected_after_tax_cost_of_debt_with_terminal = _append(
        projected_after_tax_cost_of_debt,
        float(projected_after_tax_cost_of_debt.iloc[-1]),
    )

    reinvestment_rate = projected_reinvestment / projected_operating_income_after_tax
    df_valuation = pd.DataFrame(
        {
            "cumWACC": projected_cost_of_capital_cumulative_with_terminal_rate,
            "cumCostOfEquity": projected_cost_of_equity_cumulative_with_terminal_rate,
            "beta": projected_beta,
            "ERP": ERP,
            "projected_after_tax_cost_of_debt": (
                projected_after_tax_cost_of_debt_with_terminal
            ),
            "revenueGrowth": projected_revenue_growth,
            "revneues": projected_revenues,
            "revenues": projected_revenues,
            "margins": projected_operating_margins,
            "ebit": projected_operating_income,
            "sales_to_capital_ratio": sales_to_capital_ratios,
            "taxRate": projected_tax_rates,
            "afterTaxOperatingIncome": projected_operating_income_after_tax,
            "reinvestment": projected_reinvestment,
            "invested_capital": invested_capital,
            "ROIC": roic,
            "reinvestmentRate": reinvestment_rate,
            "FCFF": projected_fcff,
            "projected_FCFF_value": projected_fcff_value,
        }
    )
    df_valuation["PVFCFF"] = df_valuation["projected_FCFF_value"] / df_valuation["cumWACC"]
    value_of_operating_assets = float(df_valuation["PVFCFF"].sum())
    firm_value = value_of_operating_assets + cash_and_non_operating_asset
    intrinsic_equity_present_value = firm_value - debt_value

    cum_cost_of_equity_at_the_end_of_valuation = float(
        projected_cost_of_equity_cumulative.iloc[-1],
    )
    acceptable_annualized_return_on_equity = (
        cum_cost_of_equity_at_the_end_of_valuation ** (1 / valuation_interval_in_years)
    ) - 1
    expected_annualized_return_on_equity = (
        (intrinsic_equity_present_value * cum_cost_of_equity_at_the_end_of_valuation)
        / equity_value
    ) ** (1 / valuation_interval_in_years) - 1
    excess_annualized_return_on_equity = (
        intrinsic_equity_present_value / equity_value
    ) ** (1 / valuation_interval_in_years) - 1

    def cum_return_calculator(value: float, period: int, append_nan: bool = True) -> pd.Series:
        values = pd.Series([1 + value] * int(period)).cumprod()
        if append_nan:
            values = _append(values, np.nan)
        return values

    df_valuation["cum_acceptable_annualized_return_on_equity"] = cum_return_calculator(
        acceptable_annualized_return_on_equity,
        valuation_interval_in_years,
    )
    df_valuation["cum_expected_annualized_return_on_equity"] = cum_return_calculator(
        expected_annualized_return_on_equity,
        valuation_interval_in_years,
    )
    df_valuation["cum_excess_annualized_return_on_equity"] = cum_return_calculator(
        excess_annualized_return_on_equity,
        valuation_interval_in_years,
    )
    df_valuation["cum_excess_annualized_return_on_equity_realized"] = (
        df_valuation["cum_expected_annualized_return_on_equity"]
        / df_valuation["cumCostOfEquity"]
    )
    df_valuation["excess_annualized_return_on_equity"] = _append(
        pd.Series([excess_annualized_return_on_equity] * int(valuation_interval_in_years)),
        np.nan,
    )
    df_valuation["year"] = np.arange(1, len(df_valuation) + 1)
    df_valuation["is_terminal"] = False
    df_valuation.loc[df_valuation.index[-1], "is_terminal"] = True

    return {
        "valuation": df_valuation,
        "firm_value": float(firm_value),
        "equity_value": float(intrinsic_equity_present_value),
        "cash_and_non_operating_asset": float(cash_and_non_operating_asset),
        "debt_value": float(debt_value),
        "value_of_operating_assets": float(value_of_operating_assets),
    }


def valuation_table_to_records(df_valuation: pd.DataFrame) -> list[dict[str, Any]]:
    records = df_valuation.replace({np.nan: None}).to_dict(orient="records")
    return [
        {
            key: (_scalar(value) if isinstance(value, np.generic) else value)
            for key, value in record.items()
        }
        for record in records
    ]
