"""Login do dono da coleção (um único usuário) e proteção CSRF dos formulários.

O usuário e o hash da senha ficam no .env (ADMIN_USERNAME / ADMIN_PASSWORD_HASH),
gerados por scripts/set_password.py. A senha em texto nunca é guardada.
"""
import hmac
import secrets
import time
from collections import defaultdict, deque

from flask import current_app, session
from werkzeug.security import check_password_hash, generate_password_hash

SESSION_USER = "user"
SESSION_CSRF = "csrf_token"

# Limite de tentativas erradas por IP (em memória; reinicia junto com o servidor).
MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
_failures: dict[str, deque] = defaultdict(deque)


def auth_enabled() -> bool:
    config = current_app.config
    return bool(config.get("ADMIN_USERNAME") and config.get("ADMIN_PASSWORD_HASH"))


def hash_password(password: str) -> str:
    return generate_password_hash(password)  # scrypt com salt (padrão do Werkzeug)


def check_credentials(username: str, password: str) -> bool:
    config = current_app.config
    expected_user = config.get("ADMIN_USERNAME", "")
    user_ok = hmac.compare_digest(username.strip().lower().encode(), expected_user.lower().encode())
    try:
        password_ok = check_password_hash(config.get("ADMIN_PASSWORD_HASH", ""), password)
    except ValueError:
        password_ok = False
    return user_ok and password_ok


def is_logged_in() -> bool:
    return not auth_enabled() or session.get(SESSION_USER) == current_app.config.get("ADMIN_USERNAME")


def log_in() -> None:
    session.clear()  # nova sessão a cada login
    session.permanent = True
    session[SESSION_USER] = current_app.config["ADMIN_USERNAME"]


def log_out() -> None:
    session.clear()


# ---------- tentativas ----------
def _recent(ip: str) -> deque:
    attempts = _failures[ip]
    while attempts and time.monotonic() - attempts[0] > WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def is_locked(ip: str) -> bool:
    return len(_recent(ip)) >= MAX_FAILURES


def register_failure(ip: str) -> None:
    _recent(ip).append(time.monotonic())


def clear_failures(ip: str) -> None:
    _failures.pop(ip, None)


# ---------- CSRF ----------
def csrf_token() -> str:
    if SESSION_CSRF not in session:
        session[SESSION_CSRF] = secrets.token_urlsafe(32)
    return session[SESSION_CSRF]


def valid_csrf(token: str | None) -> bool:
    expected = session.get(SESSION_CSRF)
    return bool(token and expected and hmac.compare_digest(token, expected))
