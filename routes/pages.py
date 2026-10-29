"""Páginas HTML (Jinja). Formulários funcionam sem JavaScript: POST → redirect → GET."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from services import card_service, gemini_service
from services.card_service import GRADING_COMPANIES, LANGUAGES, RARITY_SUGGESTIONS, ValidationError

pages = Blueprint("pages", __name__)


def _get_or_404(card_id: int):
    card = card_service.get_card(card_id)
    if card is None:
        abort(404)
    return card


def _form(card=None, values=None, errors=None, status=200):
    return render_template(
        "card_form.html",
        card=card,
        values=values or card_service.form_defaults(card),
        errors=errors or {},
        rarities=RARITY_SUGGESTIONS,
        languages=LANGUAGES,
        grading_companies=GRADING_COMPANIES,
        ai_enabled=gemini_service.is_configured(),
    ), status


@pages.get("/")
def home():
    return render_template("index.html", summary=card_service.collection_summary())


@pages.get("/cards")
def collection():
    filters = {k: request.args.get(k, "").strip() for k in ("q", "collection", "rarity")}
    cards = card_service.list_cards(**filters)
    return render_template(
        "cards.html",
        cards=cards,
        groups=card_service.group_by_collection(cards),
        total=card_service.collection_summary(recent=0)["total_cards"],
        filters=filters,
        options=card_service.filter_options(),
    )


@pages.get("/cards/new")
def new_card():
    # Vindo do Scan, os dados reconhecidos chegam na URL e só preenchem o formulário (nada é salvo aqui).
    return _form(values=card_service.form_defaults(prefill=request.args.to_dict()) if request.args else None)


@pages.post("/cards/new")
def create_card():
    try:
        card = card_service.create_card(request.form, image=request.files.get("image"))
    except ValidationError as exc:
        return _form(values=card_service.form_defaults(prefill=request.form.to_dict()), errors=exc.errors, status=400)
    flash(f"{card.pokemon_name} foi adicionado à sua coleção!", "success")
    return redirect(url_for("pages.card_detail", card_id=card.id))


@pages.get("/cards/<int:card_id>")
def card_detail(card_id: int):
    return render_template("card_detail.html", card=_get_or_404(card_id))


@pages.get("/cards/<int:card_id>/edit")
def edit_card(card_id: int):
    return _form(card=_get_or_404(card_id))


@pages.post("/cards/<int:card_id>/edit")
def update_card(card_id: int):
    card = _get_or_404(card_id)
    try:
        card_service.update_card(
            card, request.form, image=request.files.get("image"),
            remove_image=request.form.get("remove_image") == "1", partial=False,
        )
    except ValidationError as exc:
        values = card_service.form_defaults(card, prefill=request.form.to_dict())
        return _form(card=card, values=values, errors=exc.errors, status=400)
    flash("Alterações salvas.", "success")
    return redirect(url_for("pages.card_detail", card_id=card.id))


@pages.post("/cards/<int:card_id>/delete")
def delete_card(card_id: int):
    card = _get_or_404(card_id)
    name = card.pokemon_name
    card_service.delete_card(card)
    flash(f"{name} foi removido da coleção.", "success")
    return redirect(url_for("pages.collection"))
