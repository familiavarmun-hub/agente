"""
Blueprint de autenticación para conexión de cuentas de email (Gmail, Outlook, IMAP).
Cada conexión se guarda cifrada en la DB para el usuario autenticado.
"""
import hashlib
import base64
import secrets
import threading

from flask import Blueprint, redirect, url_for, session, render_template, jsonify, flash, request
from flask_login import login_required, current_user

import config
from gmail_client import GmailClient
from outlook_client import OutlookClient
from user_session import get_user_session
from imap_client import ImapClient

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# Estado del device flow de Outlook (por usuario)
_outlook_auth_state: dict = {}  # user_id -> {"flow": dict, "thread": Thread, "result": str}


# --- Gmail ---

@auth_bp.route("/gmail/connect")
@login_required
def gmail_connect():
    """Redirige al usuario a la pantalla de autorización de Google (Gmail API)."""
    try:
        redirect_uri = config.GMAIL_REDIRECT_URI or url_for("auth.gmail_callback", _external=True)
        client = GmailClient()
        flow = client.create_auth_flow(redirect_uri)

        # PKCE
        code_verifier = secrets.token_urlsafe(43)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        session["gmail_oauth_state"] = state
        session["gmail_redirect_uri"] = redirect_uri
        session["gmail_code_verifier"] = code_verifier
        return redirect(authorization_url)
    except Exception as e:
        flash(f"Error al conectar Gmail: {e}", "error")
        return redirect(url_for("index"))


@auth_bp.route("/gmail/callback")
def gmail_callback():
    """Callback de OAuth2 de Google. Recibe el código de autorización."""
    code = request.args.get("code")
    if not code:
        flash("No se recibió código de autorización de Google.", "error")
        return redirect(url_for("index"))

    if not current_user.is_authenticated:
        flash("Debes iniciar sesión primero.", "error")
        return redirect(url_for("login"))

    try:
        redirect_uri = session.pop("gmail_redirect_uri",
                                    config.GMAIL_REDIRECT_URI or url_for("auth.gmail_callback", _external=True))
        code_verifier = session.pop("gmail_code_verifier", None)

        client = GmailClient()
        flow = client.create_auth_flow(redirect_uri)
        creds_dict = client.authenticate_with_code(flow, code, code_verifier=code_verifier)

        # Guardar en sesión del usuario
        sess = get_user_session(current_user.id)
        sess.gmail_client = client
        sess.gmail_connected = True
        sess.save_gmail_credentials(creds_dict)

        flash("Gmail conectado exitosamente.", "success")
    except Exception as e:
        flash(f"Error al autenticar Gmail: {e}", "error")

    return redirect(url_for("index"))


@auth_bp.route("/gmail/disconnect")
@login_required
def gmail_disconnect():
    """Desconecta Gmail del usuario actual."""
    sess = get_user_session(current_user.id)
    sess.disconnect_account("gmail")
    flash("Gmail desconectado.", "info")
    return redirect(url_for("index"))


# --- Outlook ---

@auth_bp.route("/outlook/connect")
@login_required
def outlook_connect():
    """Inicia el device code flow de Outlook."""
    global _outlook_auth_state

    sess = get_user_session(current_user.id)
    client = OutlookClient()

    # Iniciar device flow
    flow = client.start_device_flow()
    if not flow:
        flash("Error al iniciar autenticación de Outlook. Verifica OUTLOOK_CLIENT_ID.", "error")
        return redirect(url_for("index"))

    user_id = current_user.id

    def _auth_worker():
        global _outlook_auth_state
        success = client.complete_device_flow(flow)
        if success:
            _outlook_auth_state[user_id]["result"] = "success"
            _outlook_auth_state[user_id]["client"] = client
        else:
            _outlook_auth_state[user_id]["result"] = "error"

    t = threading.Thread(target=_auth_worker, daemon=True)
    _outlook_auth_state[user_id] = {"flow": flow, "thread": t, "result": "pending"}
    t.start()

    return render_template(
        "auth/outlook_connect.html",
        verification_uri=flow["verification_uri"],
        user_code=flow["user_code"],
    )


@auth_bp.route("/outlook/poll")
@login_required
def outlook_poll():
    """Endpoint AJAX para verificar si el device flow de Outlook se completó."""
    global _outlook_auth_state

    user_id = current_user.id
    state = _outlook_auth_state.get(user_id, {})
    result = state.get("result", "pending")

    if result == "success":
        client = state.get("client")
        sess = get_user_session(user_id)
        sess.outlook_client = client
        sess.outlook_connected = True

        # Guardar token cache cifrado
        cache_data = client.get_token_cache_data()
        sess.save_outlook_credentials(cache_data)

        _outlook_auth_state.pop(user_id, None)
        return jsonify({"status": "success"})
    elif result == "error":
        _outlook_auth_state.pop(user_id, None)
        return jsonify({"status": "error", "message": "Error de autenticación"})
    else:
        return jsonify({"status": "pending"})


@auth_bp.route("/outlook/disconnect")
@login_required
def outlook_disconnect():
    """Desconecta Outlook del usuario actual."""
    sess = get_user_session(current_user.id)
    sess.disconnect_account("outlook")
    flash("Outlook desconectado.", "info")
    return redirect(url_for("index"))


# --- IMAP ---

@auth_bp.route("/imap/add", methods=["GET", "POST"])
@login_required
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

        client = ImapClient(name, host, port, email_addr, password, smtp_host, smtp_port)
        if client.authenticate():
            sess = get_user_session(current_user.id)
            sess.imap_clients[name] = client
            sess.imap_connected[name] = True
            sess.save_imap_credentials(name, {
                "host": host, "port": port, "email": email_addr,
                "password": password, "smtp_host": smtp_host, "smtp_port": smtp_port,
            })
            flash(f"Cuenta IMAP '{name}' conectada exitosamente.", "success")
            return redirect(url_for("index"))
        else:
            flash("No se pudo conectar. Verifica los datos del servidor.", "error")
            return render_template("auth/imap_connect.html")

    return render_template("auth/imap_connect.html")


@auth_bp.route("/imap/disconnect/<name>")
@login_required
def imap_disconnect(name):
    """Desconecta una cuenta IMAP del usuario actual."""
    sess = get_user_session(current_user.id)
    sess.disconnect_account("imap", name)
    flash(f"Cuenta '{name}' desconectada.", "info")
    return redirect(url_for("index"))
