"""Scan: foto da carta → reconhecimento pela IA → vitrine com coleção, raridade e valor.

Só consulta: nada é gravado no banco nem em disco. A "vitrine" é um único template
(partials/_scan_result.html), usado na página sem JavaScript e no fragmento que o JS insere.
"""
from flask import Blueprint, jsonify, render_template, request, url_for

from services import card_service, catalog_service, gemini_service, image_service, price_service

scan = Blueprint("scan", __name__)


def _analyze(file) -> dict:
    """Executa o scan e devolve os dados da vitrine. Lança ImageError/GeminiError.
    A foto só serve para o reconhecimento: na tela aparece a imagem oficial da carta."""
    data, mime = image_service.read_for_analysis(file)
    identification = gemini_service.identify_card(data, mime_type=mime)
    catalog_service.confirm(identification)
    catalog = identification.catalog or {}
    return {
        "card": identification.to_dict(),
        "tier": card_service.rarity_tier(identification.rarity),
        "images": {"official": catalog.get("image_large") or catalog.get("image_small")},
        "price": price_service.quote(identification).to_dict(),
        "add_url": url_for("pages.new_card", **identification.as_prefill()),
    }


def _page(result=None, error=None, status=200):
    return render_template("scan.html", result=result, error=error,
                           ai_enabled=gemini_service.is_configured()), status


@scan.get("/scan")
def scan_page():
    return _page()


@scan.post("/scan")
def scan_submit():
    """Sem JS: página inteira com o resultado. Com JS (cabeçalho X-Scan-Fragment): só a vitrine."""
    fragment = request.headers.get("X-Scan-Fragment") == "1"
    # Sem JS o formulário manda os dois campos (Galeria e Tirar foto): vale o que tiver arquivo.
    file = next((f for f in request.files.getlist("image") if image_service.has_file(f)), None)
    try:
        if not image_service.has_file(file):
            raise image_service.ImageError("Envie a foto da carta.")
        result = _analyze(file)
    except (image_service.ImageError, gemini_service.GeminiError) as exc:
        status = getattr(exc, "status", 400)
        if fragment:
            return jsonify({"error": str(exc)}), status
        return _page(error=str(exc), status=status)
    if fragment:
        return render_template("partials/_scan_result.html", result=result)
    return _page(result=result)


@scan.post("/api/scan")
def scan_api():
    """Mesmo scan em JSON (campo `image`). Valores em R$."""
    file = request.files.get("image")
    if not image_service.has_file(file):
        return jsonify({"errors": {"image": "Envie a foto da carta."}}), 400
    try:
        return jsonify(_analyze(file))
    except image_service.ImageError as exc:
        return jsonify({"errors": {"image": str(exc)}}), 400
    except gemini_service.GeminiError as exc:
        return jsonify({"error": str(exc)}), exc.status
