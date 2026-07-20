"""Tests for alerts HTML parsing, type matching, and tracking validation."""

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import (
    Alert,
    OneWayError,
    parse_alerts_html,
    alert_type_exists,
    validate_tracking,
)


def _html(table: str) -> str:
    return f"<html><body>{table}</body></html>"


TABLE = """<table>
<thead><tr><th>Fecha</th><th>Tipo</th><th>Tracking</th><th>Estado</th></tr></thead>
<tbody>
<tr><td>2025-06-01</td><td>Aérea</td><td>ABC123456</td><td>Activa</td></tr>
<tr><td>2025-06-02</td><td>Marítima</td><td>ABC123456</td><td>Activa</td></tr>
<tr><td>2025-06-03</td><td>Verificación</td><td>DEF789012</td><td>Activa</td></tr>
</tbody>
</table>"""


class TestParseAlertsHtml(unittest.TestCase):

    def test_matching_rows(self) -> None:
        result = parse_alerts_html(_html(TABLE), "ABC123456")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].date, "2025-06-01")
        self.assertEqual(result[0].type, "Aérea")
        self.assertEqual(result[0].tracking, "ABC123456")
        self.assertEqual(result[0].status, "Activa")
        self.assertEqual(result[1].type, "Marítima")

    def test_filters_non_matching_tracking(self) -> None:
        result = parse_alerts_html(_html(TABLE), "DEF789012")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].type, "Verificación")

    def test_no_rows_returns_empty(self) -> None:
        self.assertEqual(parse_alerts_html("<html></html>", "ABC123456"), [])

    def test_tracking_uppercased_in_output(self) -> None:
        html = _html("""<table><tbody>
<tr><td>d</td><td>t</td><td>abc123456</td><td>s</td></tr>
</tbody></table>""")
        result = parse_alerts_html(html, "ABC123456")
        self.assertEqual(result[0].tracking, "ABC123456")


class TestAlertTypeExists(unittest.TestCase):

    def test_matches_exact_and_accent_insensitive(self) -> None:
        alerts = [Alert("d", "Aérea", "TRK", "s"), Alert("d", "Marítima", "TRK", "s")]
        self.assertTrue(alert_type_exists(alerts, "aereo"))
        self.assertTrue(alert_type_exists(alerts, "maritimo"))
        self.assertFalse(alert_type_exists(alerts, "compactar"))

    def test_empty_list(self) -> None:
        self.assertFalse(alert_type_exists([], "aereo"))


class TestValidateTracking(unittest.TestCase):

    def test_valid(self) -> None:
        self.assertEqual(validate_tracking("  abc-123-def  "), "ABC-123-DEF")

    def test_invalid_raises(self) -> None:
        with self.assertRaises(OneWayError):
            validate_tracking("AB12")  # too short
        with self.assertRaises(OneWayError):
            validate_tracking("ABC@12345")  # invalid char


if __name__ == "__main__":
    unittest.main()
