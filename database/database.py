"""Sessão do SQLAlchemy e criação automática do banco SQLite."""
from pathlib import Path

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


def init_db(app: Flask) -> None:
    """Liga o SQLAlchemy ao app e cria as tabelas na primeira execução (idempotente)."""
    db.init_app(app)
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        Path(uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        from database import models  # noqa: F401  (registra as tabelas)

        db.create_all()
