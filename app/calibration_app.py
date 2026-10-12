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
    SCOPE_RANGES_MV,
    ConfigurationError,
    format_float_list,
    load_config,
    parse_float_list,
    validate_config,
    write_json,
)
from help_content import field_help
from ui_components import ScrolledFrame, add_tooltip, show_help


WORKFLOWS = {
    "Zero-event efficiency": "zero_event",
    "Dark-count spectra": "dark_count",
    "Breakdown-voltage search": "vbr_search",
}
RESULT_PATTERN = re.compile(r"Results:\s*(.+)$")


class CalibrationApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("gLOWCOST Calibration")
        self.geometry("1500x900")
        self.minsize(1120, 700)

        # Application state is kept here; acquisition and analysis remain in
        # calibration_runner.py so they can also be used from the command line.
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
        self.reviewed_signatures: set[str] = set()
        self.completed_dry_runs: set[str] = set()
        self.active_signature: str | None = None
        self.active_run_is_live = False

        self._configure_style()
        self._build_window()
        self._load_into_fields(self.config_data)
        self._watch_fields()
        self._update_workflow_steps()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_messages)

    # Window construction and visual styles
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("TkDefaultFont", 17, "bold"))
        style.configure("Heading.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Danger.TButton", foreground="#a11b1b")
        style.configure("Status.TLabel", font=("TkDefaultFont", 10, "bold"))
        style.configure("StepDone.TLabel", foreground="#147a55", font=("TkDefaultFont", 9, "bold"))
        style.configure("StepCurrent.TLabel", foreground="#1769aa", font=("TkDefaultFont", 9, "bold"))
        style.configure("StepPending.TLabel", foreground="#65737e", font=("TkDefaultFont", 9))

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

        self._build_workflow_steps(left)
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
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._update_workflow_steps())
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
        previous_button = ttk.Button(
            preview_buttons, text="Previous", command=lambda: self._change_image(-1)
        )
        previous_button.pack(side="left")
        add_tooltip(previous_button, "Show the previous PNG result produced in the latest run directory.")
        self.image_name = tk.StringVar(value="")
        ttk.Label(preview_buttons, textvariable=self.image_name, anchor="center").pack(
            side="left", fill="x", expand=True, padx=8
        )
        next_button = ttk.Button(preview_buttons, text="Next", command=lambda: self._change_image(1))
        next_button.pack(side="right")
        add_tooltip(next_button, "Show the next PNG result produced in the latest run directory.")

        log_frame = ttk.LabelFrame(right, text="Run log", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(log_frame, height=15, wrap="word", state="disabled", font=("TkFixedFont", 9))
        log_scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    # The six visible steps are also enforced before a live run. Students can
    # see what is missing without discovering it only at the final button.
    def _build_workflow_steps(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Required workflow", padding=(8, 5))
        frame.pack(fill="x", pady=(0, 7))
        self.step_labels: list[ttk.Label] = []
        names = ("Choose method", "Set values", "Review plan", "Dry run", "Check hardware", "Live run")
        for index, name in enumerate(names, start=1):
            label = ttk.Label(frame, text=f"{index}. {name}", style="StepPending.TLabel")
            label.pack(side="left", padx=(0, 14))
            self.step_labels.append(label)

    def _section(self, parent: ttk.Frame, title: str, row: int) -> int:
        ttk.Separator(parent).grid(row=row, column=0, columnspan=4, sticky="ew", pady=(12, 6))
        ttk.Label(parent, text=title, style="Heading.TLabel").grid(
            row=row + 1, column=0, columnspan=4, sticky="w"
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
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=3)
        choices: tuple[object, ...] | None = None
        if key.endswith(".range") or ".range_" in key:
            choices = SCOPE_RANGES_MV
        elif key.endswith(".atten") or ".atten_" in key:
            choices = (1, 10)
        elif ".scope_" in key:
            choices = ("A", "B", "C", "D")
        elif ".detector_" in key:
            choices = tuple(range(8))

        if choices is None:
            entry_widget: ttk.Entry | ttk.Combobox = ttk.Entry(
                parent, textvariable=variable, width=width
            )
        else:
            entry_widget = ttk.Combobox(
                parent,
                textvariable=variable,
                values=choices,
                state="readonly",
                width=width,
            )
        entry_widget.grid(
            row=row, column=1, sticky="ew", padx=(10, 6), pady=3
        )
        note_widget = ttk.Label(parent, text=note, foreground="#5b6570")
        note_widget.grid(row=row, column=2, sticky="w")
        topic = field_help(key)
        for widget in (label_widget, entry_widget, note_widget):
            add_tooltip(widget, topic.summary)
        self._help_button(parent, row, 3, key)
        return row + 1

    def _help_button(self, parent: tk.Misc, row: int, column: int, key: str) -> ttk.Button:
        topic = field_help(key)
        button = ttk.Button(parent, text="?", width=3, command=lambda: show_help(self, topic))
        button.grid(row=row, column=column, sticky="e", padx=(5, 0), pady=2)
        add_tooltip(button, f"Open help for {topic.title}")
        return button

    # Measurement-specific forms
    def _build_zero_event_tab(self, parent: ttk.Frame) -> None:
        row = 0
        ttk.Label(
            parent,
            text=(
                "The 9 x 9 cm reference tiles on scope C and D select the track. "
                "The regular gLOWCOST tiles on A and B are tested for a response."
            ),
            wraplength=650,
        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(2, 8))
        row += 1
        row = self._section(parent, "Scan", row)
        row = self._entry(parent, row, "zero.points", "DUT overvoltages", note="V, comma separated; repeats allowed")
        row = self._entry(parent, row, "zero.reference_vov", "Reference-tile overvoltage", note="V")
        row = self._entry(parent, row, "zero.events", "Events at each point")
        row = self._entry(parent, row, "zero.settle", "Settling time", note="seconds")
        row = self._entry(parent, row, "zero.minimum_refs", "Minimum accepted tracks")

        row = self._section(parent, "Reference selection", row)
        row = self._entry(parent, row, "zero.threshold_c", "Small top tile threshold (C)", note="mV, probe corrected")
        row = self._entry(parent, row, "zero.threshold_d", "Small bottom tile threshold (D)", note="mV, probe corrected")
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
        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(2, 8))
        row += 1
        row = self._section(parent, "Scan", row)
        for key, label, note in (
            ("dark.points", "Overvoltages", "V, comma separated"),
            ("dark.reference_vov", "Other two channels", "V overvoltage"),
            ("dark.events", "Events per SiPM", ""),
            ("dark.settle", "Settling time", "seconds"),
            ("dark.trigger", "Self-trigger level", "mV, probe corrected"),
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
        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(2, 8))
        row += 1
        row = self._section(parent, "Scan", row)
        for key, label, note in (
            ("vbr.points", "Absolute bias points", "V, comma separated"),
            ("vbr.minimum", "Allowed minimum bias", "V"),
            ("vbr.maximum", "Allowed maximum bias", "V"),
            ("vbr.events", "Events per SiPM", ""),
            ("vbr.settle", "Settling time", "seconds"),
            ("vbr.trigger", "Self-trigger level", "mV, probe corrected"),
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
        panel.columnconfigure(1, weight=1)
        panel.columnconfigure(5, weight=1)
        common_fields = (
            ("common.pi", "Detector Pi", 0, 0),
            ("common.tools", "Analysis scripts", 0, 4),
            ("common.output", "Run output", 1, 0),
        )
        for key, label, row, column in common_fields:
            variable = tk.StringVar()
            self.fields[key] = variable
            label_widget = ttk.Label(panel, text=label)
            label_widget.grid(row=row, column=column, sticky="w", pady=3)
            entry_widget = ttk.Entry(panel, textvariable=variable)
            entry_widget.grid(
                row=row, column=column + 1, sticky="ew", padx=(7, 5), pady=3
            )
            topic = field_help(key)
            add_tooltip(label_widget, topic.summary)
            add_tooltip(entry_widget, topic.summary)
            self._help_button(panel, row, column + 2, key)

        final_label = ttk.Label(panel, text="After run")
        final_label.grid(row=1, column=4, sticky="w")
        self.fields["common.final"] = tk.StringVar()
        final_box = ttk.Combobox(
            panel,
            textvariable=self.fields["common.final"],
            values=("hv_off", "restore_3v"),
            state="readonly",
            width=14,
        )
        final_box.grid(row=1, column=5, sticky="ew", padx=(7, 5))
        final_topic = field_help("common.final")
        add_tooltip(final_label, final_topic.summary)
        add_tooltip(final_box, final_topic.summary)
        self._help_button(panel, 1, 6, "common.final")
        self.fields["common.stop_temp"] = tk.BooleanVar(value=True)
        stop_temp = ttk.Checkbutton(
            panel,
            text="Stop temperature compensation during live calibration",
            variable=self.fields["common.stop_temp"],
        )
        stop_temp.grid(row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))
        stop_topic = field_help("common.stop_temp")
        add_tooltip(stop_temp, stop_topic.summary)
        self._help_button(panel, 2, 6, "common.stop_temp")

    def _build_actions(self, parent: ttk.Frame) -> None:
        actions = ttk.Frame(parent, padding=(0, 8, 0, 0))
        actions.pack(fill="x")
        self.armed = tk.BooleanVar(value=False)
        self.hardware_check = ttk.Checkbutton(
            actions,
            text="Hardware connections checked",
            variable=self.armed,
            command=self._update_workflow_steps,
            state="disabled",
        )
        self.hardware_check.pack(anchor="w", pady=(0, 5))
        add_tooltip(
            self.hardware_check,
            "Required before a live run. Tick only after verifying detector identity, channel wiring, probe attenuation, scope range, and physical bias voltage.",
        )
        button_row = ttk.Frame(actions)
        button_row.pack(fill="x")
        self.review_button = ttk.Button(button_row, text="Review settings", command=self._review_settings)
        self.review_button.pack(side="left", padx=(0, 4))
        add_tooltip(self.review_button, "Validate the selected method and show the complete run plan before a dry run is allowed.")
        self.dry_button = ttk.Button(button_row, text="Dry run", command=lambda: self._start(False))
        self.dry_button.pack(side="left", padx=4)
        add_tooltip(
            self.dry_button,
            "Run the selected workflow with synthetic waveforms. It tests settings, analysis, plots, and files without opening the scope or changing detector bias.",
        )
        self.live_button = ttk.Button(button_row, text="Start live run", command=lambda: self._start(True), state="disabled")
        self.live_button.pack(side="left", padx=4)
        add_tooltip(
            self.live_button,
            "Start real PicoScope acquisition and send bias commands to the detector Pi. A hardware check and typed confirmation are required.",
        )
        self.stop_button = ttk.Button(button_row, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=4)
        add_tooltip(
            self.stop_button,
            "Terminate the active acquisition, preserve completed data, and ask the runner to apply the configured final hardware state.",
        )
        hv_off_button = ttk.Button(
            button_row, text="HV off", style="Danger.TButton", command=self._emergency_off
        )
        hv_off_button.pack(side="left", padx=(16, 4))
        add_tooltip(
            hv_off_button,
            "Stop the active run and command detector channels 0-3 to the HV-off state. Always verify the physical voltage after an abnormal condition.",
        )
        file_row = ttk.Frame(actions)
        file_row.pack(fill="x", pady=(5, 0))
        open_button = ttk.Button(file_row, text="Open results", command=self._open_results)
        open_button.pack(side="right")
        add_tooltip(open_button, "Open the latest run directory, or the configured output folder if no run has completed yet.")
        load_button = ttk.Button(file_row, text="Load config", command=self._load_config_file)
        load_button.pack(side="right", padx=4)
        add_tooltip(load_button, "Load and validate a previously saved JSON configuration for all three workflows.")
        save_button = ttk.Button(file_row, text="Save config", command=self._save_config_file)
        save_button.pack(side="right", padx=4)
        add_tooltip(save_button, "Validate the current fields and save the complete calibration configuration as JSON.")

    # Configuration moves between the widgets and the saved JSON structure.
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

    def _watch_fields(self) -> None:
        """Refresh the required-step display whenever an operator edits a value."""

        for variable in self.fields.values():
            variable.trace_add("write", self._field_changed)

    def _field_changed(self, *_args: object) -> None:
        self.after_idle(self._update_workflow_steps)

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

    # Review and dry-run records are tied to the exact selected configuration.
    # Editing even one value requires those steps to be repeated.
    def _workflow_signature(self, workflow: str, config: dict) -> str:
        relevant = {
            "common": config["common"],
            "workflow": workflow,
            "settings": config[workflow],
        }
        return json.dumps(relevant, sort_keys=True, separators=(",", ":"))

    def _current_validated_plan(self) -> tuple[str, dict, str]:
        workflow = self._current_workflow()
        config = self._config_from_fields()
        validate_config(workflow, config)
        return workflow, config, self._workflow_signature(workflow, config)

    def _update_workflow_steps(self) -> None:
        if not hasattr(self, "step_labels"):
            return
        valid = False
        reviewed = False
        dry_complete = False
        try:
            _workflow, _config, signature = self._current_validated_plan()
            valid = True
            reviewed = signature in self.reviewed_signatures
            dry_complete = signature in self.completed_dry_runs
        except (ConfigurationError, KeyError, tk.TclError):
            signature = ""

        if hasattr(self, "armed") and not dry_complete and self.armed.get():
            self.armed.set(False)
        hardware_ready = bool(self.armed.get()) if hasattr(self, "armed") else False
        states = (
            "done",
            "done" if valid else "current",
            "done" if reviewed else ("current" if valid else "pending"),
            "done" if dry_complete else ("current" if reviewed else "pending"),
            "done" if hardware_ready else ("current" if dry_complete else "pending"),
            "current" if self.run_active or (dry_complete and hardware_ready) else "pending",
        )
        style_for = {"done": "StepDone.TLabel", "current": "StepCurrent.TLabel", "pending": "StepPending.TLabel"}
        for label, state in zip(self.step_labels, states):
            label.configure(style=style_for[state])

        if hasattr(self, "review_button"):
            idle = not self.run_active
            self.review_button.configure(state="normal" if idle and valid else "disabled")
            self.dry_button.configure(state="normal" if idle and reviewed else "disabled")
            self.hardware_check.configure(state="normal" if idle and dry_complete else "disabled")
            self.live_button.configure(
                state="normal" if idle and reviewed and dry_complete and hardware_ready else "disabled"
            )

    def _review_settings(self) -> None:
        if self.run_active:
            return
        try:
            workflow, config, signature = self._current_validated_plan()
        except (ConfigurationError, KeyError) as exc:
            messagebox.showerror("Check settings", str(exc))
            return

        settings = config[workflow]
        if workflow == "zero_event":
            scan_line = (
                f"{len(settings['overvoltage_points_v'])} overvoltage points, "
                f"{settings['events_per_point']} events per point"
            )
        elif workflow == "dark_count":
            scan_line = (
                f"{len(settings['overvoltage_points_v'])} overvoltage points, "
                f"{settings['events_per_channel']} events per SiPM"
            )
        else:
            scan_line = (
                f"{len(settings['bias_points_v'])} absolute-bias points, "
                f"{settings['events_per_point']} events per SiPM"
            )
        summary = (
            f"Method: {workflow.replace('_', ' ')}\n"
            f"Detector: {config['common']['pi_host']}\n"
            f"Scan: {scan_line}\n"
            f"Output: {config['common']['output_root']}\n"
            f"After run: {config['common']['final_hardware_state']}\n\n"
            "Check the channel map, probe attenuation, voltage points, event count, "
            "and final hardware state. Accepting this plan unlocks the dry run."
        )
        if messagebox.askokcancel("Review calibration plan", summary, icon="info"):
            self.reviewed_signatures.add(signature)
            self.status_text.set("Settings reviewed - run the required dry run next")
            self._update_workflow_steps()

    # Run start and live-hardware confirmation
    def _start(self, live: bool) -> None:
        if self.run_active:
            messagebox.showinfo("Run active", "A calibration run is already active.")
            return
        try:
            workflow, config, signature = self._current_validated_plan()
        except (ConfigurationError, KeyError) as exc:
            messagebox.showerror("Check settings", str(exc))
            return

        if signature not in self.reviewed_signatures:
            messagebox.showerror("Review required", "Review the current settings before running this method.")
            return
        if live and signature not in self.completed_dry_runs:
            messagebox.showerror("Dry run required", "Complete a dry run with these exact settings before using hardware.")
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
        self.active_signature = signature
        self.active_run_is_live = live
        self.cancel_requested = False
        self.review_button.configure(state="disabled")
        self.dry_button.configure(state="disabled")
        self.live_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._update_workflow_steps()
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

    # Child-process output is moved back to Tkinter through a thread-safe queue.
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
                    finished_signature = self.active_signature
                    finished_live = self.active_run_is_live
                    self.process = None
                    self.run_active = False
                    self.active_signature = None
                    self.active_run_is_live = False
                    self.stop_button.configure(state="disabled")
                    returncode = int(value)
                    if returncode == 0 and not finished_live and finished_signature:
                        self.completed_dry_runs.add(finished_signature)
                    self.status_text.set("Run completed" if returncode == 0 else f"Run ended with code {returncode}")
                    self._refresh_result_images()
                    self._update_workflow_steps()
                elif kind == "error":
                    self.process = None
                    self.run_active = False
                    self.active_signature = None
                    self.active_run_is_live = False
                    self.stop_button.configure(state="disabled")
                    self.status_text.set("Run failed to start")
                    messagebox.showerror("Run error", str(value))
                    self._update_workflow_steps()
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

    # Result log and plot preview
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
