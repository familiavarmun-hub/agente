"""
Agente de Correo Electrónico con IA
====================================
Script principal con menú interactivo en terminal.
Lee correos de Gmail y Outlook, y genera respuestas con ChatGPT.
"""
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.text import Text
from rich import box

from gmail_client import GmailClient
from outlook_client import OutlookClient
from ai_responder import analyze_and_respond

console = Console()

# Estado global
gmail = GmailClient()
outlook = OutlookClient()
gmail_connected = False
outlook_connected = False
cached_emails: list[dict] = []


def show_banner():
    banner = Text()
    banner.append("  AGENTE DE CORREO ELECTRÓNICO CON IA  \n", style="bold white on blue")
    banner.append("  Gmail + Outlook | Respuestas con ChatGPT  ", style="dim")
    console.print(Panel(banner, border_style="blue", expand=False))
    console.print()


def show_menu():
    console.print("\n[bold cyan]--- MENÚ PRINCIPAL ---[/bold cyan]")
    console.print("[1] Ver correos nuevos de Gmail")
    console.print("[2] Ver correos nuevos de Outlook")
    console.print("[3] Ver todos los correos nuevos (ambas cuentas)")
    console.print("[4] Leer un correo y generar respuesta con IA")
    console.print("[5] Conectar / Reconectar cuentas")
    console.print("[0] Salir")
    console.print()


def connect_gmail():
    global gmail_connected
    console.print("\n[yellow]Conectando a Gmail...[/yellow]")
    if gmail.authenticate():
        gmail_connected = True
        console.print("[green]Gmail conectado correctamente.[/green]")
    else:
        console.print("[red]No se pudo conectar a Gmail.[/red]")


def connect_outlook():
    global outlook_connected
    console.print("\n[yellow]Conectando a Outlook/Hotmail...[/yellow]")
    if outlook.authenticate():
        outlook_connected = True
        console.print("[green]Outlook conectado correctamente.[/green]")
    else:
        console.print("[red]No se pudo conectar a Outlook.[/red]")


