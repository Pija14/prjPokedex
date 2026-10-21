"""Entrar e sair da conta do dono da coleção."""
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for

from services import auth_service

auth = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str:
    """Só redireciona para endereços do próprio CardDex (evita redirecionamento aberto)."""
    if target:
        parts = urlparse(target)
        if not parts.scheme and not parts.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return url_for("pages.home")


@auth.get("/login")
def login():
    if not auth_service.auth_enabled() or auth_service.is_logged_in():
        return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html", next=request.args.get("next", ""), error=None, username="")


@auth.post("/login")
def login_post():
    if not auth_service.auth_enabled():
        return redirect(url_for("pages.home"))
    ip = request.remote_addr or "?"
    username = request.form.get("username", "")
    next_url = request.form.get("next", "")
    if auth_service.is_locked(ip):
        error = "Muitas tentativas erradas. Aguarde 15 minutos e tente de novo."
        return render_template("login.html", next=next_url, error=error, username=username), 429
    if not auth_service.check_credentials(username, request.form.get("password", "")):
        auth_service.register_failure(ip)
        return render_template("login.html", next=next_url, error="Usuário ou senha incorretos.", username=username), 401
    auth_service.clear_failures(ip)
    auth_service.log_in()
    return redirect(_safe_next(next_url))


@auth.post("/logout")
def logout():
    auth_service.log_out()
    flash("Você saiu do CardDex.", "success")
    return redirect(url_for("auth.login"))
