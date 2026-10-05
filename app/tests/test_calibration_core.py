import copy
import tempfile
import unittest
from pathlib import Path

import sys

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from calibration_core import (  # noqa: E402
    CommandExecutor,
    ConfigurationError,
    RunLogger,
    format_float_list,
    load_config,
    parse_float_list,
    validate_config,
)


class ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()

    def test_default_workflows_are_valid(self) -> None:
        for workflow in ("zero_event", "dark_count", "vbr_search"):
            validate_config(workflow, self.config)

    def test_float_list_round_trip(self) -> None:
        values = [0.35, 0.5, 1.25]
        self.assertEqual(parse_float_list(format_float_list(values)), values)

    def test_zero_event_rejects_unequal_gate_widths(self) -> None:
        config = copy.deepcopy(self.config)
        config["zero_event"]["dark_gate_stop_ns"] = -310
        with self.assertRaisesRegex(ConfigurationError, "same positive width"):
            validate_config("zero_event", config)

    def test_vbr_rejects_out_of_bounds_point(self) -> None:
        config = copy.deepcopy(self.config)
        config["vbr_search"]["bias_points_v"][0] = 49.0
        with self.assertRaisesRegex(ConfigurationError, "Bias point"):
            validate_config("vbr_search", config)

    def test_minimum_reference_count_cannot_exceed_capture(self) -> None:
        config = copy.deepcopy(self.config)
        config["zero_event"]["events_per_point"] = 100
        config["zero_event"]["minimum_reference_events"] = 101
        with self.assertRaisesRegex(ConfigurationError, "cannot exceed"):
            validate_config("zero_event", config)


class ProcessTests(unittest.TestCase):
    def test_command_output_is_logged_and_saved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executor = CommandExecutor(RunLogger(root / "run.log"))
            result = executor.run(
                [sys.executable, "-c", "print('calibration check')"],
                output_path=root / "command.txt",
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("calibration check", (root / "command.txt").read_text())
            self.assertIn("calibration check", (root / "run.log").read_text())


if __name__ == "__main__":
    unittest.main()
