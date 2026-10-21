"""Avaliação da condição por IA: páginas HTML e API JSON. A regra toda está em services/card_grader_service.py."""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from services import card_grader_service as grader
from services import card_service, gemini_service

grading = Blueprint("grading", __name__)


def _card_or_404(card_id: int):
    card = card_service.get_card(card_id)
    if card is None:
        abort(404, description="Card não encontrado.")
    return card


def _evaluation_or_404(card, evaluation_id: int):
    evaluation = grader.get_evaluation(card, evaluation_id)
    if evaluation is None:
        abort(404, description="Avaliação não encontrada.")
    return evaluation


def _summary(card, evaluation) -> dict:
    data = evaluation.to_dict()
    data.pop("analysis")
    return data | {"url": url_for("grading.evaluation_page", card_id=card.id, evaluation_id=evaluation.id)}


def _form(card, error=None, issues=None, tips=None, status=200):
    return render_template("grade_form.html", card=card, error=error, issues=issues or [], tips=tips or [],
                           ai_enabled=gemini_service.is_configured()), status


# ---------- páginas ----------
@grading.get("/cards/<int:card_id>/grade")
def grade_page(card_id: int):
    return _form(_card_or_404(card_id))


@grading.post("/cards/<int:card_id>/grade")
def grade_submit(card_id: int):
    """Envio pelo formulário (funciona sem JavaScript)."""
    card = _card_or_404(card_id)
    try:
        evaluation = grader.evaluate_card(card, request.files.get("front_image"), request.files.get("back_image"))
    except grader.PhotoQualityError as exc:
        return _form(card, str(exc), exc.issues, exc.tips, exc.status)
    except (grader.GradingError, gemini_service.GeminiError) as exc:
        return _form(card, str(exc), status=exc.status)
    flash("Análise concluída!", "success")
    return redirect(url_for("grading.evaluation_page", card_id=card.id, evaluation_id=evaluation.id))


@grading.get("/cards/<int:card_id>/grades/<int:evaluation_id>")
def evaluation_page(card_id: int, evaluation_id: int):
    card = _card_or_404(card_id)
    evaluation = _evaluation_or_404(card, evaluation_id)
    return render_template("grade_result.html", card=card, evaluation=evaluation, analysis=evaluation.analysis)


@grading.post("/cards/<int:card_id>/grades/<int:evaluation_id>/delete")
def delete_evaluation(card_id: int, evaluation_id: int):
    card = _card_or_404(card_id)
    grader.delete_evaluation(_evaluation_or_404(card, evaluation_id))
    flash("Avaliação removida do histórico.", "success")
    return redirect(url_for("pages.card_detail", card_id=card.id) + "#historico")


# ---------- API ----------
@grading.post("/api/cards/<int:card_id>/grade")
def api_grade(card_id: int):
    card = card_service.get_card(card_id)
    if card is None:
        return jsonify({"success": False, "error": "Card não encontrado."}), 404
    try:
        evaluation = grader.evaluate_card(card, request.files.get("front_image"), request.files.get("back_image"))
    except grader.PhotoQualityError as exc:
        return jsonify({"success": False, "error": str(exc), "issues": exc.issues, "tips": exc.tips}), exc.status
    except (grader.GradingError, gemini_service.GeminiError) as exc:
        return jsonify({"success": False, "error": str(exc)}), exc.status
    return jsonify({"success": True, "evaluation": _summary(card, evaluation)}), 201


@grading.get("/api/cards/<int:card_id>/grades")
def api_history(card_id: int):
    card = card_service.get_card(card_id)
    if card is None:
        return jsonify({"error": "Card não encontrado."}), 404
    return jsonify({
        "official": {"grading_company": card.grading_company, "official_grade": card.official_grade},
        "evaluations": [_summary(card, e) for e in card.evaluations],
    })
