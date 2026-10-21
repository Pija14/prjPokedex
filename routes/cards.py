"""API REST das cartas (JSON). Toda regra de negócio está em services/card_service.py."""
from flask import Blueprint, abort, jsonify, request

from services import card_service, gemini_service, image_service
from services.card_service import ValidationError

api = Blueprint("api_cards", __name__, url_prefix="/api/cards")


def _card_json(card):
    return card.to_dict(image_url=image_service.image_url(card.image_path))


def _payload():
    """Aceita JSON ou multipart/form-data (este último quando há imagem)."""
    if request.is_json:
        return request.get_json(silent=True) or {}, None
    return request.form, request.files.get("image")


def _get_or_404(card_id: int):
    card = card_service.get_card(card_id)
    if card is None:
        abort(404, description="Card não encontrado.")
    return card


@api.get("")
def list_cards():
    cards = card_service.list_cards(
        q=request.args.get("q", ""),
        collection=request.args.get("collection", ""),
        rarity=request.args.get("rarity", ""),
    )
    return jsonify([_card_json(c) for c in cards])


@api.post("/identify")
def identify_card():
    """Reconhece a carta da foto (campo `image`) e devolve os dados para preencher o formulário.
    Nada é salvo: a pessoa revisa e confirma antes do cadastro."""
    file = request.files.get("image")
    if not image_service.has_file(file):
        return jsonify({"errors": {"image": "Envie a foto da carta."}}), 400
    try:
        data, mime = image_service.read_for_analysis(file)
    except image_service.ImageError as exc:
        return jsonify({"errors": {"image": str(exc)}}), 400
    try:
        identification = gemini_service.identify_card(data, mime_type=mime)
    except gemini_service.GeminiError as exc:
        return jsonify({"error": str(exc)}), exc.status
    return jsonify(identification.to_dict())


@api.get("/<int:card_id>")
def get_card(card_id: int):
    return jsonify(_card_json(_get_or_404(card_id)))


@api.post("")
def create_card():
    data, image = _payload()
    card = card_service.create_card(data, image=image)
    return jsonify(_card_json(card)), 201


@api.put("/<int:card_id>")
def update_card(card_id: int):
    card = _get_or_404(card_id)
    data, image = _payload()
    remove = str(data.get("remove_image", "")).lower() in {"1", "true", "on"}
    card = card_service.update_card(card, data, image=image, remove_image=remove, partial=True)
    return jsonify(_card_json(card))


@api.delete("/<int:card_id>")
def delete_card(card_id: int):
    card_service.delete_card(_get_or_404(card_id))
    return "", 204


@api.errorhandler(ValidationError)
def validation_error(error: ValidationError):
    return jsonify({"errors": error.errors}), 400


@api.errorhandler(404)
def not_found(error):
    return jsonify({"error": getattr(error, "description", "Não encontrado.")}), 404


@api.errorhandler(413)
def too_large(error):
    return jsonify({"errors": {"image": "Arquivo grande demais."}}), 413
