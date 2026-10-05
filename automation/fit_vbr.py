#!/usr/bin/env python3
"""Fit p.e. spacing against bias and calculate breakdown voltage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--signal", required=True)
    parser.add_argument("--color", default="C0")
    parser.add_argument("--metric", choices=("height", "area"), default="height")
    parser.add_argument("--analysis-dir", default="analysis")
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    pattern = f"{args.analysis_dir}/bias_*/{args.signal}/point_summary.json"
    for path in sorted(args.run_root.glob(pattern)):
        row = json.loads(path.read_text(encoding="utf-8"))
        row["summary_path"] = str(path)
        rows.append(row)
    if not rows:
        raise FileNotFoundError(f"No point summaries matching {pattern}")

    table = pd.DataFrame(rows).sort_values("bias_v")
    if args.metric == "height":
        quality_column = "quality_pass"
        spacing_column = "one_pe_spacing_mV"
        uncertainty_column = "one_pe_spacing_unc_mV"
        count_column = "selected_peak_count"
        y_label = "One-photoelectron peak spacing (mV)"
        unit = "mV"
    else:
        quality_column = "area_quality_pass"
        spacing_column = "one_pe_area_spacing_mV_ns"
        uncertainty_column = "one_pe_area_spacing_unc_mV_ns"
        count_column = "area_selected_peak_count"
        y_label = "One-photoelectron area spacing (mV ns)"
        unit = "mV ns"
    valid = (
        table[quality_column].fillna(False)
        & np.isfinite(table[spacing_column])
        & table[count_column].ge(2)
    )
    used = table.loc[valid].copy()
    if len(used) < 3:
        raise RuntimeError(f"Only {len(used)} valid bias points; at least three are required")

    x = used["bias_v"].to_numpy(float)
    y = used[spacing_column].to_numpy(float)
    yerr = used[uncertainty_column].to_numpy(float)
    finite_positive = yerr[np.isfinite(yerr) & (yerr > 0)]
    fallback = float(np.median(finite_positive)) if len(finite_positive) else 1.0
    yerr = np.where(np.isfinite(yerr) & (yerr > 0), yerr, fallback)
    uncertainty_floor = 0.05 if args.metric == "height" else 2.5
    yerr = np.maximum(yerr, uncertainty_floor)

    # Centering the voltage keeps the weighted normal equations well-conditioned.
    inverse_variance = 1.0 / np.square(yerr)
    x_reference = float(np.average(x, weights=inverse_variance))
    centered_x = x - x_reference
    design = np.column_stack([centered_x, np.ones(len(centered_x))])
    centered_covariance = np.linalg.inv(design.T @ (inverse_variance[:, None] * design))
    centered_slope, centered_intercept = centered_covariance @ (design.T @ (inverse_variance * y))
    centered_residuals = y - (centered_slope * centered_x + centered_intercept)
    reduced_chi_squared = float(
        np.sum(np.square(centered_residuals / yerr)) / max(len(x) - 2, 1)
    )
    centered_covariance *= max(1.0, reduced_chi_squared)

    slope = float(centered_slope)
    intercept = float(centered_intercept - centered_slope * x_reference)
    transform = np.array([[1.0, 0.0], [-x_reference, 1.0]])
    covariance = transform @ centered_covariance @ transform.T
    predicted = slope * x + intercept
    residuals = y - predicted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    vbr = -intercept / slope
    derivative_slope = intercept / slope**2
    derivative_intercept = -1.0 / slope
    vbr_variance = (
        derivative_slope**2 * covariance[0, 0]
        + derivative_intercept**2 * covariance[1, 1]
        + 2.0 * derivative_slope * derivative_intercept * covariance[0, 1]
    )
    vbr_unc = float(np.sqrt(max(vbr_variance, 0.0)))
    slope_unc = float(np.sqrt(covariance[0, 0]))

    output = args.run_root / args.results_dir / args.signal / args.metric
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / "all_bias_points.csv", index=False)
    result = {
        "signal": args.signal,
        "metric": args.metric,
        "used_bias_points": int(len(used)),
        "rejected_bias_points": int(len(table) - len(used)),
        "slope_per_V": slope,
        "slope_unc_per_V": slope_unc,
        "intercept": intercept,
        "spacing_unit": unit,
        "minimum_spacing_uncertainty": uncertainty_floor,
        "reduced_chi_squared": reduced_chi_squared,
        "breakdown_voltage_V": vbr,
        "breakdown_voltage_unc_V": vbr_unc,
        "r_squared": r_squared,
        "bias_points_V": x.tolist(),
        "pe_spacings": y.tolist(),
    }
    (output / "vbr_fit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    fit_x = np.linspace(min(vbr, x.min()) - 0.1, x.max() + 0.15, 250)
    figure, axis = plt.subplots(figsize=(8.6, 6.1), dpi=180)
    axis.errorbar(
        x,
        y,
        yerr=yerr,
        fmt="o",
        color=args.color,
        capsize=4,
        markersize=7,
        label="Accepted p.e. spacing",
    )
    axis.plot(
        fit_x,
        slope * fit_x + intercept,
        color=args.color,
        linewidth=2,
        label=(
            f"linear fit: Vbr={vbr:.3f} ± {vbr_unc:.3f} V\n"
            f"slope={slope:.2f} ± {slope_unc:.2f} {unit}/V, R²={r_squared:.3f}"
        ),
    )
    axis.axhline(0, color="0.35", linewidth=1)
    axis.axvline(vbr, color=args.color, linestyle="--", linewidth=1.3)
    axis.set_title(f"{args.signal}: breakdown voltage from p.e. {args.metric} spacing")
    axis.set_xlabel("Effective SiPM bias voltage (V)")
    axis.set_ylabel(y_label)
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "vbr_fit.png")
    plt.close(figure)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
