"""Tests for login form submission."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from oneway_cli.client import LOGIN_URL, login_credentials, perform_login


class TestPerformLogin(unittest.TestCase):
    def test_uses_current_honeypot_name_from_login_form(self) -> None:
        login_page = """
        <form id="login_form">
          <input name="direccion_completa_newHoneypot" type="text" value="">
          <input name="valid_from" type="text" value="encrypted-value">
          <input name="_token" type="hidden" value="csrf-token">
          <input name="email" type="email" value="">
          <input name="ci_password" type="password">
        </form>
        """
        response = Mock(url="https://onewaycargo.net/onewayidv2/alert", text="dashboard")
        session = Mock()
        session.get.return_value = Mock(text=login_page)
        session.post.return_value = response

        with patch("oneway_cli.client.time.sleep"):
            with patch("oneway_cli.client.save_session"):
                perform_login(session, "user@example.com", "secret")

        session.post.assert_called_once_with(
            LOGIN_URL,
            data={
                "direccion_completa_newHoneypot": "",
                "valid_from": "encrypted-value",
                "_token": "csrf-token",
                "email": "user@example.com",
                "ci_password": "secret",
            },
            timeout=30,
            allow_redirects=True,
        )


class TestLoginCredentials(unittest.TestCase):
    @patch("oneway_cli.client.getpass.getpass", return_value="secret")
    @patch("oneway_cli.client.input", return_value=" user@example.com ")
    @patch("oneway_cli.client.sys.stdin.isatty", return_value=True)
    def test_prompts_for_email_and_password(self, _isatty: Mock, prompt_email: Mock, prompt_password: Mock) -> None:
        email, password = login_credentials()

        self.assertEqual((email, password), ("user@example.com", "secret"))
        prompt_email.assert_called_once_with("Correo OneWayID: ")
        prompt_password.assert_called_once_with("CI / contraseña OneWayID: ")


if __name__ == "__main__":
    unittest.main()
