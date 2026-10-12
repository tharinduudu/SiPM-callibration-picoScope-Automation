import unittest
from pathlib import Path

import sys

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from help_content import field_help, help_keys  # noqa: E402


class HelpContentTests(unittest.TestCase):
    def test_every_fixed_input_has_a_full_help_page(self) -> None:
        expected = {
            "common.pi",
            "common.tools",
            "common.output",
            "common.final",
            "common.stop_temp",
            "zero.points",
            "zero.reference_vov",
            "zero.events",
            "zero.settle",
            "zero.minimum_refs",
            "zero.threshold_c",
            "zero.threshold_d",
            "zero.coincidence",
            "zero.sample",
            "zero.pre",
            "zero.post",
            "zero.auto",
            "zero.dark_start",
            "zero.dark_stop",
            "zero.signal_start",
            "zero.signal_stop",
            "zero.s1_charge",
            "zero.s2_charge",
            "zero.s1_height",
            "zero.s2_height",
            "dark.points",
            "dark.reference_vov",
            "dark.events",
            "dark.settle",
            "dark.trigger",
            "dark.range",
            "dark.atten",
            "dark.sample",
            "dark.pre",
            "dark.post",
            "dark.auto",
            "vbr.points",
            "vbr.minimum",
            "vbr.maximum",
            "vbr.events",
            "vbr.settle",
            "vbr.trigger",
            "vbr.range",
            "vbr.atten",
            "vbr.sample",
            "vbr.pre",
            "vbr.post",
            "vbr.auto",
        }
        self.assertTrue(expected.issubset(help_keys()))
        for key in expected:
            topic = field_help(key)
            self.assertTrue(topic.title)
            self.assertGreater(len(topic.summary), 15)
            self.assertGreater(len(topic.why), 15)
            self.assertGreater(len(topic.choose), 15)

    def test_repeated_channel_inputs_receive_contextual_help(self) -> None:
        for key in (
            "zero.range_A",
            "zero.atten_D",
            "dark.name_1",
            "dark.detector_2",
            "vbr.scope_1",
        ):
            topic = field_help(key)
            self.assertNotEqual(topic.title, "Setting")
            self.assertTrue(topic.diagram)


if __name__ == "__main__":
    unittest.main()
