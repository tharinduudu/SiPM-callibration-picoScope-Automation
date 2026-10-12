import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from calibration_plots import infer_scan_directions


class ScanDirectionTests(unittest.TestCase):
    def test_one_way_scan_stays_ascending(self) -> None:
        points = [(1, 3.5), (2, 4.0), (3, 4.5), (4, 5.0)]
        self.assertEqual(
            infer_scan_directions(points),
            {1: "ascending", 2: "ascending", 3: "ascending", 4: "ascending"},
        )

    def test_return_scan_changes_direction_at_first_lower_point(self) -> None:
        points = [(1, 0.5), (2, 1.0), (3, 1.5), (4, 1.0), (5, 0.5)]
        self.assertEqual(
            infer_scan_directions(points),
            {
                1: "ascending",
                2: "ascending",
                3: "ascending",
                4: "descending",
                5: "descending",
            },
        )

    def test_decreasing_scan_is_labeled_from_first_point(self) -> None:
        points = [(1, 3.0), (2, 2.0), (3, 1.0)]
        self.assertEqual(
            infer_scan_directions(points),
            {1: "descending", 2: "descending", 3: "descending"},
        )


if __name__ == "__main__":
    unittest.main()
