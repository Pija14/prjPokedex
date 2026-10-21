from conftest import JPG, PNG, WEBP, image


def create(client, **fields):
    data = {"pokemon_name": "Charizard", "collection_name": "Base Set", "card_number": "004/102",
            "rarity": "Holo Rare", "language": "Inglês", "price": "1.250,00", "price_source": "LigaPokémon"} | fields
    return client.post("/api/cards", data=data, content_type="multipart/form-data")


def test_crud_completo_com_imagem(client, upload_dir):
    r = create(client, image=image(PNG))
    assert r.status_code == 201
    card = r.get_json()
    assert card["price"] == "1250.00" and card["image_url"].startswith("/static/images/cards/")
    stored = upload_dir / card["image_path"].rsplit("/", 1)[1]
    assert stored.is_file() and stored.suffix == ".png" and stored.name != "carta.png"

    assert client.get(f"/api/cards/{card['id']}").get_json()["pokemon_name"] == "Charizard"
    assert [c["id"] for c in client.get("/api/cards?q=chari").get_json()] == [card["id"]]

    r = client.put(f"/api/cards/{card['id']}", json={"price": "1300", "rarity": "Rare Holo"})
    assert r.status_code == 200 and r.get_json()["price"] == "1300.00" and r.get_json()["pokemon_name"] == "Charizard"

    r = client.put(f"/api/cards/{card['id']}", data={"image": image(JPG, "nova.jpg")}, content_type="multipart/form-data")
    novo = upload_dir / r.get_json()["image_path"].rsplit("/", 1)[1]
    assert novo.is_file() and not stored.exists()  # imagem antiga removida ao trocar

    assert client.delete(f"/api/cards/{card['id']}").status_code == 204
    assert not novo.exists()  # imagem removida ao excluir
    assert client.get(f"/api/cards/{card['id']}").status_code == 404


def test_cria_por_json_sem_imagem(client):
    r = client.post("/api/cards", json={"pokemon_name": "Pikachu", "price": 15.9})
    assert r.status_code == 201 and r.get_json()["price"] == "15.90" and r.get_json()["image_url"] is None


def test_validacao_400(client):
    r = client.post("/api/cards", json={"pokemon_name": "", "price": "abc"})
    assert r.status_code == 400 and set(r.get_json()["errors"]) == {"pokemon_name", "price"}


def test_recusa_extensao_e_conteudo_invalidos(client, upload_dir):
    r = create(client, image=image(b"nao sou imagem" * 10, "falso.jpg"))
    assert r.status_code == 400 and "image" in r.get_json()["errors"]
    r = create(client, image=image(PNG, "carta.gif"))
    assert r.status_code == 400 and "Formato" in r.get_json()["errors"]["image"]
    assert not any(upload_dir.glob("*")) if upload_dir.exists() else True
    assert create(client, image=image(WEBP, "c.webp")).status_code == 201


def test_recusa_imagem_grande(client, app):
    app.config["MAX_IMAGE_MB"] = 1
    r = create(client, image=image(PNG + b"\x00" * (1024 * 1024 + 10)))
    assert r.status_code == 400 and "grande" in r.get_json()["errors"]["image"]


def test_404(client):
    assert client.get("/api/cards/999").status_code == 404
    assert client.put("/api/cards/999", json={"price": "1"}).status_code == 404
    assert client.delete("/api/cards/999").status_code == 404


def test_paginas_html(client):
    assert client.get("/").status_code == 200
    assert "Cards cadastrados" in client.get("/").get_data(as_text=True)
    r = client.post("/cards/new", data={"pokemon_name": "Mew", "price": "50", "image": image(PNG)}, content_type="multipart/form-data")
    assert r.status_code == 302
    card_id = int(r.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    html = client.get(f"/cards/{card_id}").get_data(as_text=True)
    assert "Mew" in html and "R$ 50,00" in html
    assert client.post("/cards/new", data={"pokemon_name": ""}).status_code == 400
    assert "Mew" in client.get("/cards?q=me").get_data(as_text=True)
    r = client.post(f"/cards/{card_id}/edit", data={"pokemon_name": "Mew", "price": "60,00"})
    assert r.status_code == 302 and "R$ 60,00" in client.get(f"/cards/{card_id}").get_data(as_text=True)
    assert client.post(f"/cards/{card_id}/delete").status_code == 302
    assert client.get(f"/cards/{card_id}").status_code == 404
