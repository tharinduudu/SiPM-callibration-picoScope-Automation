#!/usr/bin/env python3
"""Lightweight, read-only monitor for a running zero-event acquisition."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402


CHANNELS = ("A", "B", "C", "D")
CHANNEL_LABELS = {
    "A": "SiPM 1 (△) - GSU top",
    "B": "SiPM 2 (★) - GSU bottom",
    "C": "9x9 cm top reference - trigger",
    "D": "9x9 cm bottom reference - coincidence",
}
CHANNEL_COLORS = {
    "A": (0.12, 0.47, 0.71),
    "B": (0.93, 0.49, 0.13),
    "C": (0.16, 0.63, 0.38),
    "D": (0.82, 0.20, 0.23),
}
EVENT_PATTERN = re.compile(r"event_(\d+)\.csv$")
RATE_PATTERN = re.compile(r"captured\s+(\d+)/(\d+)\s+events\s+\(([0-9.]+)\s+events/s\)")


def human_duration(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "--"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d} h {minutes:02d} min"
    if minutes:
        return f"{minutes:d} min {seconds:02d} s"
    return f"{seconds:d} s"


def tail_text(path: Path, limit: int = 8192) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def running_capture() -> tuple[int | None, list[str]]:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        decoded = [item.decode("utf-8", errors="replace") for item in args if item]
        if any(item.endswith("pico_scintillator_capture.py") for item in decoded):
            return int(entry.name), decoded
    return None, []


def argument_value(arguments: list[str], option: str, default: str | None = None) -> str | None:
    try:
        return arguments[arguments.index(option) + 1]
    except (ValueError, IndexError):
        return default


def newest_experiment(experiments_root: Path) -> Path | None:
    candidates = []
    try:
        for raw in experiments_root.glob("*/raw"):
            if raw.is_dir():
                candidates.append((raw.stat().st_mtime, raw.parent))
    except OSError:
        return None
    return max(candidates, default=(0.0, None))[1]


def read_waveform(path: Path) -> tuple[list[float], dict[str, list[float]]]:
    times: list[float] = []
    traces = {channel: [] for channel in CHANNELS}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader)
        next(reader)
        next(reader)
        for row in reader:
            if len(row) < 5:
                continue
            values = [float(value) for value in row[:5]]
            times.append(values[0])
            for index, channel in enumerate(CHANNELS, start=1):
                traces[channel].append(values[index])
    if len(times) < 2:
        raise ValueError("waveform file is incomplete")
    return times, traces


def reference_event(
    times: list[float],
    traces: dict[str, list[float]],
    threshold_mv: float = 700.0,
) -> tuple[bool, dict[str, float]]:
    baseline_indices = [index for index, value in enumerate(times) if value < -200.0]
    prompt_indices = [index for index, value in enumerate(times) if -100.0 <= value <= 150.0]
    peaks: dict[str, float] = {}
    for channel in CHANNELS:
        values = traces[channel]
        baseline_values = [values[index] for index in baseline_indices] or values[: max(1, len(values) // 5)]
        baseline = statistics.median(baseline_values)
        selected = prompt_indices if channel in ("C", "D") else range(len(values))
        peaks[channel] = max(values[index] - baseline for index in selected)
    return peaks["C"] >= threshold_mv and peaks["D"] >= threshold_mv, peaks


class WaveformView(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(720, 440)
        self.times: list[float] = []
        self.traces: dict[str, list[float]] = {channel: [] for channel in CHANNELS}
        self.event_name = ""
        self.connect("draw", self.on_draw)

    def set_waveform(
        self,
        times: list[float],
        traces: dict[str, list[float]],
        event_name: str,
    ) -> None:
        self.times = times
        self.traces = traces
        self.event_name = event_name
        self.queue_draw()

    @staticmethod
    def text(context, x: float, y: float, value: str, size: float, color=(0.25, 0.28, 0.27)) -> None:
        context.set_source_rgb(*color)
        context.select_font_face("Sans", 0, 0)
        context.set_font_size(size)
        context.move_to(x, y)
        context.show_text(value)

    def on_draw(self, _widget, context) -> bool:
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        context.set_source_rgb(0.985, 0.988, 0.987)
        context.paint()

        if not self.times:
            self.text(context, width / 2 - 85, height / 2, "Waiting for a completed event", 14)
            return False

        left, right, top, bottom = 76.0, 18.0, 14.0, 34.0
        plot_width = max(100.0, width - left - right)
        panel_gap = 10.0
        panel_height = max(50.0, (height - top - bottom - panel_gap * 3) / 4)
        time_min, time_max = min(self.times), max(self.times)
        time_span = max(1.0, time_max - time_min)

        for panel_index, channel in enumerate(CHANNELS):
            y_top = top + panel_index * (panel_height + panel_gap)
            values = [value for value in self.traces[channel] if math.isfinite(value)]
            if not values:
                continue
            value_min, value_max = min(values), max(values)
            value_span = max(1.0, value_max - value_min)
            padding = max(5.0, value_span * 0.10)
            value_min -= padding
            value_max += padding
            value_span = value_max - value_min

            context.set_source_rgb(0.93, 0.94, 0.935)
            context.rectangle(left, y_top, plot_width, panel_height)
            context.fill()

            for fraction in (0.25, 0.5, 0.75):
                context.set_source_rgb(0.82, 0.84, 0.83)
                context.set_line_width(0.6)
                context.move_to(left, y_top + fraction * panel_height)
                context.line_to(left + plot_width, y_top + fraction * panel_height)
                context.stroke()

            trigger_x = left + (0.0 - time_min) / time_span * plot_width
            if left <= trigger_x <= left + plot_width:
                context.set_source_rgb(0.43, 0.46, 0.44)
                context.set_line_width(0.8)
                context.set_dash([4.0, 4.0])
                context.move_to(trigger_x, y_top)
                context.line_to(trigger_x, y_top + panel_height)
                context.stroke()
                context.set_dash([])

            if value_min <= 0.0 <= value_max:
                zero_y = y_top + (value_max / value_span) * panel_height
                context.set_source_rgb(0.63, 0.66, 0.64)
                context.set_line_width(0.7)
                context.move_to(left, zero_y)
                context.line_to(left + plot_width, zero_y)
                context.stroke()

            color = CHANNEL_COLORS[channel]
            context.set_source_rgb(*color)
            context.set_line_width(1.25)
            for index, (time_ns, value) in enumerate(zip(self.times, self.traces[channel])):
                x = left + (time_ns - time_min) / time_span * plot_width
                y = y_top + (value_max - value) / value_span * panel_height
                if index == 0:
                    context.move_to(x, y)
                else:
                    context.line_to(x, y)
            context.stroke()

            self.text(context, 10, y_top + 17, f"{channel}", 13, color)
            self.text(context, 27, y_top + 17, CHANNEL_LABELS[channel], 10)
            self.text(context, 10, y_top + panel_height - 4, f"{value_min:.0f}", 9, (0.42, 0.45, 0.43))
            self.text(context, 10, y_top + 31, f"{value_max:.0f} mV", 9, (0.42, 0.45, 0.43))

        axis_y = height - 10
        for value in (time_min, 0.0, time_max):
            x = left + (value - time_min) / time_span * plot_width
            self.text(context, x - 18, axis_y, f"{value:.0f}", 9, (0.42, 0.45, 0.43))
        self.text(context, left + plot_width / 2 - 25, axis_y, "Time (ns)", 10)
        return False


class MonitorWindow(Gtk.Window):
    def __init__(self, experiments_root: Path, refresh_ms: int) -> None:
        super().__init__(title="gLOWCOST Zero-Event Monitor")
        self.experiments_root = experiments_root
        self.refresh_ms = max(1000, refresh_ms)
        self.run_dir: Path | None = None
        self.raw_dir: Path | None = None
        self.total_events = 0
        self.latest_file: Path | None = None
        self.latest_valid_file: Path | None = None
        self.evaluated_event = -1
        self.evaluated_count = 0
        self.valid_count = 0
        self.latest_peaks: dict[str, float] = {}
        self.first_event_time: float | None = None
        self.environment: dict = {}
        self.bias_status: dict = {}

        self.set_default_size(1260, 820)
        self.set_size_request(960, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)
        self._install_style()
        self._build_ui()
        self.refresh()
        GLib.timeout_add(self.refresh_ms, self.refresh)

    def _install_style(self) -> None:
        css = b"""
        window { background: #f4f6f5; color: #202523; }
        headerbar { background: #ffffff; border-bottom: 1px solid #cfd6d2; }
        .section-title { font-size: 15px; font-weight: 700; color: #28302c; }
        .run-name { font-family: monospace; font-size: 11px; color: #5c6661; }
        .metric-label { font-size: 10px; color: #68726d; }
        .metric-value { font-size: 18px; font-weight: bold; color: #18201c; }
        .meta { font-family: monospace; font-size: 10px; color: #4f5954; }
        .status-running { color: #08745b; font-weight: 700; }
        .status-waiting { color: #a25a08; font-weight: 700; }
        .status-stopped { color: #a42b25; font-weight: 700; }
        progressbar trough { min-height: 12px; background: #dfe5e2; }
        progressbar progress { min-height: 12px; background: #08766a; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    @staticmethod
    def label(text: str = "", css_class: str | None = None, xalign: float = 0.0) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=xalign)
        if css_class:
            label.get_style_context().add_class(css_class)
        return label

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar(title="gLOWCOST Zero-Event Monitor", show_close_button=True)
        header.set_subtitle("Read-only acquisition view")
        self.status_label = self.label("STARTING", "status-waiting")
        header.pack_end(self.status_label)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.add(root)

        run_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.run_label = self.label("Finding active experiment...", "run-name")
        self.run_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.age_label = self.label("", "meta", 1.0)
        run_row.pack_start(self.run_label, True, True, 0)
        run_row.pack_end(self.age_label, False, False, 0)
        root.pack_start(run_row, False, False, 0)

        self.progress = Gtk.ProgressBar(show_text=True)
        root.pack_start(self.progress, False, False, 0)

        metrics = Gtk.Grid(column_spacing=24, row_spacing=2)
        self.metric_values: dict[str, Gtk.Label] = {}
        for index, (key, title) in enumerate(
            (("events", "RAW CAPTURES"), ("valid", "VALID C/D"), ("rate", "CAPTURE RATE"),
             ("elapsed", "ELAPSED"), ("remaining", "EST. REMAINING"))
        ):
            metrics.attach(self.label(title, "metric-label"), index, 0, 1, 1)
            value = self.label("--", "metric-value")
            metrics.attach(value, index, 1, 1, 1)
            self.metric_values[key] = value
        root.pack_start(metrics, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        root.pack_start(separator, False, False, 0)

        metadata_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        self.acquisition_label = self.label("Acquisition metadata: --", "meta")
        self.environment_label = self.label("Environment: --", "meta")
        self.bias_label = self.label("Bias: --", "meta")
        metadata_row.pack_start(self.acquisition_label, False, False, 0)
        metadata_row.pack_start(self.environment_label, False, False, 0)
        metadata_row.pack_start(self.bias_label, False, False, 0)
        root.pack_start(metadata_row, False, False, 0)

        waveform_heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        waveform_heading.pack_start(
            self.label("Latest valid C/D reference waveform", "section-title"), False, False, 0
        )
        self.event_label = self.label("", "meta", 1.0)
        waveform_heading.pack_end(self.event_label, False, False, 0)
        root.pack_start(waveform_heading, False, False, 0)

        self.waveform = WaveformView()
        frame = Gtk.Frame()
        frame.add(self.waveform)
        root.pack_start(frame, True, True, 0)

        self.peak_label = self.label(
            "Reference selection: C and D >= 700 mV from -100 to +150 ns; A and B unfiltered",
            "meta",
        )
        root.pack_start(self.peak_label, False, False, 0)

    def set_status(self, text: str, css_class: str) -> None:
        context = self.status_label.get_style_context()
        for name in ("status-running", "status-waiting", "status-stopped"):
            context.remove_class(name)
        context.add_class(css_class)
        self.status_label.set_text(text)

    def discover(self) -> tuple[int | None, list[str]]:
        pid, arguments = running_capture()
        output = argument_value(arguments, "--output")
        if output:
            raw_dir = Path(output)
            run_dir = raw_dir.parent
        else:
            run_dir = newest_experiment(self.experiments_root)
            raw_dir = run_dir / "raw" if run_dir else None

        if run_dir != self.run_dir:
            self.run_dir = run_dir
            self.raw_dir = raw_dir
            self.latest_file = None
            self.latest_valid_file = None
            self.evaluated_event = -1
            self.evaluated_count = 0
            self.valid_count = 0
            self.latest_peaks = {}
            self.first_event_time = None
            self.environment = read_json(run_dir / "pre_environment.json") if run_dir else {}
            self.bias_status = read_json(run_dir / "pre_bias_status.json") if run_dir else {}

        if arguments:
            self.total_events = int(argument_value(arguments, "--events", "0") or 0)
            interval = argument_value(arguments, "--sample-interval-ns", "--")
            trigger = argument_value(arguments, "--trigger-mv", "--")
            coincidence = argument_value(arguments, "--coincidence-trigger-mv", "--")
            self.acquisition_label.set_text(
                f"Sampling {interval} ns | C/D coincidence {trigger}/{coincidence} mV"
            )
        return pid, arguments

    def event_files(self) -> tuple[int, Path | None, float | None, list[tuple[int, Path]]]:
        if not self.raw_dir or not self.raw_dir.is_dir():
            return 0, None, None, []
        count = 0
        latest: tuple[int, Path] | None = None
        first_mtime: float | None = None
        indexed_files: list[tuple[int, Path]] = []
        try:
            for entry in os.scandir(self.raw_dir):
                match = EVENT_PATTERN.match(entry.name)
                if not match or not entry.is_file():
                    continue
                event_index = int(match.group(1))
                count += 1
                indexed_files.append((event_index, Path(entry.path)))
                if latest is None or event_index > latest[0]:
                    latest = (event_index, Path(entry.path))
                try:
                    mtime = entry.stat().st_mtime
                    first_mtime = mtime if first_mtime is None else min(first_mtime, mtime)
                except OSError:
                    pass
        except OSError:
            return 0, None, None, []
        indexed_files.sort(key=lambda item: item[0])
        return count, latest[1] if latest else None, first_mtime, indexed_files

    def update_metadata(self) -> None:
        if self.environment:
            temperature = self.environment.get("temperature_C")
            pressure = self.environment.get("pressure_hPa")
            if temperature is not None and pressure is not None:
                self.environment_label.set_text(f"Start {temperature:.2f} C | {pressure:.1f} hPa")
        channels = self.bias_status.get("plan", {}).get("channels", {})
        try:
            ch2 = channels["2"]["effective_bias_v"]
            ch3 = channels["3"]["effective_bias_v"]
            self.bias_label.set_text(f"Bias SiPM 1/2: {ch2:.3f}/{ch3:.3f} V")
        except (KeyError, TypeError, ValueError):
            pass

    def update_waveform(self, latest: Path | None) -> None:
        if latest is None or latest == self.latest_file:
            return
        try:
            times, traces = read_waveform(latest)
        except (OSError, ValueError, StopIteration):
            return
        self.latest_file = latest
        self.waveform.set_waveform(times, traces, latest.name)
        self.event_label.set_text(latest.name)
        _valid, peaks = reference_event(times, traces)
        self.latest_peaks = peaks
        peak_text = " | ".join(f"{channel} {peaks[channel]:.0f} mV" for channel in CHANNELS)
        self.peak_label.set_text(
            f"Prompt selection C/D >= 700 mV | Baseline-subtracted peaks: {peak_text}"
        )

    def classify_new_events(self, indexed_files: list[tuple[int, Path]]) -> None:
        for event_index, path in indexed_files:
            if event_index <= self.evaluated_event:
                continue
            try:
                times, traces = read_waveform(path)
                valid, peaks = reference_event(times, traces)
            except (OSError, ValueError, StopIteration):
                break
            self.evaluated_event = event_index
            self.evaluated_count += 1
            if valid:
                self.valid_count += 1
                self.latest_valid_file = path
                self.latest_peaks = peaks

    def refresh(self) -> bool:
        try:
            pid, _arguments = self.discover()
            count, latest, first_mtime, indexed_files = self.event_files()
            self.classify_new_events(indexed_files)
            now = time.time()
            latest_age = now - latest.stat().st_mtime if latest else None
            self.first_event_time = self.first_event_time or first_mtime

            rate = 0.0
            if self.run_dir:
                matches = RATE_PATTERN.findall(tail_text(self.run_dir / "run.log"))
                if matches:
                    _logged_count, logged_total, logged_rate = matches[-1]
                    rate = float(logged_rate)
                    if not self.total_events:
                        self.total_events = int(logged_total)
            elapsed = now - self.first_event_time if self.first_event_time else None
            if rate <= 0.0 and elapsed and elapsed > 0:
                rate = count / elapsed
            remaining = (self.total_events - count) / rate if rate > 0 and self.total_events > count else 0.0

            if pid is not None and (latest_age is None or latest_age > 8.0):
                self.set_status("WAITING FOR TRIGGER", "status-waiting")
            elif pid is not None:
                self.set_status("ACQUIRING", "status-running")
            elif self.total_events and count >= self.total_events:
                self.set_status("COMPLETE", "status-running")
            else:
                self.set_status("NOT RUNNING", "status-stopped")

            run_name = self.run_dir.name if self.run_dir else "No experiment found"
            self.run_label.set_text(run_name)
            self.run_label.set_tooltip_text(str(self.run_dir) if self.run_dir else "")
            process_text = f"PID {pid}" if pid else ""
            age_text = f"raw event {latest_age:.1f} s ago" if latest_age is not None else ""
            self.age_label.set_text(" | ".join(value for value in (process_text, age_text) if value))

            fraction = min(1.0, count / self.total_events) if self.total_events else 0.0
            self.progress.set_fraction(fraction)
            self.progress.set_text(
                f"{fraction * 100:.1f}%" if self.total_events else f"{count:,} events"
            )
            self.metric_values["events"].set_text(
                f"{count:,} / {self.total_events:,}" if self.total_events else f"{count:,}"
            )
            valid_fraction = self.valid_count / self.evaluated_count if self.evaluated_count else 0.0
            self.metric_values["valid"].set_text(
                f"{self.valid_count:,} ({valid_fraction * 100:.1f}%)"
                if self.evaluated_count else "--"
            )
            self.metric_values["rate"].set_text(f"{rate * 60:.1f} / min" if rate > 0 else "--")
            self.metric_values["elapsed"].set_text(human_duration(elapsed))
            self.metric_values["remaining"].set_text(human_duration(remaining))
            self.update_metadata()
            self.update_waveform(self.latest_valid_file)
        except Exception as error:  # Keep the monitor alive without affecting acquisition.
            self.set_status("MONITOR ERROR", "status-stopped")
            self.run_label.set_text(str(error))
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiments-root",
        type=Path,
        default=Path("/home/muon/brDownVstudy/experiments"),
    )
    parser.add_argument("--refresh-ms", type=int, default=2500)
    args = parser.parse_args()

    window = MonitorWindow(args.experiments_root, args.refresh_ms)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
