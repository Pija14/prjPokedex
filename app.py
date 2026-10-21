"""CardDex — ponto de entrada. Execute: python app.py  →  http://localhost:5000"""
import socket
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from config import Config
from database import init_db
from routes import api, pages
from services import card_service, image_service

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def create_app(config: type = Config, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    app.config.update(overrides)

    init_db(app)
    app.register_blueprint(pages)
    app.register_blueprint(api)
    _register_template_helpers(app)
    _register_error_pages(app)
    return app


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
            return {"errors": {"image": message}}, 413
        values = card_service.form_defaults()
        return render_template("card_form.html", card=None, values=values, errors={"image": message},
                               rarities=card_service.RARITY_SUGGESTIONS, languages=card_service.LANGUAGES), 413


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
