"""Sessão do SQLAlchemy e criação automática do banco SQLite."""
from pathlib import Path

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
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
        _add_missing_columns()


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_connection, _record) -> None:
    """No SQLite as chaves estrangeiras (ON DELETE CASCADE) só valem com este PRAGMA."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def _add_missing_columns() -> None:
    """Migração leve: create_all não altera tabelas existentes, então colunas novas dos models
    (ex.: nota oficial do card) são adicionadas aqui. Idempotente; não mexe nos dados."""
    inspector = inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or column.primary_key:
                continue
            ddl = column.type.compile(dialect=db.engine.dialect)
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))
