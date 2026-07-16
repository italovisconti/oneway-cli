<p align="center">
  <img src="static/oneway-cli-logo.png" alt="oneway-cli logo" width="220"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/CLI-Typer-ff6348" alt="Typer" />
  <img src="https://img.shields.io/badge/TUI-Rich-212121" alt="Rich" />
  <img src="https://img.shields.io/badge/HTTP-curl__cffi-FF6C37" alt="curl_cffi" />
  <img src="https://img.shields.io/badge/License-MIT-4CAF50" alt="License" />
</p>

# oneway-cli

CLI no oficial para consultar trackings, historial y alertas de cuentas One Way Cargo.

## Estado

El proyecto está en desarrollo local. Antes de distribuirlo públicamente, es necesario publicar el repositorio, registrar el paquete en PyPI y verificar que la automatización cumple las condiciones de One Way Cargo.

## Características

- Inicio y cierre de sesión.
- Caché de sesión de dos horas con renovación automática.
- Consulta de tracking e historial mediante el endpoint estructurado del sitio.
- Listado de órdenes/tracking pendientes desde el panel de cuentas.
- Consulta de alertas existentes por tracking.
- Creación confirmada de alertas individuales sin duplicados.
- Salida JSON para integrar con otros scripts.

## Requisitos

- Python 3.11 o superior.
- Un llavero del sistema disponible: Keychain en macOS, Credential Manager en Windows o Secret Service en Linux.
- Cuenta activa de One Way Cargo.

## Instalación Desde Código Fuente

```bash
git clone <URL-DEL-REPOSITORIO> oneway-cli
cd oneway-cli
uv tool install .
```

Alternativa con pipx:

```bash
pipx install .
```

Para comprobar la instalación:

```bash
oneway-cli --version
oneway-cli --help
```

## Inicio De Sesión

La primera vez que se usa el CLI sin credenciales guardadas, cualquier comando protegido solicita el correo y la contraseña de la cuenta One Way Cargo. Tras un login exitoso, el CLI las guarda automáticamente:

```bash
oneway-cli track 1Z19X22R0393685602
# Correo OneWayID: correo@example.com
# CI / contraseña OneWayID:
```

También es posible iniciar sesión de forma explícita con:

```bash
oneway-cli login
```

En ambos casos:

- El correo se guarda en el directorio de configuración del sistema.
- La contraseña se guarda en el llavero del sistema (Keychain en macOS, Credential Manager en Windows, Secret Service en Linux).
- Las cookies de sesión se almacenan con permisos restringidos en el directorio de configuración de la aplicación.

Para automatización no interactiva se definen las variables de entorno `ONEWAY_EMAIL` y `ONEWAY_PASSWORD`. Tienen prioridad sobre las credenciales guardadas:

```bash
ONEWAY_EMAIL=correo@example.com ONEWAY_PASSWORD=clave oneway-cli track TRACKING
```

Para cerrar sesión:

```bash
oneway-cli logout                          # solo borra la sesión local
oneway-cli logout --forget-credentials      # también borra correo y clave del llavero
```

## Autocompletado

Typer genera scripts de autocompletado para bash, zsh y fish, pero es necesario instalarlos manualmente en el shell por seguridad (pip no modifica archivos de configuración del shell).

```bash
oneway-cli --install-completion
```

Reinicia la terminal o recarga el shell para activarla. Para ver el script sin instalarlo:

```bash
oneway-cli --show-completion
```

Una vez activo, al presionar `Tab` después de `oneway-cli` se completan comandos y opciones, junto con una breve descripción de cada uno.

## Comandos

### Listar Órdenes

```bash
oneway-cli orders
oneway-cli orders --json
oneway-cli orders --all
oneway-cli orders --status "Por Pagar"
```

Muestra las órdenes activas del panel de cuentas. Por defecto omite los detalles de costos (handling fee, storage fee, etc.) y excluye las filas marcadas como pagadas. Usa `--all` para ver todas las filas y `--status` para filtrar por un estado específico.

### Consultar Un Tracking

```bash
oneway-cli track 1Z19X22R0393685602
oneway-cli track 1Z19X22R0393685602 --json
```

Muestra llegada a Miami y Venezuela, peso, dimensiones e historial de movimientos.

### Consultar Alertas

```bash
oneway-cli alerts TRACKING
oneway-cli alerts TRACKING --json
```

### Crear Una Alerta

```bash
oneway-cli create-alert TRACKING --type aereo
oneway-cli create-alert TRACKING --type maritimo --yes
oneway-cli create-alert TRACKING --type compactar
oneway-cli create-alert TRACKING --type aereo --type compactar
```

Tipos individuales disponibles:

| Tipo API | Descripción |
| --- | --- |
| `aereo` | Alerta Aérea |
| `maritimo` | Alerta Marítima |
| `compactar` | Solicita compactar un solo paquete |
| `verification` | Solicita verificación del contenido |
| `quotation` | Solicita cotización |
| `hold` | Solicita retener un paquete |

`verification`, `quotation` y `hold` requieren una aceptación explícita del cargo de almacenamiento cuando aplique:

```bash
oneway-cli create-alert TRACKING --type verification --accept-storage-fee
```

Antes de enviar una alerta, el CLI consulta las alertas existentes del tracking y no crea un duplicado del mismo tipo. Después del envío, vuelve a consultarlas para confirmar la creación. Repetir `--type` permite crear varios tipos de alerta con una sola confirmación.

`repack` todavía no está disponible porque debe enviar varios trackings y sus consentimientos en una sola operación.

### Sesión

```bash
oneway-cli session-status
oneway-cli logout
oneway-cli logout --forget-credentials
```

`logout` elimina la sesión local. `--forget-credentials` también elimina el correo y la clave almacenada en el llavero.

## Arquitectura

```text
Typer CLI
  -> cliente HTTP curl_cffi
  -> One Way Cargo
  -> config platformdirs + credenciales keyring + caché privada de sesión
```

La autenticación respeta el campo temporal del formulario de login. Las operaciones protegidas detectan la redirección al login y no declaran éxito hasta confirmar el resultado en el sitio.

## Seguridad Y Privacidad

- No incluir la contraseña en scripts, historial de shell ni repositorios.
- El CLI usa la cuenta del usuario y realiza operaciones reales cuando no se usa `--dry-run`.
- El sitio puede cambiar sus formularios o endpoints sin aviso.
- Revisar las condiciones de One Way Cargo antes de usar o redistribuir esta herramienta.

## Desarrollo

```bash
python -m pip install --user -e .
oneway-cli --help
```

El paquete usa `src/oneway_cli/` para el código, `Typer` para comandos, `Rich` para salida, `BeautifulSoup` para analizar listados HTML y `curl_cffi` para las solicitudes autenticadas.

## Licencia

MIT. Consulta [LICENSE](LICENSE).

*Este proyecto no está afiliado, respaldado ni patrocinado por One Way Cargo. Es una herramienta independiente desarrollada por terceros.*
