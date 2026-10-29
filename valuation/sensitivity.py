from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents import _logger

from .dcf_tool import run_dcf_valuation
from .schemas import DCFValuationParams


@dataclass(frozen=True)
class SensitivitySpec:
    variable: str
    label: str
    low_delta: float
    high_delta: float
    unit: str
    note: str
    lower_bound: float | None = None
    upper_bound: float | None = None


KEY_SENSITIVITIES: tuple[SensitivitySpec, ...] = (
    SensitivitySpec(
        variable="ERP",
        label="Equity risk premium",
        low_delta=-0.005,
        high_delta=0.005,
        unit="percent",
        note="Market risk premium sensitivity; percentages are decimal inputs.",
        lower_bound=0.0,
        upper_bound=0.25,
    ),
    SensitivitySpec(
        variable="unlevered_beta",
        label="Unlevered beta",
        low_delta=-0.10,
        high_delta=0.10,
        unit="multiple",
        note="Cost of equity sensitivity through beta.",
        lower_bound=0.01,
        upper_bound=5.0,
    ),
    SensitivitySpec(
        variable="terminal_operating_margin",
        label="Terminal operating margin",
        low_delta=-0.01,
        high_delta=0.01,
        unit="percent",
        note="Margin expansion / compression sensitivity.",
        lower_bound=-0.50,
        upper_bound=0.80,
    ),
    SensitivitySpec(
        variable="revenue_growth_rate_cycle1_end",
        label="Cycle 1 exit revenue growth",
        low_delta=-0.01,
        high_delta=0.01,
        unit="percent",
        note="Near-term growth ramp sensitivity.",
        lower_bound=-0.90,
        upper_bound=1.00,
    ),
    SensitivitySpec(
        variable="revenue_growth_rate_cycle2_end",
        label="Cycle 2 exit revenue growth",
        low_delta=-0.01,
        high_delta=0.01,
        unit="percent",
        note="Mid-period growth fade sensitivity.",
        lower_bound=-0.90,
        upper_bound=1.00,
    ),
    SensitivitySpec(
        variable="revenue_growth_rate_cycle3_end",
        label="Terminal growth",
        low_delta=-0.005,
        high_delta=0.005,
        unit="percent",
        note="Terminal growth is capped at the risk-free rate by valuation policy.",
        lower_bound=-0.10,
        upper_bound=0.12,
    ),
    SensitivitySpec(
        variable="terminal_sales_to_capital_ratio",
        label="Terminal sales / capital",
        low_delta=-0.10,
        high_delta=0.10,
        unit="multiple",
        note="Reinvestment intensity sensitivity.",
        lower_bound=0.01,
        upper_bound=20.0,
    ),
    SensitivitySpec(
        variable="additional_return_on_cost_of_capital_in_perpetuity",
        label="Perpetuity excess return",
        low_delta=-0.005,
        high_delta=0.005,
        unit="percent",
        note="Terminal spread between ROIC and cost of capital.",
        lower_bound=-0.10,
        upper_bound=0.30,
    ),
)


def _clamp(value: float, low: float | None, high: float | None) -> float:
    if low is not None:
        value = max(value, low)
    if high is not None:
        value = min(value, high)
    return value


def _scenario_params(
    base: DCFValuationParams,
    variable: str,
    value: float,
) -> dict[str, Any]:
    params = base.model_dump(mode="python")
    params[variable] = value
    return params


def _run_equity_value(params: dict[str, Any]) -> dict[str, Any]:
    result = run_dcf_valuation(params)
    if result.get("status") != "success":
        return {
            "status": result.get("status", "error"),
            "message": result.get("message", "DCF scenario failed."),
            "equity_value": None,
            "firm_value": None,
            "premium_discount": None,
        }
    return {
        "status": "success",
        "message": None,
        "equity_value": result["intrinsic_equity_value"],
        "firm_value": result["firm_value"],
        "premium_discount": result["implied_premium_discount"],
    }


def _bounded_value(
    *,
    base: DCFValuationParams,
    spec: SensitivitySpec,
    delta: float,
) -> tuple[float, list[str]]:
    base_value = float(getattr(base, spec.variable))
    notes: list[str] = []
    upper_bound = spec.upper_bound
    if spec.variable == "revenue_growth_rate_cycle3_end":
        upper_bound = min(upper_bound or base.risk_free_rate, base.risk_free_rate)
    if spec.variable == "risk_free_rate":
        lower_bound = max(spec.lower_bound or -0.02, base.revenue_growth_rate_cycle3_end)
    else:
        lower_bound = spec.lower_bound

    raw_value = base_value + delta
    value = _clamp(raw_value, lower_bound, upper_bound)
    if value != raw_value:
        notes.append(f"Scenario input clamped from {raw_value:.4f} to {value:.4f}.")
    return value, notes


