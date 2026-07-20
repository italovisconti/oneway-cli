"""Tests for tracking JSON payload parsing and error paths (no networking)."""

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import (
    TrackingResult,
    OneWayError,
    parse_tracking_payload,
)

TRK = "TRK123456"


class TestParseTrackingPayload(unittest.TestCase):

    def test_valid_full(self) -> None:
        result = parse_tracking_payload({
            "uuid": "x",
            "peso": "5.2 kg",
            "dimensiones": "30×20×15",
            "fecha_llegada_usa": "2025-06-01",
            "fecha_llegada_venezuela": "2025-06-20",
            "warehouse_updates": [
                {"title": "Arrived", "description": "At Miami", "date": "2025-06-01"},
            ],
        }, TRK)
        self.assertIsInstance(result, TrackingResult)
        self.assertEqual(result.tracking, TRK)
        self.assertEqual(result.weight, "5.2 kg")
        self.assertEqual(result.dimensions, "30×20×15")
        self.assertEqual(result.arrived_miami, "2025-06-01")
        self.assertEqual(result.arrived_venezuela, "2025-06-20")
        self.assertEqual(len(result.history), 1)
        self.assertEqual(result.history[0]["title"], "Arrived")

    def test_minimal_defaults(self) -> None:
        result = parse_tracking_payload({"uuid": "x"}, TRK)
        self.assertEqual(result.weight, "-")
        self.assertEqual(result.dimensions, "-")
        self.assertEqual(result.arrived_miami, "-")
        self.assertEqual(result.arrived_venezuela, "-")
        self.assertEqual(result.history, [])

    def test_invalid_non_dict_raises(self) -> None:
        for val in (None, "string", 42, []):
            with self.subTest(case=val):
                with self.assertRaises(OneWayError):
                    parse_tracking_payload(val, TRK)

    def test_invalid_no_uuid_raises(self) -> None:
        with self.assertRaises(OneWayError):
            parse_tracking_payload({"peso": "1 kg"}, TRK)

    def test_history_robust(self) -> None:
        payload: dict = {
            "uuid": "x",
            "warehouse_updates": [
                {"title": "A", "description": "B", "date": "C"},
                "not-a-dict",
                {},
            ],
        }
        result = parse_tracking_payload(payload, TRK)
        self.assertEqual(len(result.history), 2)
        # Non-dict item skipped; empty dict yields empty strings
        self.assertEqual(result.history[1]["title"], "")


if __name__ == "__main__":
    unittest.main()
