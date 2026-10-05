#!/usr/bin/env python3
"""Safely set two SiPM channels to equal-overvoltage operating points."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from pi_bias_control import (
        DAC_MAX_CODE,
        DEFAULT_DAC_SCRIPT,
        DEFAULT_LOCK_FILE,
        DEFAULT_LOG_FILE,
        DEFAULT_MAX_BINARY,
        DEFAULT_STATE_FILE,
        MAX_LINEAR_MAX_CODE,
        MAX_LINEAR_MIN_CODE,
        dac_code_for_voltage,
        dac_voltage,
        high_side_voltage,
        read_environment,
        run_command,
        switch_off,
    )
except ModuleNotFoundError:
    # The deployed controller retains its original vbr_bias_control.py name.
    from vbr_bias_control import (
        DAC_MAX_CODE,
        DEFAULT_DAC_SCRIPT,
        DEFAULT_LOCK_FILE,
        DEFAULT_LOG_FILE,
        DEFAULT_MAX_BINARY,
        DEFAULT_STATE_FILE,
        MAX_LINEAR_MAX_CODE,
        MAX_LINEAR_MIN_CODE,
        dac_code_for_voltage,
        dac_voltage,
        high_side_voltage,
        read_environment,
        run_command,
        switch_off,
    )


def choose_plan(targets: dict[int, float]) -> dict[str, object]:
    midpoint = 0.5 * dac_voltage(DAC_MAX_CODE)
    candidates: list[tuple[tuple[float, float], dict[str, object]]] = []
    for max_code in range(MAX_LINEAR_MIN_CODE, MAX_LINEAR_MAX_CODE + 1):
        high_side = high_side_voltage(max_code)
        channels: dict[str, object] = {}
        valid = True
        errors: list[float] = []
        low_sides: list[float] = []
        for channel, target in targets.items():
            required_low = high_side - target
            if not 0.08 <= required_low <= dac_voltage(DAC_MAX_CODE) - 0.08:
                valid = False
                break
            dac_code = dac_code_for_voltage(required_low)
            low_side = dac_voltage(dac_code)
            effective = high_side - low_side
            error_mv = 1000.0 * (effective - target)
            channels[str(channel)] = {
                "target_bias_v": target,
                "dac_code": dac_code,
                "dac_code_hex": f"0x{dac_code:03X}",
                "low_side_v": low_side,
                "effective_bias_v": effective,
                "error_mv": error_mv,
            }
            errors.append(abs(error_mv))
            low_sides.append(low_side)
        if valid:
            plan = {
                "max1932_code": max_code,
                "max1932_code_hex": f"0x{max_code:02X}",
                "high_side_v": high_side,
                "channels": channels,
            }
            score = (max(abs(value - midpoint) for value in low_sides), max(errors))
            candidates.append((score, plan))
    if not candidates:
        raise RuntimeError("No shared calibrated MAX1932 setting can produce both target biases")
    return min(candidates, key=lambda item: item[0])[1]


def apply_plan(plan: dict[str, object], *, ramp_step: int, ramp_delay: float) -> list[str]:
    channels = sorted(int(value) for value in plan["channels"])
    messages: list[str] = []
    for channel in channels:
        messages.append(run_command([sys.executable, str(DEFAULT_DAC_SCRIPT), str(channel), "0x3FF"], False))
    messages.append(run_command([str(DEFAULT_MAX_BINARY), str(plan["max1932_code_hex"])], False))
    for channel in channels:
        target_code = int(plan["channels"][str(channel)]["dac_code"])
        codes = list(range(DAC_MAX_CODE, target_code, -max(1, ramp_step)))
        if not codes or codes[-1] != target_code:
            codes.append(target_code)
        for code in codes[1:]:
            messages.append(
                run_command([sys.executable, str(DEFAULT_DAC_SCRIPT), str(channel), f"0x{code:03X}"], False)
            )
            if ramp_delay > 0:
                time.sleep(ramp_delay)
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sipm1-channel", type=int, default=2)
    parser.add_argument("--sipm2-channel", type=int, default=0)
    parser.add_argument("--sipm1-vbr-20c", type=float, default=50.63024796943835)
    parser.add_argument("--sipm2-vbr-20c", type=float, default=51.95649336083294)
    parser.add_argument("--overvoltage-v", type=float, default=3.0)
    parser.add_argument("--temperature-coefficient-v-per-c", type=float, default=0.054)
    parser.add_argument("--reference-temperature-c", type=float, default=20.0)
    parser.add_argument("--ramp-step-codes", type=int, default=32)
    parser.add_argument("--ramp-delay-s", type=float, default=0.08)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != "SET_DUAL_BIAS":
        parser.error("live operation requires --confirm SET_DUAL_BIAS")
    if args.sipm1_channel == args.sipm2_channel:
        parser.error("the two SiPMs must use different DAC channels")

    environment = read_environment(False)
    temperature = environment.get("temperature_C")
    if temperature is None:
        raise RuntimeError(f"BME280 temperature unavailable: {environment}")
    correction = args.temperature_coefficient_v_per_c * (
        float(temperature) - args.reference_temperature_c
    )
    targets = {
        args.sipm1_channel: args.sipm1_vbr_20c + args.overvoltage_v + correction,
        args.sipm2_channel: args.sipm2_vbr_20c + args.overvoltage_v + correction,
    }
    plan = choose_plan(targets)
    record: dict[str, object] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "action": "set_dual_equal_overvoltage",
        "environment": environment,
        "reference_temperature_C": args.reference_temperature_c,
        "temperature_coefficient_V_per_C": args.temperature_coefficient_v_per_c,
        "overvoltage_V": args.overvoltage_v,
        "sipm_mapping": {
            "SIPM1": {"channel": args.sipm1_channel, "vbr_20C_V": args.sipm1_vbr_20c},
            "SIPM2": {"channel": args.sipm2_channel, "vbr_20C_V": args.sipm2_vbr_20c},
        },
        "plan": plan,
    }

    DEFAULT_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_LOCK_FILE.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            record["commands"] = apply_plan(
                plan,
                ramp_step=args.ramp_step_codes,
                ramp_delay=args.ramp_delay_s,
            )
        except Exception:
            switch_off(
                sorted(targets),
                max_binary=DEFAULT_MAX_BINARY,
                dac_script=DEFAULT_DAC_SCRIPT,
                dry_run=False,
            )
            raise
        DEFAULT_STATE_FILE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        with DEFAULT_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