def _sensitivity_row(
    base: DCFValuationParams,
    base_equity_value: float,
    spec: SensitivitySpec,
) -> dict[str, Any]:
    low_value, low_notes = _bounded_value(base=base, spec=spec, delta=spec.low_delta)
    high_value, high_notes = _bounded_value(base=base, spec=spec, delta=spec.high_delta)
    low_result = _run_equity_value(_scenario_params(base, spec.variable, low_value))
    high_result = _run_equity_value(_scenario_params(base, spec.variable, high_value))

    low_delta = (
        low_result["equity_value"] - base_equity_value
        if low_result["equity_value"] is not None
        else None
    )
    high_delta = (
        high_result["equity_value"] - base_equity_value
        if high_result["equity_value"] is not None
        else None
    )
    absolute_swing = max(
        abs(value)
        for value in [low_delta or 0.0, high_delta or 0.0]
    )
    return {
        "variable": spec.variable,
        "label": spec.label,
        "unit": spec.unit,
        "base_value": float(getattr(base, spec.variable)),
        "low_input_value": low_value,
        "high_input_value": high_value,
        "low_input_equity_value": low_result["equity_value"],
        "high_input_equity_value": high_result["equity_value"],
        "low_input_delta": low_delta,
        "high_input_delta": high_delta,
        "low_input_delta_percent": (
            low_delta / base_equity_value if low_delta is not None else None
        ),
        "high_input_delta_percent": (
            high_delta / base_equity_value if high_delta is not None else None
        ),
        "absolute_swing": absolute_swing,
        "low_input_status": low_result["status"],
        "high_input_status": high_result["status"],
        "notes": [spec.note, *low_notes, *high_notes],
    }


def _unique_sorted(values: list[float]) -> list[float]:
    return sorted({round(value, 6) for value in values})


def _two_way_terminal_matrix(base: DCFValuationParams) -> dict[str, Any]:
    margin_values = _unique_sorted(
        [
            _clamp(base.terminal_operating_margin - 0.01, -0.50, 0.80),
            base.terminal_operating_margin,
            _clamp(base.terminal_operating_margin + 0.01, -0.50, 0.80),
        ]
    )
    growth_values = _unique_sorted(
        [
            _clamp(base.revenue_growth_rate_cycle3_end - 0.005, -0.10, base.risk_free_rate),
            base.revenue_growth_rate_cycle3_end,
            _clamp(base.revenue_growth_rate_cycle3_end + 0.005, -0.10, base.risk_free_rate),
        ]
    )

    cells: list[list[dict[str, Any]]] = []
    for margin in margin_values:
        row: list[dict[str, Any]] = []
        for growth in growth_values:
            params = base.model_dump(mode="python")
            params["terminal_operating_margin"] = margin
            params["revenue_growth_rate_cycle3_end"] = growth
            row.append(
                {
                    "row_value": margin,
                    "column_value": growth,
                    **_run_equity_value(params),
                }
            )
        cells.append(row)

    return {
        "name": "Terminal Growth x Terminal Operating Margin",
        "row_variable": "terminal_operating_margin",
        "row_label": "Terminal operating margin",
        "row_unit": "percent",
        "column_variable": "revenue_growth_rate_cycle3_end",
        "column_label": "Terminal growth",
        "column_unit": "percent",
        "rows": margin_values,
        "columns": growth_values,
        "cells": cells,
        "notes": [
            "Terminal growth cases are capped at the risk-free rate.",
            "Values shown are intrinsic equity values in USD billions.",
        ],
    }


def run_dcf_sensitivity(
    base_params: DCFValuationParams | dict[str, Any],
    base_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic one-factor and terminal matrix sensitivity analysis."""
    base = (
        base_params
        if isinstance(base_params, DCFValuationParams)
        else DCFValuationParams.model_validate(base_params)
    )
    if base_result is None or base_result.get("status") != "success":
        base_result = run_dcf_valuation(base)
    if base_result.get("status") != "success":
        raise ValueError(base_result.get("message") or "Base DCF did not run.")

    base_equity_value = float(base_result["intrinsic_equity_value"])
    rows = [
        _sensitivity_row(base, base_equity_value, spec)
        for spec in KEY_SENSITIVITIES
    ]
    top_drivers = sorted(
        rows,
        key=lambda row: row["absolute_swing"],
        reverse=True,
    )[:5]
    matrix = _two_way_terminal_matrix(base)
    _logger.info("DCF sensitivity completed across %s one-factor cases", len(rows))
    return {
        "status": "success",
        "base_case": {
            "intrinsic_equity_value": base_equity_value,
            "firm_value": base_result["firm_value"],
            "current_market_equity_value": base_result["current_market_equity_value"],
            "implied_premium_discount": base_result["implied_premium_discount"],
        },
        "one_factor_sensitivities": rows,
        "top_value_drivers": top_drivers,
        "matrices": [matrix],
        "shock_policy": {
            "percent_inputs": "100 bps for growth/margin drivers except terminal growth and perpetuity spread at 50 bps.",
            "cost_of_capital_inputs": "ERP +/- 50 bps and beta +/- 0.10.",
            "reinvestment_inputs": "Terminal sales-to-capital ratio +/- 0.10x.",
        },
    }
