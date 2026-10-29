from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from agents import _logger

from .dcf_model import valuator_multi_phase
from .schemas import DCFValuationParams
from .schemas import DistributionSpec


INTEGER_FIELDS = {
    "year_beta_begins_to_converge_to_terminal_beta",
    "year_cost_of_debt_begins_to_converge_to_terminal_cost_of_debt",
    "year_effective_tax_rate_begin_to_converge_marginal_tax_rate",
    "revenue_convergence_periods_cycle1",
    "revenue_convergence_periods_cycle2",
    "revenue_convergence_periods_cycle3",
    "length_of_cycle1",
    "length_of_cycle2",
    "length_of_cycle3",
    "year_sales_to_capital_begins_to_converge_to_terminal_sales_to_capital",
    "year_operating_margin_begins_to_converge_to_terminal_operating_margin",
}


def _draw_distribution(
    spec: DistributionSpec,
    base_value: float,
    rng: np.random.Generator,
    sample_size: int,
) -> np.ndarray:
    if spec.distribution == "fixed":
        values = np.full(sample_size, float(spec.value))
    elif spec.distribution == "normal":
        values = rng.normal(
            loc=float(spec.mean if spec.mean is not None else base_value),
            scale=float(spec.stdev),
            size=sample_size,
        )
    elif spec.distribution == "triangular":
        values = rng.triangular(
            left=float(spec.low),
            mode=float(spec.mode),
            right=float(spec.high),
            size=sample_size,
        )
    elif spec.distribution == "uniform":
        values = rng.uniform(float(spec.low), float(spec.high), size=sample_size)
    else:
        raise ValueError(f"Unsupported distribution {spec.distribution}.")

    if spec.min_value is not None or spec.max_value is not None:
        low = spec.min_value if spec.min_value is not None else -np.inf
        high = spec.max_value if spec.max_value is not None else np.inf
        values = np.clip(values, low, high)
    return values


def _summarize(values: np.ndarray) -> dict[str, float]:
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    return {
        "mean": float(np.mean(values)),
        "stdev": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "percentiles": {
            str(percentile): float(np.percentile(values, percentile))
            for percentile in percentiles
        },
    }


def run_monte_carlo_valuation(
    base_params: DCFValuationParams | dict[str, Any],
    distributions: list[DistributionSpec],
    sample_size: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    """Run banker-approved distribution scenarios through the deterministic DCF."""
    base = (
        base_params
        if isinstance(base_params, DCFValuationParams)
        else DCFValuationParams.model_validate(base_params)
    )
    if sample_size < 10 or sample_size > 5000:
        raise ValueError("sample_size must be between 10 and 5,000.")

    base_dict = base.model_dump(mode="python")
    unknown = [
        spec.variable
        for spec in distributions
        if spec.variable not in DCFValuationParams.model_fields
    ]
    if unknown:
        raise ValueError(f"Unknown DCF variables in distributions: {unknown}")

    rng = np.random.default_rng(seed)
    sampled_columns: dict[str, np.ndarray] = {}
    for spec in distributions:
        base_value = base_dict[spec.variable]
        if base_value == "implicit":
            raise ValueError(
                f"Cannot distribute {spec.variable} while it is set to 'implicit'.",
            )
        sampled_columns[spec.variable] = _draw_distribution(
            spec,
            float(base_value),
            rng,
            sample_size,
        )

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for index in range(sample_size):
        params = dict(base_dict)
        for variable, values in sampled_columns.items():
            value = float(values[index])
            if variable in INTEGER_FIELDS:
                value = max(1, int(round(value)))
            params[variable] = value
        try:
            validated = DCFValuationParams.model_validate(params)
            result = valuator_multi_phase(**validated.model_dump(mode="python"))
        except Exception as exc:
            if len(failures) < 10:
                failures.append(str(exc))
            continue

        rows.append(
            {
                **{
                    variable: params[variable]
                    for variable in sampled_columns
                    if isinstance(params[variable], (int, float))
                },
                "equity_value": float(result["equity_value"]),
                "firm_value": float(result["firm_value"]),
                "value_of_operating_assets": float(result["value_of_operating_assets"]),
            }
        )

    if not rows:
        raise ValueError("All Monte Carlo scenarios failed validation or execution.")

    df = pd.DataFrame(rows)
    equity_values = df["equity_value"].to_numpy()
    firm_values = df["firm_value"].to_numpy()
    driver_rows: list[dict[str, float | str]] = []
    for variable in sampled_columns:
        if df[variable].nunique() <= 1:
            continue
        corr = df[[variable, "equity_value"]].corr(method="pearson").iloc[0, 1]
        if not np.isnan(corr):
            driver_rows.append(
                {
                    "variable": variable,
                    "correlation_to_equity_value": float(corr),
                    "absolute_correlation": float(abs(corr)),
                }
            )
    driver_rows = sorted(
        driver_rows,
        key=lambda item: item["absolute_correlation"],
        reverse=True,
    )[:10]

    _logger.info(
        "Monte Carlo completed with %s successes and %s failures",
        len(rows),
        sample_size - len(rows),
    )
    return {
        "status": "success",
        "sample_size_requested": sample_size,
        "successful_samples": len(rows),
        "failed_samples": sample_size - len(rows),
        "failure_examples": failures,
        "seed": seed,
        "current_market_equity_value": base.equity_value,
        "probability_above_current_market_value": float(
            np.mean(equity_values > base.equity_value),
        ),
        "equity_value_distribution": _summarize(equity_values),
        "firm_value_distribution": _summarize(firm_values),
        "value_drivers": driver_rows,
    }
