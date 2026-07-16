from __future__ import annotations

import contextlib
import json
import sys
from datetime import datetime
from importlib.metadata import version
from typing import Annotated, Any

import typer
from curl_cffi.requests import RequestsError
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from typer.core import TyperCommand, TyperGroup, TyperOption

from . import client


class SpanishTyperGroup(TyperGroup):
    def get_help_option(self, ctx: Any) -> TyperOption | None:
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = "Mostrar esta ayuda y salir."
        return option


class SpanishTyperCommand(TyperCommand):
    def get_help_option(self, ctx: Any) -> TyperOption | None:
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = "Mostrar esta ayuda y salir."
        return option


app = typer.Typer(no_args_is_help=True, add_completion=True, cls=SpanishTyperGroup)
console = Console()
error_console = Console(stderr=True)
VERSION = version("oneway-cli")


def fail(message: str) -> None:
    error_console.print(f"[red]Error:[/] {message}")
    raise typer.Exit(code=1)


def version_callback(value: bool) -> None:
    if value:
        console.print(VERSION)
        raise typer.Exit()


@app.callback()
def main(
    version_flag: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Mostrar versión"),
    ] = False,
) -> None:
    """Cliente de terminal no oficial de One Way Cargo."""


def _session_spinner() -> Any:
    if sys.stderr.isatty():
        return error_console.status("Estableciendo sesión...", spinner="dots")
    return contextlib.nullcontext()


def _login_spinner() -> Any:
    if sys.stderr.isatty():
        return error_console.status("Iniciando sesión...", spinner="dots")
    return contextlib.nullcontext()


def session_or_fail(interactive: bool = True) -> tuple[client.requests.Session, str]:
    try:
        with _session_spinner():
            return client.authenticated_session(interactive=interactive)
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
        raise AssertionError("unreachable")


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "__dict__"):
        return {
            key: _serialize(value)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }
    if isinstance(obj, dict):
        return {key: _serialize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_serialize(value) for value in obj]
    return obj


def _format_cargos_cell(order: Any) -> str:
    charges = getattr(order, "charges", [])
    if not charges:
        return "-"
    lines: list[str] = []
    for charge in charges:
        label = escape(getattr(charge, "label", "") or "-")
        total = escape(getattr(charge, "total", "") or "-")
        status = escape(getattr(charge, "status", "") or "-")
        lines.append(f"{label}: {total} ({status})")
    return "\n".join(lines)


def _format_reempaques_cell(order: Any) -> str:
    packages = getattr(order, "repacked_packages", [])
    if not packages:
        return "-"
    lines: list[str] = []
    for package in packages:
        tracking = escape(getattr(package, "tracking", "") or "-")
        total = escape(getattr(package, "total", "") or "-")
        lines.append(f"{tracking} [strike]{total}[/]")
    return "\n".join(lines)


@app.command(cls=SpanishTyperCommand)
def login(
    email: Annotated[str | None, typer.Option("--email", help="Correo OneWayID")] = None,
) -> None:
    """Iniciar sesión y guardar credenciales en el llavero del sistema."""
    try:
        with _login_spinner():
            client.login(email)
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
    console.print("[green]Sesión iniciada y credenciales guardadas en el llavero del sistema.[/]")


@app.command(cls=SpanishTyperCommand)
def logout(
    forget_credentials: Annotated[
        bool, typer.Option("--forget-credentials", help="Eliminar correo y clave guardados")
    ] = False,
) -> None:
    """Cerrar sesión local y, opcionalmente, borrar credenciales guardadas."""
    try:
        client.logout(forget_credentials)
    except RequestsError as error:
        fail(str(error))
    console.print("[green]Sesión local eliminada.[/]")


@app.command("session-status", cls=SpanishTyperCommand)
def session_status() -> None:
    """Mostrar si la sesión guardada sigue activa y cuándo expira."""
    active, expires = client.session_status()
    if not active or expires is None:
        console.print("No hay una sesión activa.")
        return
    timestamp = datetime.fromtimestamp(expires).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    console.print(f"Sesión activa hasta {timestamp}.")


@app.command("create-alert", cls=SpanishTyperCommand)
def create_alert(
    tracking: Annotated[str, typer.Argument(help="Número de tracking a registrar")],
    alert_types: Annotated[
        list[str],
        typer.Option(
            "--type",
            help="Repetible: aereo, maritimo, compactar, verification, quotation o hold",
        ),
    ],
    notes: Annotated[str, typer.Option("--notes", help="Notas para la alerta")] = "",
    accept_storage_fee: Annotated[
        bool, typer.Option("--accept-storage-fee", help="Aceptar cargos de almacenamiento cuando aplique")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="No pedir confirmación")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="No crear la alerta")] = False,
) -> None:
    """Crear una o más alertas para un tracking."""
    try:
        tracking = client.validate_tracking(tracking)
        requested: list[str] = []
        for raw_type in alert_types:
            alert_type = raw_type.lower()
            if alert_type in client.UNSUPPORTED_ALERT_TYPES:
                raise client.OneWayError("repack se habilitará cuando soporte varios trackings.")
            if alert_type not in client.ALERT_TYPES:
                raise client.OneWayError(f"Tipo inválido: {alert_type}.")
            if alert_type not in requested:
                requested.append(alert_type)
        if not requested:
            raise client.OneWayError("Indica al menos un --type.")
        session, origin = session_or_fail()
        try:
            existing = client.alerts_for_tracking(session, tracking)
            missing = [
                alert_type
                for alert_type in requested
                if not client.alert_type_exists(existing, alert_type)
            ]
            if dry_run:
                action = ", ".join(client.ALERT_TYPES[alert_type] for alert_type in missing)
                console.print(f"Sesión: {origin}. Se crearían: {action or 'ninguna; ya existen'}.")
                return
            if not missing:
                console.print(f"Las alertas solicitadas ya existen para {tracking}.")
                return
            labels = ", ".join(client.ALERT_TYPES[alert_type] for alert_type in missing)
            if not yes and not typer.confirm(f"Crear alertas {labels} para {tracking}"):
                console.print("Cancelado.")
                return
            for alert_type in missing:
                try:
                    client.create_alert(session, tracking, alert_type, notes, accept_storage_fee)
                except client.AuthenticationExpired:
                    session.close()
                    session, _ = session_or_fail()
                    client.create_alert(session, tracking, alert_type, notes, accept_storage_fee)
                console.print(f"[green]Alerta {client.ALERT_TYPES[alert_type].lower()} creada:[/] {tracking}")
        finally:
            session.close()
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))


