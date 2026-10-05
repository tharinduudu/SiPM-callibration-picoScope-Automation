#!/usr/bin/env python3
"""Measure reference-triggered scintillator miss probability from four-channel waveforms."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analyze_point import quadratic_peak, robust_baseline


CHANNEL_COLUMN = {"A": 1, "B": 2, "C": 3, "D": 4}
CHANNEL_OVERFLOW_BIT = {"A": 0, "B": 1, "C": 2, "D": 3}
COLORS = {"A": "#1f77b4", "B": "#ff7f0e", "C": "#2ca02c", "D": "#d62728"}


@dataclass(frozen=True)
class Dut:
    channel: str
    label: str
    charge_gap: float
    height_gap: float


def parse_dut(text: str) -> Dut:
    try:
        channel, label, charge_gap, height_gap = text.split(":", 3)
        channel = channel.upper()
        if channel not in CHANNEL_COLUMN:
            raise ValueError(channel)
        return Dut(channel, label, float(charge_gap), float(height_gap))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "DUT must be CHANNEL:LABEL:CHARGE_GAP_MV_NS:HEIGHT_GAP_MV"
        ) from exc


def parse_thresholds(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    try:
        for item in text.split(","):
            channel, value = item.split("=", 1)
            values[channel.strip().upper()] = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("thresholds must look like C=100,D=100") from exc
    return values


def read_waveform(path: Path) -> np.ndarray:
    waveform = np.loadtxt(path, delimiter=",", skiprows=3, dtype=float)
    if waveform.ndim != 2 or waveform.shape[1] < 5:
        raise ValueError(f"{path} is not a four-channel waveform")
    return waveform


def peak(time_ns: np.ndarray, signal: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    values = signal[mask]
    times = time_ns[mask]
    index = int(np.argmax(values))
    return quadratic_peak(values, index), float(times[index])


def fd_bins(values: np.ndarray, minimum: int = 60, maximum: int = 240) -> int:
    q25, q75 = np.percentile(values, [25, 75])
    width = 2.0 * (q75 - q25) / np.cbrt(len(values))
    if not np.isfinite(width) or width <= 0:
        return minimum
    return int(np.clip(np.ceil(np.ptp(values) / width), minimum, maximum))


def interval_summary(signal_zero: int, dark_zero: int, total: int, seed: int) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    signal_draw = rng.beta(signal_zero + 0.5, total - signal_zero + 0.5, 200000)
    dark_draw = rng.beta(dark_zero + 0.5, total - dark_zero + 0.5, 200000)
    scintillator_zero = np.clip(signal_draw / dark_draw, 1e-12, 1.0)
    efficiency = 1.0 - scintillator_zero
    occupancy = -np.log(scintillator_zero)
    point_signal = signal_zero / total
    point_dark = dark_zero / total
    point_scintillator = min(1.0, point_signal / point_dark) if point_dark > 0 else math.nan
    point_efficiency = 1.0 - point_scintillator if np.isfinite(point_scintillator) else math.nan
    point_occupancy = -math.log(point_scintillator) if point_scintillator > 0 else math.inf

    def quantiles(values: np.ndarray) -> tuple[float, float, float, float, float]:
        return tuple(float(value) for value in np.quantile(values, [0.025, 0.16, 0.5, 0.84, 0.975]))

    eff = quantiles(efficiency)
    occ = quantiles(occupancy)
    p0 = quantiles(scintillator_zero)
    return {
        "signal_zero_fraction": point_signal,
        "dark_zero_fraction": point_dark,
        "scintillator_zero_fraction": point_scintillator,
        "efficiency": point_efficiency,
        "efficiency_median": eff[2],
        "efficiency_68_low": eff[1],
        "efficiency_68_high": eff[3],
        "efficiency_95_low": eff[0],
        "efficiency_95_high": eff[4],
        "zero_equivalent_occupancy": point_occupancy,
        "occupancy_median": occ[2],
        "occupancy_68_low": occ[1],
        "occupancy_68_high": occ[3],
        "scintillator_zero_95_low": p0[0],
        "scintillator_zero_95_high": p0[4],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-channels", default="C,D")
    parser.add_argument(
        "--reference-thresholds-mv", type=parse_thresholds, default=parse_thresholds("C=100,D=100")
    )
    parser.add_argument("--reference-coincidence-ns", type=float, default=30.0)
    parser.add_argument(
        "--minimum-reference-events",
        type=int,
        default=100,
        help="minimum selected reference coincidences required for analysis",
    )
    parser.add_argument("--reference-search-start-ns", type=float, default=-40.0)
    parser.add_argument("--reference-search-stop-ns", type=float, default=140.0)
    parser.add_argument(
        "--dut",
        action="append",
        type=parse_dut,
        default=None,
        help="repeat for each DUT: CHANNEL:LABEL:CHARGE_GAP_MV_NS:HEIGHT_GAP_MV",
    )
    parser.add_argument("--baseline-stop-ns", type=float, default=-600.0)
    parser.add_argument("--dark-gate-start-ns", type=float, default=-520.0)
    parser.add_argument("--dark-gate-stop-ns", type=float, default=-300.0)
    parser.add_argument("--signal-relative-start-ns", type=float, default=-20.0)
    parser.add_argument("--signal-relative-stop-ns", type=float, default=200.0)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()

    references = tuple(channel.strip().upper() for channel in args.reference_channels.split(","))
    if len(references) != 2 or any(channel not in CHANNEL_COLUMN for channel in references):
        parser.error("--reference-channels must contain exactly two channels")
    if any(channel not in args.reference_thresholds_mv for channel in references):
        parser.error("both reference channels need thresholds")
    duts = args.dut or [
        Dut("A", "SIPM2", 1651.8, 31.61),
        Dut("B", "SIPM1", 1595.4, 32.36),
    ]
    if any(dut.channel in references for dut in duts):
        parser.error("DUT and reference channels must be different")
    gate_width = args.signal_relative_stop_ns - args.signal_relative_start_ns
    dark_width = args.dark_gate_stop_ns - args.dark_gate_start_ns
    if gate_width <= 0 or not math.isclose(gate_width, dark_width, abs_tol=1e-9):
        parser.error("signal and dark gates must have the same positive width")

    files = sorted(args.run_dir.glob("event_[0-9]*.csv"))
    if not files:
        raise FileNotFoundError(f"No waveform CSV files in {args.run_dir}")
    args.output.mkdir(parents=True, exist_ok=True)
    overflow_by_event: dict[int, int] = {}
    status_path = args.run_dir / "event_status.csv"
    if status_path.exists():
        status = pd.read_csv(status_path)
        overflow_column = "overflow_mask" if "overflow_mask" in status else "overflow"
        overflow_by_event = {
            int(row.event): int(getattr(row, overflow_column)) for row in status.itertuples(index=False)
        }

    first_pass: list[dict[str, object]] = []
    for event, path in enumerate(files):
        waveform = read_waveform(path)
        time_ns = waveform[:, 0]
        baseline_mask = time_ns < args.baseline_stop_ns
        reference_mask = (time_ns >= args.reference_search_start_ns) & (
            time_ns <= args.reference_search_stop_ns
        )
        if np.sum(baseline_mask) < 10 or not np.any(reference_mask):
            raise ValueError("waveform does not cover the requested baseline/reference windows")
        row: dict[str, object] = {
            "event": event,
            "file": path.name,
            "overflow_mask": overflow_by_event.get(event, 0),
        }
        corrected: dict[str, np.ndarray] = {}
        noises: dict[str, float] = {}
        for channel in set(references) | {dut.channel for dut in duts}:
            signal = waveform[:, CHANNEL_COLUMN[channel]]
            baseline, noise = robust_baseline(signal[baseline_mask])
            corrected[channel] = signal - baseline
            noises[channel] = noise
            row[f"{channel}_baseline_mV"] = baseline
            row[f"{channel}_noise_mV"] = noise
        for channel in references:
            height, peak_time = peak(time_ns, corrected[channel], reference_mask)
            row[f"{channel}_reference_height_mV"] = height
            row[f"{channel}_reference_time_ns"] = peak_time
        for dut in duts:
            height, peak_time = peak(time_ns, corrected[dut.channel], reference_mask)
            row[f"{dut.channel}_candidate_height_mV"] = height
            row[f"{dut.channel}_candidate_time_ns"] = peak_time
        reference_overflow = any(
            int(row["overflow_mask"]) & (1 << CHANNEL_OVERFLOW_BIT[channel])
            for channel in references
        )
        row["reference_overflow"] = reference_overflow
        reference_pass = (
            not reference_overflow
            and all(
                row[f"{channel}_reference_height_mV"] >= args.reference_thresholds_mv[channel]
                for channel in references
            )
            and abs(
                row[f"{references[0]}_reference_time_ns"]
                - row[f"{references[1]}_reference_time_ns"]
            )
            <= args.reference_coincidence_ns
        )
        row["reference_selected"] = reference_pass
        first_pass.append(row)

    table = pd.DataFrame(first_pass)
    table.to_csv(args.output / "reference_candidate_measurements.csv", index=False)
    selected = table["reference_selected"].fillna(False)
    if selected.sum() < args.minimum_reference_events:
        raise RuntimeError(
            f"Only {int(selected.sum())} reference coincidences; "
            f"at least {args.minimum_reference_events} are required"
        )

    expected_times: dict[str, float] = {}
    for dut in duts:
        noise = table.loc[selected, f"{dut.channel}_noise_mV"].to_numpy(float)
        height = table.loc[selected, f"{dut.channel}_candidate_height_mV"].to_numpy(float)
        time_values = table.loc[selected, f"{dut.channel}_candidate_time_ns"].to_numpy(float)
        clear = height > np.maximum(8.0 * noise, 0.5 * dut.height_gap)
        if np.sum(clear) < 30:
            raise RuntimeError(f"Only {int(np.sum(clear))} clear pulses to time-align {dut.label}")
        expected_times[dut.channel] = float(np.median(time_values[clear]))

    event_rows: list[dict[str, object]] = []
    for event, path in enumerate(files):
        if not bool(table.loc[event, "reference_selected"]):
            continue
        waveform = read_waveform(path)
        time_ns = waveform[:, 0]
        baseline_mask = time_ns < args.baseline_stop_ns
        dark_mask = (time_ns >= args.dark_gate_start_ns) & (time_ns <= args.dark_gate_stop_ns)
        row = table.loc[event].to_dict()
        for dut in duts:
            signal = waveform[:, CHANNEL_COLUMN[dut.channel]]
            baseline, _ = robust_baseline(signal[baseline_mask])
            corrected = signal - baseline
            center = expected_times[dut.channel]
            signal_mask = (
                time_ns >= center + args.signal_relative_start_ns
            ) & (time_ns <= center + args.signal_relative_stop_ns)
            row[f"{dut.channel}_signal_charge_mV_ns"] = float(
                np.trapezoid(corrected[signal_mask], time_ns[signal_mask])
            )
            row[f"{dut.channel}_dark_charge_mV_ns"] = float(
                np.trapezoid(corrected[dark_mask], time_ns[dark_mask])
            )
        event_rows.append(row)

    events = pd.DataFrame(event_rows)
    events.to_csv(args.output / "selected_event_measurements.csv", index=False)
    summaries: list[dict[str, object]] = []
    for index, dut in enumerate(duts):
        signal_charge = events[f"{dut.channel}_signal_charge_mV_ns"].to_numpy(float)
        dark_charge = events[f"{dut.channel}_dark_charge_mV_ns"].to_numpy(float)
        pedestal_center = float(np.median(dark_charge))
        zero_threshold = pedestal_center + 0.5 * dut.charge_gap
        signal_zero = int(np.sum(signal_charge < zero_threshold))
        dark_zero = int(np.sum(dark_charge < zero_threshold))
        interval = interval_summary(signal_zero, dark_zero, len(events), args.seed + index)
        summaries.append(
            {
                "label": dut.label,
                "channel": dut.channel,
                "reference_selected_events": int(len(events)),
                "expected_pulse_time_ns": expected_times[dut.channel],
                "charge_gap_mV_ns": dut.charge_gap,
                "pedestal_center_mV_ns": pedestal_center,
                "zero_threshold_mV_ns": zero_threshold,
                "signal_zero_events": signal_zero,
                "dark_zero_events": dark_zero,
                **interval,
            }
        )

    summary = pd.DataFrame(summaries)
    summary.to_csv(args.output / "scintillator_zero_summary.csv", index=False)
    (args.output / "scintillator_zero_summary.json").write_text(
        json.dumps(summaries, indent=2) + "\n", encoding="utf-8"
    )

    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "figure.dpi": 170,
            "savefig.dpi": 230,
            "savefig.bbox": "tight",
        }
    )
    figure, axes = plt.subplots(2, 2, figsize=(14.0, 9.0))
    ref0, ref1 = references
    rejected = ~table["reference_selected"].fillna(False)
    axes[0, 0].scatter(
        table.loc[rejected, f"{ref0}_reference_height_mV"],
        table.loc[rejected, f"{ref1}_reference_height_mV"],
        s=8,
        alpha=0.18,
        color="0.55",
        label="rejected trigger",
    )
    axes[0, 0].scatter(
        table.loc[selected, f"{ref0}_reference_height_mV"],
        table.loc[selected, f"{ref1}_reference_height_mV"],
        s=9,
        alpha=0.35,
        color="#2ca02c",
        label="reference coincidence",
    )
    axes[0, 0].axvline(args.reference_thresholds_mv[ref0], color=COLORS[ref0], linestyle="--")
    axes[0, 0].axhline(args.reference_thresholds_mv[ref1], color=COLORS[ref1], linestyle="--")
    axes[0, 0].set_xlabel(f"Reference {ref0} peak height (mV)")
    axes[0, 0].set_ylabel(f"Reference {ref1} peak height (mV)")
    axes[0, 0].set_title("Independent muon-reference selection")
    axes[0, 0].legend()

    time_difference = (
        table[f"{ref0}_reference_time_ns"] - table[f"{ref1}_reference_time_ns"]
    ).to_numpy(float)
    shown = time_difference[np.abs(time_difference) <= 3.0 * args.reference_coincidence_ns]
    axes[0, 1].hist(shown, bins=70, histtype="stepfilled", alpha=0.45, color="#2ca02c")
    axes[0, 1].axvline(-args.reference_coincidence_ns, color="0.25", linestyle="--")
    axes[0, 1].axvline(args.reference_coincidence_ns, color="0.25", linestyle="--")
    axes[0, 1].set_xlabel(f"{ref0} - {ref1} peak time (ns)")
    axes[0, 1].set_ylabel("Events per bin")
    axes[0, 1].set_title(f"Reference timing: {int(selected.sum()):,} selected")

    for axis, dut, result in zip(axes[1], duts, summaries):
        efficiency_uncertainty = 0.5 * (
            result["efficiency_68_high"] - result["efficiency_68_low"]
        )
        signal_charge = events[f"{dut.channel}_signal_charge_mV_ns"].to_numpy(float)
        dark_charge = events[f"{dut.channel}_dark_charge_mV_ns"].to_numpy(float)
        combined = np.concatenate([signal_charge, dark_charge])
        low, high = np.percentile(combined, [0.1, 99.8])
        shown_combined = combined[(combined >= low) & (combined <= high)]
        edges = np.linspace(low, high, fd_bins(shown_combined) + 1)
        axis.hist(
            dark_charge,
            bins=edges,
            histtype="stepfilled",
            alpha=0.30,
            color="0.45",
            label="off-time dark gate",
        )
        axis.hist(
            signal_charge,
            bins=edges,
            histtype="step",
            linewidth=1.35,
            color=COLORS[dut.channel],
            label="reference-coincident signal gate",
        )
        axis.axvline(result["zero_threshold_mV_ns"], color="#c62828", linestyle="--", label="0/1 p.e. boundary")
        axis.set_yscale("log")
        axis.set_ylim(bottom=0.8)
        axis.set_xlabel("Fixed-gate charge (mV ns)")
        axis.set_ylabel("Events per bin (log scale)")
        axis.set_title(f"{dut.label} on scope {dut.channel}")
        axis.legend(
            title=(
                f"zero events: {result['signal_zero_events']}/{result['reference_selected_events']}\n"
                f"dark-corrected efficiency = {100.0 * result['efficiency_median']:.3f}% "
                f"\N{PLUS-MINUS SIGN}{100.0 * efficiency_uncertainty:.3f}% (stat.)"
            )
        )

    figure.suptitle(
        "Scintillator zero-event test with an independent EPIC-tile coincidence trigger",
        fontsize=16,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.97))
    figure.savefig(args.output / "scintillator_zero_test.png")
    plt.close(figure)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
