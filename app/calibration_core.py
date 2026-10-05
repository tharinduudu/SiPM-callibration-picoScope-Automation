#!/usr/bin/env python3
"""Shared configuration checks and process helpers for the calibration app."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = APP_DIR / "calibration_defaults.json"
SCOPE_RANGES_MV = (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000)


class ConfigurationError(ValueError):
    """Raised before hardware is touched when a setting is unsafe or invalid."""


class RunCancelled(RuntimeError):
    """Raised when the user stops a running acquisition."""


class CommandFailed(RuntimeError):
    def __init__(self, command: list[str], returncode: int) -> None:
        self.command = command
        self.returncode = returncode
        super().__init__(f"Command failed with exit code {returncode}: {format_command(command)}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def parse_float_list(text: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in text.split(",") if item.strip()]
    except ValueError as exc:
        raise ConfigurationError("Voltage points must be comma-separated numbers") from exc
    if not values:
        raise ConfigurationError("At least one voltage point is required")
    return values


def format_float_list(values: list[float]) -> str:
    return ", ".join(f"{value:g}" for value in values)


def format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def require_number(
    value: object,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not minimum <= number <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def require_integer(value: object, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= number <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return number


def validate_common(config: dict) -> None:
    common = config.get("common", {})
    if not common.get("pi_host"):
        raise ConfigurationError("Pi host is required")
    if not common.get("automation_dir"):
        raise ConfigurationError("Automation directory is required")
    if common.get("final_hardware_state") not in {"hv_off", "restore_3v"}:
        raise ConfigurationError("Final hardware state must be 'hv_off' or 'restore_3v'")


def validate_scope(
    *,
    range_mv: float,
    attenuation: float,
    trigger_mv: float,
    name: str,
) -> None:
    if int(range_mv) not in SCOPE_RANGES_MV:
        raise ConfigurationError(f"{name} scope range is not supported by the PicoScope")
    require_number(attenuation, f"{name} probe attenuation", 1.0, 100.0)
    require_number(trigger_mv, f"{name} trigger", 0.1, 0.9 * range_mv * attenuation)


def validate_zero_event(config: dict) -> None:
    settings = config["zero_event"]
    points = settings.get("overvoltage_points_v", [])
    if not points:
        raise ConfigurationError("Zero-event scan needs at least one overvoltage")
    for point in points:
        require_number(point, "DUT overvoltage", 0.2, 4.0)
    require_number(settings["reference_overvoltage_v"], "Reference overvoltage", 1.0, 4.0)
    require_integer(settings["events_per_point"], "Events per point", 50, 100000)
    require_number(settings["settle_seconds"], "Settling time", 10, 1800)
    require_number(settings["reference_coincidence_ns"], "Coincidence window", 1, 200)
    require_number(settings["sample_interval_ns"], "Sample interval", 0.2, 50)
    require_number(settings["pre_trigger_ns"], "Pre-trigger time", 650, 10000)
    require_number(settings["post_trigger_ns"], "Post-trigger time", 220, 10000)
    require_integer(settings["minimum_reference_events"], "Minimum reference events", 10, 100000)
    if int(settings["minimum_reference_events"]) > int(settings["events_per_point"]):
        raise ConfigurationError("Minimum reference events cannot exceed events per point")

    signal_width = float(settings["signal_relative_stop_ns"]) - float(
        settings["signal_relative_start_ns"]
    )
    dark_width = float(settings["dark_gate_stop_ns"]) - float(settings["dark_gate_start_ns"])
    if signal_width <= 0 or abs(signal_width - dark_width) > 1e-9:
        raise ConfigurationError("Signal and dark windows must have the same positive width")
    if float(settings["dark_gate_start_ns"]) < -float(settings["pre_trigger_ns"]):
        raise ConfigurationError("Dark window begins before the captured waveform")

    for channel in "ABCD":
        channel_range = float(settings["channel_ranges_mv"][channel])
        attenuation = float(settings["probe_attenuations"][channel])
        trigger = float(settings["reference_thresholds_mv"].get(channel, 1.0))
        if channel in settings["reference_channels"]:
            validate_scope(
                range_mv=channel_range,
                attenuation=attenuation,
                trigger_mv=trigger,
                name=f"Channel {channel}",
            )


def validate_dark_count(config: dict) -> None:
    settings = config["dark_count"]
    for point in settings.get("overvoltage_points_v", []):
        require_number(point, "Dark-count overvoltage", 0.5, 4.0)
    if not settings.get("overvoltage_points_v"):
        raise ConfigurationError("Dark-count scan needs at least one overvoltage")
    require_integer(settings["events_per_channel"], "Events per channel", 100, 100000)
    require_number(settings["settle_seconds"], "Settling time", 10, 1800)
    validate_scope(
        range_mv=float(settings["scope_range_mv"]),
        attenuation=float(settings["probe_attenuation"]),
        trigger_mv=float(settings["trigger_mv"]),
        name="Dark-count",
    )
    _validate_signals(settings.get("signals", []))


def validate_vbr_search(config: dict) -> None:
    settings = config["vbr_search"]
    minimum = require_number(settings["minimum_bias_v"], "Minimum bias", 45, 57)
    maximum = require_number(settings["maximum_bias_v"], "Maximum bias", 50, 60)
    if minimum >= maximum:
        raise ConfigurationError("Minimum bias must be below maximum bias")
    points = settings.get("bias_points_v", [])
    if len(points) < 3:
        raise ConfigurationError("Breakdown-voltage search needs at least three bias points")
    for point in points:
        require_number(point, "Bias point", minimum, maximum)
    require_integer(settings["events_per_point"], "Events per point", 200, 100000)
    require_number(settings["settle_seconds"], "Settling time", 10, 1800)
    validate_scope(
        range_mv=float(settings["scope_range_mv"]),
        attenuation=float(settings["probe_attenuation"]),
        trigger_mv=float(settings["trigger_mv"]),
        name="Vbr search",
    )
    _validate_signals(settings.get("signals", []))


def _validate_signals(signals: list[dict]) -> None:
    if not 1 <= len(signals) <= 2:
        raise ConfigurationError("One or two SiPM signals must be configured")
    scope_channels = [item.get("scope_channel") for item in signals]
    detector_channels = [item.get("detector_channel") for item in signals]
    if any(channel not in {"A", "B", "C", "D"} for channel in scope_channels):
        raise ConfigurationError("Scope channels must be A, B, C, or D")
    if len(set(scope_channels)) != len(scope_channels):
        raise ConfigurationError("Each SiPM must use a different scope channel")
    if any(not isinstance(channel, int) or not 0 <= channel <= 7 for channel in detector_channels):
        raise ConfigurationError("Detector channels must be integers from 0 to 7")


def validate_config(workflow: str, config: dict) -> None:
    validate_common(config)
    if workflow == "zero_event":
        validate_zero_event(config)
    elif workflow == "dark_count":
        validate_dark_count(config)
    elif workflow == "vbr_search":
        validate_vbr_search(config)
    else:
        raise ConfigurationError(f"Unknown workflow: {workflow}")


@dataclass
class RunLogger:
    path: Path
    callback: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str) -> None:
        line = message.rstrip("\n")
        timestamped = f"[{datetime.now().strftime('%H:%M:%S')}] {line}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(timestamped + "\n")
        print(timestamped, flush=True)
        if self.callback:
            self.callback(timestamped)


class CommandExecutor:
    """Runs one child process at a time and can terminate it during cancellation."""

    def __init__(self, logger: RunLogger) -> None:
        self.logger = logger
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        process = self._process
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def clear_cancellation_for_cleanup(self) -> None:
        """Allow only the final hardware-safety command to run after Stop."""
        self._cancelled.clear()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise RunCancelled("Run cancelled by the user")

    def run(
        self,
        command: list[str],
        *,
        output_path: Path | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.check_cancelled()
        command = [str(part) for part in command]
        self.logger.write("$ " + format_command(command))
        collected: list[str] = []
        started = datetime.now()
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        try:
            assert self._process.stdout is not None
            for line in self._process.stdout:
                collected.append(line)
                self.logger.write(line)
                if timeout is not None and (datetime.now() - started).total_seconds() > timeout:
                    self.cancel()
                    raise TimeoutError(f"Command exceeded {timeout:g} seconds")
                self.check_cancelled()
            returncode = self._process.wait()
        finally:
            if self._process is not None and self._process.stdout is not None:
                self._process.stdout.close()
            self._process = None
        stdout = "".join(collected)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(stdout, encoding="utf-8")
        if check and returncode != 0:
            raise CommandFailed(command, returncode)
        return subprocess.CompletedProcess(command, returncode, stdout, "")