@app.command(cls=SpanishTyperCommand)
def alerts(
    tracking: Annotated[str, typer.Argument(help="Número de tracking a consultar")],
    as_json: Annotated[bool, typer.Option("--json", help="Emitir JSON")] = False,
) -> None:
    """Listar las alertas existentes de un tracking."""
    try:
        tracking = client.validate_tracking(tracking)
        session, _ = session_or_fail()
        try:
            result = client.alerts_for_tracking(session, tracking)
        finally:
            session.close()
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
        return
    if as_json:
        console.print_json(data=_serialize(result))
        return
    if not result:
        console.print(f"No hay alertas para {tracking}.")
        return
    table = Table(title=f"Alertas: {tracking}")
    table.add_column("Fecha", style="cyan")
    table.add_column("Tipo")
    table.add_column("Estado")
    for alert in result:
        table.add_row(alert.date, alert.type, alert.status)
    console.print(table)


@app.command(cls=SpanishTyperCommand)
def track(
    tracking: Annotated[str, typer.Argument(help="Número de tracking a consultar")],
    as_json: Annotated[bool, typer.Option("--json", help="Emitir JSON")] = False,
) -> None:
    """Consultar el estado, peso, dimensiones e historial de un tracking."""
    try:
        tracking = client.validate_tracking(tracking)
        session, _ = session_or_fail()
        try:
            result = client.lookup_tracking(session, tracking)
        finally:
            session.close()
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
        return
    if as_json:
        console.print_json(data=_serialize(result))
        return
    summary = Table(title=f"Tracking {result.tracking}", show_header=False)
    summary.add_row("Llegada a Miami", result.arrived_miami)
    summary.add_row("Llegada a Venezuela", result.arrived_venezuela)
    summary.add_row("Peso", result.weight)
    summary.add_row("Dimensiones", result.dimensions)
    console.print(summary)
    if result.history:
        history = Table(title="Historial")
        history.add_column("Fecha", style="cyan", no_wrap=True)
        history.add_column("Evento", style="bold")
        history.add_column("Detalle")
        for event in result.history:
            history.add_row(event["date"], event["title"], event["description"])
        console.print(history)


@app.command(cls=SpanishTyperCommand)
def orders(
    as_json: Annotated[bool, typer.Option("--json", help="Emitir JSON")] = False,
    status_filter: Annotated[
        str | None, typer.Option("--status", help="Filtrar por estado exacto o parcial")
    ] = None,
    all_rows: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Incluir órdenes principales pagadas (cargos y reempaques permanecen anidados)",
        ),
    ] = False,
) -> None:
    """Listar las órdenes principales del panel de cuentas."""
    try:
        session, _ = session_or_fail()
        try:
            result: Any = client.orders(session)
        finally:
            session.close()
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
        return

    if not hasattr(result, "orders"):
        fail("La respuesta del panel de órdenes no tiene el formato esperado.")
        return

    orders_list = list(result.orders)
    global_total = getattr(result, "total", "-")

    if status_filter:
        needle = status_filter.lower()
        orders_list = [order for order in orders_list if needle in order.status.lower()]
    elif not all_rows:
        orders_list = [order for order in orders_list if order.status.lower() != "pagado"]

    if as_json:
        console.print_json(data=_serialize({"orders": orders_list, "total": global_total}))
        return

    if not orders_list:
        console.print("No se encontraron órdenes con los filtros indicados.")
        return

    table = Table(
        title="Órdenes",
        caption=f"Total general: {escape(global_total)}",
        show_lines=True,
        pad_edge=False,
        collapse_padding=True,
    )
    table.add_column("Warehouse", style="cyan", no_wrap=True)
    table.add_column("Tracking", no_wrap=True)
    table.add_column("Estado", no_wrap=True)
    table.add_column("Peso/Vol", no_wrap=True)
    table.add_column("Llegada USA", no_wrap=True)
    table.add_column("Llegada VEN", no_wrap=True)
    table.add_column("Cargos", min_width=13, max_width=15, overflow="fold")
    table.add_column("Reempaques", min_width=13, max_width=15, overflow="fold")
    table.add_column("Total", no_wrap=True)

    for order in orders_list:
        table.add_row(
            order.warehouse,
            order.tracking,
            order.status,
            f"{order.weight}\n{order.dimensions}",
            order.arrived_usa,
            order.arrived_venezuela,
            _format_cargos_cell(order),
            _format_reempaques_cell(order),
            order.total,
        )

    console.print(table)


if __name__ == "__main__":
    app()
