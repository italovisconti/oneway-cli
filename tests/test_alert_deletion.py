"""Tests for alert deletion request and confirmation."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import ALERTS_URL, OneWayError, delete_alert


TRACKING = "ABC123456"
EDIT_URL = "https://onewaycargo.net/onewayidv2/alert/alert-uuid/edit"
DELETE_URL = "https://onewaycargo.net/onewayidv2/alert/123"
LIST_WITH_ALERT = f"""
<table><tbody><tr>
  <td>2026-07-22</td><td>Envio Aereo</td><td>{TRACKING}</td><td>Activa</td>
  <td><a href=\"{EDIT_URL}\">Editar</a></td>
</tr></tbody></table>
"""
EDIT_PAGE = f"""
<form action=\"{DELETE_URL}\" method=\"post\">
  <input type=\"hidden\" name=\"_token\" value=\"csrf-token\">
  <input type=\"hidden\" name=\"_method\" value=\"DELETE\">
</form>
"""


def response(url: str, html: str = "", status: int = 200, location: str = "") -> Mock:
    result = Mock(url=url, text=html, status_code=status, headers={"location": location})
    result.raise_for_status.return_value = None
    return result


class TestDeleteAlert(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Mock()
        self.protected_get = patch("oneway_cli.client.protected_get").start()
        self.save_session = patch("oneway_cli.client.save_session").start()

    def tearDown(self) -> None:
        patch.stopall()

    def test_deletes_matching_alert_and_confirms_its_absence(self) -> None:
        self.protected_get.side_effect = [
            response(ALERTS_URL, LIST_WITH_ALERT),
            response(EDIT_URL, EDIT_PAGE),
            response(ALERTS_URL, "<table><tbody></tbody></table>"),
        ]
        self.session.post.return_value = response(DELETE_URL, status=302, location=ALERTS_URL)

        delete_alert(self.session, TRACKING, "aereo")

        self.session.post.assert_called_once_with(
            DELETE_URL,
            data={"_token": "csrf-token", "_method": "DELETE"},
            timeout=30,
            allow_redirects=False,
        )

    def test_rejects_multiple_matching_alerts(self) -> None:
        self.protected_get.return_value = response(ALERTS_URL, LIST_WITH_ALERT + LIST_WITH_ALERT)

        with self.assertRaises(OneWayError) as error:
            delete_alert(self.session, TRACKING, "aereo")

        self.assertIn("varias alertas", str(error.exception))
        self.session.post.assert_not_called()

    def test_rejects_alert_without_edit_form(self) -> None:
        self.protected_get.side_effect = [
            response(ALERTS_URL, LIST_WITH_ALERT),
            response(EDIT_URL, "<html></html>"),
        ]

        with self.assertRaises(OneWayError) as error:
            delete_alert(self.session, TRACKING, "aereo")

        self.assertIn("formulario", str(error.exception))
        self.session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
