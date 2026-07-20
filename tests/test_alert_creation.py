"""Tests for create_alert: validation, redirect/auth, and server confirmation."""

import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import (
    Alert,
    OneWayError,
    AuthenticationExpired,
    create_alert,
    ALERT_URL,
    LOGIN_URL,
)

TRK = "ABC123456"


class TestCreateAlertValidation(unittest.TestCase):
    """Pure validation — no mocks needed."""

    def test_fee_consent_and_unknown_type(self) -> None:
        with self.assertRaises(OneWayError) as ctx:
            create_alert(Mock(), TRK, "verification", "", False)
        self.assertIn("--accept-storage-fee", str(ctx.exception))

        with self.assertRaises(OneWayError) as ctx:
            create_alert(Mock(), TRK, "repack", "", False)
        self.assertIn("repack", str(ctx.exception))

        with self.assertRaises(OneWayError) as ctx:
            create_alert(Mock(), TRK, "bogus", "", False)
        self.assertIn("bogus", str(ctx.exception))


class TestCreateAlertNetwork(unittest.TestCase):
    """Mock-based tests for network response paths."""

    def setUp(self) -> None:
        self.session = Mock()
        self.af_patch = patch("oneway_cli.client.alert_form", return_value={"_token": "t"})
        self.al_patch = patch("oneway_cli.client.alerts_for_tracking")
        self.mock_af = self.af_patch.start()
        self.mock_al = self.al_patch.start()

    def tearDown(self) -> None:
        self.af_patch.stop()
        self.al_patch.stop()

    def _set_response(self, status: int = 302, location: str = f"{ALERT_URL}/ok") -> None:
        resp = Mock(status_code=status, headers={"location": location})
        self.session.post.return_value = resp

    def test_non_redirect_rejected(self) -> None:
        self._set_response(status=200)
        with self.assertRaises(OneWayError) as ctx:
            create_alert(self.session, TRK, "aereo", "", False)
        self.assertIn("200", str(ctx.exception))

    def test_redirect_to_login_expired(self) -> None:
        self._set_response(location=LOGIN_URL)
        with self.assertRaises(AuthenticationExpired):
            create_alert(self.session, TRK, "aereo", "", False)

    def test_non_login_redirect_succeeds_without_polling(self) -> None:
        """A non-login 302 is authoritative — no POST-confirmation GET."""
        self._set_response()
        create_alert(self.session, TRK, "aereo", "", False)
        self.mock_al.assert_not_called()

    def test_successful_creation(self) -> None:
        self._set_response()
        self.mock_al.return_value = [Alert("d", "Aérea", TRK, "s")]
        create_alert(self.session, TRK, "aereo", "", False)
        self.session.post.assert_called_once()
        self.mock_af.assert_called_once_with(self.session)

    def test_fee_consent_field_sent(self) -> None:
        self._set_response()
        self.mock_al.return_value = [Alert("d", "Verificación", TRK, "s")]
        create_alert(self.session, TRK, "verification", "", True)
        data = self.session.post.call_args[1]["data"]
        self.assertEqual(data["consent_storage_fee"], "on")


if __name__ == "__main__":
    unittest.main()
