"""
Aplicación web Flask para el Agente de Correo Electrónico.
Multi-usuario con Google Sign-In y MySQL.
"""
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import requests as http_requests

import config
from models import db, User
from auth import auth_bp
from user_session import get_user_session, remove_user_session
from ai_responder import analyze_and_respond

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
app.register_blueprint(auth_bp)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Crear tablas al arrancar
with app.app_context():
    db.create_all()


@app.after_request
def add_iframe_headers(response):
    """Permitir que la app se incruste como iframe en Waply Fusion."""
    response.headers.pop('X-Frame-Options', None)
    response.headers['Content-Security-Policy'] = "frame-ancestors *"
    return response


@app.context_processor
def inject_globals():
    """Variables disponibles en todos los templates."""
    if current_user.is_authenticated:
        sess = get_user_session(current_user.id)
        return {
            "gmail_connected": sess.gmail_connected,
            "outlook_connected": sess.outlook_connected,
            "sources": sess.get_sources(),
            "imap_connected": sess.imap_connected,
            "user": current_user,
        }
    return {
        "gmail_connected": False,
        "outlook_connected": False,
        "sources": [],
        "imap_connected": {},
        "user": None,
    }


# --- Google Sign-In ---

@app.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/auth/google/login")
def google_login():
    """Redirige a Google para iniciar sesión."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state
    session["google_oauth_nonce"] = nonce

    params = {
        "client_id": config.GOOGLE_SIGN_IN_CLIENT_ID,
        "redirect_uri": config.GOOGLE_SIGN_IN_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "access_type": "offline",
        "prompt": "select_account",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(auth_url)


@app.route("/auth/google/callback")
def google_callback():
    """Callback de Google Sign-In. Crea o actualiza usuario."""
    error = request.args.get("error")
    if error:
        flash(f"Error de Google: {error}", "error")
        return redirect(url_for("login"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or state != session.pop("google_oauth_state", None):
        flash("Error de autenticación. Intenta de nuevo.", "error")
        return redirect(url_for("login"))

    # Intercambiar code por tokens
    token_resp = http_requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": config.GOOGLE_SIGN_IN_CLIENT_ID,
        "client_secret": config.GOOGLE_SIGN_IN_CLIENT_SECRET,
        "redirect_uri": config.GOOGLE_SIGN_IN_REDIRECT_URI,
        "grant_type": "authorization_code",
    })

    if token_resp.status_code != 200:
        flash("Error al obtener token de Google.", "error")
        return redirect(url_for("login"))

    token_data = token_resp.json()

    # Obtener info del usuario
    userinfo_resp = http_requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )

    if userinfo_resp.status_code != 200:
        flash("Error al obtener información del usuario.", "error")
        return redirect(url_for("login"))

    userinfo = userinfo_resp.json()
    google_id = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name", email)
    picture = userinfo.get("picture", "")

    # Crear o actualizar usuario en DB
    user = User.query.filter_by(google_id=google_id).first()
    if user:
        user.last_login = datetime.now(timezone.utc)
        user.name = name
        user.picture = picture
    else:
        user = User(
            google_id=google_id, email=email, name=name, picture=picture,
        )
        db.session.add(user)
    db.session.commit()

    # Login con Flask-Login
    login_user(user, remember=True)

    # Restaurar conexiones de email desde DB
    sess = get_user_session(user.id)
    sess.restore_connections()

    return redirect(url_for("index"))


@app.route("/logout")
@login_required
def logout():
    remove_user_session(current_user.id)
    logout_user()
    return redirect(url_for("login"))


# --- Rutas principales ---

@app.route("/")
@login_required
def index():
    source = request.args.get("source", "all")
    sess = get_user_session(current_user.id)
    any_connected = sess.gmail_connected or sess.outlook_connected or any(sess.imap_connected.values())
    emails = sess.fetch_all_emails(source) if any_connected else []
    return render_template("index.html", emails=emails, current_source=source)


@app.route("/emails/fetch")
@login_required
def fetch_emails():
    source = request.args.get("source", "all")
    sess = get_user_session(current_user.id)
    emails = sess.fetch_all_emails(source)
    for e in emails:
        if e.get("date"):
            e["date"] = e["date"].isoformat()
    return jsonify(emails)


@app.route("/emails/refresh", methods=["POST"])
@login_required
def refresh():
    """Fuerza recarga de emails desde las APIs y retorna info de nuevos."""
    source = request.args.get("source", "all")
    sess = get_user_session(current_user.id)
    result = sess.refresh_emails(source)
    return jsonify(result)


@app.route("/email/<source>/<path:email_id>")
@login_required
def email_detail(source, email_id):
    sess = get_user_session(current_user.id)
    email = sess.get_cached_email(source, email_id)
    if not email:
        flash("Email no encontrado.", "error")
        return redirect(url_for("index"))

    from_address = email.get("from", "")
    match = re.search(r'<(.+?)>', from_address)
    reply_to = match.group(1) if match else from_address

    return render_template("email_detail.html", email=email, reply_to=reply_to)


@app.route("/email/<source>/<path:email_id>/analyze", methods=["POST"])
@login_required
def analyze_email(source, email_id):
    sess = get_user_session(current_user.id)

    cached = sess.get_analysis(email_id)
    if cached:
        return jsonify(cached)

    email = sess.get_cached_email(source, email_id)
    if not email:
        return jsonify({"error": "Email no encontrado"}), 404

    result = analyze_and_respond(email)
    sess.set_analysis(email_id, source, result)
    return jsonify(result)


@app.route("/analysis-cache")
@login_required
def analysis_cache():
    sess = get_user_session(current_user.id)
    return jsonify(sess.get_all_analysis())


@app.route("/email/<source>/<path:email_id>/mark-read", methods=["POST"])
@login_required
def mark_read(source, email_id):
    sess = get_user_session(current_user.id)
    if sess.mark_email_as_read(source, email_id):
        return jsonify({"status": "ok"})
    return jsonify({"error": "No se pudo marcar como leído"}), 500


@app.route("/email/<source>/<path:email_id>/archive", methods=["POST"])
@login_required
def archive(source, email_id):
    sess = get_user_session(current_user.id)
    if sess.archive_email(source, email_id):
        return jsonify({"status": "ok"})
    return jsonify({"error": "No se pudo archivar"}), 500


@app.route("/email/<source>/<path:email_id>/reply", methods=["POST"])
@login_required
def reply_email(source, email_id):
    data = request.get_json() or request.form
    to = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")

    if not to or not body:
        return jsonify({"error": "Faltan campos requeridos (to, body)"}), 400

    sess = get_user_session(current_user.id)
    if sess.send_reply(source, email_id, to, subject, body):
        sess.mark_email_as_read(source, email_id)
        return jsonify({"status": "ok", "message": "Respuesta enviada"})
    return jsonify({"error": "No se pudo enviar la respuesta"}), 500


@app.route("/emails/batch/analyze", methods=["POST"])
@login_required
def batch_analyze():
    data = request.get_json()
    if not data or "emails" not in data:
        return jsonify({"error": "Se requiere lista de emails"}), 400

    sess = get_user_session(current_user.id)
    results = []
    for item in data["emails"]:
        cached = sess.get_analysis(item["id"])
        if cached:
            cached["email_id"] = item["id"]
            cached["source"] = item["source"]
            results.append(cached)
            continue

        email = sess.get_cached_email(item["source"], item["id"])
        if email:
            result = analyze_and_respond(email)
            result["email_id"] = item["id"]
            result["source"] = item["source"]
            result["subject"] = email.get("subject", "")
            sess.set_analysis(item["id"], item["source"], result)
            results.append(result)

    return jsonify(results)


@app.route("/status")
@login_required
def status():
    sess = get_user_session(current_user.id)
    return jsonify({
        "gmail": sess.gmail_connected,
        "outlook": sess.outlook_connected,
        "imap": dict(sess.imap_connected),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
