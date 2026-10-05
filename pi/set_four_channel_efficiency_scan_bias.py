#!/usr/bin/env python3
"""Set the two 9x9 cm reference tiles and scan the two GSU-tile SiPMs."""

from __future__ import annotations

import argparse
import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

from set_dual_operating_point import apply_plan, choose_plan
from vbr_bias_control import (
    DEFAULT_DAC_SCRIPT,
    DEFAULT_LOCK_FILE,
    DEFAULT_LOG_FILE,
    DEFAULT_MAX_BINARY,
    DEFAULT_STATE_FILE,
    read_environment,
    switch_off,
)


TEMPERATURE_COEFFICIENT_V_PER_C = 0.054
MIN_DUT_OVERVOLTAGE_V = 0.2
MAX_DUT_OVERVOLTAGE_V = 4.5
DEVICES = {
    0: {
        "label": "SiPM C1 - top 9x9 cm reference tile",
        "vbr_V": 50.71218812384128,
        "reference_temperature_C": 20.680859375,
        "role": "reference",
    },
    1: {
        "label": "SiPM C2 - bottom 9x9 cm reference tile",
        "vbr_V": 50.984694735109414,
        "reference_temperature_C": 20.680859375,
        "role": "reference",
    },
    2: {
        "label": "SiPM 1 - top GSU gLOWCOST tile",
        "vbr_V": 50.512,
        "reference_temperature_C": 20.4,
        "role": "dut",
    },
    3: {
        "label": "SiPM 2 - bottom GSU gLOWCOST tile",
        "vbr_V": 50.574,
        "reference_temperature_C": 20.4,
        "role": "dut",
    },
}


def corrected_vbr(device: dict[str, object], temperature_c: float) -> float:
    return float(device["vbr_V"]) + TEMPERATURE_COEFFICIENT_V_PER_C * (
        temperature_c - float(device["reference_temperature_C"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dut-overvoltage", type=float, required=True)
    parser.add_argument("--reference-overvoltage", type=float, default=3.0)
    parser.add_argument("--ramp-step-codes", type=int, default=32)
    parser.add_argument("--ramp-delay-s", type=float, default=0.08)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    if args.confirm != "SET_FOUR_SCAN_BIASES":
        parser.error("live operation requires --confirm SET_FOUR_SCAN_BIASES")
    if not MIN_DUT_OVERVOLTAGE_V <= args.dut_overvoltage <= MAX_DUT_OVERVOLTAGE_V:
        parser.error(
            f"DUT overvoltage must be between {MIN_DUT_OVERVOLTAGE_V} "
            f"and {MAX_DUT_OVERVOLTAGE_V} V"
        )
    if not 1.0 <= args.reference_overvoltage <= 4.0:
        parser.error("reference overvoltage must be between 1.0 and 4.0 V")

    environment = read_environment(False)
    temperature_c = float(environment["temperature_C"])
    targets: dict[int, float] = {}
    mapping: dict[str, dict[str, object]] = {}
    for channel, device in DEVICES.items():
        vbr_at_temperature = corrected_vbr(device, temperature_c)
        overvoltage = (
            args.reference_overvoltage
            if device["role"] == "reference"
            else args.dut_overvoltage
        )
        targets[channel] = vbr_at_temperature + overvoltage
        mapping[str(channel)] = {
            **device,
            "vbr_at_temperature_V": vbr_at_temperature,
            "requested_overvoltage_V": overvoltage,
            "target_bias_V": targets[channel],
        }

    plan = choose_plan(targets)
    record: dict[str, object] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "action": "set_four_channel_efficiency_scan_bias",
        "environment": environment,
        "temperature_coefficient_V_per_C": TEMPERATURE_COEFFICIENT_V_PER_C,
        "reference_overvoltage_V": args.reference_overvoltage,
        "dut_overvoltage_V": args.dut_overvoltage,
        "channel_mapping": mapping,
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
                sorted(DEVICES),
                max_binary=DEFAULT_MAX_BINARY,
                dac_script=DEFAULT_DAC_SCRIPT,
                dry_run=False,
            )
            raise
        DEFAULT_STATE_FILE.write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        with DEFAULT_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
