"""Avaliação da condição por IA (Gemini simulado: nenhuma chamada real)."""
import io
import json
import random
import sqlite3
import threading

import pytest
import requests
from PIL import Image

from database.database import db
from database.models import CardGradingEvaluation
from services import card_grader_service as grader
from services import card_service, gemini_service


# ---------- imagens de teste ----------
def photo(kind: str = "ok", size=(800, 1100), fmt="JPEG") -> bytes:
    """'ok' = textura nítida · 'dark' · 'blur' (lisa) · 'glare' (estourada)."""
    rnd = random.Random(7)
    img = Image.new("RGB", size, (128, 128, 128))
    if kind in ("ok", "dark"):
        base = 30 if kind == "dark" else 0
        px = img.load()
        for x in range(0, size[0], 4):
            for y in range(0, size[1], 4):
                v = rnd.randint(0, 35) if kind == "dark" else rnd.randint(40, 220)
                for dx in range(4):
                    for dy in range(4):
                        if x + dx < size[0] and y + dy < size[1]:
                            px[x + dx, y + dy] = (v, max(0, v - base), v)
    elif kind == "glare":
        img = Image.new("RGB", size, (255, 255, 255))
        img.paste(Image.effect_noise((size[0] // 3, size[1] // 3), 90).convert("RGB"), (0, 0))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


OK = photo("ok")


def analysis(**overrides) -> dict:
    data = {
        "photo_quality": {"usable": True, "issues": []},
        "overall": {"estimated_range": "8-9", "confidence": "medium"},
        "centering": {"score": 9, "assessment": "Bordas equilibradas.", "front_lr": "aprox. 55/45", "front_tb": "", "back_lr": "", "back_tb": "", "confidence": "high"},
        "corners": {"score": 9, "assessment": "Cantos firmes.", "corners": {"top_left": "ok", "top_right": "ok", "bottom_left": "leve whitening", "bottom_right": "ok"}, "confidence": "medium"},
        "edges": {"score": 8, "assessment": "Whitening leve na borda inferior.", "confidence": "medium"},
        "surface": {"score": 9, "assessment": "Sem riscos visíveis.", "confidence": "medium"},
        "defects": [{"type": "edge_whitening", "location": "back_bottom_edge", "severity": "minor", "visible": True, "description": "Whitening leve."}],
        "summary": "Carta em ótimo estado aparente.",
    }
    for key, value in overrides.items():
        data[key] = value if not isinstance(value, dict) or key not in data else data[key] | value
    return data


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


def gemini_returns(data) -> FakeResponse:
    text = data if isinstance(data, str) else json.dumps(data)
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


@pytest.fixture()
def gemini(monkeypatch):
    """Fila de respostas simuladas em `gemini.responses`; as chamadas feitas ficam em `gemini.calls`."""
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    monkeypatch.setenv("GEMINI_MODEL", "")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3-teste,modelo-b")

    class State:
        calls, responses = [], []

    def fake_post(url, json=None, headers=None, timeout=None):
        State.calls.append({"url": url, "json": json, "headers": headers})
        item = State.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(gemini_service.requests, "post", fake_post)
    return State


@pytest.fixture()
def card(app):
    with app.app_context():
        return card_service.create_card({"pokemon_name": "Charizard", "collection_name": "Base Set", "card_number": "4/102"}).id


def grade(client, card_id, front=OK, back=OK):
    data = {}
    if front is not None:
        data["front_image"] = (io.BytesIO(front), "frente.jpg")
    if back is not None:
        data["back_image"] = (io.BytesIO(back), "verso.jpg")
    return client.post(f"/api/cards/{card_id}/grade", data=data, content_type="multipart/form-data")


# ---------- fluxo principal ----------
def test_duas_imagens_validas_salva_avaliacao(client, app, card, gemini):
    gemini.responses.append(gemini_returns(analysis()))
    r = grade(client, card)
    assert r.status_code == 201
    body = r.get_json()
    assert body["success"] is True
    ev = body["evaluation"]
    assert (ev["estimated_range"], ev["confidence"], ev["is_official"]) == ("8-9", "medium", False)
    assert ev["scores"] == {"centering": 9.0, "corners": 9.0, "edges": 8.0, "surface": 9.0}
    assert ev["url"].endswith(f"/cards/{card}/grades/{ev['id']}")
    sent = gemini.calls[0]["json"]
    parts = sent["contents"][0]["parts"]
    assert sum(1 for p in parts if "inline_data" in p) == 2  # frente e verso
    assert sent["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "medium"
    with app.app_context():
        saved = db.session.get(CardGradingEvaluation, ev["id"])
        assert saved.analysis["defects"][0]["type"] == "edge_whitening"
        assert saved.edges_score == 8


@pytest.mark.parametrize("front, back", [(OK, None), (None, OK), (None, None)], ids=["sem-verso", "sem-frente", "nenhuma"])
def test_foto_ausente(client, card, gemini, front, back):
    r = grade(client, card, front, back)
    assert r.status_code == 400 and r.get_json()["error"] == grader.MISSING_PHOTO_MESSAGE
    assert gemini.calls == []


def test_imagem_invalida_nao_chama_a_ia(client, card, gemini):
    r = grade(client, card, front=b"isto nao e uma imagem" * 10)
    assert r.status_code == 400 and "imagem válida" in r.get_json()["error"]
    assert gemini.calls == []


@pytest.mark.parametrize("bad, expected", [
    (photo("ok", size=(300, 420)), "pequena demais"),
    (photo("dark"), "muito escura"),
    (photo("blur"), "desfocada"),
    (photo("glare"), "reflexo"),
], ids=["pequena", "escura", "desfocada", "reflexo"])
def test_qualidade_ruim_nao_chama_a_ia(client, card, gemini, bad, expected):
    r = grade(client, card, back=bad)
    body = r.get_json()
    assert r.status_code == 422 and expected in body["error"] and "do verso" in body["error"]
    assert body["tips"] and gemini.calls == []


def test_ia_diz_que_a_foto_nao_serve(client, app, card, gemini):
    gemini.responses.append(gemini_returns(analysis(photo_quality={"usable": False, "issues": ["carta parcialmente cortada"]})))
    r = grade(client, card)
    body = r.get_json()
    assert r.status_code == 422 and "avaliação confiável" in body["error"] and body["issues"] == ["carta parcialmente cortada"]
    with app.app_context():
        assert db.session.query(CardGradingEvaluation).count() == 0


@pytest.mark.parametrize("bad", [
    "isto não é json",
    {"overall": {"estimated_range": "PSA dez", "confidence": "medium"}},
    analysis(overall={"estimated_range": "11"}),
    analysis(overall={"estimated_range": "9-7"}),
    analysis(edges={"score": 15}),
    analysis(surface="bom"),
])
def test_json_invalido_nao_salva(client, app, card, gemini, bad):
    gemini.responses.append(gemini_returns(bad))
    r = grade(client, card)
    assert r.status_code == 502 and r.get_json()["success"] is False
    with app.app_context():
        assert db.session.query(CardGradingEvaluation).count() == 0


# ---------- conteúdo da análise ----------
def test_sem_defeitos(client, card, gemini):
    gemini.responses.append(gemini_returns(analysis(defects=[], overall={"estimated_range": "9-10"},
                                                    edges={"score": 9.5})))
    ev = grade(client, card).get_json()["evaluation"]
    assert ev["estimated_range"] == "9-10"


def test_com_defeitos_normalizados(app):
    clean = grader.validate_analysis(analysis(defects=[
        {"type": "crease", "location": "front_center", "severity": "major", "visible": True, "description": "Vinco"},
        {"type": "alien_mark", "severity": "terrible", "visible": False, "description": "Talvez um risco sob o reflexo"},
        "lixo",
    ]))
    assert [d["type"] for d in clean["defects"]] == ["crease", "unknown"]
    assert clean["defects"][1] | {} == {"type": "unknown", "location": "", "severity": "minor", "visible": False,
                                       "description": "Talvez um risco sob o reflexo"}


def test_confianca_baixa_e_criterio_nao_avaliavel(client, app, card, gemini):
    gemini.responses.append(gemini_returns(analysis(
        overall={"estimated_range": "8-9", "confidence": "high"},
        surface={"score": None, "assessment": "Reflexo impede avaliar a superfície.", "confidence": "medium"})))
    ev = grade(client, card).get_json()["evaluation"]
    assert ev["confidence"] == "medium"  # rebaixada: superfície não avaliável
    with app.app_context():
        saved = db.session.get(CardGradingEvaluation, ev["id"])
        assert saved.surface_score is None and saved.analysis["surface"]["confidence"] == "low"


@pytest.mark.parametrize("ai_range, confidence, scores, expected", [
    ("8-9", "medium", (9, 9, 8, 9), "8-9"),
    ("9-10", "high", (10, 9.5, 9.5, 9.5), "9-10"),
    ("9", "medium", (9, 9, 9, 9), "8-9"),  # nota única sem confiança alta vira faixa
    ("9", "high", (9, 9, 9, 9), "9"),
    ("9-10", "medium", (9, 9, 7, 9), "8"),  # limitado pelo critério mais fraco (7 + 1) e ...
    ("10", "medium", (10, 10, 10, 10), "9-10"),
])
def test_regra_conservadora(ai_range, confidence, scores, expected):
    data = analysis(overall={"estimated_range": ai_range, "confidence": confidence})
    for name, score in zip(grader.CRITERIA, scores):
        data[name] = data[name] | {"score": score, "confidence": "high"}
    result = grader.apply_conservative_rules(grader.validate_analysis(data))
    # ... com confiança abaixo de alta, "8" vira "7-8"
    assert result["overall"]["estimated_range"] == (expected if expected != "8" else "7-8")
    assert result["overall"]["ai_estimated_range"] == grader.format_range(*grader.parse_range(ai_range))


@pytest.mark.parametrize("text, expected", [("8-9", (8, 9)), ("8–9", (8, 9)), ("PSA 9 - 10", (9, 10)), ("9", (9, 9))])
def test_parse_range(text, expected):
    assert grader.parse_range(text) == expected


# ---------- erros da IA ----------
def test_erro_da_api(client, card, gemini):
    gemini.responses += [FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), FakeResponse(503)]
    r = grade(client, card)
    assert r.status_code == 502 and "sobrecarregada" in r.get_json()["error"]


def test_timeout(client, card, gemini):
    gemini.responses += [requests.Timeout(), requests.Timeout()]
    r = grade(client, card)
    assert r.status_code == 504 and "demorou" in r.get_json()["error"]


def test_sem_chave(client, card, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    r = grade(client, card)
    assert r.status_code == 503


def test_card_inexistente(client, gemini):
    assert grade(client, 999).status_code == 404


def test_avaliacoes_simultaneas_do_mesmo_card(app, card, gemini, monkeypatch):
    """Enquanto uma avaliação espera a IA, a segunda do mesmo card recebe 409."""
    release, started = threading.Event(), threading.Event()

    def slow_post(*args, **kwargs):
        started.set()
        release.wait(5)
        return gemini_returns(analysis())

    monkeypatch.setattr(gemini_service.requests, "post", slow_post)
    results = {}
    first = threading.Thread(target=lambda: results.update(first=grade(app.test_client(), card).status_code))
    first.start()
    assert started.wait(5)
    results["second"] = grade(app.test_client(), card).status_code
    release.set()
    first.join(5)
    assert results == {"first": 201, "second": 409}
    assert not grader.is_busy(card)  # trava liberada


# ---------- histórico e nota oficial ----------
def test_historico_reavaliacao_e_exclusao(client, app, card, gemini):
    gemini.responses += [gemini_returns(analysis()), gemini_returns(analysis(overall={"estimated_range": "9-10"},
                                                                            edges={"score": 9}))]
    first = grade(client, card).get_json()["evaluation"]["id"]
    second = grade(client, card).get_json()["evaluation"]["id"]
    history = client.get(f"/api/cards/{card}/grades").get_json()["evaluations"]
    assert [e["id"] for e in history] == [second, first]  # mais recente primeiro
    page = client.get(f"/cards/{card}").get_data(as_text=True)
    assert "Histórico de avaliações" in page and "Possível faixa PSA 9–10" in page
    with app.app_context():
        card_service.delete_card(card_service.get_card(card))
        assert db.session.query(CardGradingEvaluation).count() == 0  # excluir o card apaga o histórico


def test_nota_oficial_separada_da_estimativa(client, app, gemini):
    with app.app_context():
        card_id = card_service.create_card({"pokemon_name": "Pikachu", "grading_company": "PSA", "official_grade": "10"}).id
    gemini.responses.append(gemini_returns(analysis()))
    ev = grade(client, card_id).get_json()["evaluation"]
    assert ev["official_grade_at_time"] == "PSA 10"
    with app.app_context():
        c = card_service.get_card(card_id)
        assert (c.grading_company, c.official_grade) == ("PSA", "10")  # a IA nunca altera a nota oficial
    page = client.get(f"/cards/{card_id}").get_data(as_text=True)
    assert "PSA oficial" in page and "Estimativa IA" in page


def test_validacao_da_nota_oficial(app):
    with app.app_context():
        with pytest.raises(card_service.ValidationError) as err:
            card_service.create_card({"pokemon_name": "Mew", "grading_company": "PSA", "official_grade": "11"})
        assert "official_grade" in err.value.errors
        with pytest.raises(card_service.ValidationError) as err:
            card_service.create_card({"pokemon_name": "Mew", "official_grade": "9"})
        assert "grading_company" in err.value.errors
        assert card_service.create_card({"pokemon_name": "Mew", "grading_company": "CGC", "official_grade": "9,5"}).official_grade == "9.5"


def test_resultado_nunca_parece_nota_oficial(client, card, gemini):
    gemini.responses.append(gemini_returns(analysis(overall={"estimated_range": "10", "confidence": "high"},
                                                    **{c: {"score": 10, "confidence": "high"} for c in grader.CRITERIA})))
    url = grade(client, card).get_json()["evaluation"]["url"]
    html = client.get(url).get_data(as_text=True)
    assert "Possível faixa" in html and "Avaliação visual por IA" in html and "não representa uma avaliação oficial" in html
    assert "PSA 10" in html.split("Possível faixa")[1][:200]  # "PSA 10" só logo depois de "Possível faixa"
    assert html.count("PSA 10") == 1


def test_formulario_sem_js(client, card, gemini):
    page = client.get(f"/cards/{card}/grade").get_data(as_text=True)
    assert 'capture="environment"' in page and 'name="front_image"' in page and 'name="back_image"' in page
    r = client.post(f"/cards/{card}/grade", data={"front_image": (io.BytesIO(OK), "f.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 400 and grader.MISSING_PHOTO_MESSAGE in r.get_data(as_text=True)
    gemini.responses.append(gemini_returns(analysis()))
    r = client.post(f"/cards/{card}/grade", data={"front_image": (io.BytesIO(OK), "f.jpg"), "back_image": (io.BytesIO(OK), "v.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 302 and "/grades/" in r.headers["Location"]


# ---------- migração do banco antigo ----------
def test_migracao_adiciona_colunas_sem_perder_dados(tmp_path):
    from app import create_app

    path = tmp_path / "antigo.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE cards (id INTEGER PRIMARY KEY, pokemon_name VARCHAR(120) NOT NULL, collection_name VARCHAR(120),
                   card_number VARCHAR(30), rarity VARCHAR(60), language VARCHAR(40), image_path VARCHAR(255), price NUMERIC(12,2),
                   price_source VARCHAR(120), price_date DATE, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)""")
    con.execute("INSERT INTO cards (pokemon_name, created_at, updated_at) VALUES ('Bulbasaur', '2026-10-01', '2026-10-01')")
    con.commit()
    con.close()
    app = create_app(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{path.as_posix()}", UPLOAD_FOLDER=tmp_path / "cards",
                     ADMIN_USERNAME="", ADMIN_PASSWORD_HASH="", IS_PRODUCTION=False, DATA_DIR=tmp_path)
    with app.app_context():
        card = card_service.list_cards()[0]
        assert card.pokemon_name == "Bulbasaur" and card.official_grade is None
        card_service.update_card(card, {"grading_company": "PSA", "official_grade": "8"}, partial=True)
        assert card_service.get_card(card.id).official_grade == "8"
    create_app(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{path.as_posix()}", DATA_DIR=tmp_path)  # idempotente
