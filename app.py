"""
Aplicación web Flask para el Agente de Correo Electrónico.
"""
import re

from flask import Flask, render_template, request, jsonify, flash, redirect, url_for

import config
from auth import auth_bp
from email_service import (
    get_gmail_client, get_outlook_client,
    is_gmail_connected, is_outlook_connected,
    set_gmail_connected, set_outlook_connected,
    fetch_all_emails, get_cached_email, refresh_emails,
    mark_email_as_read, send_reply, archive_email,
    get_all_sources, init_imap_clients, get_imap_clients, get_imap_connected,
    get_analysis, set_analysis, get_all_analysis,
)
from ai_responder import analyze_and_respond

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.register_blueprint(auth_bp)


@app.context_processor
def inject_globals():
    """Variables disponibles en todos los templates."""
    return {
        "gmail_connected": is_gmail_connected(),
        "outlook_connected": is_outlook_connected(),
        "sources": get_all_sources(),
        "imap_connected": get_imap_connected(),
    }


@app.route("/")
def index():
    source = request.args.get("source", "all")
    emails = []
    any_connected = is_gmail_connected() or is_outlook_connected() or any(get_imap_connected().values())
    if any_connected:
        emails = fetch_all_emails(source)

    return render_template("index.html", emails=emails, current_source=source)


@app.route("/emails/fetch")
def fetch_emails():
    source = request.args.get("source", "all")
    emails = fetch_all_emails(source)
    for e in emails:
        if e.get("date"):
            e["date"] = e["date"].isoformat()
    return jsonify(emails)


@app.route("/emails/refresh", methods=["POST"])
def refresh():
    """Fuerza recarga de emails desde las APIs y retorna info de nuevos."""
    source = request.args.get("source", "all")
    result = refresh_emails(source)
    return jsonify(result)


@app.route("/email/<source>/<path:email_id>")
def email_detail(source, email_id):
    email = get_cached_email(source, email_id)
    if not email:
        flash("Email no encontrado.", "error")
        return redirect(url_for("index"))

    from_address = email.get("from", "")
    match = re.search(r'<(.+?)>', from_address)
    reply_to = match.group(1) if match else from_address

    return render_template("email_detail.html", email=email, reply_to=reply_to)


@app.route("/email/<source>/<path:email_id>/analyze", methods=["POST"])
def analyze_email(source, email_id):
    # Revisar caché primero
    cached = get_analysis(email_id)
    if cached:
        return jsonify(cached)

    email = get_cached_email(source, email_id)
    if not email:
        return jsonify({"error": "Email no encontrado"}), 404

    result = analyze_and_respond(email)
    set_analysis(email_id, result)
    return jsonify(result)


@app.route("/analysis-cache")
def analysis_cache():
    return jsonify(get_all_analysis())


@app.route("/email/<source>/<path:email_id>/mark-read", methods=["POST"])
def mark_read(source, email_id):
    success = mark_email_as_read(source, email_id)
    if success:
        return jsonify({"status": "ok"})
    return jsonify({"error": "No se pudo marcar como leído"}), 500


@app.route("/email/<source>/<path:email_id>/archive", methods=["POST"])
def archive(source, email_id):
    success = archive_email(source, email_id)
    if success:
        return jsonify({"status": "ok"})
    return jsonify({"error": "No se pudo archivar"}), 500


@app.route("/email/<source>/<path:email_id>/reply", methods=["POST"])
def reply_email(source, email_id):
    data = request.get_json() or request.form
    to = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")

    if not to or not body:
        return jsonify({"error": "Faltan campos requeridos (to, body)"}), 400

    success = send_reply(source, email_id, to, subject, body)
    if success:
        mark_email_as_read(source, email_id)
        return jsonify({"status": "ok", "message": "Respuesta enviada"})
    return jsonify({"error": "No se pudo enviar la respuesta"}), 500


@app.route("/emails/batch/analyze", methods=["POST"])
def batch_analyze():
    data = request.get_json()
    if not data or "emails" not in data:
        return jsonify({"error": "Se requiere lista de emails"}), 400

    results = []
    for item in data["emails"]:
        cached = get_analysis(item["id"])
        if cached:
            cached["email_id"] = item["id"]
            cached["source"] = item["source"]
            results.append(cached)
            continue

        email = get_cached_email(item["source"], item["id"])
        if email:
            result = analyze_and_respond(email)
            result["email_id"] = item["id"]
            result["source"] = item["source"]
            result["subject"] = email.get("subject", "")
            set_analysis(item["id"], result)
            results.append(result)

    return jsonify(results)


@app.route("/status")
def status():
    return jsonify({
        "gmail": is_gmail_connected(),
        "outlook": is_outlook_connected(),
        "imap": get_imap_connected(),
    })


def _init_connections():
    """Inicializa conexiones a cuentas de correo al arrancar."""
    # IMAP
    init_imap_clients()
    for name, client in get_imap_clients().items():
        try:
            if client.authenticate():
                from email_service import _imap_connected
                _imap_connected[name] = True
                print(f"[OK] IMAP ({name}) conectado.")
        except Exception:
            pass

    # Gmail
    try:
        gmail = get_gmail_client()
        if gmail.authenticate():
            set_gmail_connected(True)
            print("[OK] Gmail conectado con token existente.")
        else:
            print("[--] Gmail: no hay token válido. Conecta desde el sidebar.")
    except Exception as e:
        print(f"[!!] Gmail error: {e}")

    # Outlook
    try:
        outlook = get_outlook_client()
        if outlook.try_silent_auth():
            set_outlook_connected(True)
            print("[OK] Outlook conectado con token existente.")
        else:
            print("[--] Outlook: no hay token válido. Conecta desde el sidebar.")
    except Exception as e:
        print(f"[!!] Outlook error: {e}")


# Inicializar al importar (funciona con gunicorn y con python app.py)
_init_connections()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
