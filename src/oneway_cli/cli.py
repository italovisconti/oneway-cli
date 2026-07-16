from __future__ import annotations

import json
from datetime import datetime
from importlib.metadata import version
from typing import Annotated

import typer
from curl_cffi.requests import RequestsError
from rich.console import Console
from rich.table import Table

from . import client


app = typer.Typer(no_args_is_help=True, add_completion=True)
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


def session_or_fail(interactive: bool = True) -> tuple[client.requests.Session, str]:
    try:
        return client.authenticated_session(interactive=interactive)
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
        raise AssertionError("unreachable")


@app.command()
def login(
    email: Annotated[str | None, typer.Option("--email", help="Correo OneWayID")] = None,
) -> None:
    try:
        client.login(email)
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
    console.print("[green]Sesión iniciada y credenciales guardadas en el llavero del sistema.[/]")


@app.command()
def logout(
    forget_credentials: Annotated[
        bool, typer.Option("--forget-credentials", help="Eliminar correo y clave guardados")
    ] = False,
) -> None:
    try:
        client.logout(forget_credentials)
    except RequestsError as error:
        fail(str(error))
    console.print("[green]Sesión local eliminada.[/]")


@app.command("session-status")
def session_status() -> None:
    active, expires = client.session_status()
    if not active or expires is None:
        console.print("No hay una sesión activa.")
        return
    timestamp = datetime.fromtimestamp(expires).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    console.print(f"Sesión activa hasta {timestamp}.")


@app.command("create-alert")
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


@app.command()
def alerts(
    tracking: Annotated[str, typer.Argument(help="Número de tracking a consultar")],
    as_json: Annotated[bool, typer.Option("--json", help="Emitir JSON")] = False,
) -> None:
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
        console.print_json(json.dumps([alert.__dict__ for alert in result], ensure_ascii=False))
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


@app.command()
def track(
    tracking: Annotated[str, typer.Argument(help="Número de tracking a consultar")],
    as_json: Annotated[bool, typer.Option("--json", help="Emitir JSON")] = False,
) -> None:
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
        console.print_json(json.dumps(result.__dict__, ensure_ascii=False))
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


@app.command()
def orders(
    as_json: Annotated[bool, typer.Option("--json", help="Emitir JSON")] = False,
    status_filter: Annotated[
        str | None, typer.Option("--status", help="Filtrar por estado exacto o parcial")
    ] = None,
    all_rows: Annotated[
        bool, typer.Option("--all", help="Mostrar todas las filas incluyendo detalles de costos")
    ] = False,
) -> None:
    try:
        session, _ = session_or_fail()
        try:
            result = client.orders(session)
        finally:
            session.close()
    except (client.OneWayError, RequestsError) as error:
        fail(str(error))
        return
    if not all_rows:
        result = [order for order in result if not order.is_detail]
    if status_filter:
        needle = status_filter.lower()
        result = [order for order in result if needle in order.status.lower()]
    else:
        result = [order for order in result if order.status.lower() != "pagado"]
    if as_json:
        console.print_json(json.dumps([order.__dict__ for order in result], ensure_ascii=False))
        return
    if not result:
        console.print("No se encontraron órdenes pendientes.")
        return
    table = Table(title="Órdenes pendientes")
    table.add_column("Warehouse", style="cyan")
    table.add_column("Tracking")
    table.add_column("Status")
    table.add_column("Peso/Vol")
    table.add_column("Llegada USA")
    table.add_column("Total")
    for order in result:
        table.add_row(
            order.warehouse,
            order.tracking,
            order.status,
            order.weight,
            order.arrived_usa,
            order.total,
        )
    console.print(table)


if __name__ == "__main__":
    app()
