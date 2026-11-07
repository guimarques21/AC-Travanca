"""
taticas.py — as 4 formações táticas e as regras de posição
===========================================================

Este módulo é só dados e lógica: não sabe nada de Flask nem de Excel.

Cada tática tem 7 posições ("slots"). Cada posição tem:
  - o papel (guarda-redes, defesa, médio, avançado);
  - o perfil de pesos dos atributos, tal como está no enunciado (soma sempre 100%);
  - onde fica no campo desenhado (x, y em %, a baliza própria fica em baixo).

Os números das posições (p1…p7) seguem a numeração das imagens do enunciado.

Notas sobre o enunciado (ver README):
  - Tática 4 (texto corrigido pelo autor): GR 100%; defesa central 43/43/10/4; defesas laterais
    31/31/15/10/10/3; médio Defesa 10, Drible 30, Físico 10, Passe 35, Velocidade 10, Remate 5
    (a mesma fórmula dos médios da tática 3); avançado 23/28/23/10/15/1.
  - "Drible+Remate+Velocidade (X%)" é repartido em partes iguais pelos três atributos.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import permutations

# Papéis (o que uma posição é, e o que um jogador sabe jogar)
GR, DEF, MED, AVA = "gr", "def", "med", "ava"

SIGLA_PAPEL = {GR: "GR", DEF: "DEF", MED: "MED", AVA: "AVA"}
NOME_PAPEL = {GR: "Guarda-redes", DEF: "Defesa", MED: "Médio", AVA: "Avançado"}

# Atributos usados no cálculo (as chaves usadas em forca.py)
ATRIBUTOS = ("gr", "defesa", "drible", "remate", "fisico", "passe", "velocidade")


# --------------------------------------------------------------------------- #
# Perfis de pesos (percentagens do enunciado)
# --------------------------------------------------------------------------- #

def _perfil(*, gr=0, defesa=0, drible=0, remate=0, fisico=0, passe=0, velocidade=0, dvr=0) -> dict[str, float]:
    """Constrói um perfil em frações (45 -> 0.45). `dvr` é "Drible+Remate+Velocidade", repartido por 3."""
    pesos = {
        "gr": gr, "defesa": defesa, "fisico": fisico, "passe": passe,
        "drible": drible + dvr / 3, "remate": remate + dvr / 3, "velocidade": velocidade + dvr / 3,
    }
    pesos = {nome: valor / 100 for nome, valor in pesos.items() if valor}
    assert abs(sum(pesos.values()) - 1) < 1e-9, f"os pesos têm de somar 100%: {pesos}"
    return pesos


PERFIS = {
    "guarda_redes":   _perfil(gr=100),
    "defesa":         _perfil(defesa=42, fisico=42, passe=11, dvr=5),
    "defesa_central": _perfil(defesa=43, fisico=43, passe=10, dvr=4),
    "defesa_lateral": _perfil(defesa=31, fisico=31, passe=15, velocidade=10, drible=10, remate=3),
    "medio_central":  _perfil(defesa=10, drible=30, fisico=10, passe=35, velocidade=5, remate=10),   # T1 (nº4) e T2 (nº5)
    "medio_ala":      _perfil(drible=30, remate=15, passe=25, velocidade=20, defesa=5, fisico=5),    # T1 (nº5 e 6)
    "medio":          _perfil(defesa=10, drible=30, fisico=10, passe=35, velocidade=10, remate=5),   # T3 e T4
    "avancado":       _perfil(drible=23, remate=28, fisico=23, passe=10, velocidade=15, defesa=1),
}


# --------------------------------------------------------------------------- #
# As 4 táticas
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Posicao:
    id: str          # "p1" … "p7" (numeração do enunciado)
    papel: str       # GR, DEF, MED ou AVA
    perfil: str      # chave de PERFIS
    nome: str        # texto para leitores de ecrã, ex.: "Defesa lateral"
    x: float         # posição no campo desenhado, em % da largura (0 = esquerda)
    y: float         # em % da altura (0 = baliza adversária, 100 = baliza própria)


@dataclass(frozen=True)
class Tatica:
    id: int
    esquema: str                      # ex.: "2-3-1" (defesas-médios-avançados)
    posicoes: tuple[Posicao, ...]

    @property
    def nome(self) -> str:
        return f"Tática {self.id}"

    @property
    def descricao(self) -> str:
        contagem = {papel: sum(1 for p in self.posicoes if p.papel == papel) for papel in (DEF, MED, AVA)}
        def plural(n, singular, plural_):
            return f"{n} {singular if n == 1 else plural_}"
        return ", ".join([
            plural(contagem[DEF], "defesa", "defesas"),
            plural(contagem[MED], "médio", "médios"),
            plural(contagem[AVA], "avançado", "avançados"),
        ])


def _p(id_, papel, perfil, nome, x, y) -> Posicao:
    return Posicao(id_, papel, perfil, nome, x, y)


_GR = _p("p1", GR, "guarda_redes", "Guarda-redes", 50, 83)

TATICAS: dict[int, Tatica] = {
    # Tática 1: 1 GR, 2 defesas, 3 médios (1 central e 2 pelas laterais), 1 avançado
    1: Tatica(1, "2-3-1", (
        _GR,
        _p("p2", DEF, "defesa", "Defesa", 30, 62),
        _p("p3", DEF, "defesa", "Defesa", 70, 62),
        _p("p4", MED, "medio_central", "Médio central", 50, 40),
        _p("p5", MED, "medio_ala", "Médio ala", 13, 34),
        _p("p6", MED, "medio_ala", "Médio ala", 87, 34),
        _p("p7", AVA, "avancado", "Avançado", 50, 13),
    )),
    # Tática 2: 1 GR, 3 defesas (1 central e 2 laterais), 1 médio, 2 avançados
    2: Tatica(2, "3-1-2", (
        _GR,
        _p("p2", DEF, "defesa_lateral", "Defesa lateral", 14, 58),
        _p("p3", DEF, "defesa_lateral", "Defesa lateral", 86, 58),
        _p("p4", DEF, "defesa_central", "Defesa central", 50, 62),
        _p("p5", MED, "medio_central", "Médio central", 50, 38),
        _p("p6", AVA, "avancado", "Avançado", 32, 13),
        _p("p7", AVA, "avancado", "Avançado", 68, 13),
    )),
    # Tática 3: 1 GR, 2 defesas, 2 médios, 2 avançados  (p2/p4 defesas, p3/p5 médios, como na imagem 3)
    3: Tatica(3, "2-2-2", (
        _GR,
        _p("p2", DEF, "defesa", "Defesa", 30, 62),
        _p("p3", MED, "medio", "Médio", 30, 38),
        _p("p4", DEF, "defesa", "Defesa", 70, 62),
        _p("p5", MED, "medio", "Médio", 70, 38),
        _p("p6", AVA, "avancado", "Avançado", 32, 13),
        _p("p7", AVA, "avancado", "Avançado", 68, 13),
    )),
    # Tática 4: 1 GR, 3 defesas (1 central e 2 laterais), 2 médios, 1 avançado
    4: Tatica(4, "3-2-1", (
        _GR,
        _p("p2", DEF, "defesa_lateral", "Defesa lateral", 14, 58),
        _p("p3", DEF, "defesa_lateral", "Defesa lateral", 86, 58),
        _p("p4", DEF, "defesa_central", "Defesa central", 50, 62),
        _p("p5", MED, "medio", "Médio", 32, 38),
        _p("p6", MED, "medio", "Médio", 68, 38),
        _p("p7", AVA, "avancado", "Avançado", 50, 13),
    )),
}

for _t in TATICAS.values():
    assert len(_t.posicoes) == 7 and _t.posicoes[0].papel == GR
    assert len({p.id for p in _t.posicoes}) == 7


def obter_tatica(id_) -> Tatica | None:
    """A tática com esse número, ou None se não existir (aceita int ou texto)."""
    if isinstance(id_, int) and not isinstance(id_, bool):
        return TATICAS.get(id_)
    # Só algarismos 0-9 normais ("٣" ou "³" também passariam em int(), mas não são pedidos legítimos)
    if isinstance(id_, str) and id_.isascii() and id_.isdigit():
        return TATICAS.get(int(id_))
    return None


# --------------------------------------------------------------------------- #
# Posição natural dos jogadores
# --------------------------------------------------------------------------- #

def _normalizar(texto: str) -> str:
    sem_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return sem_acentos.casefold().strip()


_PAPEL_POR_TEXTO = {"guarda-redes": GR, "defesa": DEF, "medio": MED, "avancado": AVA}


def papeis_do_jogador(posicao: str) -> frozenset[str]:
    """'Defesa/Médio' -> {DEF, MED}. Aceita maiúsculas/acentos diferentes. Texto desconhecido é erro."""
    papeis = set()
    for parte in str(posicao).split("/"):
        chave = _normalizar(parte)
        if chave not in _PAPEL_POR_TEXTO:
            raise ValueError(f"Posição desconhecida no Excel: {parte!r}")
        papeis.add(_PAPEL_POR_TEXTO[chave])
    return frozenset(papeis)


def fora_de_posicao(posicao_natural: str, posicao: Posicao) -> bool:
    """True se o jogador não joga naturalmente no papel desta posição."""
    return posicao.papel not in papeis_do_jogador(posicao_natural)


# --------------------------------------------------------------------------- #
# Colocar os jogadores nas posições
# --------------------------------------------------------------------------- #

def distribuir(
    tatica: Tatica,
    jogadores: Sequence[str],
    posicoes_naturais: Mapping[str, str],
    papeis_anteriores: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Sugere onde pôr cada jogador (posição -> nome). O utilizador pode trocar depois.

    Escolhe a distribuição com mais jogadores no seu papel natural. Se `papeis_anteriores`
    (nome -> papel que tinha na tática anterior) vier preenchido, tenta primeiro manter cada
    jogador no mesmo papel, para que mudar de tática não deite fora as escolhas já feitas.
    Em empate ganha a primeira por ordem de escolha (resultado sempre igual para os mesmos dados).
    """
    if len(jogadores) != len(tatica.posicoes):
        raise ValueError("São precisos exatamente 7 jogadores.")
    anteriores = papeis_anteriores or {}
    naturais = {nome: papeis_do_jogador(posicoes_naturais[nome]) for nome in jogadores}

    melhor, melhor_pontos = None, None
    for ordem in permutations(range(len(jogadores))):
        manteve = naturais_certos = 0
        for posicao, indice in zip(tatica.posicoes, ordem):
            nome = jogadores[indice]
            manteve += anteriores.get(nome) == posicao.papel
            naturais_certos += posicao.papel in naturais[nome]
        pontos = (manteve, naturais_certos)
        if melhor_pontos is None or pontos > melhor_pontos:
            melhor, melhor_pontos = ordem, pontos
    return {posicao.id: jogadores[indice] for posicao, indice in zip(tatica.posicoes, melhor)}


def trocar(escalacao: Mapping[str, str], posicao_a: str, posicao_b: str) -> dict[str, str]:
    """Uma cópia da escalação com os jogadores destas duas posições trocados."""
    if posicao_a not in escalacao or posicao_b not in escalacao:
        raise KeyError("Posição inexistente.")
    nova = dict(escalacao)
    nova[posicao_a], nova[posicao_b] = escalacao[posicao_b], escalacao[posicao_a]
    return nova


def escalacao_valida(tatica: Tatica, escalacao: Mapping[str, str], equipa: Sequence[str]) -> bool:
    """True se há exatamente um dos 7 jogadores da equipa em cada posição da tática."""
    return (
        set(escalacao) == {p.id for p in tatica.posicoes}
        and sorted(escalacao.values()) == sorted(equipa)
        and len(set(escalacao.values())) == len(tatica.posicoes)
    )


def papeis_da_escalacao(tatica: Tatica, escalacao: Mapping[str, str]) -> dict[str, str]:
    """nome -> papel da posição onde está (guarda-se para `distribuir` na próxima troca de tática)."""
    papel_de = {p.id: p.papel for p in tatica.posicoes}
    return {nome: papel_de[posicao_id] for posicao_id, nome in escalacao.items()}
