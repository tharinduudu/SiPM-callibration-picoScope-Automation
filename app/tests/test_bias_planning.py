import sys
import unittest
from pathlib import Path


PI_DIR = Path(__file__).resolve().parents[2] / "pi"
sys.path.insert(0, str(PI_DIR))

from set_dual_operating_point import choose_plan  # noqa: E402
from vbr_bias_control import dac_voltage, high_side_voltage, plan_bias  # noqa: E402


class BiasPlanningTests(unittest.TestCase):
    def test_single_target_is_within_half_a_dac_step(self) -> None:
        plan = plan_bias(53.5)
        self.assertAlmostEqual(
            plan.effective_bias_v,
            plan.high_side_v - plan.low_side_v,
            places=12,
        )
        self.assertLessEqual(abs(plan.error_mv), 1.6)
        self.assertAlmostEqual(plan.high_side_v, high_side_voltage(plan.max1932_code))
        self.assertAlmostEqual(plan.low_side_v, dac_voltage(plan.dac_code))

    def test_shared_high_side_reaches_each_channel_target(self) -> None:
        targets = {0: 53.25, 1: 53.90, 2: 54.10, 3: 53.60}
        plan = choose_plan(targets)
        self.assertEqual(set(plan["channels"]), {"0", "1", "2", "3"})
        for channel, target in targets.items():
            channel_plan = plan["channels"][str(channel)]
            self.assertLessEqual(abs(channel_plan["effective_bias_v"] - target), 0.0016)

    def test_out_of_range_target_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_bias(60.0)


if __name__ == "__main__":
    unittest.main()
