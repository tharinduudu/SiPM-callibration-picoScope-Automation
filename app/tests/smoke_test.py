#!/usr/bin/env python3
"""Short synthetic run through all three calibration workflows."""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from calibration_core import load_config, write_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="glowcost_smoke_") as temporary:
        root = Path(temporary)
        config = copy.deepcopy(load_config())
        config["common"]["automation_dir"] = str(args.tools.resolve())
        config["common"]["output_root"] = str(root / "runs")

        config["zero_event"]["overvoltage_points_v"] = [1.0]
        config["zero_event"]["events_per_point"] = 100
        config["zero_event"]["minimum_reference_events"] = 50
        config["zero_event"]["settle_seconds"] = 10

        config["dark_count"]["overvoltage_points_v"] = [2.0]
        config["dark_count"]["events_per_channel"] = 100
        config["dark_count"]["settle_seconds"] = 10

        config["vbr_search"]["bias_points_v"] = [52.5, 54.0, 55.5]
        config["vbr_search"]["events_per_point"] = 200
        config["vbr_search"]["settle_seconds"] = 10

        config_path = root / "smoke_config.json"
        write_json(config_path, config)
        for workflow in ("zero_event", "dark_count", "vbr_search"):
            print(f"\n=== {workflow} ===", flush=True)
            subprocess.run(
                [
                    sys.executable,
                    str(APP_DIR / "calibration_runner.py"),
                    workflow,
                    "--config",
                    str(config_path),
                    "--dry-run",
                ],
                check=True,
            )
        print(f"\nAll synthetic workflows passed. Temporary results were in {root}")


if __name__ == "__main__":
    main()
