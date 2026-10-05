#!/usr/bin/env python3
"""Summary plots that tolerate an incomplete calibration run."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


STEP_PATTERN = re.compile(r"step_(\d+)_vov_(\d+)p(\d+)V")
COLORS = {"SiPM_1": "#1f77b4", "SiPM_2": "#ff7f0e", "SIPM1": "#1f77b4", "SIPM2": "#ff7f0e"}


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 12,
            "axes.grid": True,
            "grid.alpha": 0.24,
            "figure.dpi": 160,
            "savefig.dpi": 220,
            "savefig.bbox": "tight",
        }
    )


def logistic(voltage: np.ndarray, plateau: float, v50: float, width: float) -> np.ndarray:
    return plateau / (1.0 + np.exp(-(voltage - v50) / width))


def zero_event_summary(root: Path) -> Path:
    output = root / "summary"
    output.mkdir(parents=True, exist_ok=True)
    point_dirs = sorted(root.glob("step_*_vov_*V"))
    total_steps = len(point_dirs)
    rows: list[dict] = []
    failures: list[dict] = []

    for point_dir in point_dirs:
        match = STEP_PATTERN.fullmatch(point_dir.name)
        if not match:
            continue
        step = int(match.group(1))
        voltage = float(f"{match.group(2)}.{match.group(3)}")
        summary_path = point_dir / "analysis" / "scintillator_zero_summary.csv"
        if not summary_path.exists():
            failures.append({"step": step, "overvoltage_V": voltage, "reason": "analysis missing"})
            continue
        direction = "ascending" if step <= math.ceil(total_steps / 2) else "descending"
        for row in pd.read_csv(summary_path).to_dict("records"):
            rows.append({**row, "step": step, "overvoltage_V": voltage, "direction": direction})

    if not rows:
        raise RuntimeError("No completed zero-event analyses were found")

    table = pd.DataFrame(rows).sort_values(["label", "step"])
    table.to_csv(output / "zero_event_results.csv", index=False)
    pd.DataFrame(failures).to_csv(output / "analysis_failures.csv", index=False)

    configure_style()
    labels = list(dict.fromkeys(table["label"].tolist()))
    figure, axes = plt.subplots(1, len(labels), figsize=(7.2 * len(labels), 5.8), sharey=True)
    if len(labels) == 1:
        axes = [axes]
    diagnostics: list[dict] = []

    for axis, label in zip(axes, labels):
        selected = table[table["label"] == label].copy()
        color = COLORS.get(label, "#2878b5")
        for direction, marker in (("ascending", "^"), ("descending", "v")):
            pass_rows = selected[selected["direction"] == direction]
            if pass_rows.empty:
                continue
            y = 100 * pass_rows["efficiency_median"].to_numpy(float)
            low = 100 * pass_rows["efficiency_68_low"].to_numpy(float)
            high = 100 * pass_rows["efficiency_68_high"].to_numpy(float)
            axis.errorbar(
                pass_rows["overvoltage_V"],
                y,
                yerr=np.vstack((y - low, high - y)),
                fmt=marker,
                color=color,
                markerfacecolor="white",
                capsize=3,
                alpha=0.75,
                label=direction,
            )

        grouped = selected.groupby("overvoltage_V")["efficiency_median"]
        spread = grouped.max() - grouped.min()
        maximum_spread = float(spread.max()) if len(spread) else 0.0
        monotonic = selected.sort_values("overvoltage_V").groupby("overvoltage_V")[
            "efficiency_median"
        ].median()
        violations = int(np.sum(np.diff(monotonic.to_numpy(float)) < -0.03))
        fit_status = "not attempted"

        combined = selected.groupby("overvoltage_V", as_index=False).agg(
            efficiency=("efficiency_median", "median"),
            uncertainty=("efficiency_median", lambda values: max(float(np.std(values)), 0.005)),
        )
        if len(combined) >= 4 and maximum_spread <= 0.05 and violations == 0:
            try:
                x = combined["overvoltage_V"].to_numpy(float)
                y = combined["efficiency"].to_numpy(float)
                sigma = combined["uncertainty"].to_numpy(float)
                parameters, covariance = curve_fit(
                    logistic,
                    x,
                    y,
                    sigma=sigma,
                    absolute_sigma=True,
                    p0=(0.995, float(np.median(x)), 0.12),
                    bounds=((0.5, -1.0, 0.005), (1.0, 5.0, 2.0)),
                    maxfev=100000,
                )
                dense = np.linspace(x.min(), x.max(), 400)
                axis.plot(dense, 100 * logistic(dense, *parameters), color=color, linewidth=2)
                plateau, v50, width = parameters
                v99 = float(v50 + width * math.log(99))
                fit_status = f"plateau={100*plateau:.2f}%, V99={v99:.3f} V"
            except Exception as exc:
                fit_status = f"fit failed: {exc}"
        elif maximum_spread > 0.05:
            fit_status = "fit withheld: repeated points disagree by more than 5%"
        elif violations:
            fit_status = "fit withheld: efficiency is not monotonic"

        diagnostics.append(
            {
                "label": label,
                "maximum_repeat_spread": maximum_spread,
                "monotonicity_violations": violations,
                "fit_status": fit_status,
            }
        )
        axis.set_title(label.replace("_", " "))
        axis.set_xlabel("SiPM overvoltage (V)")
        axis.set_ylim(0, 102)
        axis.legend(title=fit_status, fontsize=9, title_fontsize=9)

    axes[0].set_ylabel("Dark-corrected efficiency (%)")
    figure.suptitle("Reference-triggered zero-event efficiency", fontsize=16)
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    plot_path = output / "zero_event_efficiency.png"
    figure.savefig(plot_path)
    plt.close(figure)
    (output / "zero_event_diagnostics.json").write_text(
        json.dumps({"channels": diagnostics, "analysis_failures": failures}, indent=2) + "\n",
        encoding="utf-8",
    )
    return plot_path


def dark_count_summary(root: Path) -> Path:
    output = root / "summary"
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for point_dir in sorted(root.glob("point_*")):
        metadata_path = point_dir / "point_metadata.json"
        if not metadata_path.exists():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for analysis_dir in sorted((point_dir / "analysis").glob("*")):
            summary_path = analysis_dir / "point_summary.json"
            if not summary_path.exists():
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            status_path = point_dir / "raw" / analysis_dir.name / "event_status.csv"
            observed_rate = math.nan
            if status_path.exists():
                status = pd.read_csv(status_path)
                if len(status) > 1 and float(status["elapsed_s"].iloc[-1]) > 0:
                    observed_rate = len(status) / float(status["elapsed_s"].iloc[-1])
            rows.append(
                {
                    "overvoltage_V": metadata["overvoltage_V"],
                    "sipm": summary["sipm"],
                    "bias_V": summary["bias_v"],
                    "accepted_events": summary["accepted_events"],
                    "observed_trigger_rate_Hz": observed_rate,
                    "height_gap_mV": summary["one_pe_spacing_mV"],
                    "height_gap_unc_mV": summary["one_pe_spacing_unc_mV"],
                    "area_gap_mV_ns": summary["one_pe_area_spacing_mV_ns"],
                    "area_gap_unc_mV_ns": summary["one_pe_area_spacing_unc_mV_ns"],
                    "height_fit_pass": summary["quality_pass"],
                    "area_fit_pass": summary["area_quality_pass"],
                }
            )

    if not rows:
        raise RuntimeError("No completed dark-count analyses were found")
    table = pd.DataFrame(rows).sort_values(["sipm", "overvoltage_V"])
    table.to_csv(output / "dark_count_summary.csv", index=False)

    configure_style()
    figure, axes = plt.subplots(1, 3, figsize=(16, 5.4))
    for sipm, selected in table.groupby("sipm"):
        color = COLORS.get(sipm, None)
        axes[0].plot(
            selected["overvoltage_V"], selected["observed_trigger_rate_Hz"], "o-", color=color, label=sipm
        )
        axes[1].errorbar(
            selected["overvoltage_V"],
            selected["height_gap_mV"],
            yerr=selected["height_gap_unc_mV"],
            fmt="o-",
            capsize=3,
            color=color,
            label=sipm,
        )
        axes[2].errorbar(
            selected["overvoltage_V"],
            selected["area_gap_mV_ns"],
            yerr=selected["area_gap_unc_mV_ns"],
            fmt="o-",
            capsize=3,
            color=color,
            label=sipm,
        )
    axes[0].set_ylabel("Observed acquisition trigger rate (Hz)")
    axes[1].set_ylabel("1 p.e. peak-height spacing (mV)")
    axes[2].set_ylabel("1 p.e. pulse-area spacing (mV ns)")
    for axis in axes:
        axis.set_xlabel("SiPM overvoltage (V)")
        axis.legend()
    figure.suptitle("Dark-pulse response versus overvoltage", fontsize=16)
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    plot_path = output / "dark_count_scan.png"
    figure.savefig(plot_path)
    plt.close(figure)
    return plot_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", choices=("zero_event", "dark_count"))
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.workflow == "zero_event":
        print(zero_event_summary(args.root))
    else:
        print(dark_count_summary(args.root))


if __name__ == "__main__":
    main()
