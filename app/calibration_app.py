#!/usr/bin/env python3
"""Desktop controls for the gLOWCOST SiPM calibration workflows."""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from calibration_core import (
    APP_DIR,
    DEFAULT_CONFIG,
    ConfigurationError,
    format_float_list,
    load_config,
    parse_float_list,
    validate_config,
    write_json,
)


WORKFLOWS = {
    "Zero-event efficiency": "zero_event",
    "Dark-count spectra": "dark_count",
    "Breakdown-voltage search": "vbr_search",
}
RESULT_PATTERN = re.compile(r"Results:\s*(.+)$")


class ScrolledFrame(ttk.Frame):
    """A plain vertical form that still fits on a small lab monitor."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas, padding=(4, 4, 12, 12))
        window = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)
        self.body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )


class CalibrationApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("gLOWCOST Calibration")
        self.geometry("1500x900")
        self.minsize(1120, 700)

        self.config_data = load_config(DEFAULT_CONFIG)
        self.fields: dict[str, tk.Variable] = {}
        self.process: subprocess.Popen[str] | None = None
        self.run_active = False
        self.cancel_requested = False
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_result_dir: Path | None = None
        self.result_images: list[Path] = []
        self.result_image_index = 0
        self.preview_image: tk.PhotoImage | None = None

        self._configure_style()
        self._build_window()
        self._load_into_fields(self.config_data)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_messages)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("TkDefaultFont", 17, "bold"))
        style.configure("Heading.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Danger.TButton", foreground="#a11b1b")
        style.configure("Status.TLabel", font=("TkDefaultFont", 10, "bold"))

    def _build_window(self) -> None:
        header = ttk.Frame(self, padding=(14, 10, 14, 8))
        header.pack(fill="x")
        ttk.Label(header, text="gLOWCOST Calibration", style="Title.TLabel").pack(side="left")
        self.status_text = tk.StringVar(value="Ready - dry run does not touch hardware")
        ttk.Label(header, textvariable=self.status_text, style="Status.TLabel").pack(side="right")

        split = ttk.Panedwindow(self, orient="horizontal")
        split.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        left = ttk.Frame(split)
        right = ttk.Frame(split)
        split.add(left, weight=3)
        split.add(right, weight=2)

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill="both", expand=True)
        self.tabs: dict[str, ScrolledFrame] = {}
        for title in WORKFLOWS:
            tab = ScrolledFrame(self.notebook)
            self.tabs[title] = tab
            self.notebook.add(tab, text=title)

        self._build_zero_event_tab(self.tabs["Zero-event efficiency"].body)
        self._build_dark_count_tab(self.tabs["Dark-count spectra"].body)
        self._build_vbr_tab(self.tabs["Breakdown-voltage search"].body)
        self._build_common_panel(left)
        self._build_actions(left)

        preview_frame = ttk.LabelFrame(right, text="Latest result", padding=8)
        preview_frame.pack(fill="both", expand=True)
        self.preview_label = ttk.Label(
            preview_frame,
            text="A result plot will appear here after a completed analysis.",
            anchor="center",
            justify="center",
        )
        self.preview_label.pack(fill="both", expand=True)
        preview_buttons = ttk.Frame(preview_frame)
        preview_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(preview_buttons, text="Previous", command=lambda: self._change_image(-1)).pack(side="left")
        self.image_name = tk.StringVar(value="")
        ttk.Label(preview_buttons, textvariable=self.image_name, anchor="center").pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(preview_buttons, text="Next", command=lambda: self._change_image(1)).pack(side="right")

        log_frame = ttk.LabelFrame(right, text="Run log", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(log_frame, height=15, wrap="word", state="disabled", font=("TkFixedFont", 9))
        log_scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _section(self, parent: ttk.Frame, title: str, row: int) -> int:
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 6))
        ttk.Label(parent, text=title, style="Heading.TLabel").grid(
            row=row + 1, column=0, columnspan=3, sticky="w"
        )
        return row + 2

    def _entry(
        self,
        parent: ttk.Frame,
        row: int,
        key: str,
        label: str,
        *,
        width: int = 24,
        note: str = "",
    ) -> int:
        variable = tk.StringVar()
        self.fields[key] = variable
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable, width=width).grid(
            row=row, column=1, sticky="ew", padx=(10, 6), pady=3
        )
        ttk.Label(parent, text=note, foreground="#5b6570").grid(row=row, column=2, sticky="w")
        return row + 1

    def _build_zero_event_tab(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(
            parent,
            text=(
                "The 9 x 9 cm reference tiles on scope C and D select the track. "
                "The regular gLOWCOST tiles on A and B are tested for a response."
            ),
            wraplength=650,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1
        row = self._section(parent, "Scan", row)
        row = self._entry(parent, row, "zero.points", "DUT overvoltages", note="V, comma separated; repeats allowed")
        row = self._entry(parent, row, "zero.reference_vov", "Reference-tile overvoltage", note="V")
        row = self._entry(parent, row, "zero.events", "Events at each point")
        row = self._entry(parent, row, "zero.settle", "Settling time", note="seconds")
        row = self._entry(parent, row, "zero.minimum_refs", "Minimum accepted tracks")

        row = self._section(parent, "Reference selection", row)
        row = self._entry(parent, row, "zero.threshold_c", "Small top tile threshold (C)", note="mV at scope input")
        row = self._entry(parent, row, "zero.threshold_d", "Small bottom tile threshold (D)", note="mV at scope input")
        row = self._entry(parent, row, "zero.coincidence", "C-D coincidence window", note="ns")

        row = self._section(parent, "Scope channels", row)
        for channel, name in (("A", "Regular tile 1"), ("B", "Regular tile 2"), ("C", "Small top tile"), ("D", "Small bottom tile")):
            row = self._entry(parent, row, f"zero.range_{channel}", f"{name} range ({channel})", note="mV full scale")
            row = self._entry(parent, row, f"zero.atten_{channel}", f"{name} probe ({channel})", note="attenuation")

        row = self._section(parent, "Timing and measured p.e. spacing", row)
        for key, label, note in (
            ("zero.sample", "Requested sampling interval", "ns"),
            ("zero.pre", "Pre-trigger record", "ns"),
            ("zero.post", "Post-trigger record", "ns"),
            ("zero.auto", "Scope auto-trigger timeout", "ms"),
            ("zero.dark_start", "Dark window start", "ns"),
            ("zero.dark_stop", "Dark window stop", "ns"),
            ("zero.signal_start", "Signal window start", "ns relative to track"),
            ("zero.signal_stop", "Signal window stop", "ns relative to track"),
            ("zero.s1_charge", "SiPM 1 area gap per volt", "mV ns / V"),
            ("zero.s2_charge", "SiPM 2 area gap per volt", "mV ns / V"),
            ("zero.s1_height", "SiPM 1 height gap per volt", "mV / V"),
            ("zero.s2_height", "SiPM 2 height gap per volt", "mV / V"),
        ):
            row = self._entry(parent, row, key, label, note=note)

    def _build_dark_count_tab(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(
            parent,
            text=(
                "Self-triggered dark pulses are recorded for photoelectron spectra and relative rate checks. "
                "The displayed acquisition rate is not an absolute dead-time-corrected SiPM dark-count rate."
            ),
            wraplength=650,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1
        row = self._section(parent, "Scan", row)
        for key, label, note in (
            ("dark.points", "Overvoltages", "V, comma separated"),
            ("dark.reference_vov", "Other two channels", "V overvoltage"),
            ("dark.events", "Events per SiPM", ""),
            ("dark.settle", "Settling time", "seconds"),
            ("dark.trigger", "Self-trigger level", "mV at scope input"),
            ("dark.range", "Scope range", "mV full scale"),
            ("dark.atten", "Probe attenuation", ""),
        ):
            row = self._entry(parent, row, key, label, note=note)
        row = self._section(parent, "SiPM connections", row)
        row = self._signal_entries(parent, row, "dark")
        row = self._section(parent, "Acquisition timing", row)
        for key, label, note in (
            ("dark.sample", "Requested sampling interval", "ns"),
            ("dark.pre", "Pre-trigger record", "ns"),
            ("dark.post", "Post-trigger record", "ns"),
            ("dark.auto", "Auto-trigger timeout", "ms"),
        ):
            row = self._entry(parent, row, key, label, note=note)

    def _build_vbr_tab(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(
            parent,
            text=(
                "Absolute bias is scanned. The p.e. peak spacing is fitted against bias, "
                "and the zero-spacing intercept gives the breakdown-voltage estimate."
            ),
            wraplength=650,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        row += 1
        row = self._section(parent, "Scan", row)
        for key, label, note in (
            ("vbr.points", "Absolute bias points", "V, comma separated"),
            ("vbr.minimum", "Allowed minimum bias", "V"),
            ("vbr.maximum", "Allowed maximum bias", "V"),
            ("vbr.events", "Events per SiPM", ""),
            ("vbr.settle", "Settling time", "seconds"),
            ("vbr.trigger", "Self-trigger level", "mV at scope input"),
            ("vbr.range", "Scope range", "mV full scale"),
            ("vbr.atten", "Probe attenuation", ""),
        ):
            row = self._entry(parent, row, key, label, note=note)
        row = self._section(parent, "SiPM connections", row)
        row = self._signal_entries(parent, row, "vbr")
        row = self._section(parent, "Acquisition timing", row)
        for key, label, note in (
            ("vbr.sample", "Requested sampling interval", "ns"),
            ("vbr.pre", "Pre-trigger record", "ns"),
            ("vbr.post", "Post-trigger record", "ns"),
            ("vbr.auto", "Auto-trigger timeout", "ms"),
        ):
            row = self._entry(parent, row, key, label, note=note)

    def _signal_entries(self, parent: ttk.Frame, row: int, prefix: str) -> int:
        for number in (1, 2):
            row = self._entry(parent, row, f"{prefix}.name_{number}", f"SiPM {number} name")
            row = self._entry(parent, row, f"{prefix}.detector_{number}", f"SiPM {number} detector channel", note="0 to 7")
            row = self._entry(parent, row, f"{prefix}.scope_{number}", f"SiPM {number} scope channel", note="A, B, C, or D")
        return row

    def _build_common_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Hardware and files", padding=(10, 6))
        panel.pack(fill="x", pady=(8, 0))
        for column in (1, 3):
            panel.columnconfigure(column, weight=1)
        common_fields = (
            ("common.pi", "Detector Pi", 0, 0),
            ("common.tools", "Analysis scripts", 0, 2),
            ("common.output", "Run output", 1, 0),
        )
        for key, label, row, column in common_fields:
            variable = tk.StringVar()
            self.fields[key] = variable
            ttk.Label(panel, text=label).grid(row=row, column=column, sticky="w", pady=3)
            ttk.Entry(panel, textvariable=variable).grid(
                row=row, column=column + 1, sticky="ew", padx=(7, 12), pady=3
            )

        ttk.Label(panel, text="After run").grid(row=1, column=2, sticky="w")
        self.fields["common.final"] = tk.StringVar()
        ttk.Combobox(
            panel,
            textvariable=self.fields["common.final"],
            values=("hv_off", "restore_3v"),
            state="readonly",
            width=14,
        ).grid(row=1, column=3, sticky="w", padx=(7, 12))
        self.fields["common.stop_temp"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            panel,
            text="Stop temperature compensation during live calibration",
            variable=self.fields["common.stop_temp"],
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

    def _build_actions(self, parent: ttk.Frame) -> None:
        actions = ttk.Frame(parent, padding=(0, 8, 0, 0))
        actions.pack(fill="x")
        self.armed = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="Hardware connections checked", variable=self.armed).pack(
            anchor="w", pady=(0, 5)
        )
        button_row = ttk.Frame(actions)
        button_row.pack(fill="x")
        self.dry_button = ttk.Button(button_row, text="Dry run", command=lambda: self._start(False))
        self.dry_button.pack(side="left", padx=(0, 4))
        self.live_button = ttk.Button(button_row, text="Start live run", command=lambda: self._start(True))
        self.live_button.pack(side="left", padx=4)
        self.stop_button = ttk.Button(button_row, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=4)
        ttk.Button(button_row, text="HV off", style="Danger.TButton", command=self._emergency_off).pack(
            side="left", padx=(16, 4)
        )
        ttk.Button(button_row, text="Open results", command=self._open_results).pack(side="right")
        ttk.Button(button_row, text="Load config", command=self._load_config_file).pack(side="right", padx=4)
        ttk.Button(button_row, text="Save config", command=self._save_config_file).pack(side="right", padx=4)

    def _load_into_fields(self, config: dict) -> None:
        common = config["common"]
        self.fields["common.pi"].set(common["pi_host"])
        self.fields["common.tools"].set(common["automation_dir"])
        self.fields["common.output"].set(common["output_root"])
        self.fields["common.final"].set(common["final_hardware_state"])
        self.fields["common.stop_temp"].set(bool(common["stop_temperature_compensation"]))

        zero = config["zero_event"]
        zero_values = {
            "zero.points": format_float_list(zero["overvoltage_points_v"]),
            "zero.reference_vov": zero["reference_overvoltage_v"],
            "zero.events": zero["events_per_point"],
            "zero.settle": zero["settle_seconds"],
            "zero.minimum_refs": zero["minimum_reference_events"],
            "zero.threshold_c": zero["reference_thresholds_mv"]["C"],
            "zero.threshold_d": zero["reference_thresholds_mv"]["D"],
            "zero.coincidence": zero["reference_coincidence_ns"],
            "zero.sample": zero["sample_interval_ns"],
            "zero.pre": zero["pre_trigger_ns"],
            "zero.post": zero["post_trigger_ns"],
            "zero.auto": zero["auto_trigger_ms"],
            "zero.dark_start": zero["dark_gate_start_ns"],
            "zero.dark_stop": zero["dark_gate_stop_ns"],
            "zero.signal_start": zero["signal_relative_start_ns"],
            "zero.signal_stop": zero["signal_relative_stop_ns"],
            "zero.s1_charge": zero["sipm1_charge_gap_per_v_mV_ns"],
            "zero.s2_charge": zero["sipm2_charge_gap_per_v_mV_ns"],
            "zero.s1_height": zero["sipm1_height_gap_per_v_mv"],
            "zero.s2_height": zero["sipm2_height_gap_per_v_mv"],
        }
        for channel in "ABCD":
            zero_values[f"zero.range_{channel}"] = zero["channel_ranges_mv"][channel]
            zero_values[f"zero.atten_{channel}"] = zero["probe_attenuations"][channel]
        self._set_values(zero_values)
        self._load_simple_scan("dark", config["dark_count"], point_key="overvoltage_points_v")
        self._load_simple_scan("vbr", config["vbr_search"], point_key="bias_points_v")

    def _load_simple_scan(self, prefix: str, settings: dict, *, point_key: str) -> None:
        values = {
            f"{prefix}.points": format_float_list(settings[point_key]),
            f"{prefix}.events": settings["events_per_channel" if prefix == "dark" else "events_per_point"],
            f"{prefix}.settle": settings["settle_seconds"],
            f"{prefix}.trigger": settings["trigger_mv"],
            f"{prefix}.range": settings["scope_range_mv"],
            f"{prefix}.atten": settings["probe_attenuation"],
            f"{prefix}.sample": settings["sample_interval_ns"],
            f"{prefix}.pre": settings["pre_trigger_ns"],
            f"{prefix}.post": settings["post_trigger_ns"],
            f"{prefix}.auto": settings["auto_trigger_ms"],
        }
        if prefix == "dark":
            values["dark.reference_vov"] = settings["reference_overvoltage_v"]
        else:
            values["vbr.minimum"] = settings["minimum_bias_v"]
            values["vbr.maximum"] = settings["maximum_bias_v"]
        for number, signal_config in enumerate(settings["signals"], start=1):
            values[f"{prefix}.name_{number}"] = signal_config["name"]
            values[f"{prefix}.detector_{number}"] = signal_config["detector_channel"]
            values[f"{prefix}.scope_{number}"] = signal_config["scope_channel"]
        self._set_values(values)

    def _set_values(self, values: dict[str, object]) -> None:
        for key, value in values.items():
            self.fields[key].set(str(value))

    def _current_workflow(self) -> str:
        title = self.notebook.tab(self.notebook.select(), "text")
        return WORKFLOWS[title]

    def _number(self, key: str, kind: type = float) -> float | int:
        try:
            return kind(self.fields[key].get().strip())
        except ValueError as exc:
            raise ConfigurationError(f"{key} is not a valid {kind.__name__}") from exc

    def _config_from_fields(self) -> dict:
        config = copy.deepcopy(self.config_data)
        common = config["common"]
        common["pi_host"] = self.fields["common.pi"].get().strip()
        common["automation_dir"] = self.fields["common.tools"].get().strip()
        common["output_root"] = self.fields["common.output"].get().strip()
        common["final_hardware_state"] = self.fields["common.final"].get()
        common["stop_temperature_compensation"] = bool(self.fields["common.stop_temp"].get())

        zero = config["zero_event"]
        zero["overvoltage_points_v"] = parse_float_list(self.fields["zero.points"].get())
        for field, config_key, kind in (
            ("zero.reference_vov", "reference_overvoltage_v", float),
            ("zero.events", "events_per_point", int),
            ("zero.settle", "settle_seconds", float),
            ("zero.minimum_refs", "minimum_reference_events", int),
            ("zero.coincidence", "reference_coincidence_ns", float),
            ("zero.sample", "sample_interval_ns", float),
            ("zero.pre", "pre_trigger_ns", float),
            ("zero.post", "post_trigger_ns", float),
            ("zero.auto", "auto_trigger_ms", int),
            ("zero.dark_start", "dark_gate_start_ns", float),
            ("zero.dark_stop", "dark_gate_stop_ns", float),
            ("zero.signal_start", "signal_relative_start_ns", float),
            ("zero.signal_stop", "signal_relative_stop_ns", float),
            ("zero.s1_charge", "sipm1_charge_gap_per_v_mV_ns", float),
            ("zero.s2_charge", "sipm2_charge_gap_per_v_mV_ns", float),
            ("zero.s1_height", "sipm1_height_gap_per_v_mv", float),
            ("zero.s2_height", "sipm2_height_gap_per_v_mv", float),
        ):
            zero[config_key] = self._number(field, kind)
        zero["reference_thresholds_mv"] = {
            "C": self._number("zero.threshold_c"),
            "D": self._number("zero.threshold_d"),
        }
        zero["channel_ranges_mv"] = {
            channel: self._number(f"zero.range_{channel}", int) for channel in "ABCD"
        }
        zero["probe_attenuations"] = {
            channel: self._number(f"zero.atten_{channel}") for channel in "ABCD"
        }

        self._read_simple_scan(config["dark_count"], "dark", "overvoltage_points_v", "events_per_channel")
        config["dark_count"]["reference_overvoltage_v"] = self._number("dark.reference_vov")
        self._read_simple_scan(config["vbr_search"], "vbr", "bias_points_v", "events_per_point")
        config["vbr_search"]["minimum_bias_v"] = self._number("vbr.minimum")
        config["vbr_search"]["maximum_bias_v"] = self._number("vbr.maximum")
        return config

    def _read_simple_scan(self, settings: dict, prefix: str, point_key: str, event_key: str) -> None:
        settings[point_key] = parse_float_list(self.fields[f"{prefix}.points"].get())
        settings[event_key] = self._number(f"{prefix}.events", int)
        settings["settle_seconds"] = self._number(f"{prefix}.settle")
        settings["trigger_mv"] = self._number(f"{prefix}.trigger")
        settings["scope_range_mv"] = self._number(f"{prefix}.range", int)
        settings["probe_attenuation"] = self._number(f"{prefix}.atten")
        settings["sample_interval_ns"] = self._number(f"{prefix}.sample")
        settings["pre_trigger_ns"] = self._number(f"{prefix}.pre")
        settings["post_trigger_ns"] = self._number(f"{prefix}.post")
        settings["auto_trigger_ms"] = self._number(f"{prefix}.auto", int)
        settings["signals"] = [
            {
                "name": self.fields[f"{prefix}.name_{number}"].get().strip(),
                "detector_channel": self._number(f"{prefix}.detector_{number}", int),
                "scope_channel": self.fields[f"{prefix}.scope_{number}"].get().strip().upper(),
                "color": f"C{number - 1}",
            }
            for number in (1, 2)
        ]

    def _start(self, live: bool) -> None:
        if self.run_active:
            messagebox.showinfo("Run active", "A calibration run is already active.")
            return
        workflow = self._current_workflow()
        try:
            config = self._config_from_fields()
            validate_config(workflow, config)
        except (ConfigurationError, KeyError) as exc:
            messagebox.showerror("Check settings", str(exc))
            return

        if live:
            if not self.armed.get():
                messagebox.showerror("Hardware check", "Tick 'Hardware connections checked' before a live run.")
                return
            if not self._confirm_live_run(workflow, config):
                return

        state_dir = Path.home() / ".config" / "glowcost-calibration"
        state_dir.mkdir(parents=True, exist_ok=True)
        config_path = state_dir / "last_run_config.json"
        write_json(config_path, config)
        self.config_data = config

        command = [
            sys.executable,
            str(APP_DIR / "calibration_runner.py"),
            workflow,
            "--config",
            str(config_path),
            "--live" if live else "--dry-run",
        ]
        if live:
            command.extend(["--confirm", "RUN_LIVE_HARDWARE"])
        self._append_log("\n$ " + " ".join(shlex.quote(part) for part in command))
        self.status_text.set(f"Running {workflow.replace('_', ' ')} ({'LIVE' if live else 'dry run'})")
        self.run_active = True
        self.cancel_requested = False
        self.dry_button.configure(state="disabled")
        self.live_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        worker = threading.Thread(target=self._run_worker, args=(command,), daemon=True)
        worker.start()

    def _confirm_live_run(self, workflow: str, config: dict) -> bool:
        dialog = tk.Toplevel(self)
        dialog.title("Confirm live hardware run")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="This run will change SiPM bias voltage.", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                f"Workflow: {workflow.replace('_', ' ')}\n"
                f"Detector: {config['common']['pi_host']}\n"
                f"Final state: {config['common']['final_hardware_state']}\n\n"
                "Type RUN LIVE to continue."
            ),
            justify="left",
        ).pack(anchor="w", pady=(8, 6))
        answer = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=answer, width=24)
        entry.pack(fill="x")
        result = {"accepted": False}

        def accept() -> None:
            if answer.get().strip() == "RUN LIVE":
                result["accepted"] = True
                dialog.destroy()
            else:
                messagebox.showerror("Confirmation", "The confirmation text does not match.", parent=dialog)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Start live run", command=accept).pack(side="right", padx=(0, 6))
        entry.focus_set()
        dialog.bind("<Return>", lambda _event: accept())
        self.wait_window(dialog)
        return bool(result["accepted"])

    def _run_worker(self, command: list[str]) -> None:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            self.process = process
            if self.cancel_requested:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            assert process.stdout is not None
            for line in process.stdout:
                self.messages.put(("log", line.rstrip()))
            returncode = process.wait()
            self.messages.put(("finished", returncode))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def _stop(self) -> None:
        self.cancel_requested = True
        process = self.process
        if process is None:
            return
        self.status_text.set("Stopping acquisition and applying the final safety state...")
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def _emergency_off(self) -> None:
        if not messagebox.askyesno(
            "HV off",
            "Stop any active run and command channels 0, 1, 2, and 3 to HV off?",
        ):
            return
        self._stop()
        pi = self.fields["common.pi"].get().strip()
        agent = self.config_data["common"]["pi_bias_agent"]
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            pi,
            f"python3 {shlex.quote(agent)} off --channels 0,1,2,3",
        ]
        self.status_text.set("Sending HV-off command...")
        threading.Thread(target=self._safety_worker, args=(command,), daemon=True).start()

    def _safety_worker(self, command: list[str]) -> None:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.messages.put(("safety", (completed.returncode, completed.stdout)))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "log":
                    line = str(value)
                    self._append_log(line)
                    match = RESULT_PATTERN.search(line)
                    if match:
                        self.last_result_dir = Path(match.group(1).strip())
                elif kind == "finished":
                    self.process = None
                    self.run_active = False
                    self.stop_button.configure(state="disabled")
                    self.dry_button.configure(state="normal")
                    self.live_button.configure(state="normal")
                    returncode = int(value)
                    self.status_text.set("Run completed" if returncode == 0 else f"Run ended with code {returncode}")
                    self._refresh_result_images()
                elif kind == "error":
                    self.process = None
                    self.run_active = False
                    self.stop_button.configure(state="disabled")
                    self.dry_button.configure(state="normal")
                    self.live_button.configure(state="normal")
                    self.status_text.set("Run failed to start")
                    messagebox.showerror("Run error", str(value))
                elif kind == "safety":
                    returncode, output = value
                    self._append_log(str(output))
                    if returncode == 0:
                        self.status_text.set("HV-off command completed")
                    else:
                        self.status_text.set("HV-off command failed - verify detector manually")
                        messagebox.showerror("HV off failed", str(output))
        except queue.Empty:
            pass
        self.after(100, self._drain_messages)

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _refresh_result_images(self) -> None:
        if self.last_result_dir is None or not self.last_result_dir.exists():
            return
        self.result_images = sorted(self.last_result_dir.rglob("*.png"))
        self.result_image_index = 0
        self._show_image()

    def _change_image(self, amount: int) -> None:
        if not self.result_images:
            return
        self.result_image_index = (self.result_image_index + amount) % len(self.result_images)
        self._show_image()

    def _show_image(self) -> None:
        if not self.result_images:
            return
        path = self.result_images[self.result_image_index]
        try:
            image = tk.PhotoImage(file=path)
            max_width, max_height = 570, 390
            factor = max(1, (image.width() + max_width - 1) // max_width, (image.height() + max_height - 1) // max_height)
            if factor > 1:
                image = image.subsample(factor, factor)
            self.preview_image = image
            self.preview_label.configure(image=image, text="")
            self.image_name.set(path.name)
        except tk.TclError:
            self.preview_label.configure(image="", text=f"Plot saved at:\n{path}")
            self.image_name.set(path.name)

    def _open_results(self) -> None:
        path = self.last_result_dir or Path(self.fields["common.output"].get()).expanduser()
        if not path.exists():
            messagebox.showinfo("Results", f"No result folder exists yet:\n{path}")
            return
        subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", str(path)])

    def _save_config_file(self) -> None:
        try:
            config = self._config_from_fields()
            validate_config(self._current_workflow(), config)
        except ConfigurationError as exc:
            messagebox.showerror("Check settings", str(exc))
            return
        path = filedialog.asksaveasfilename(
            title="Save calibration settings",
            defaultextension=".json",
            filetypes=(("JSON settings", "*.json"),),
        )
        if path:
            write_json(Path(path), config)

    def _load_config_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load calibration settings",
            filetypes=(("JSON settings", "*.json"), ("All files", "*")),
        )
        if not path:
            return
        try:
            config = load_config(Path(path))
            for workflow in WORKFLOWS.values():
                validate_config(workflow, config)
        except (OSError, json.JSONDecodeError, ConfigurationError, KeyError) as exc:
            messagebox.showerror("Cannot load settings", str(exc))
            return
        self.config_data = config
        self._load_into_fields(config)
        self.status_text.set(f"Loaded settings from {path}")

    def _on_close(self) -> None:
        if self.run_active:
            messagebox.showwarning("Run active", "Stop the active calibration before closing the application.")
            return
        self.destroy()


def main() -> None:
    CalibrationApp().mainloop()


if __name__ == "__main__":
    main()
