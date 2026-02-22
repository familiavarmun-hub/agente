"""
Modelos SQLAlchemy para la base de datos multi-usuario.
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(255), unique=True, nullable=False)
    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    picture = db.Column(db.String(512), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    email_accounts = db.relationship("EmailAccount", backref="user", lazy=True, cascade="all, delete-orphan")
    analysis_entries = db.relationship("AnalysisCache", backref="user", lazy=True, cascade="all, delete-orphan")


class EmailAccount(db.Model):
    __tablename__ = "email_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider = db.Column(db.String(50), nullable=False)  # gmail, outlook, imap
    name = db.Column(db.String(255), nullable=False)
    encrypted_credentials = db.Column(db.Text, nullable=False)
    connected = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AnalysisCache(db.Model):
    __tablename__ = "analysis_cache"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    email_id = db.Column(db.String(512), nullable=False)
    source = db.Column(db.String(50), nullable=False)
    result_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("user_id", "email_id", name="uq_user_email"),
    )
