"""Nomes em português do Brasil: raridades e coleções (sets) do Pokémon TCG.

Raridade: tradução fixa a partir do nome oficial em inglês (do catálogo ou da IA).
Coleção: nome oficial do lançamento brasileiro. Sets que não têm nome oficial em
português conhecido aqui ficam com o nome em inglês — melhor que inventar uma tradução.
"""
import re
import unicodedata

RARITY_PT = {
    "common": "Comum",
    "uncommon": "Incomum",
    "rare": "Rara",
    "rare holo": "Rara Holo",
    "holo rare": "Rara Holo",
    "reverse holo": "Holo Reversa",
    "rare holo ex": "Rara Holo EX",
    "rare holo gx": "Rara Holo GX",
    "rare holo lv.x": "Rara Holo LV.X",
    "rare holo star": "Rara Holo Estrela",
    "rare holo v": "Rara Holo V",
    "rare holo vmax": "Rara Holo VMAX",
    "rare holo vstar": "Rara Holo VSTAR",
    "double rare": "Rara Dupla",
    "rare ultra": "Ultra Rara",
    "ultra rare": "Ultra Rara",
    "illustration rare": "Rara Ilustração",
    "special illustration rare": "Rara Ilustração Especial",
    "hyper rare": "Hiper Rara",
    "rare secret": "Rara Secreta",
    "secret rare": "Rara Secreta",
    "rare rainbow": "Rara Arco-íris",
    "rare shiny": "Rara Brilhante",
    "shiny rare": "Rara Brilhante",
    "rare shiny gx": "Rara Brilhante GX",
    "shiny ultra rare": "Ultra Rara Brilhante",
    "rare shining": "Rara Reluzente",
    "rare break": "Rara BREAK",
    "rare prism star": "Rara Prisma Estrela",
    "rare prime": "Rara Prime",
    "rare ace": "Rara ACE SPEC",
    "ace spec rare": "Rara ACE SPEC",
    "amazing rare": "Rara Incrível",
    "radiant rare": "Rara Radiante",
    "legend": "LENDA",
    "trainer gallery rare holo": "Rara Holo Galeria de Treinador",
    "classic collection": "Coleção Clássica",
    "promo": "Promo",
}

# Nomes oficiais dos lançamentos no Brasil (eras Sol e Lua, Espada e Escudo, Escarlate e Violeta).
SET_NAME_PT = {
    # Clássicos (sem nome oficial em português): só deixa o nome do catálogo mais claro
    "Base": "Base Set",
    # Sol e Lua
    "Sun & Moon": "Sol e Lua",
    "Guardians Rising": "Guardiões Ascendentes",
    "Burning Shadows": "Sombras Ardentes",
    "Shining Legends": "Lendas Luminescentes",
    "Crimson Invasion": "Invasão Carmim",
    "Ultra Prism": "Ultraprisma",
    "Forbidden Light": "Luz Proibida",
    "Celestial Storm": "Tempestade Celestial",
    "Dragon Majesty": "Majestade dos Dragões",
    "Lost Thunder": "Trovões Perdidos",
    "Team Up": "União de Aliados",
    "Detective Pikachu": "Detetive Pikachu",
    "Unbroken Bonds": "Elos Inquebráveis",
    "Unified Minds": "Sintonia Mental",
    "Hidden Fates": "Destinos Ocultos",
    "Cosmic Eclipse": "Eclipse Cósmico",
    # Espada e Escudo
    "Sword & Shield": "Espada e Escudo",
    "Rebel Clash": "Conflito Rebelde",
    "Darkness Ablaze": "Escuridão Incandescente",
    "Champion's Path": "Caminho do Campeão",
    "Vivid Voltage": "Voltagem Vívida",
    "Shining Fates": "Destinos Brilhantes",
    "Battle Styles": "Estilos de Batalha",
    "Chilling Reign": "Reinado Arrepiante",
    "Evolving Skies": "Céus em Evolução",
    "Celebrations": "Celebrações",
    "Fusion Strike": "Golpe Fusão",
    "Brilliant Stars": "Astros Cintilantes",
    "Lost Origin": "Origem Perdida",
    "Pokémon GO": "Pokémon GO",
    "Silver Tempest": "Tempestade Prateada",
    "Crown Zenith": "Realeza Absoluta",
    # Escarlate e Violeta
    "Scarlet & Violet": "Escarlate e Violeta",
    "Paldea Evolved": "Evoluções em Paldea",
    "Obsidian Flames": "Obsidiana em Chamas",
    "151": "Escarlate e Violeta 151",
    "Scarlet & Violet—151": "Escarlate e Violeta 151",
    "Paradox Rift": "Fenda Paradoxal",
    "Paldean Fates": "Destinos de Paldea",
    "Temporal Forces": "Forças Temporais",
    "Twilight Masquerade": "Máscaras do Crepúsculo",
    "Shrouded Fable": "Fábula Sombria",
    "Stellar Crown": "Coroa Estelar",
    "Surging Sparks": "Fagulhas Impetuosas",
    "Prismatic Evolutions": "Evoluções Prismáticas",
    "Journey Together": "Amigos de Jornada",
    "Destined Rivals": "Rivais Predestinados",
}


def _key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9.]+", " ", text).strip()


_RARITY_BY_KEY = {_key(k): v for k, v in RARITY_PT.items()}
_SET_BY_KEY = {_key(k): v for k, v in SET_NAME_PT.items()}
_PT_SET_NAMES = {_key(v) for v in SET_NAME_PT.values()}
_PT_RARITIES = {_key(v) for v in RARITY_PT.values()}


def rarity_pt(name: str | None) -> str | None:
    """'Rare Holo' → 'Rara Holo'. Já em português ou desconhecida: devolve como veio."""
    if not name:
        return None
    key = _key(name)
    if key in _PT_RARITIES:
        return name
    return _RARITY_BY_KEY.get(key, name)


def set_name_pt(name: str | None) -> str | None:
    """'Crown Zenith' → 'Realeza Absoluta'. Sem nome oficial conhecido: mantém o inglês."""
    if not name:
        return None
    key = _key(name)
    if key in _PT_SET_NAMES:
        return name
    return _SET_BY_KEY.get(key, name)
