from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agents import _logger

from .dcf_model import valuation_table_to_records
from .dcf_model import valuator_multi_phase
from .schemas import DCFValuationParams


REQUIRED_DCF_KEYS = [
    field
    for field, info in DCFValuationParams.model_fields.items()
    if info.is_required()
]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]


def _terminal_row(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    return next((row for row in records if row.get("is_terminal")), records[-1])


def run_dcf_valuation(params: dict[str, Any] | DCFValuationParams) -> dict[str, Any]:
    """
    Runs the multi-phase DCF valuation tool.

    Percentage inputs are decimals: 4% is 0.04. The tool performs deterministic
    math only; it does not invent assumptions or retrieve data.
    """
    raw_params = params.model_dump(mode="json") if isinstance(params, DCFValuationParams) else params
    missing = [key for key in REQUIRED_DCF_KEYS if key not in raw_params]
    if missing:
        return {
            "status": "missing_inputs",
            "missing_inputs": missing,
            "message": "DCF cannot run until all required inputs are provided.",
        }

    try:
        validated = DCFValuationParams.model_validate(raw_params)
    except ValidationError as exc:
        _logger.warning("DCF parameter validation failed: %s", exc)
        return {
            "status": "invalid_inputs",
            "message": "DCF assumptions failed validation.",
            "errors": _format_validation_error(exc),
        }

    if validated.revenue_growth_rate_cycle3_end > validated.risk_free_rate:
        return {
            "status": "invalid_inputs",
            "message": (
                "Terminal growth exceeds the risk-free rate. Please revise or "
                "explicitly escalate this assumption through valuation policy."
            ),
            "terminal_growth_rate": validated.revenue_growth_rate_cycle3_end,
            "risk_free_rate": validated.risk_free_rate,
        }

    try:
        result = valuator_multi_phase(**validated.model_dump(mode="python"))
    except Exception as exc:
        _logger.exception("DCF valuation execution failed")
        return {
            "status": "error",
            "message": str(exc),
        }

    valuation_table = valuation_table_to_records(result["valuation"])
    terminal = _terminal_row(valuation_table)
    firm_value = _float(result["firm_value"])
    intrinsic_equity_value = _float(result["equity_value"])
    current_market_equity_value = validated.equity_value
    price_to_value = (
        current_market_equity_value / intrinsic_equity_value
        if intrinsic_equity_value
        else None
    )

    return {
        "status": "success",
        "firm_value": firm_value,
        "intrinsic_equity_value": intrinsic_equity_value,
        "current_market_equity_value": current_market_equity_value,
        "value_of_operating_assets": _float(result["value_of_operating_assets"]),
        "cash_and_non_operating_asset": _float(result["cash_and_non_operating_asset"]),
        "debt_value": _float(result["debt_value"]),
        "price_to_intrinsic_value": price_to_value,
        "implied_premium_discount": (
            (intrinsic_equity_value / current_market_equity_value) - 1
            if current_market_equity_value
            else None
        ),
        "valuation_interval_years": (
            validated.length_of_cycle1
            + validated.length_of_cycle2
            + validated.length_of_cycle3
        ),
        "terminal_metrics": {
            "terminal_revenue": terminal.get("revenues"),
            "terminal_operating_margin": terminal.get("margins"),
            "terminal_reinvestment_rate": terminal.get("reinvestmentRate"),
            "terminal_fcff": terminal.get("FCFF"),
            "terminal_roic": terminal.get("ROIC"),
            "terminal_growth": terminal.get("revenueGrowth"),
        },
        "valuation_table": valuation_table,
    }
