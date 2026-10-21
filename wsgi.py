"""Ponto de entrada WSGI para servidores de produção (PythonAnywhere, waitress, gunicorn).

Localmente continue usando:  python app.py
"""
from app import create_app

application = create_app()
app = application
