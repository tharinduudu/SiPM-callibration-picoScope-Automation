#!/usr/bin/env python3
"""Plan and apply a combined MAX1932 + low-side DAC SiPM bias point.

This file is intended to be installed on detector 10.51.100.224.  Planning and
dry-run operation work on any computer and never access hardware.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


MAX_OFF_CODE = 0x00
MAX_LINEAR_MIN_CODE = 0x45
MAX_LINEAR_MAX_CODE = 0xFF
MAX_INTERCEPT_V = 103.547086380256
MAX_SLOPE_V_PER_CODE = -0.195212522852

# Measured calibration installed in /home/cosmic/dac.py on detector .224.
DAC_VOFF_V = 0.0005
DAC_SPAN_V = 2.9968
DAC_MIN_CODE = 0
DAC_MAX_CODE = 1023

DEFAULT_MAX_BINARY = Path("/home/cosmic/mppcInterface/firmware/libraries/max1932/main")
DEFAULT_DAC_SCRIPT = Path("/home/cosmic/dac.py")
DEFAULT_STATE_FILE = Path("/home/cosmic/.vbr_bias_state.json")
DEFAULT_LOG_FILE = Path("/home/cosmic/vbr_bias_control.jsonl")
DEFAULT_LOCK_FILE = Path("/tmp/glowcost_vbr_bias.lock")


@dataclass(frozen=True)
class BiasPlan:
    requested_bias_v: float
    max1932_code: int
    max1932_code_hex: str
    high_side_v: float
    dac_code: int
    dac_code_hex: str
    low_side_v: float
    effective_bias_v: float
    error_mv: float


def high_side_voltage(code: int) -> float:
    if code == MAX_OFF_CODE:
        return 0.0
    if not MAX_LINEAR_MIN_CODE <= code <= MAX_LINEAR_MAX_CODE:
        raise ValueError(f"MAX1932 code 0x{code:02X} is outside the calibrated linear region")
    return MAX_INTERCEPT_V + MAX_SLOPE_V_PER_CODE * code


def dac_voltage(code: int) -> float:
    code = max(DAC_MIN_CODE, min(DAC_MAX_CODE, int(code)))
    return max(0.0, DAC_VOFF_V + DAC_SPAN_V * code / DAC_MAX_CODE)


def dac_code_for_voltage(voltage_v: float) -> int:
    code = round((float(voltage_v) - DAC_VOFF_V) * DAC_MAX_CODE / DAC_SPAN_V)
    return max(DAC_MIN_CODE, min(DAC_MAX_CODE, int(code)))


def plan_bias(
    requested_bias_v: float,
    *,
    minimum_bias_v: float = 50.0,
    maximum_bias_v: float = 57.0,
    preferred_low_side_v: float = 1.15,
    low_side_margin_v: float = 0.08,
) -> BiasPlan:
    if not minimum_bias_v <= requested_bias_v <= maximum_bias_v:
        raise ValueError(
            f"Requested {requested_bias_v:.3f} V is outside the permitted "
            f"{minimum_bias_v:.3f} to {maximum_bias_v:.3f} V range"
        )

    candidates: list[BiasPlan] = []
    for max_code in range(MAX_LINEAR_MIN_CODE, MAX_LINEAR_MAX_CODE + 1):
        high_v = high_side_voltage(max_code)
        required_low_v = high_v - requested_bias_v
        if not low_side_margin_v <= required_low_v <= dac_voltage(DAC_MAX_CODE) - low_side_margin_v:
            continue
        dac_code = dac_code_for_voltage(required_low_v)
        low_v = dac_voltage(dac_code)
        effective_v = high_v - low_v
        error_mv = 1000.0 * (effective_v - requested_bias_v)
        plan = BiasPlan(
            requested_bias_v=requested_bias_v,
            max1932_code=max_code,
            max1932_code_hex=f"0x{max_code:02X}",
            high_side_v=high_v,
            dac_code=dac_code,
            dac_code_hex=f"0x{dac_code:03X}",
            low_side_v=low_v,
            effective_bias_v=effective_v,
            error_mv=error_mv,
        )
        candidates.append(plan)

    if not candidates:
        raise RuntimeError(f"No calibrated MAX1932/DAC combination can produce {requested_bias_v:.3f} V")
    # Every DAC code is quantized. Select a point within half an LSB of the
    # requested voltage, then keep Vlow near midrange to retain adjustment room.
    maximum_quantization_error_mv = 1000.0 * DAC_SPAN_V / (2.0 * DAC_MAX_CODE) + 0.1
    accurate = [plan for plan in candidates if abs(plan.error_mv) <= maximum_quantization_error_mv]
    choices = accurate if accurate else candidates
    return min(
        choices,
        key=lambda plan: (abs(plan.low_side_v - preferred_low_side_v), abs(plan.error_mv)),
    )


def run_command(command: list[str], dry_run: bool) -> str:
    if dry_run:
        return "DRY-RUN: " + " ".join(command)
    completed = subprocess.run(command, check=True, text=True, capture_output=True, timeout=15)
    return completed.stdout.strip()


def write_record(path: Path, record: dict[str, object], dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def apply_plan(
    plan: BiasPlan,
    channels: list[int],
    *,
    max_binary: Path,
    dac_script: Path,
    ramp_step_codes: int,
    ramp_delay_s: float,
    dry_run: bool,
) -> list[str]:
    messages: list[str] = []

    # A maximum low-side voltage minimizes the SiPM bias while the shared
    # MAX1932 high-side setting is changed.
    for channel in channels:
        messages.append(
            run_command([sys.executable, str(dac_script), str(channel), "0x3FF"], dry_run)
        )

    messages.append(run_command([str(max_binary), plan.max1932_code_hex], dry_run))

    for channel in channels:
        codes = list(range(DAC_MAX_CODE, plan.dac_code, -max(1, ramp_step_codes)))
        if not codes or codes[-1] != plan.dac_code:
            codes.append(plan.dac_code)
        for code in codes[1:]:
            messages.append(
                run_command(
                    [sys.executable, str(dac_script), str(channel), f"0x{code:03X}"],
                    dry_run,
                )
            )
            if not dry_run and ramp_delay_s > 0:
                time.sleep(ramp_delay_s)
    return messages


def switch_off(
    channels: list[int], *, max_binary: Path, dac_script: Path, dry_run: bool
) -> list[str]:
    messages = [
        run_command([sys.executable, str(dac_script), str(channel), "0x3FF"], dry_run)
        for channel in channels
    ]
    messages.append(run_command([str(max_binary), "0x00"], dry_run))
    return messages


def parse_channels(text: str) -> list[int]:
    channels = sorted({int(value.strip(), 0) for value in text.split(",") if value.strip()})
    if not channels or any(channel < 0 or channel > 7 for channel in channels):
        raise argparse.ArgumentTypeError("channels must be a comma-separated subset of 0..7")
    return channels


def read_environment(dry_run: bool) -> dict[str, object]:
    if dry_run:
        return {"temperature_C": None, "pressure_hPa": None, "humidity_pct": None, "dry_run": True}
    try:
        import board
        import busio
        from adafruit_bme280 import basic as bme280

        i2c = busio.I2C(board.SCL, board.SDA)
        sensor = bme280.Adafruit_BME280_I2C(i2c, address=0x77)
        return {
            "temperature_C": float(sensor.temperature),
            "pressure_hPa": float(sensor.pressure),
            "humidity_pct": float(sensor.humidity),
            "sensor": "BME280@0x77",
        }
    except Exception as exc:
        return {"temperature_C": None, "pressure_hPa": None, "humidity_pct": None, "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "set", "normal", "off", "status", "environment"])
    parser.add_argument("--voltage", type=float)
    parser.add_argument("--channels", type=parse_channels, default=[0, 2])
    parser.add_argument("--minimum-bias-v", type=float, default=50.0)
    parser.add_argument("--maximum-bias-v", type=float, default=57.0)
    parser.add_argument("--max-binary", type=Path, default=DEFAULT_MAX_BINARY)
    parser.add_argument("--dac-script", type=Path, default=DEFAULT_DAC_SCRIPT)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--ramp-step-codes", type=int, default=32)
    parser.add_argument("--ramp-delay-s", type=float, default=0.08)
    parser.add_argument("--normal-max-code", type=lambda value: int(value, 0), default=0xEA)
    parser.add_argument("--normal-dac-code", type=lambda value: int(value, 0), default=0x2F1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.action in {"plan", "set"} and args.voltage is None:
        parser.error("--voltage is required for plan and set")

    if args.action == "status":
        if args.state_file.exists():
            print(args.state_file.read_text(encoding="utf-8"))
        else:
            print(json.dumps({"state": "unknown", "reason": "no state file"}, indent=2))
        return
    if args.action == "environment":
        print(json.dumps({"timestamp_utc": datetime.now(timezone.utc).isoformat(), **read_environment(args.dry_run)}, indent=2))
        return

    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        timestamp = datetime.now(timezone.utc).isoformat()

        if args.action == "off":
            messages = switch_off(
                args.channels,
                max_binary=args.max_binary,
                dac_script=args.dac_script,
                dry_run=args.dry_run,
            )
            record: dict[str, object] = {
                "timestamp_utc": timestamp,
                "action": "off",
                "channels": args.channels,
                "dry_run": args.dry_run,
                "commands": messages,
            }
        elif args.action == "normal":
            if not MAX_LINEAR_MIN_CODE <= args.normal_max_code <= MAX_LINEAR_MAX_CODE:
                parser.error("--normal-max-code is outside the calibrated MAX1932 region")
            if not DAC_MIN_CODE <= args.normal_dac_code <= DAC_MAX_CODE:
                parser.error("--normal-dac-code must be 0..1023")
            normal_high = high_side_voltage(args.normal_max_code)
            normal_low = dac_voltage(args.normal_dac_code)
            normal_plan = BiasPlan(
                requested_bias_v=normal_high - normal_low,
                max1932_code=args.normal_max_code,
                max1932_code_hex=f"0x{args.normal_max_code:02X}",
                high_side_v=normal_high,
                dac_code=args.normal_dac_code,
                dac_code_hex=f"0x{args.normal_dac_code:03X}",
                low_side_v=normal_low,
                effective_bias_v=normal_high - normal_low,
                error_mv=0.0,
            )
            record = {
                "timestamp_utc": timestamp,
                "action": "normal",
                "channels": args.channels,
                "dry_run": args.dry_run,
                "plan": asdict(normal_plan),
                "commands": apply_plan(
                    normal_plan,
                    args.channels,
                    max_binary=args.max_binary,
                    dac_script=args.dac_script,
                    ramp_step_codes=args.ramp_step_codes,
                    ramp_delay_s=args.ramp_delay_s,
                    dry_run=args.dry_run,
                ),
            }
        else:
            plan = plan_bias(
                args.voltage,
                minimum_bias_v=args.minimum_bias_v,
                maximum_bias_v=args.maximum_bias_v,
            )
            record = {
                "timestamp_utc": timestamp,
                "action": args.action,
                "channels": args.channels,
                "dry_run": args.dry_run,
                "plan": asdict(plan),
            }
            if args.action == "set":
                record["commands"] = apply_plan(
                    plan,
                    args.channels,
                    max_binary=args.max_binary,
                    dac_script=args.dac_script,
                    ramp_step_codes=args.ramp_step_codes,
                    ramp_delay_s=args.ramp_delay_s,
                    dry_run=args.dry_run,
                )

        if not args.dry_run and args.action in {"set", "normal", "off"}:
            args.state_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        write_record(args.log_file, record, args.dry_run)
        print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
