from __future__ import annotations

import getpass
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import keyring
from bs4 import BeautifulSoup
from curl_cffi import requests
from keyring.errors import KeyringError, PasswordDeleteError
from platformdirs import user_config_path


BASE_URL = "https://onewaycargo.net"
LOGIN_URL = f"{BASE_URL}/login"
LOGOUT_URL = f"{BASE_URL}/logout"
ALERT_URL = f"{BASE_URL}/onewayidv2/alert"
ALERTS_URL = f"{BASE_URL}/onewayidv2/alerts"
TRACKING_URL = f"{BASE_URL}/onewayidv2/tracking"
TRACKING_LOOKUP_URL = f"{BASE_URL}/buscar_tracking"
ORDERS_URL = f"{BASE_URL}/onewayidv2/orders"
CONFIG_DIR = user_config_path("oneway-cli", ensure_exists=True)
CONFIG_PATH = CONFIG_DIR / "config.json"
SESSION_PATH = CONFIG_DIR / "session.json"
LEGACY_CONFIG_PATH = Path.home() / ".config" / "oneway-alerts" / "config"
LEGACY_SESSION_PATH = LEGACY_CONFIG_PATH.with_name("session.json")
KEYRING_SERVICE = "oneway-cli"
TRACKING_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
ALERT_TYPES = {
    "aereo": "Aérea",
    "maritimo": "Marítima",
    "compactar": "Compactar",
    "verification": "Verificación",
    "quotation": "Cotización",
    "hold": "Hold",
}
ALERT_TYPE_LABELS = {
    "aereo": {"aerea", "aereo", "envio aereo"},
    "maritimo": {"maritima", "maritimo", "envio maritimo"},
    "compactar": {"compactar"},
    "verification": {"verificacion", "verification"},
    "quotation": {"cotizacion", "quotation"},
    "hold": {"hold"},
}
UNSUPPORTED_ALERT_TYPES = {"repack"}
FEE_CONSENT_TYPES = {"verification", "quotation", "hold"}


class OneWayError(RuntimeError):
    """Raised for expected One Way Cargo failures."""


class AuthenticationExpired(OneWayError):
    """Raised when a protected endpoint redirects to the login page."""


@dataclass(frozen=True)
class Alert:
    date: str
    type: str
    tracking: str
    status: str


@dataclass(frozen=True)
class AlertDetail:
    alert: Alert
    edit_url: str | None


@dataclass(frozen=True)
class TrackingResult:
    tracking: str
    weight: str
    dimensions: str
    arrived_miami: str
    arrived_venezuela: str
    history: list[dict[str, str]]


@dataclass(frozen=True)
class OrderCharge:
    warehouse: str
    status: str
    label: str
    total: str


@dataclass(frozen=True)
class RepackedPackage:
    warehouse: str
    tracking: str
    dimensions: str
    weight: str
    arrived_usa: str
    arrived_venezuela: str
    total: str


@dataclass(frozen=True)
class OrdersResult:
    orders: list[Order]
    total: str

    def __iter__(self):
        return iter(self.orders)

    def __len__(self) -> int:
        return len(self.orders)


@dataclass(frozen=True)
class Order:
    warehouse: str
    status: str
    tracking: str
    dimensions: str
    weight: str
    arrived_usa: str
    arrived_venezuela: str
    notes: str
    total: str
    is_detail: bool
    order_uuid: str
    charges: list[OrderCharge]
    repacked_packages: list[RepackedPackage]


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)


def atomic_write(path: Path, content: str, mode: int) -> None:
    ensure_config_dir()
    descriptor, temporary_name = tempfile.mkstemp(dir=CONFIG_DIR, prefix=f".{path.name}.")
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def legacy_credentials() -> tuple[str | None, str | None]:
    try:
        lines = LEGACY_CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    return values.get("ONEWAY_EMAIL"), values.get("ONEWAY_PASSWORD")


def configured_email() -> str | None:
    config = read_json(CONFIG_PATH)
    email = config.get("email") if config else None
    return email if isinstance(email, str) and email else None


