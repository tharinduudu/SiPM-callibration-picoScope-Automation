#!/usr/bin/env python3
"""Extract one-photoelectron peak spacing from one waveform capture point."""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import curve_fit
from scipy.signal import find_peaks


def read_waveform(path: Path) -> np.ndarray:
    return np.loadtxt(path, delimiter=",", skiprows=3, dtype=float)


def robust_baseline(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    sigma = 1.4826 * float(np.median(np.abs(values - median)))
    if not np.isfinite(sigma) or sigma <= 0:
        sigma = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    keep = np.abs(values - median) <= max(4.0 * sigma, 1e-9)
    clipped = values[keep] if np.any(keep) else values
    baseline = float(np.mean(clipped))
    noise = float(np.std(clipped, ddof=1)) if len(clipped) > 1 else sigma
    return baseline, noise


def quadratic_peak(values: np.ndarray, index: int) -> float:
    """Estimate the local maximum between samples with a three-point parabola."""
    if index <= 0 or index >= len(values) - 1:
        return float(values[index])
    previous, center, following = values[index - 1 : index + 2]
    quadratic = 0.5 * (previous + following - 2.0 * center)
    linear = 0.5 * (following - previous)
    if quadratic >= 0:
        return float(center)
    offset = -linear / (2.0 * quadratic)
    if abs(offset) > 1.0:
        return float(center)
    return float(center - linear**2 / (4.0 * quadratic))


def fd_bin_count(values: np.ndarray, minimum: int = 50, maximum: int = 220) -> int:
    q25, q75 = np.percentile(values, [25, 75])
    width = 2.0 * (q75 - q25) / np.cbrt(len(values))
    span = float(np.max(values) - np.min(values))
    if not np.isfinite(width) or width <= 0:
        width = span / 80.0 if span > 0 else 1.0
    return int(np.clip(np.ceil(span / width), minimum, maximum))


def gaussian_linear(x: np.ndarray, amplitude: float, center: float, sigma: float, offset: float, slope: float) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset + slope * (x - center)


def refine_peaks(centers: np.ndarray, counts: np.ndarray, candidate_indexes: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    bin_width = float(np.mean(np.diff(centers)))
    for index in candidate_indexes:
        center0 = float(centers[index])
        half_width = max(4.0 * bin_width, 7.0)
        selection = np.abs(centers - center0) <= half_width
        x = centers[selection]
        y = counts[selection]
        if len(x) < 6:
            continue
        floor = float(np.percentile(y, 15))
        initial = [max(float(counts[index]) - floor, 1.0), center0, max(1.5 * bin_width, 1.0), floor, 0.0]
        lower = [0.0, center0 - 0.5 * half_width, 0.3, 0.0, -np.inf]
        upper = [np.inf, center0 + 0.5 * half_width, half_width, np.inf, np.inf]
        try:
            parameters, covariance = curve_fit(
                gaussian_linear,
                x,
                y,
                p0=initial,
                bounds=(lower, upper),
                maxfev=20000,
            )
            errors = np.sqrt(np.diag(covariance))
            center_uncertainty = float(errors[1])
            if not np.isfinite(center_uncertainty) or center_uncertainty > half_width:
                raise ValueError("Gaussian peak-center uncertainty is not constrained")
            rows.append(
                {
                    "center_mV": float(parameters[1]),
                    "center_unc_mV": max(center_uncertainty, bin_width / np.sqrt(12.0)),
                    "sigma_mV": abs(float(parameters[2])),
                    "amplitude": float(parameters[0]),
                }
            )
        except Exception:
            rows.append(
                {
                    "center_mV": center0,
                    "center_unc_mV": bin_width / np.sqrt(12.0),
                    "sigma_mV": np.nan,
                    "amplitude": float(counts[index]),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["center_mV", "center_unc_mV", "sigma_mV", "amplitude"])
    return pd.DataFrame(rows).sort_values("center_mV").drop_duplicates("center_mV").reset_index(drop=True)


def fit_sequence(
    values: np.ndarray,
    uncertainties: np.ndarray,
    minimum_spacing: float = 6.0,
    maximum_spacing: float = 130.0,
) -> tuple[list[int], float, float, float]:
    if len(values) < 2:
        return [], np.nan, np.nan, np.nan
    if len(values) == 2:
        spacing = float(values[1] - values[0])
        if not minimum_spacing <= spacing <= maximum_spacing:
            return [], np.nan, np.nan, np.nan
        finite_positive = uncertainties[np.isfinite(uncertainties) & (uncertainties > 0)]
        fallback = float(np.median(finite_positive)) if len(finite_positive) else 1.0
        errors = np.where(
            np.isfinite(uncertainties) & (uncertainties > 0), uncertainties, fallback
        )
        return [0, 1], spacing, float(np.hypot(errors[0], errors[1])), 1.0
    best: tuple[float, list[int], float, float, float] | None = None
    for count in range(min(6, len(values)), 2, -1):
        for selected_tuple in combinations(range(len(values)), count):
            selected = list(selected_tuple)
            y = values[selected]
            yerr = uncertainties[selected]
            finite_positive = yerr[np.isfinite(yerr) & (yerr > 0)]
            fallback = float(np.median(finite_positive)) if len(finite_positive) else 1.0
            yerr = np.where(np.isfinite(yerr) & (yerr > 0), yerr, fallback)
            indexes = np.arange(len(y), dtype=float)
            design = np.column_stack([indexes, np.ones(len(indexes))])
            inverse_variance = 1.0 / np.square(yerr)
            normal = design.T @ (inverse_variance[:, None] * design)
            try:
                covariance = np.linalg.inv(normal)
            except np.linalg.LinAlgError:
                continue
            slope, intercept = covariance @ (design.T @ (inverse_variance * y))
            if not minimum_spacing <= slope <= maximum_spacing:
                continue
            residuals = y - (intercept + slope * indexes)
            residual_rms = float(np.sqrt(np.mean(residuals**2)))
            score = residual_rms / slope - 0.01 * (count - 3)
            if best is None or score < best[0]:
                ss_res = float(np.sum(residuals**2))
                ss_tot = float(np.sum((y - np.mean(y)) ** 2))
                r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
                reduced_chi_squared = float(np.sum(np.square(residuals / yerr)) / (count - 2))
                covariance *= max(1.0, reduced_chi_squared)
                slope_unc = float(np.sqrt(max(covariance[0, 0], 0.0)))
                best = (score, selected, float(slope), slope_unc, r_squared)
    if best is None:
        return [], np.nan, np.nan, np.nan
    return best[1], best[2], best[3], best[4]


def sequence_quality(peaks: pd.DataFrame, selected: list[int], spacing: float, r_squared: float) -> tuple[bool, float]:
    if len(selected) < 2 or not np.isfinite(spacing):
        return False, np.nan
    selected_widths = peaks.loc[selected, "sigma_mV"].to_numpy(float)
    finite_widths = selected_widths[np.isfinite(selected_widths) & (selected_widths > 0)]
    if len(finite_widths) >= 2:
        resolution = float(spacing / np.hypot(finite_widths[0], finite_widths[1]))
    elif len(finite_widths) == 1:
        resolution = float(spacing / (np.sqrt(2.0) * finite_widths[0]))
    else:
        resolution = np.nan
    if len(selected) == 2:
        return bool(spacing >= 12.0 and (not np.isfinite(resolution) or resolution >= 1.5)), resolution
    return bool(np.isfinite(r_squared) and r_squared >= 0.995), resolution


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bias-v", type=float, required=True)
    parser.add_argument("--sipm", required=True)
    parser.add_argument("--detector-channel", type=int, required=True)
    parser.add_argument("--scope-channel", choices=["A", "B", "C", "D"], required=True)
    parser.add_argument("--color", default="C0")
    parser.add_argument("--integration-mode", choices=["fixed", "peak-aligned"], default="fixed")
    parser.add_argument("--peak-search-start-ns", type=float, default=-20.0)
    parser.add_argument("--peak-search-stop-ns", type=float, default=120.0)
    parser.add_argument("--integration-start-ns", type=float, default=-5.0)
    parser.add_argument("--integration-stop-ns", type=float, default=250.0)
    parser.add_argument("--relative-integration-start-ns", type=float, default=-20.0)
    parser.add_argument("--relative-integration-stop-ns", type=float, default=200.0)
    parser.add_argument("--minimum-spacing", type=float, default=6.0)
    parser.add_argument("--maximum-spacing", type=float, default=130.0)
    args = parser.parse_args()

    files = sorted(args.run_dir.glob("event_[0-9]*.csv"))
    if not files:
        raise FileNotFoundError(f"No waveform CSV files in {args.run_dir}")
    args.output.mkdir(parents=True, exist_ok=True)
    signal_column = {"A": 1, "B": 2, "C": 3, "D": 4}[args.scope_channel]
    overflow_by_event: dict[int, bool] = {}
    status_path = args.run_dir / "event_status.csv"
    if status_path.exists():
        status = pd.read_csv(status_path)
        overflow_by_event = {
            int(row.event): bool(row.overflow) for row in status.itertuples(index=False)
        }
    measurements: list[dict[str, object]] = []

    for event, path in enumerate(files):
        try:
            waveform = read_waveform(path)
            time_ns = waveform[:, 0]
            event_signal_column = 1 if waveform.shape[1] == 2 else signal_column
            if event_signal_column >= waveform.shape[1]:
                raise ValueError(f"scope channel {args.scope_channel} is absent from {path.name}")
            signal_mv = waveform[:, event_signal_column]
            pretrigger = time_ns < -30.0
            search = (time_ns >= args.peak_search_start_ns) & (
                time_ns <= args.peak_search_stop_ns
            )
            if np.sum(pretrigger) < 5 or not np.any(search):
                raise ValueError("waveform does not contain the required pretrigger and peak-search regions")
            baseline, noise = robust_baseline(signal_mv[pretrigger])
            corrected = signal_mv - baseline
            search_values = corrected[search]
            search_times = time_ns[search]
            peak_index = int(np.argmax(search_values))
            sampled_peak = float(search_values[peak_index])
            peak = quadratic_peak(search_values, peak_index)
            peak_time = float(search_times[peak_index])
            if args.integration_mode == "peak-aligned":
                integration_start = peak_time + args.relative_integration_start_ns
                integration_stop = peak_time + args.relative_integration_stop_ns
            else:
                integration_start = args.integration_start_ns
                integration_stop = args.integration_stop_ns
            integration = (time_ns >= integration_start) & (time_ns <= integration_stop)
            if not np.any(integration):
                raise ValueError("waveform does not contain the requested integration region")
            pulse_area = float(np.trapezoid(corrected[integration], time_ns[integration]))
            overflow = overflow_by_event.get(event, False)
            measurements.append(
                {
                    "event": event,
                    "file": path.name,
                    "baseline_mV": baseline,
                    "baseline_noise_mV": noise,
                    "sampled_peak_height_mV": sampled_peak,
                    "peak_height_mV": peak,
                    "peak_time_ns": peak_time,
                    "pulse_area_mV_ns": pulse_area,
                    "overflow": overflow,
                    "accepted": bool(
                        not overflow
                        and peak > max(5.0 * noise, 5.0)
                        and args.peak_search_start_ns <= peak_time < args.peak_search_stop_ns
                    ),
                }
            )
        except Exception as exc:
            measurements.append({"event": event, "file": path.name, "accepted": False, "error": str(exc)})

    table = pd.DataFrame(measurements)
    table.to_csv(args.output / "pulse_measurements.csv", index=False)
    accepted = table.loc[table["accepted"].fillna(False), "peak_height_mV"].dropna().to_numpy(float)
    if len(accepted) < 50:
        raise RuntimeError(f"Only {len(accepted)} accepted events; at least 50 are required")

    low, high = np.percentile(accepted, [0.2, 99.8])
    spectrum = accepted[(accepted >= low) & (accepted <= high)]
    core_bins = fd_bin_count(spectrum)
    core_bin_width = (high - low) / core_bins
    histogram_margin = max(8.0, 4.0 * core_bin_width)
    histogram_bins = int(np.ceil((high - low + 2.0 * histogram_margin) / core_bin_width))
    counts, edges = np.histogram(
        spectrum,
        bins=histogram_bins,
        range=(low - histogram_margin, high + histogram_margin),
    )
    centers = 0.5 * (edges[:-1] + edges[1:])
    bin_width = float(np.mean(np.diff(centers)))
    # Smooth over one source-side ADC level to locate the physical p.e. envelopes
    # rather than the narrow 8-bit quantization spikes within each envelope.
    smoothing_sigma_bins = max(1.0, 4.0 / bin_width)
    smoothed = gaussian_filter1d(counts.astype(float), sigma=smoothing_sigma_bins)
    candidate_indexes, _ = find_peaks(
        smoothed,
        prominence=max(4.0, 0.018 * float(np.max(smoothed))),
        distance=max(2, int(round(12.0 / bin_width))),
    )
    peaks = refine_peaks(centers, counts, candidate_indexes)
    selected, spacing, spacing_unc, sequence_r_squared = fit_sequence(
        peaks["center_mV"].to_numpy(float),
        peaks["center_unc_mV"].to_numpy(float),
        args.minimum_spacing,
        args.maximum_spacing,
    )
    peaks["selected"] = False
    peaks["pe_index"] = np.nan
    for pe_index, row_index in enumerate(selected, start=1):
        peaks.loc[row_index, "selected"] = True
        peaks.loc[row_index, "pe_index"] = pe_index
    peaks.to_csv(args.output / "peak_fits.csv", index=False)

    selected_centers = peaks.loc[peaks["selected"], "center_mV"].to_list()
    quality_pass, peak_resolution = sequence_quality(
        peaks, selected, spacing, sequence_r_squared
    )

    area_scale = 50.0
    accepted_areas = table.loc[
        table["accepted"].fillna(False), "pulse_area_mV_ns"
    ].dropna().to_numpy(float)
    accepted_areas = accepted_areas[accepted_areas > 0]
    scaled_areas = accepted_areas / area_scale
    area_low, area_high = np.percentile(scaled_areas, [0.2, 99.5])
    area_spectrum = scaled_areas[(scaled_areas >= area_low) & (scaled_areas <= area_high)]
    area_core_bins = fd_bin_count(area_spectrum)
    area_core_bin_width = (area_high - area_low) / area_core_bins
    area_margin = max(8.0, 4.0 * area_core_bin_width)
    area_bins = int(
        np.ceil((area_high - area_low + 2.0 * area_margin) / area_core_bin_width)
    )
    area_counts, area_edges = np.histogram(
        area_spectrum,
        bins=area_bins,
        range=(area_low - area_margin, area_high + area_margin),
    )
    area_centers = 0.5 * (area_edges[:-1] + area_edges[1:])
    area_bin_width = float(np.mean(np.diff(area_centers)))
    area_smoothing_sigma_bins = max(1.0, 4.0 / area_bin_width)
    area_smoothed = gaussian_filter1d(
        area_counts.astype(float), sigma=area_smoothing_sigma_bins
    )
    area_candidate_indexes, _ = find_peaks(
        area_smoothed,
        prominence=max(4.0, 0.018 * float(np.max(area_smoothed))),
        distance=max(2, int(round(12.0 / area_bin_width))),
    )
    area_peaks = refine_peaks(area_centers, area_counts, area_candidate_indexes)
    area_selected, area_spacing_scaled, area_spacing_unc_scaled, area_r_squared = fit_sequence(
        area_peaks["center_mV"].to_numpy(float),
        area_peaks["center_unc_mV"].to_numpy(float),
        args.minimum_spacing,
        args.maximum_spacing,
    )
    area_peaks["selected"] = False
    area_peaks["pe_index"] = np.nan
    for pe_index, row_index in enumerate(area_selected, start=1):
        area_peaks.loc[row_index, "selected"] = True
        area_peaks.loc[row_index, "pe_index"] = pe_index
    area_peaks["center_mV_ns"] = area_peaks["center_mV"] * area_scale
    area_peaks["center_unc_mV_ns"] = area_peaks["center_unc_mV"] * area_scale
    area_peaks.to_csv(args.output / "area_peak_fits.csv", index=False)
    area_spacing = area_spacing_scaled * area_scale
    area_spacing_unc = area_spacing_unc_scaled * area_scale
    area_selected_centers = area_peaks.loc[area_peaks["selected"], "center_mV_ns"].to_list()
    area_quality_pass, area_peak_resolution = sequence_quality(
        area_peaks, area_selected, area_spacing_scaled, area_r_squared
    )
    summary = {
        "sipm": args.sipm,
        "detector_channel": args.detector_channel,
        "scope_channel": args.scope_channel,
        "bias_v": args.bias_v,
        "integration_mode": args.integration_mode,
        "peak_search_start_ns": args.peak_search_start_ns,
        "peak_search_stop_ns": args.peak_search_stop_ns,
        "integration_start_ns": args.integration_start_ns,
        "integration_stop_ns": args.integration_stop_ns,
        "relative_integration_start_ns": args.relative_integration_start_ns,
        "relative_integration_stop_ns": args.relative_integration_stop_ns,
        "event_files": len(files),
        "accepted_events": int(len(accepted)),
        "overflow_events_rejected": int(table.get("overflow", pd.Series(dtype=bool)).fillna(False).sum()),
        "histogram_bins": int(len(counts)),
        "histogram_bin_width_mV": bin_width,
        "gaussian_smoothing_sigma_bins": smoothing_sigma_bins,
        "candidate_peak_count": int(len(candidate_indexes)),
        "refined_peak_count": int(len(peaks)),
        "selected_peak_count": int(len(selected)),
        "selected_peak_centers_mV": selected_centers,
        "one_pe_spacing_mV": spacing,
        "one_pe_spacing_unc_mV": spacing_unc,
        "sequence_r_squared": sequence_r_squared,
        "two_peak_resolution_sigma": peak_resolution,
        "quality_pass": quality_pass,
        "area_selected_peak_count": int(len(area_selected)),
        "area_selected_peak_centers_mV_ns": area_selected_centers,
        "one_pe_area_spacing_mV_ns": area_spacing,
        "one_pe_area_spacing_unc_mV_ns": area_spacing_unc,
        "area_sequence_r_squared": area_r_squared,
        "area_two_peak_resolution_sigma": area_peak_resolution,
        "area_quality_pass": area_quality_pass,
    }
    (args.output / "point_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    figure, axis = plt.subplots(figsize=(10.5, 6.2), dpi=170)
    axis.step(centers, counts, where="mid", color=args.color, alpha=0.72, label="Pulse-height histogram")
    axis.plot(centers, smoothed, color="black", linewidth=1.5, label="Gaussian-smoothed histogram")
    for _, peak in peaks.iterrows():
        axis.axvline(
            peak["center_mV"],
            color="tab:red" if peak["selected"] else "0.6",
            linewidth=1.4 if peak["selected"] else 0.8,
            alpha=0.9 if peak["selected"] else 0.5,
        )
    axis.set_title(f"{args.sipm}: p.e. peak-height spectrum at {args.bias_v:.2f} V")
    axis.set_xlabel(f"Pulse height on PicoScope channel {args.scope_channel} (mV)")
    axis.set_ylabel("Events per bin")
    axis.grid(True, alpha=0.25)
    spacing_text = f"1 p.e. spacing = {spacing:.2f} ± {spacing_unc:.2f} mV" if np.isfinite(spacing_unc) else f"1 p.e. spacing = {spacing:.2f} mV"
    axis.legend(title=spacing_text)
    figure.tight_layout()
    figure.savefig(args.output / "pulse_height_peaks.png")
    plt.close(figure)

    area_figure, area_axis = plt.subplots(figsize=(10.5, 6.2), dpi=170)
    area_axis.step(
        area_centers * area_scale,
        area_counts,
        where="mid",
        color=args.color,
        alpha=0.72,
        label="Pulse-area histogram",
    )
    area_axis.plot(
        area_centers * area_scale,
        area_smoothed,
        color="black",
        linewidth=1.5,
        label="Gaussian-smoothed histogram",
    )
    for _, peak in area_peaks.iterrows():
        area_axis.axvline(
            peak["center_mV_ns"],
            color="tab:red" if peak["selected"] else "0.6",
            linewidth=1.4 if peak["selected"] else 0.8,
            alpha=0.9 if peak["selected"] else 0.5,
        )
    area_axis.set_title(f"{args.sipm}: p.e. pulse-area spectrum at {args.bias_v:.2f} V")
    area_axis.set_xlabel("Baseline-subtracted pulse area (mV ns)")
    area_axis.set_ylabel("Events per bin")
    area_axis.grid(True, alpha=0.25)
    area_text = (
        f"1 p.e. area spacing = {area_spacing:.0f} ± {area_spacing_unc:.0f} mV ns"
        if np.isfinite(area_spacing_unc)
        else f"1 p.e. area spacing = {area_spacing:.0f} mV ns"
    )
    area_axis.legend(title=area_text)
    area_figure.tight_layout()
    area_figure.savefig(args.output / "pulse_area_peaks.png")
    plt.close(area_figure)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
