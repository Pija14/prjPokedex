"""CardDex — ponto de entrada. Execute: python app.py  →  http://localhost:5000"""
import socket
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from database import init_db
from routes import api, auth, grading, pages, scan
from services import auth_service, card_service, gemini_service, image_service

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def create_app(config: type = Config, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    app.config.update(overrides)

    _check_production_config(app)
    if app.config["IS_PRODUCTION"]:
        # Atrás do proxy HTTPS do PythonAnywhere: IP real do visitante e esquema https.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    init_db(app)
    app.register_blueprint(auth)
    app.register_blueprint(pages)
    app.register_blueprint(api)
    app.register_blueprint(grading)
    app.register_blueprint(scan)
    _register_security(app)
    _register_template_helpers(app)
    _register_error_pages(app)
    return app


def _check_production_config(app: Flask) -> None:
    """Em produção o app não sobe aberto: exige senha e SECRET_KEY próprios."""
    if not app.config["IS_PRODUCTION"]:
        return
    missing = []
    if not (app.config.get("ADMIN_USERNAME") and app.config.get("ADMIN_PASSWORD_HASH")):
        missing.append("ADMIN_USERNAME/ADMIN_PASSWORD_HASH (rode: python scripts/set_password.py)")
    if app.config.get("SECRET_KEY") in (None, "", "carddex-dev-local") or len(app.config["SECRET_KEY"]) < 32:
        missing.append("SECRET_KEY com pelo menos 32 caracteres aleatórios")
    if missing:
        raise RuntimeError("CardDex em produção sem configuração de segurança: defina no .env " + "; ".join(missing))


PUBLIC_ENDPOINTS = {"auth.login", "auth.login_post", "static"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _register_security(app: Flask) -> None:
    @app.before_request
    def require_login_and_csrf():
        if not auth_service.auth_enabled():
            return None  # sem senha configurada (uso local): app aberto, como antes
        is_api = request.path.startswith("/api/")
        if request.endpoint not in PUBLIC_ENDPOINTS and not auth_service.is_logged_in():
            if is_api:
                return jsonify({"error": "Faça login para continuar."}), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if request.method in UNSAFE_METHODS:
            token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not auth_service.valid_csrf(token):
                if is_api:
                    return jsonify({"error": "Sessão expirada. Recarregue a página."}), 400
                return render_template("login.html", next="", username="",
                                       error="Sua sessão expirou. Entre novamente."), 400
        return None


def brl(value) -> str:
    """Decimal → 'R$ 1.250,00'."""
    if value is None:
        return "—"
    whole, cents = f"{Decimal(value):.2f}".split(".")
    return f"R$ {int(whole):,}".replace(",", ".") + f",{cents}"


def date_br(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(LOCAL_TZ)
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _register_template_helpers(app: Flask) -> None:
    app.add_template_filter(brl, "brl")
    app.add_template_filter(date_br, "date_br")
    app.add_template_global(image_service.image_url, "image_url")
    app.add_template_global(card_service.rarity_tier, "rarity_tier")
    app.add_template_global(app.config["MAX_IMAGE_MB"], "max_image_mb")
    app.add_template_global(auth_service.csrf_token, "csrf_token")
    app.add_template_global(auth_service.auth_enabled, "auth_enabled")
    app.add_template_global(auth_service.is_logged_in, "logged_in")


def _register_error_pages(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return {"error": "Não encontrado."}, 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        message = f"Imagem grande demais. O limite é {app.config['MAX_IMAGE_MB']} MB."
        if request.path.startswith("/api/"):
            return {"errors": {"image": message}, "error": message}, 413
        if request.endpoint == "grading.grade_submit":
            card = card_service.get_card(request.view_args["card_id"])
            if card:
                return render_template("grade_form.html", card=card, error=message, issues=[], tips=[],
                                       ai_enabled=gemini_service.is_configured()), 413
        if request.endpoint == "scan.scan_submit":
            if request.headers.get("X-Scan-Fragment") == "1":
                return {"error": message}, 413
            return render_template("scan.html", result=None, error=message,
                                   ai_enabled=gemini_service.is_configured()), 413
        values = card_service.form_defaults()
        return render_template("card_form.html", card=None, values=values, errors={"image": message},
                               rarities=card_service.RARITY_SUGGESTIONS, languages=card_service.LANGUAGES,
                               grading_companies=card_service.GRADING_COMPANIES,
                               ai_enabled=gemini_service.is_configured()), 413


def _lan_address() -> str | None:
    """IP da máquina na rede local, para abrir o CardDex no celular."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # não envia nada; só escolhe a interface de rede
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    app = create_app()
    port = app.config["PORT"]
    print(f"\n  CardDex rodando em http://localhost:{port}")
    if (ip := _lan_address()) and app.config["HOST"] == "0.0.0.0":
        print(f"  No celular (mesma rede Wi-Fi): http://{ip}:{port}\n")
    app.run(host=app.config["HOST"], port=port, debug=app.config["DEBUG"])