def display_emails(emails: list[dict]):
    """Muestra una tabla con los correos."""
    global cached_emails
    cached_emails = emails

    if not emails:
        console.print("[dim]No hay correos nuevos.[/dim]")
        return

    table = Table(
        title="Correos No Leídos",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("#", style="bold", width=4, justify="center")
    table.add_column("Cuenta", style="magenta", width=8)
    table.add_column("De", style="green", max_width=30, overflow="ellipsis")
    table.add_column("Asunto", style="white", max_width=40, overflow="ellipsis")
    table.add_column("Fecha", style="dim", width=18)
    table.add_column("Vista previa", style="dim", max_width=40, overflow="ellipsis")

    for i, email in enumerate(emails, 1):
        date_display = ""
        if email.get("date"):
            date_display = email["date"].strftime("%d/%m/%Y %H:%M")
        elif email.get("date_str"):
            date_display = email["date_str"][:20]

        from_display = email.get("from", "Desconocido")
        # Acortar el campo "from" si es muy largo
        if len(from_display) > 30:
            from_display = from_display[:27] + "..."

        table.add_row(
            str(i),
            email.get("source", "?"),
            from_display,
            email.get("subject", "(Sin asunto)"),
            date_display,
            email.get("snippet", "")[:40],
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(emails)} correos no leídos[/dim]")


def fetch_gmail_emails() -> list[dict]:
    if not gmail_connected:
        console.print("[red]Gmail no está conectado. Usa la opción 5 para conectar.[/red]")
        return []
    console.print("[yellow]Obteniendo correos de Gmail...[/yellow]")
    emails = gmail.get_unread_emails()
    console.print(f"[green]Se encontraron {len(emails)} correos no leídos en Gmail.[/green]")
    return emails


def fetch_outlook_emails() -> list[dict]:
    if not outlook_connected:
        console.print("[red]Outlook no está conectado. Usa la opción 5 para conectar.[/red]")
        return []
    console.print("[yellow]Obteniendo correos de Outlook...[/yellow]")
    emails = outlook.get_unread_emails()
    console.print(f"[green]Se encontraron {len(emails)} correos no leídos en Outlook.[/green]")
    return emails


def read_and_respond():
    """Permite seleccionar un correo, verlo completo y generar respuesta con IA."""
    global cached_emails

    if not cached_emails:
        console.print("[red]No hay correos cargados. Primero usa las opciones 1-3 para cargar correos.[/red]")
        return

    console.print(f"\n[cyan]Selecciona un correo (1-{len(cached_emails)}) o 0 para cancelar:[/cyan]")
    try:
        choice = IntPrompt.ask("Número")
    except (KeyboardInterrupt, EOFError):
        return

    if choice == 0 or choice < 1 or choice > len(cached_emails):
        console.print("[dim]Cancelado.[/dim]")
        return

    email = cached_emails[choice - 1]

    # Mostrar correo completo
    console.print(Panel(
        f"[bold]De:[/bold] {email.get('from', 'Desconocido')}\n"
        f"[bold]Asunto:[/bold] {email.get('subject', 'Sin asunto')}\n"
        f"[bold]Fecha:[/bold] {email.get('date_str', 'Sin fecha')}\n"
        f"[bold]Cuenta:[/bold] {email.get('source', '?')}\n"
        f"\n{'─' * 50}\n\n"
        f"{email.get('body', email.get('snippet', 'Sin contenido'))}",
        title="Correo Completo",
        border_style="cyan",
        expand=True,
    ))

    # Preguntar si quiere generar respuesta
    generate = Prompt.ask(
        "\n[cyan]¿Generar respuesta con IA?[/cyan]",
        choices=["s", "n"],
        default="s",
    )

    if generate.lower() != "s":
        return

    console.print("\n[yellow]Analizando correo con ChatGPT...[/yellow]")

    result = analyze_and_respond(email)

    # Mostrar resultado
    category_colors = {
        "REQUIERE_RESPUESTA": "bold red",
        "INFORMATIVO": "bold yellow",
        "SPAM": "bold dim",
        "ERROR": "bold red on white",
    }
    cat_style = category_colors.get(result["category"], "bold white")

    console.print(f"\n[bold]Categoría:[/bold] [{cat_style}]{result['category']}[/{cat_style}]")
    console.print(f"[bold]Resumen:[/bold] {result.get('summary', 'N/A')}")

    if result.get("draft_response"):
        console.print(Panel(
            result["draft_response"],
            title="Borrador de Respuesta",
            border_style="green",
            expand=True,
        ))
        console.print("[dim]Puedes copiar este borrador y pegarlo en tu cliente de correo.[/dim]")
    else:
        console.print("[dim]Este correo no requiere respuesta según el análisis.[/dim]")


def connect_accounts():
    """Menú para conectar/reconectar cuentas."""
    console.print("\n[bold cyan]--- CONECTAR CUENTAS ---[/bold cyan]")
    status_g = "[green]Conectado[/green]" if gmail_connected else "[red]No conectado[/red]"
    status_o = "[green]Conectado[/green]" if outlook_connected else "[red]No conectado[/red]"
    console.print(f"  [1] Gmail     - {status_g}")
    console.print(f"  [2] Outlook   - {status_o}")
    console.print(f"  [3] Ambas")
    console.print(f"  [0] Volver")

    try:
        choice = IntPrompt.ask("Opción")
    except (KeyboardInterrupt, EOFError):
        return

    if choice == 1:
        connect_gmail()
    elif choice == 2:
        connect_outlook()
    elif choice == 3:
        connect_gmail()
        connect_outlook()


def main():
    show_banner()

    # Conexión automática al inicio
    console.print("[bold]Iniciando conexiones...[/bold]\n")

    import config as cfg
    if cfg.GMAIL_CREDENTIALS_FILE.exists():
        connect_gmail()
    else:
        console.print("[dim]Gmail: Sin credenciales configuradas (ver setup_guide.md)[/dim]")

    if cfg.OUTLOOK_CLIENT_ID:
        connect_outlook()
    else:
        console.print("[dim]Outlook: Sin Client ID configurado (ver setup_guide.md)[/dim]")

    if not cfg.OPENAI_API_KEY:
        console.print("\n[yellow]OPENAI_API_KEY no configurada. Las respuestas con IA no funcionarán.[/yellow]")
        console.print("[dim]Configúrala en el archivo .env: OPENAI_API_KEY=tu-api-key[/dim]")

    while True:
        show_menu()
        try:
            choice = IntPrompt.ask("Opción", default=0)
        except (KeyboardInterrupt, EOFError):
            break

        if choice == 1:
            emails = fetch_gmail_emails()
            display_emails(emails)

        elif choice == 2:
            emails = fetch_outlook_emails()
            display_emails(emails)

        elif choice == 3:
            all_emails = []
            if gmail_connected:
                all_emails.extend(fetch_gmail_emails())
            if outlook_connected:
                all_emails.extend(fetch_outlook_emails())
            # Ordenar por fecha (más recientes primero)
            all_emails.sort(key=lambda e: e.get("date") or "", reverse=True)
            display_emails(all_emails)

        elif choice == 4:
            read_and_respond()

        elif choice == 5:
            connect_accounts()

        elif choice == 0:
            console.print("\n[bold blue]¡Hasta luego![/bold blue]")
            break

        else:
            console.print("[red]Opción no válida.[/red]")


if __name__ == "__main__":
    main()