def save_email(email: str) -> None:
    atomic_write(CONFIG_PATH, json.dumps({"email": email}), 0o600)


def validate_tracking(tracking: str) -> str:
    normalized = tracking.strip().upper()
    if len(normalized) < 8 or not TRACKING_PATTERN.fullmatch(normalized):
        raise OneWayError("El tracking debe tener al menos 8 caracteres alfanuméricos y guiones.")
    return normalized


def text(node: Any) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def form_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for field in soup.select("input[name]"):
        name = field.get("name")
        if field.get("type") == "hidden" and isinstance(name, str):
            fields[name] = str(field.get("value", ""))
    return fields


def csrf_token(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    token_input = soup.select_one('input[name="_token"]')
    token_meta = soup.select_one('meta[name="csrf-token"]')
    if token_input and token_input.get("value"):
        return str(token_input["value"])
    if token_meta and token_meta.get("content"):
        return str(token_meta["content"])
    match = re.search(
        r"['\"]X-CSRF-TOKEN['\"]\s*:\s*['\"]([^'\"]+)['\"]", html, re.IGNORECASE
    )
    return match.group(1) if match else None


def login_page(response: requests.Response) -> bool:
    return response.url.rstrip("/") == LOGIN_URL.rstrip("/") or 'id="login_form"' in response.text


def protected_get(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    response = session.get(url, timeout=30, **kwargs)
    response.raise_for_status()
    if login_page(response):
        raise AuthenticationExpired("La sesión expiró.")
    return response


def clear_session() -> None:
    SESSION_PATH.unlink(missing_ok=True)


def serialize_session(session: requests.Session) -> list[dict[str, Any]]:
    cookies = {
        cookie.name: {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": cookie.secure,
            "expires": cookie.expires,
        }
        for cookie in session.cookies.jar
        if cookie.name in {"XSRF-TOKEN", "one_way_cargo_session"}
    }
    if set(cookies) != {"XSRF-TOKEN", "one_way_cargo_session"}:
        raise OneWayError("El servidor no devolvió una sesión completa.")
    return list(cookies.values())


SESSION_MAX_AGE_SECONDS = 3600  # 1 hora


def save_session(session: requests.Session) -> None:
    atomic_write(
        SESSION_PATH,
        json.dumps({"cookies": serialize_session(session), "saved_at": time.time()}),
        0o600,
    )


def session_payload() -> dict[str, Any] | None:
    return read_json(SESSION_PATH) or read_json(LEGACY_SESSION_PATH)


def restore_session(session: requests.Session) -> bool:
    payload = session_payload()
    cookies = payload.get("cookies") if payload else None
    if not isinstance(cookies, list) or len(cookies) != 2:
        clear_session()
        return False
    names = {cookie.get("name") for cookie in cookies if isinstance(cookie, dict)}
    if names != {"XSRF-TOKEN", "one_way_cargo_session"}:
        clear_session()
        return False

    # Determine the earliest expiration boundary: cookie expires (if present)
    # or the local 1-hour limit from when the session was saved.
    saved_at = payload.get("saved_at") if isinstance(payload, dict) else None
    local_limit = (saved_at + SESSION_MAX_AGE_SECONDS) if isinstance(saved_at, int | float) else None
    now = time.time()
    for cookie in cookies:
        cookie_expires = cookie.get("expires")
        if isinstance(cookie_expires, int | float) and cookie_expires <= now:
            clear_session()
            return False
        if local_limit is not None and local_limit <= now:
            clear_session()
            return False

    try:
        for cookie in cookies:
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie["path"],
                secure=bool(cookie["secure"]),
            )
    except (KeyError, TypeError):
        clear_session()
        return False
    return True


def save_credentials(email: str, password: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, email, password)
    except KeyringError as error:
        raise OneWayError(f"No se pudo guardar la clave en el llavero del sistema: {error}") from error
    save_email(email)


def credentials(interactive: bool) -> tuple[str, str, bool]:
    environment_email = os.getenv("ONEWAY_EMAIL")
    environment_password = os.getenv("ONEWAY_PASSWORD")
    if environment_email and environment_password:
        return environment_email, environment_password, False

    email = environment_email or configured_email()
    password = environment_password
    if email and not password:
        try:
            password = keyring.get_password(KEYRING_SERVICE, email)
        except KeyringError as error:
            raise OneWayError(f"No se pudo leer el llavero del sistema: {error}") from error
    if email and password:
        return email, password, False

    legacy_email, legacy_password = legacy_credentials()
    if legacy_email and legacy_password:
        return legacy_email, legacy_password, True
    if not interactive or not sys.stdin.isatty():
        raise OneWayError("Ejecuta `oneway-cli login` o define ONEWAY_EMAIL y ONEWAY_PASSWORD.")
    email = input("Correo OneWayID: ").strip()
    password = getpass.getpass("CI / contraseña OneWayID: ")
    return email, password, True


def perform_login(session: requests.Session, email: str, password: str) -> None:
    response = session.get(LOGIN_URL, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    login_form = soup.select_one("#login_form")
    if login_form is None:
        raise OneWayError("El formulario de inicio de sesión no está disponible.")
    fields = {
        str(field["name"]): str(field.get("value", ""))
        for field in login_form.select("input[name]")
        if field.get("type") not in {"email", "password", "submit"}
    }
    # Detect and include dynamically named honeypot field (direccion_completa_*)
    honeypot_name: str | None = None
    honeypot = soup.select_one('input[name^="direccion_completa"]')
    if honeypot:
        name_val = honeypot.get("name")
        if isinstance(name_val, str):
            honeypot_name = name_val
    if honeypot_name:
        fields[honeypot_name] = ""

    valid_from = soup.select_one('input[name="valid_from"]')
    fields.update(
        {
            "email": email,
            "ci_password": password,
            "valid_from": str(valid_from.get("value", "")) if valid_from else "",
        }
    )
    time.sleep(5)
    response = session.post(LOGIN_URL, data=fields, timeout=30, allow_redirects=True)
    response.raise_for_status()
    if login_page(response):
        raise OneWayError("No se pudo iniciar sesión. Verifica el correo y la clave.")
    save_session(session)


def authenticated_session(interactive: bool = True) -> tuple[requests.Session, str]:
    session = requests.Session(impersonate="chrome")
    try:
        if restore_session(session):
            try:
                protected_get(session, ALERT_URL)
                save_session(session)
                return session, "sesión guardada"
            except AuthenticationExpired:
                clear_session()
        email, password, persist_credentials = credentials(interactive)
        perform_login(session, email, password)
        protected_get(session, ALERT_URL)
        if persist_credentials:
            save_credentials(email, password)
        return session, "inicio de sesión"
    except Exception:
        session.close()
        raise


def alert_form(session: requests.Session) -> dict[str, str]:
    response = protected_get(session, ALERT_URL)
    fields = form_fields(response.text)
    token = csrf_token(response.text)
    if not token:
        raise OneWayError("El formulario de alertas no contiene un token CSRF.")
    fields["_token"] = token
    save_session(session)
    return fields


def _find_orders_table(soup: BeautifulSoup) -> Any:
    """Locate the desktop 9-column orders table.

    Primary: table containing an anchor with */onewayidv2/orders/{uuid}.
    Fallback: first table with any 9‑cell row (empty‑orders page).
    Returns None when neither is found.
    """
    table = soup.select_one('table:has(a[href*="/onewayidv2/orders/"])')
    if table is not None:
        return table
    for candidate in soup.find_all("table"):
        for row in candidate.find_all("tr"):
            if len(row.find_all(["td", "th"])) >= 9:
                return candidate
    return None


def _is_empty_text(val: str) -> bool:
    """True for strings that represent an empty/placeholder cell."""
    return not val or val.strip("—–-\u00a0 ") == ""


def parse_orders(html: str) -> OrdersResult:
    """Parse the desktop 9-column orders table from raw HTML.

    Returns an OrdersResult with parsed main orders, their repacked packages
    and charges, and the page-provided final total.
    """
    soup = BeautifulSoup(html, "html.parser")

    orders_table = _find_orders_table(soup)
    if orders_table is None:
        raise OneWayError(
            "No se encontró la tabla de órdenes (9 columnas escritorio)."
        )

    orders: list[Order] = []
    total: str = ""

    # Accumulation state for the current main order
    pending: dict[str, Any] | None = None
    pending_charges: list[OrderCharge] = []
    pending_repacked: list[RepackedPackage] = []

    for tr in orders_table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue

        cell_texts = [text(cell) for cell in cells]

        # Total footer row — may have colspan, handle before cell count gate
        if cell_texts[0].lower().startswith("total"):
            total = cell_texts[-1]
            continue

        # Skip header row
        if cell_texts[0].lower() == "warehouse":
            continue

        # Only rows with 9+ cells are data rows
        if len(cells) < 9:
            continue

        # Main order row — has a link to /onewayidv2/orders/{uuid}
        uuid_link = tr.select_one('a[href*="/onewayidv2/orders/"]')

        if uuid_link is not None:
            # Flush previous pending order
            if pending is not None:
                orders.append(
                    Order(
                        **pending,
                        charges=list(pending_charges),
                        repacked_packages=list(pending_repacked),
                    )
                )

            href = str(uuid_link.get("href") or "")
            match = re.search(r"/onewayidv2/orders/([\w-]+)", href)
            order_uuid = match.group(1) if match else ""

            tracking = cell_texts[2].upper()
            dimensions = cell_texts[3]
            weight = cell_texts[4]

            pending = dict(
                warehouse=cell_texts[0].split()[0] if cell_texts[0] else "",
                status=cell_texts[1],
                tracking=tracking,
                dimensions=dimensions,
                weight=weight,
                arrived_usa=cell_texts[5],
                arrived_venezuela=cell_texts[6],
                notes=cell_texts[7],
                total=cell_texts[8],
                is_detail=_is_empty_text(tracking)
                and _is_empty_text(dimensions)
                and _is_empty_text(weight),
                order_uuid=order_uuid,
            )
            pending_charges = []
            pending_repacked = []
        elif pending is not None:
            # Struck-through repacked child row
            if tr.select_one(".line-through"):
                pending_repacked.append(
                    RepackedPackage(
                        warehouse=cell_texts[0],
                        tracking=cell_texts[2].upper(),
                        dimensions=cell_texts[3],
                        weight=cell_texts[4],
                        arrived_usa=cell_texts[5],
                        arrived_venezuela=cell_texts[6],
                        total=cell_texts[8],
                    )
                )
            else:
                # Fee rows — label lives in the Notes column
                notes_lower = cell_texts[7].lower()
                fee_label: str | None = None
                for candidate in ("repack fee", "storage fee", "handling fee"):
                    if candidate in notes_lower:
                        fee_label = candidate.title()
                        break

                if fee_label is not None:
                    pending_charges.append(
                        OrderCharge(
                            warehouse=cell_texts[0],
                            status=cell_texts[1],
                            label=fee_label,
                            total=cell_texts[8],
                        )
                    )

    # Flush last pending order
    if pending is not None:
        orders.append(
            Order(
                **pending,
                charges=list(pending_charges),
                repacked_packages=list(pending_repacked),
            )
        )

    return OrdersResult(orders=orders, total=total)


def orders(session: requests.Session) -> OrdersResult:
    response = protected_get(session, ORDERS_URL)
    result = parse_orders(response.text)
    save_session(session)
    return result


def parse_alert_details_html(html: str, tracking: str) -> list[AlertDetail]:
    """Parse alerts table HTML, including edit links when available.

    Pure function — no session, no network.
    """
    soup = BeautifulSoup(html, "html.parser")
    alerts: list[AlertDetail] = []
    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 4 or text(cells[2]).upper() != tracking:
            continue
        edit_link = row.select_one('a[href*="/onewayidv2/alert/"][href$="/edit"]')
        edit_url = str(edit_link["href"]) if edit_link else None
        alerts.append(
            AlertDetail(
                Alert(text(cells[0]), text(cells[1]), text(cells[2]).upper(), text(cells[3])),
                edit_url,
            )
        )
    return alerts


def parse_alerts_html(html: str, tracking: str) -> list[Alert]:
    """Parse alerts table HTML into Alert objects, filtering by tracking number."""
    return [detail.alert for detail in parse_alert_details_html(html, tracking)]


def alert_details_for_tracking(session: requests.Session, tracking: str) -> list[AlertDetail]:
    response = protected_get(session, ALERTS_URL, params={"tracking": tracking})
    alerts = parse_alert_details_html(response.text, tracking)
    save_session(session)
    return alerts


def alerts_for_tracking(session: requests.Session, tracking: str) -> list[Alert]:
    return [detail.alert for detail in alert_details_for_tracking(session, tracking)]


def alert_type_exists(alerts: list[Alert], alert_type: str) -> bool:
    labels = ALERT_TYPE_LABELS[alert_type]
    return any(
        any(label in unicodedata.normalize("NFKD", alert.type).encode("ascii", "ignore").decode().lower() for label in labels)
        for alert in alerts
    )


def create_alert(
    session: requests.Session,
    tracking: str,
    alert_type: str,
    notes: str,
    accept_storage_fee: bool,
) -> None:
    if alert_type in UNSUPPORTED_ALERT_TYPES:
        raise OneWayError(f"{alert_type} aún no está disponible en el CLI.")
    if alert_type not in ALERT_TYPES:
        raise OneWayError(f"Tipo de alerta no soportado: {alert_type}.")
    if alert_type in FEE_CONSENT_TYPES and not accept_storage_fee:
        raise OneWayError(f"{ALERT_TYPES[alert_type]} requiere --accept-storage-fee.")
    fields = alert_form(session)
    fields.update({"type": alert_type, "tracking[]": tracking, "notas": notes})
    if alert_type in FEE_CONSENT_TYPES:
        fields["consent_storage_fee"] = "on"
    response = session.post(ALERT_URL, data=fields, timeout=30, allow_redirects=False)
    if response.status_code not in {301, 302, 303}:
        raise OneWayError(f"El servidor rechazó la alerta ({response.status_code}).")
    location = urljoin(ALERT_URL, response.headers.get("location", ""))
    if location.rstrip("/") == LOGIN_URL.rstrip("/"):
        raise AuthenticationExpired("La sesión expiró durante la creación de la alerta.")


def delete_alert(session: requests.Session, tracking: str, alert_type: str) -> None:
    if alert_type in UNSUPPORTED_ALERT_TYPES or alert_type not in ALERT_TYPES:
        raise OneWayError(f"Tipo de alerta no soportado: {alert_type}.")
    matching = [
        detail
        for detail in alert_details_for_tracking(session, tracking)
        if alert_type_exists([detail.alert], alert_type)
    ]
    if not matching:
        raise OneWayError(f"No existe una alerta {ALERT_TYPES[alert_type].lower()} para {tracking}.")
    if len(matching) > 1:
        raise OneWayError(
            f"Hay varias alertas {ALERT_TYPES[alert_type].lower()} para {tracking}; elimínalas desde el sitio."
        )
    edit_url = matching[0].edit_url
    if not edit_url:
        raise OneWayError("Esta alerta no se puede eliminar desde el sitio.")

    response = protected_get(session, urljoin(ALERTS_URL, edit_url))
    soup = BeautifulSoup(response.text, "html.parser")
    delete_form = next(
        (
            form
            for form in soup.select("form")
            if (method := form.select_one('input[name="_method"]'))
            and str(method.get("value", "")).upper() == "DELETE"
        ),
        None,
    )
    if delete_form is None:
        raise OneWayError("El sitio no ofrece un formulario para eliminar esta alerta.")
    fields = form_fields(str(delete_form))
    if "_token" not in fields:
        raise OneWayError("El formulario para eliminar la alerta no contiene un token CSRF.")
    delete_url = urljoin(response.url, str(delete_form.get("action", "")))
    response = session.post(delete_url, data=fields, timeout=30, allow_redirects=False)
    if response.status_code not in {301, 302, 303}:
        raise OneWayError(f"El servidor rechazó la eliminación de la alerta ({response.status_code}).")
    location = urljoin(delete_url, response.headers.get("location", ""))
    if location.rstrip("/") == LOGIN_URL.rstrip("/"):
        raise AuthenticationExpired("La sesión expiró durante la eliminación de la alerta.")
    if any(
        alert_type_exists([detail.alert], alert_type)
        for detail in alert_details_for_tracking(session, tracking)
    ):
        raise OneWayError("El sitio no confirmó la eliminación de la alerta.")


def lookup_tracking(session: requests.Session, tracking: str) -> TrackingResult:
    response = protected_get(session, TRACKING_URL)
    csrf = csrf_token(response.text)
    if not csrf:
        raise OneWayError("La página de tracking no contiene un token CSRF.")
    response = session.post(
        TRACKING_LOOKUP_URL,
        json={"tracking": tracking},
        headers={"X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest"},
        timeout=30,
        allow_redirects=False,
    )
    if response.status_code in {301, 302, 303} or login_page(response):
        raise AuthenticationExpired("La sesión expiró al consultar el tracking.")
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise OneWayError("El servidor devolvió una respuesta de tracking inválida.") from error
    result = parse_tracking_payload(payload, tracking)
    save_session(session)
    return result


def parse_tracking_payload(payload: Any, tracking: str) -> TrackingResult:
    """Parse a tracking JSON dict into a TrackingResult.

    Pure function — no session, no network.
    Raises OneWayError when the payload is invalid.
    """
    if not isinstance(payload, dict) or "uuid" not in payload:
        raise OneWayError(f"No se encontró información para {tracking}.")
    updates = payload.get("warehouse_updates")
    history = [
        {key: str(update.get(key, "")) for key in ("title", "description", "date")}
        for update in updates
        if isinstance(update, dict)
    ] if isinstance(updates, list) else []
    return TrackingResult(
        tracking=tracking,
        weight=str(payload.get("peso", "-")),
        dimensions=str(payload.get("dimensiones", "-")),
        arrived_miami=str(payload.get("fecha_llegada_usa", "-")),
        arrived_venezuela=str(payload.get("fecha_llegada_venezuela", "-")),
        history=history,
    )


def login_credentials(email: str | None = None) -> tuple[str, str]:
    if not sys.stdin.isatty():
        raise OneWayError("`oneway-cli login` requiere una terminal interactiva.")
    email = email or input("Correo OneWayID: ").strip()
    password = getpass.getpass("CI / contraseña OneWayID: ")
    return email, password


def login(email: str | None = None, password: str | None = None) -> None:
    if email is None or password is None:
        email, password = login_credentials(email)
    session = requests.Session(impersonate="chrome")
    try:
        perform_login(session, email, password)
        protected_get(session, ALERT_URL)
        save_email(email)
        save_credentials(email, password)
    finally:
        session.close()


def logout(forget_credentials: bool = False) -> None:
    session = requests.Session(impersonate="chrome")
    try:
        if restore_session(session):
            session.get(LOGOUT_URL, timeout=30)
    finally:
        session.close()
        clear_session()
    if forget_credentials:
        email = configured_email()
        if email:
            try:
                keyring.delete_password(KEYRING_SERVICE, email)
            except PasswordDeleteError:
                pass
        CONFIG_PATH.unlink(missing_ok=True)


def session_status() -> tuple[bool, int | None]:
    payload = session_payload()
    cookies = payload.get("cookies") if payload else None
    if not isinstance(cookies, list):
        return False, None
    now = time.time()
    cookie_expirations = [
        int(cookie["expires"])
        for cookie in cookies
        if isinstance(cookie, dict) and isinstance(cookie.get("expires"), int | float)
    ]
    if cookie_expirations:
        expires = min(cookie_expirations)
    else:
        saved_at = payload.get("saved_at") if isinstance(payload, dict) else None
        if not isinstance(saved_at, int | float):
            return False, None
        expires = int(saved_at + SESSION_MAX_AGE_SECONDS)
    return expires > now, expires
