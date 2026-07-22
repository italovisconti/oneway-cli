"""Tests for perform_login: dynamic honeypot detection and credential submission."""

import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import perform_login, OneWayError, LOGIN_URL


LOGIN_PAGE_HTML = """<html><body>
<form id="login_form">
    <input type="hidden" name="_token" value="tok123">
    <input type="email" name="email">
    <input type="password" name="ci_password">
    <input type="text" name="direccion_completa_RANDOMXYZ">
    <input type="hidden" name="valid_from" value="2025-01-15">
</form>
</body></html>"""

NO_FORM_HTML = """<html><body><p>No form here</p></body></html>"""

POST_SUCCESS_HTML = """<html><body>Dashboard</body></html>"""


class TestPerformLogin(unittest.TestCase):
    """Mock-based tests for the login flow."""

    def _mock_response(self, text: str, url: str = LOGIN_URL) -> Mock:
        resp = Mock()
        resp.text = text
        resp.url = url
        resp.raise_for_status.return_value = None
        return resp

    def setUp(self):
        self.sleep_patch = patch("oneway_cli.client.time.sleep")
        self.mock_sleep = self.sleep_patch.start()
        self.save_session_patch = patch("oneway_cli.client.save_session")
        self.mock_save_session = self.save_session_patch.start()
        self.session = Mock()
        self.login_html = LOGIN_PAGE_HTML
        self.login_response = self._mock_response(self.login_html)
        self.success_response = self._mock_response(
            POST_SUCCESS_HTML, url="https://onewaycargo.net/dashboard"
        )
        self.session.get.return_value = self.login_response
        self.session.post.return_value = self.success_response

    def tearDown(self):
        self.save_session_patch.stop()
        self.sleep_patch.stop()

    # ── Dynamic honeypot detection ──────────────────────────────────────

    def test_honeypot_detected_and_submitted(self) -> None:
        """Honeypot inside #login_form with dynamic suffix is submitted empty."""
        perform_login(self.session, "user@test.com", "secret123")
        _, kwargs = self.session.post.call_args
        data = kwargs["data"]
        self.assertIn("direccion_completa_RANDOMXYZ", data)
        self.assertEqual(data["direccion_completa_RANDOMXYZ"], "")

    def test_honeypot_outside_form_is_still_detected(self) -> None:
        """Honeypot outside #login_form is found by full-page scan."""
        html = """<html><body>
<input type="text" name="direccion_completa_OUTSIDER">
<form id="login_form">
    <input type="hidden" name="_token" value="tok">
    <input type="hidden" name="valid_from" value="">
</form>
</body></html>"""
        self.session.get.return_value = self._mock_response(html)
        perform_login(self.session, "user@test.com", "secret123")
        _, kwargs = self.session.post.call_args
        data = kwargs["data"]
        self.assertIn("direccion_completa_OUTSIDER", data)
        self.assertEqual(data["direccion_completa_OUTSIDER"], "")

    def test_honeypot_missing_does_not_crash(self) -> None:
        """No direccion_completa field — login proceeds normally."""
        html = self.login_html.replace(
            '<input type="text" name="direccion_completa_RANDOMXYZ">\n    ',
            "",
        )
        self.session.get.return_value = self._mock_response(html)
        perform_login(self.session, "user@test.com", "secret123")
        self.session.post.assert_called_once()

    # ── Credential and required-field submission ────────────────────────

    def test_email_submitted(self) -> None:
        perform_login(self.session, "user@test.com", "secret123")
        _, kwargs = self.session.post.call_args
        self.assertEqual(kwargs["data"]["email"], "user@test.com")

    def test_ci_password_submitted(self) -> None:
        perform_login(self.session, "user@test.com", "secret123")
        _, kwargs = self.session.post.call_args
        self.assertEqual(kwargs["data"]["ci_password"], "secret123")

    def test_valid_from_submitted(self) -> None:
        perform_login(self.session, "user@test.com", "secret123")
        _, kwargs = self.session.post.call_args
        self.assertEqual(kwargs["data"]["valid_from"], "2025-01-15")

    def test_valid_from_missing_uses_empty(self) -> None:
        """When the page has no valid_from, an empty string is sent."""
        html = """<html><body>
<form id="login_form">
    <input type="hidden" name="_token" value="tok">
    <input type="text" name="direccion_completa_X">
</form>
</body></html>"""
        self.session.get.return_value = self._mock_response(html)
        perform_login(self.session, "a@b.com", "pw")
        _, kwargs = self.session.post.call_args
        self.assertEqual(kwargs["data"]["valid_from"], "")

    # ── Hidden fields from form_fields are included ─────────────────────

    def test_hidden_token_included(self) -> None:
        perform_login(self.session, "user@test.com", "secret123")
        _, kwargs = self.session.post.call_args
        self.assertIn("_token", kwargs["data"])
        self.assertEqual(kwargs["data"]["_token"], "tok123")

    # ── Error path ──────────────────────────────────────────────────────

    def test_no_login_form_raises(self) -> None:
        self.session.get.return_value = self._mock_response(NO_FORM_HTML)
        with self.assertRaises(OneWayError) as ctx:
            perform_login(self.session, "user@test.com", "secret123")
        self.assertIn("formulario de inicio de sesión", str(ctx.exception))
        self.session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
