"""Preço pela MYP Cards: leitura da busca e da página do produto (HTML simulado no formato real do site)."""
import io

import pytest

from services import myp_service, price_service
from services.gemini_service import CardIdentification
from test_gemini import CHARIZARD, calls, gemini_ok  # noqa: F401  (calls é fixture)


def item(key, title, set_name, set_code, price="R$&nbsp;60,00"):
    edition = f'<span class="card-edicao" title="{set_name}">{set_code}</span>' if set_code else ""
    return f'''<li class="stream-item" data-key="{key}"> <div class="card" data-ga-item-id="x">
      <a class="card-img-link" href="/pokemon/produto/{key}/carta"><img class="card-thumb" src="x.jpg"></a>
      <div class="card-dados"><div class="card-name"><h3 title="{title}"> {title} </h3>
      <div class="card-subname"><span class="nome-original "></span> {edition} </div></div>
      <div class="card-estatistica"><span class="quantidade"><span class="quantidade-num">8</span></span>
      <span class="card-preco moeda"> {price} </span></div></div></div> </li>'''


def search_page(*items):
    return "<html><ul>" + "".join(items) + "</ul></html>"


PRODUCT = '''<div class="estatistica-precos estatistica-precos--cabecalho"> <div class="resumo-precos"><span class="resumo-preco
 resumo-preco--menor" title="Menor preço · Preço médio R$ 4.890,32" role="group" aria-label="Menor preço"><i class="fas fa-arrow-down"></i><span class="moeda">R$&nbsp;849,96</span></span><span class="resumo-preco resumo-preco--tcg" title="Preço TCG Player"><span class="svg-icon"><svg><path d="M0"/></svg></span><span class="moeda">R$&nbsp;41,05</span></span><span class="resumo-preco resumo-preco--ultimo" title="Último preço vendido (NM · Normal · Português)" role="group"><span class="moeda">R$&nbsp;1.800,00</span></span></div></div>'''.replace("resumo-preco\n resumo", "resumo-preco resumo")

# Página 1: reimpressão com o mesmo número; página 2: a carta da coleção Base.
PAGES = {
    1: search_page(item(1, "Moeda Charizard VMAX", None, None), item(456300, "Charizard (004/102)", "ME: 30th Celebration", "30CC"),
                   item(206056, "Charizard ex (183/165)", "Escarlate e Violeta: 151", "MEW")),
    2: search_page(item(1592, "Charizard (004/102)", "Coleção Básica", "BS", "R$&nbsp;849,96"),
                   item(476248, "Charizard (004/102)", "Celebrations: Classic Collection", "CCC")),
    3: search_page(),
}


@pytest.fixture()
def myp(monkeypatch):
    """Site simulado; `myp.calls` guarda as páginas pedidas."""
    calls_log = []

    def fake_get(path, params=None, deadline=None):
        calls_log.append((path, dict(params or {})))
        if path == "/pokemon":
            return PAGES[int((params or {}).get("page", 1))]
        return PRODUCT

    monkeypatch.setattr(myp_service, "_get", fake_get)
    return calls_log


def test_le_a_busca():
    items = myp_service.parse_search(PAGES[1])
    assert [(i["title"], i["number"], i["set_code"], i["price"]) for i in items] == [
        ("Moeda Charizard VMAX", None, None, 60.0),
        ("Charizard (004/102)", "004/102", "30CC", 60.0),
        ("Charizard ex (183/165)", "183/165", "MEW", 60.0),
    ]
    assert items[1]["href"] == "/pokemon/produto/456300/carta"


def test_le_o_resumo_do_produto():
    assert myp_service.parse_product(PRODUCT) == {
        "lowest": 849.96, "average": 4890.32, "last_sold": 1800.0, "last_sold_detail": "NM · Normal · Português"}
    assert myp_service.parse_product("<html>layout novo</html>") == {}


def test_acha_a_colecao_certa_mesmo_com_reimpressao(myp):
    price = myp_service.lookup("Charizard", "4/102", "BS")
    assert (price.title, price.set_code, price.average, price.lowest, price.last_sold) == (
        "Charizard (004/102)", "BS", 4890.32, 849.96, 1800.0)
    assert price.url == "https://mypcards.com/pokemon/produto/1592/carta"
    assert [c[1].get("page", 1) for c in myp if c[0] == "/pokemon"] == [1, 2]  # parou ao achar


def test_sem_codigo_e_ambiguo_nao_chuta(myp):
    assert myp_service.lookup("Charizard", "4/102") is None  # 3 coleções com 004/102


def test_sem_codigo_mas_unica_colecao(myp):
    assert myp_service.lookup("Charizard ex", "183/165").set_code == "MEW"


def test_nao_achou_ou_site_fora(myp, monkeypatch):
    assert myp_service.lookup("Charizard", "999/102", "BS") is None
    monkeypatch.setattr(myp_service, "_cache", {})
    monkeypatch.setattr(myp_service, "_get", lambda *a, **k: None)
    assert myp_service.lookup("Charizard", "4/102", "BS") is None
    assert myp_service.lookup(None, "4/102") is None and myp_service.lookup("Charizard", None) is None


def test_layout_inesperado_nao_quebra(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("layout mudou")

    monkeypatch.setattr(myp_service, "_lookup", boom)
    assert myp_service.lookup("Charizard", "4/102", "BS") is None


def test_cache(myp):
    myp_service.lookup("Charizard", "4/102", "BS")
    pedidos = len(myp)
    myp_service.lookup("Charizard", "4/102", "BS")
    assert len(myp) == pedidos


def test_preco_usa_myp_antes_da_referencia(myp):
    ident = CardIdentification(pokemon_name="Charizard", card_number="4/102", extra={},
                               catalog={"set_code": "BS", "ref_prices": {"tcgplayer": {"variants": {"holofoil": 954.65}}}})
    q = price_service.quote(ident)
    assert q.source == "myp"
    assert q.main == {"name": "myp", "source": "MYP Cards", "label": "preço médio", "value": 4890.32}
    assert q.myp["last_sold"] == 1800.0


def test_vitrine_com_preco_da_myp(client, calls, myp):
    calls.responses.append(gemini_ok(CHARIZARD | {"extra": {"set_code": "BS"}}))
    response = client.post("/scan", data={"image": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 64), "c.jpg")},
                           content_type="multipart/form-data", headers={"X-Scan-Fragment": "1"})
    html = response.get_data(as_text=True)
    assert "Preço no Brasil" in html and "R$ 4.890,32" in html and "R$ 849,96" in html and "R$ 1.800,00" in html
    assert "Ver ofertas na MYP Cards" in html and "mypcards.com/pokemon/produto/1592" in html


@pytest.mark.parametrize("printed, expected", [
    ("PBLPT", "PBL"), ("PBL PT", "PBL"), ("MEW", "MEW"), ("svp", "SVP"), ("OBFEN", "OBF"), ("PT", "PT"), ("", None), (None, None),
])
def test_codigo_sem_idioma(printed, expected):
    assert price_service.set_code_without_language(printed) == expected


def test_codigo_impresso_em_portugues_acha_na_myp(myp):
    """A IA lê 'BSPT' (idioma colado ao código) e o catálogo não confirmou: ainda assim acha pela sigla BS."""
    ident = CardIdentification(pokemon_name="Charizard", card_number="4/102", extra={"set_code": "BSPT"})
    assert price_service.quote(ident).myp["set_code"] == "BS"
