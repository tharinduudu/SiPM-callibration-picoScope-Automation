#!/usr/bin/env python3
"""Run one gLOWCOST calibration workflow without depending on the GUI."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shlex
import signal
import sys
import time
from pathlib import Path

from calibration_core import (
    APP_DIR,
    CommandExecutor,
    CommandFailed,
    ConfigurationError,
    RunCancelled,
    RunLogger,
    load_config,
    run_tag,
    utc_now,
    validate_config,
    write_json,
)


LIVE_CONFIRMATION = "RUN_LIVE_HARDWARE"
LOCAL_LOCK = Path("/tmp/glowcost_calibration_app.lock")


class CalibrationRun:
    def __init__(self, workflow: str, config: dict, live: bool) -> None:
        self.workflow = workflow
        self.config = config
        self.live = live
        self.common = config["common"]
        self.tools = Path(self.common["automation_dir"]).expanduser()
        if not self.tools.is_absolute():
            self.tools = (APP_DIR / self.tools).resolve()
        self.output_root = Path(self.common["output_root"]).expanduser()
        self.run_root = self.output_root / f"{workflow}_{run_tag()}"
        self.run_root.mkdir(parents=True, exist_ok=False)
        self.logger = RunLogger(self.run_root / "run.log")
        self.commands = CommandExecutor(self.logger)
        self.manifest: dict[str, object] = {
            "workflow": workflow,
            "mode": "live" if live else "dry-run",
            "started_at_utc": utc_now(),
            "completed": False,
            "points": [],
        }
        write_json(self.run_root / "configuration.json", config)
        self.save_manifest()

    def save_manifest(self) -> None:
        write_json(self.run_root / "manifest.json", self.manifest)

    def ssh(self, remote_parts: list[str]) -> list[str]:
        remote_command = " ".join(shlex.quote(str(part)) for part in remote_parts)
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            self.common["pi_host"],
            remote_command,
        ]

    def stop_temperature_compensation(self) -> None:
        if not self.live or not self.common.get("stop_temperature_compensation", True):
            return
        remote = [
            "bash",
            "-lc",
            "pkill -TERM -f '[b]iasAdj.py' || true; sleep 2; "
            "pgrep -af '[b]iasAdj.py' && exit 1 || true",
        ]
        self.commands.run(self.ssh(remote))

    def start_temperature_compensation(self) -> None:
        remote = [
            "bash",
            "-lc",
            "cd /home/cosmic && nohup python3 /home/cosmic/biasAdj.py "
            ">/home/cosmic/biasAdj_calibration_restore.log 2>&1 </dev/null &",
        ]
        self.commands.run(self.ssh(remote))

    def scope_preflight(self, range_mv: int, attenuation: float) -> None:
        if not self.live:
            self.logger.write("Dry run: scope preflight skipped")
            return
        self.commands.run(
            [
                sys.executable,
                str(self.tools / "pico_capture.py"),
                "--probe",
                "--driver",
                self.common["scope_driver"],
                "--range-mv",
                str(range_mv),
                "--probe-attenuation",
                str(attenuation),
            ],
            output_path=self.run_root / "scope_preflight.json",
        )

    def set_four_channel_bias(self, dut_overvoltage: float, reference_overvoltage: float, path: Path) -> dict:
        if not self.live:
            record = {
                "mode": "dry-run",
                "dut_overvoltage_V": dut_overvoltage,
                "reference_overvoltage_V": reference_overvoltage,
            }
            write_json(path, record)
            return record
        command = self.ssh(
            [
                "python3",
                self.common["pi_four_channel_setter"],
                "--dut-overvoltage",
                str(dut_overvoltage),
                "--reference-overvoltage",
                str(reference_overvoltage),
                "--confirm",
                "SET_FOUR_SCAN_BIASES",
            ]
        )
        completed = self.commands.run(command, output_path=path)
        return json.loads(completed.stdout)

    def set_absolute_bias(self, voltage: float, channels: list[int], path: Path) -> dict:
        if not self.live:
            record = {
                "mode": "dry-run",
                "plan": {"effective_bias_v": voltage, "requested_bias_v": voltage},
            }
            write_json(path, record)
            return record
        command = self.ssh(
            [
                "python3",
                self.common["pi_bias_agent"],
                "set",
                "--voltage",
                str(voltage),
                "--channels",
                ",".join(str(channel) for channel in channels),
            ]
        )
        completed = self.commands.run(command, output_path=path)
        return json.loads(completed.stdout)

    def environment(self, path: Path) -> None:
        if not self.live:
            write_json(path, {"mode": "dry-run", "temperature_C": 20.0})
            return
        self.commands.run(
            self.ssh(["python3", self.common["pi_bias_agent"], "environment"]),
            output_path=path,
        )

    def sleep(self, seconds: float) -> None:
        if not self.live:
            return
        self.logger.write(f"Waiting {seconds:g} seconds for the bias to settle")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.commands.check_cancelled()
            time.sleep(min(0.25, deadline - time.monotonic()))

    def safe_finalize(self) -> None:
        if not self.live:
            self.manifest["final_hardware_state"] = "dry-run; hardware unchanged"
            return
        final_state = self.common["final_hardware_state"]
        try:
            if final_state == "restore_3v":
                path = self.run_root / "final_restore_3v.json"
                self.set_four_channel_bias(3.0, 3.0, path)
                self.manifest["final_hardware_state"] = "all four channels restored to 3.0 V overvoltage"
                if self.common.get("restart_temperature_compensation", False):
                    self.start_temperature_compensation()
                    self.manifest["temperature_compensation"] = "restarted"
            else:
                self.commands.run(
                    self.ssh(
                        [
                            "python3",
                            self.common["pi_bias_agent"],
                            "off",
                            "--channels",
                            "0,1,2,3",
                        ]
                    ),
                    output_path=self.run_root / "final_hv_off.json",
                )
                self.manifest["final_hardware_state"] = "HV off"
        except Exception as exc:
            self.manifest["final_hardware_state"] = f"UNKNOWN: finalization failed: {exc}"
            self.logger.write(str(self.manifest["final_hardware_state"]))

    def run(self) -> None:
        self.logger.write(f"Starting {self.workflow.replace('_', ' ')} in {'LIVE' if self.live else 'DRY-RUN'} mode")
        try:
            if self.workflow == "zero_event":
                self.run_zero_event()
            elif self.workflow == "dark_count":
                self.run_dark_count()
            else:
                self.run_vbr_search()
            self.manifest["completed"] = True
            self.manifest["finished_at_utc"] = utc_now()
        except RunCancelled as exc:
            self.manifest["cancelled"] = True
            self.manifest["error"] = str(exc)
            self.logger.write(str(exc))
            raise
        except Exception as exc:
            self.manifest["error"] = str(exc)
            self.logger.write(f"Run failed: {exc}")
            raise
        finally:
            self.commands.clear_cancellation_for_cleanup()
            self.safe_finalize()
            self.save_manifest()
            self.logger.write(f"Results: {self.run_root}")

    def run_zero_event(self) -> None:
        settings = self.config["zero_event"]
        self.scope_preflight(
            max(int(settings["channel_ranges_mv"][channel]) for channel in "ABCD"),
            max(float(settings["probe_attenuations"][channel]) for channel in "ABCD"),
        )
        self.stop_temperature_compensation()
        self.environment(self.run_root / "pre_environment.json")

        points = settings["overvoltage_points_v"]
        for index, voltage in enumerate(points, start=1):
            self.commands.check_cancelled()
            tag = str(voltage).replace(".", "p")
            point_root = self.run_root / f"step_{index:02d}_vov_{tag}V"
            point_root.mkdir(parents=True)
            point = {
                "step": index,
                "overvoltage_V": voltage,
                "status": "setting bias",
                "started_at_utc": utc_now(),
            }
            self.manifest["points"].append(point)
            self.save_manifest()

            self.set_four_channel_bias(
                float(voltage),
                float(settings["reference_overvoltage_v"]),
                point_root / "bias_set.json",
            )
            self.sleep(float(settings["settle_seconds"]))
            point["status"] = "acquiring"
            self.save_manifest()

            capture = [
                sys.executable,
                str(self.tools / "pico_scintillator_capture.py"),
                "--output",
                str(point_root / "raw"),
                "--events",
                str(settings["events_per_point"]),
                "--driver",
                self.common["scope_driver"],
                "--enabled-channels",
                "A,B,C,D",
                "--channel-ranges-mv",
                ",".join(f"{channel}={settings['channel_ranges_mv'][channel]}" for channel in "ABCD"),
                "--channel-attenuations",
                ",".join(f"{channel}={settings['probe_attenuations'][channel]}" for channel in "ABCD"),
                "--sample-interval-ns",
                str(settings["sample_interval_ns"]),
                "--pre-trigger-ns",
                str(settings["pre_trigger_ns"]),
                "--post-trigger-ns",
                str(settings["post_trigger_ns"]),
                "--trigger-channel",
                settings["reference_channels"][0],
                "--trigger-mv",
                str(settings["reference_thresholds_mv"][settings["reference_channels"][0]]),
                "--coincidence-channel",
                settings["reference_channels"][1],
                "--coincidence-trigger-mv",
                str(settings["reference_thresholds_mv"][settings["reference_channels"][1]]),
                "--auto-trigger-ms",
                str(settings["auto_trigger_ms"]),
            ]
            if not self.live:
                capture.append("--synthetic")
            self.commands.run(capture, output_path=point_root / "capture.log")

            point["status"] = "analyzing"
            self.save_manifest()
            analysis_thresholds = settings["reference_thresholds_mv"]
            if not self.live:
                # Synthetic reference pulses are intentionally modest. Lowering
                # only the dry-run selection threshold lets the complete plumbing
                # be tested without changing a saved live-hardware setting.
                analysis_thresholds = {
                    channel: min(float(settings["reference_thresholds_mv"][channel]), 100.0)
                    for channel in settings["reference_channels"]
                }
                self.logger.write(
                    "Dry run: using 100 mV maximum synthetic reference thresholds"
                )
            analysis = [
                sys.executable,
                str(self.tools / "analyze_scintillator_zero.py"),
                "--run-dir",
                str(point_root / "raw"),
                "--output",
                str(point_root / "analysis"),
                "--reference-channels",
                ",".join(settings["reference_channels"]),
                "--reference-thresholds-mv",
                ",".join(
                    f"{channel}={analysis_thresholds[channel]}"
                    for channel in settings["reference_channels"]
                ),
                "--reference-coincidence-ns",
                str(settings["reference_coincidence_ns"]),
                "--minimum-reference-events",
                str(settings["minimum_reference_events"]),
                "--dark-gate-start-ns",
                str(settings["dark_gate_start_ns"]),
                "--dark-gate-stop-ns",
                str(settings["dark_gate_stop_ns"]),
                "--signal-relative-start-ns",
                str(settings["signal_relative_start_ns"]),
                "--signal-relative-stop-ns",
                str(settings["signal_relative_stop_ns"]),
                "--dut",
                f"A:SiPM_1:{settings['sipm1_charge_gap_per_v_mV_ns'] * voltage}:"
                f"{settings['sipm1_height_gap_per_v_mv'] * voltage}",
                "--dut",
                f"B:SiPM_2:{settings['sipm2_charge_gap_per_v_mV_ns'] * voltage}:"
                f"{settings['sipm2_height_gap_per_v_mv'] * voltage}",
            ]
            try:
                self.commands.run(analysis, output_path=point_root / "analysis.log")
                point["status"] = "complete"
            except CommandFailed as exc:
                point["status"] = "analysis failed"
                point["analysis_error"] = str(exc)
                self.logger.write("Raw data retained; continuing to the next voltage point")
            point["finished_at_utc"] = utc_now()
            self.save_manifest()

        self.environment(self.run_root / "post_environment.json")
        self.commands.run(
            [
                sys.executable,
                str(Path(__file__).with_name("calibration_plots.py")),
                "zero_event",
                "--root",
                str(self.run_root),
            ],
            output_path=self.run_root / "summary.log",
        )

    def run_dark_count(self) -> None:
        settings = self.config["dark_count"]
        self.scope_preflight(int(settings["scope_range_mv"]), float(settings["probe_attenuation"]))
        self.stop_temperature_compensation()
        self.environment(self.run_root / "pre_environment.json")

        for index, voltage in enumerate(settings["overvoltage_points_v"], start=1):
            point_root = self.run_root / f"point_{index:02d}_{str(voltage).replace('.', 'p')}Vov"
            point_root.mkdir(parents=True)
            point = {"step": index, "overvoltage_V": voltage, "status": "setting bias"}
            self.manifest["points"].append(point)
            self.save_manifest()
            bias_record = self.set_four_channel_bias(
                float(voltage),
                float(settings["reference_overvoltage_v"]),
                point_root / "bias_set.json",
            )
            self.sleep(float(settings["settle_seconds"]))
            write_json(point_root / "point_metadata.json", {"overvoltage_V": voltage})

            for signal_config in settings["signals"]:
                name = signal_config["name"].replace(" ", "_")
                if self.live:
                    channel = str(signal_config["detector_channel"])
                    effective_bias = float(bias_record["plan"]["channels"][channel]["effective_bias_v"])
                else:
                    effective_bias = 50.5 + float(voltage)
                raw = point_root / "raw" / name
                analysis_dir = point_root / "analysis" / name
                capture = [
                    sys.executable,
                    str(self.tools / "pico_capture.py"),
                    "--output",
                    str(raw),
                    "--events",
                    str(settings["events_per_channel"]),
                    "--bias-v",
                    str(effective_bias),
                    "--driver",
                    self.common["scope_driver"],
                    "--range-mv",
                    str(settings["scope_range_mv"]),
                    "--probe-attenuation",
                    str(settings["probe_attenuation"]),
                    "--sample-interval-ns",
                    str(settings["sample_interval_ns"]),
                    "--pre-trigger-ns",
                    str(settings["pre_trigger_ns"]),
                    "--post-trigger-ns",
                    str(settings["post_trigger_ns"]),
                    "--trigger-channel",
                    signal_config["scope_channel"],
                    "--trigger-mv",
                    str(settings["trigger_mv"]),
                    "--auto-trigger-ms",
                    str(settings["auto_trigger_ms"]),
                ]
                if not self.live:
                    capture.append("--synthetic")
                self.commands.run(capture, output_path=point_root / f"capture_{name}.log")
                analysis = [
                    sys.executable,
                    str(self.tools / "analyze_point.py"),
                    "--run-dir",
                    str(raw),
                    "--output",
                    str(analysis_dir),
                    "--bias-v",
                    str(effective_bias),
                    "--sipm",
                    name,
                    "--detector-channel",
                    str(signal_config["detector_channel"]),
                    "--scope-channel",
                    signal_config["scope_channel"],
                    "--color",
                    signal_config["color"],
                    "--integration-mode",
                    "peak-aligned",
                ]
                try:
                    self.commands.run(analysis, output_path=point_root / f"analysis_{name}.log")
                except CommandFailed as exc:
                    point.setdefault("analysis_errors", []).append(str(exc))
            point["status"] = "complete" if not point.get("analysis_errors") else "acquired with analysis warnings"
            self.save_manifest()

        self.environment(self.run_root / "post_environment.json")
        self.commands.run(
            [
                sys.executable,
                str(Path(__file__).with_name("calibration_plots.py")),
                "dark_count",
                "--root",
                str(self.run_root),
            ],
            output_path=self.run_root / "summary.log",
        )

    def run_vbr_search(self) -> None:
        settings = self.config["vbr_search"]
        self.scope_preflight(int(settings["scope_range_mv"]), float(settings["probe_attenuation"]))
        self.stop_temperature_compensation()
        self.environment(self.run_root / "pre_environment.json")
        channels = [int(signal_config["detector_channel"]) for signal_config in settings["signals"]]

        for index, voltage in enumerate(settings["bias_points_v"], start=1):
            tag = f"bias_{float(voltage):06.3f}".replace(".", "p")
            point = {"step": index, "requested_bias_V": voltage, "status": "setting bias"}
            self.manifest["points"].append(point)
            bias_record = self.set_absolute_bias(
                float(voltage), channels, self.run_root / "bias" / f"{tag}.json"
            )
            effective_bias = float(bias_record["plan"]["effective_bias_v"])
            point["effective_bias_V"] = effective_bias
            self.sleep(float(settings["settle_seconds"]))

            for signal_config in settings["signals"]:
                raw = self.run_root / "raw" / tag / signal_config["name"]
                analysis_dir = self.run_root / "analysis" / tag / signal_config["name"]
                capture = [
                    sys.executable,
                    str(self.tools / "pico_capture.py"),
                    "--output",
                    str(raw),
                    "--events",
                    str(settings["events_per_point"]),
                    "--bias-v",
                    str(effective_bias),
                    "--driver",
                    self.common["scope_driver"],
                    "--range-mv",
                    str(settings["scope_range_mv"]),
                    "--probe-attenuation",
                    str(settings["probe_attenuation"]),
                    "--sample-interval-ns",
                    str(settings["sample_interval_ns"]),
                    "--pre-trigger-ns",
                    str(settings["pre_trigger_ns"]),
                    "--post-trigger-ns",
                    str(settings["post_trigger_ns"]),
                    "--trigger-channel",
                    signal_config["scope_channel"],
                    "--trigger-mv",
                    str(settings["trigger_mv"]),
                    "--auto-trigger-ms",
                    str(settings["auto_trigger_ms"]),
                ]
                if not self.live:
                    capture.extend(
                        [
                            "--synthetic",
                            "--synthetic-vbr-a",
                            "50.5",
                            "--synthetic-vbr-b",
                            "50.6",
                            "--synthetic-gain-a",
                            "10.0",
                            "--synthetic-gain-b",
                            "10.5",
                        ]
                    )
                self.commands.run(capture, output_path=self.run_root / f"capture_{tag}_{signal_config['name']}.log")
                analysis = [
                    sys.executable,
                    str(self.tools / "analyze_point.py"),
                    "--run-dir",
                    str(raw),
                    "--output",
                    str(analysis_dir),
                    "--bias-v",
                    str(effective_bias),
                    "--sipm",
                    signal_config["name"],
                    "--detector-channel",
                    str(signal_config["detector_channel"]),
                    "--scope-channel",
                    signal_config["scope_channel"],
                    "--color",
                    signal_config["color"],
                    "--integration-mode",
                    "peak-aligned",
                ]
                try:
                    self.commands.run(analysis, output_path=self.run_root / f"analysis_{tag}_{signal_config['name']}.log")
                except CommandFailed as exc:
                    point.setdefault("analysis_errors", []).append(str(exc))
            point["status"] = "complete" if not point.get("analysis_errors") else "acquired with analysis warnings"
            self.save_manifest()

        for signal_config in settings["signals"]:
            for metric in ("height", "area"):
                try:
                    self.commands.run(
                        [
                            sys.executable,
                            str(self.tools / "fit_vbr.py"),
                            "--run-root",
                            str(self.run_root),
                            "--signal",
                            signal_config["name"],
                            "--color",
                            signal_config["color"],
                            "--metric",
                            metric,
                        ],
                        output_path=self.run_root / f"fit_{signal_config['name']}_{metric}.log",
                    )
                except CommandFailed as exc:
                    self.manifest.setdefault("fit_errors", []).append(str(exc))
        self.environment(self.run_root / "post_environment.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", choices=("zero_event", "dark_count", "vbr_search"))
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    config = load_config(args.config)
    validate_config(args.workflow, config)
    if args.live and args.confirm != LIVE_CONFIRMATION:
        parser.error(f"Live operation requires --confirm {LIVE_CONFIRMATION}")

    LOCAL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_LOCK.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit("Another calibration run currently owns the hardware lock") from exc

        run = CalibrationRun(args.workflow, config, args.live)

        def stop_requested(_signum: int, _frame: object) -> None:
            run.commands.cancel()

        signal.signal(signal.SIGINT, stop_requested)
        signal.signal(signal.SIGTERM, stop_requested)
        try:
            run.run()
        except RunCancelled:
            raise SystemExit(130)


if __name__ == "__main__":
    try:
        main()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
