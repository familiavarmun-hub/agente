"""
Blueprint de autenticación para Gmail, Outlook e IMAP.
"""
import threading

from flask import Blueprint, redirect, url_for, session, render_template, jsonify, flash, request

import config
from email_service import (
    get_gmail_client, get_outlook_client,
    set_gmail_connected, set_outlook_connected,
    add_imap_client, remove_imap_client,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# Estado del device flow de Outlook (por sesión)
_outlook_auth_state: dict = {}  # {"flow": dict, "thread": Thread, "result": str}


# --- Gmail ---

@auth_bp.route("/gmail/connect")
def gmail_connect():
    """Redirige al usuario a la pantalla de autorización de Google."""
    try:
        redirect_uri = config.GMAIL_REDIRECT_URI or url_for("auth.gmail_callback", _external=True)
        flow = get_gmail_client().create_auth_flow(redirect_uri)
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        session["gmail_oauth_state"] = state
        session["gmail_redirect_uri"] = redirect_uri
        return redirect(authorization_url)
    except Exception as e:
        flash(f"Error al conectar Gmail: {e}", "error")
        return redirect(url_for("index"))


@auth_bp.route("/gmail/callback")
def gmail_callback():
    """Callback de OAuth2 de Google. Recibe el código de autorización."""
    from flask import request

    code = request.args.get("code")
    if not code:
        flash("No se recibió código de autorización de Google.", "error")
        return redirect(url_for("index"))

    try:
        redirect_uri = session.pop("gmail_redirect_uri", config.GMAIL_REDIRECT_URI or url_for("auth.gmail_callback", _external=True))
        flow = get_gmail_client().create_auth_flow(redirect_uri)
        gmail = get_gmail_client()
        gmail.authenticate_with_code(flow, code)
        set_gmail_connected(True)
        flash("Gmail conectado exitosamente.", "success")
    except Exception as e:
        flash(f"Error al autenticar Gmail: {e}", "error")

    return redirect(url_for("index"))


@auth_bp.route("/gmail/disconnect")
def gmail_disconnect():
    """Desconecta Gmail eliminando el token."""
    if config.GMAIL_TOKEN_FILE.exists():
        config.GMAIL_TOKEN_FILE.unlink()
    gmail = get_gmail_client()
    gmail.service = None
    gmail.creds = None
    set_gmail_connected(False)
    flash("Gmail desconectado.", "info")
    return redirect(url_for("index"))


# --- Outlook ---

@auth_bp.route("/outlook/connect")
def outlook_connect():
    """Inicia el device code flow de Outlook y muestra el código al usuario."""
    global _outlook_auth_state

    outlook = get_outlook_client()

    # Intentar auth silencioso primero
    if outlook.try_silent_auth():
        set_outlook_connected(True)
        flash("Outlook conectado exitosamente.", "success")
        return redirect(url_for("index"))

    # Iniciar device flow
    flow = outlook.start_device_flow()
    if not flow:
        flash("Error al iniciar autenticación de Outlook. Verifica OUTLOOK_CLIENT_ID.", "error")
        return redirect(url_for("index"))

    # Ejecutar la espera en un thread de fondo
    def _auth_worker():
        global _outlook_auth_state
        success = outlook.complete_device_flow(flow)
        _outlook_auth_state["result"] = "success" if success else "error"

    t = threading.Thread(target=_auth_worker, daemon=True)
    _outlook_auth_state = {"flow": flow, "thread": t, "result": "pending"}
    t.start()

    return render_template(
        "auth/outlook_connect.html",
        verification_uri=flow["verification_uri"],
        user_code=flow["user_code"],
    )


@auth_bp.route("/outlook/poll")
def outlook_poll():
    """Endpoint AJAX para verificar si el device flow de Outlook se completó."""
    global _outlook_auth_state

    result = _outlook_auth_state.get("result", "pending")

    if result == "success":
        set_outlook_connected(True)
        _outlook_auth_state = {}
        return jsonify({"status": "success"})
    elif result == "error":
        _outlook_auth_state = {}
        return jsonify({"status": "error", "message": "Error de autenticación"})
    else:
        return jsonify({"status": "pending"})


@auth_bp.route("/outlook/disconnect")
def outlook_disconnect():
    """Desconecta Outlook eliminando la caché de tokens."""
    if config.OUTLOOK_TOKEN_CACHE.exists():
        config.OUTLOOK_TOKEN_CACHE.unlink()
    outlook = get_outlook_client()
    outlook.access_token = None
    outlook._app = None
    set_outlook_connected(False)
    flash("Outlook desconectado.", "info")
    return redirect(url_for("index"))


# --- IMAP ---

@auth_bp.route("/imap/add", methods=["GET", "POST"])
def imap_add():
    """Formulario para agregar una cuenta IMAP."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        host = request.form.get("host", "").strip()
        port = int(request.form.get("port", 993))
        email_addr = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        smtp_host = request.form.get("smtp_host", "").strip() or host
        smtp_port = int(request.form.get("smtp_port", 587))

        if not all([name, host, email_addr, password]):
            flash("Todos los campos obligatorios deben estar completos.", "error")
            return render_template("auth/imap_connect.html")

        if add_imap_client(name, host, port, email_addr, password, smtp_host, smtp_port):
            flash(f"Cuenta IMAP '{name}' conectada exitosamente.", "success")
            return redirect(url_for("index"))
        else:
            flash("No se pudo conectar. Verifica los datos del servidor.", "error")
            return render_template("auth/imap_connect.html")

    return render_template("auth/imap_connect.html")


@auth_bp.route("/imap/disconnect/<name>")
def imap_disconnect(name):
    """Desconecta una cuenta IMAP."""
    remove_imap_client(name)
    flash(f"Cuenta '{name}' desconectada.", "info")
    return redirect(url_for("index"))
