"""
draft.py — lógica do sorteio (draft) de jogadores
==================================================

Regras do jogo:
  - A equipa tem 7 jogadores, escolhidos em 7 rondas.
  - Em cada ronda sorteiam-se 5 jogadores (guarda-redes e jogadores de campo juntos)
    e o utilizador escolhe 1.
  - Um jogador sorteado mas NÃO escolhido volta ao conjunto e pode reaparecer.
  - Um jogador já ESCOLHIDO nunca mais aparece.

Este módulo é só lógica: não sabe nada de Flask nem de Excel. Recebe nomes e devolve
nomes, por isso é fácil de testar (e serve igual para o modo offline e, mais tarde, o online).
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence

TAMANHO_EQUIPA = 7
OPCOES_POR_SORTEIO = 5


def sortear_opcoes(
    nomes: Sequence[str],
    escolhidos: Iterable[str],
    quantidade: int = OPCOES_POR_SORTEIO,
    rng: random.Random | None = None,
) -> list[str]:
    """Sorteia `quantidade` nomes diferentes de entre os que ainda não foram escolhidos.

    - `nomes`: todos os jogadores do Excel (o total é sempre o nº de linhas lidas).
    - `escolhidos`: os que já estão na equipa (nunca saem no sorteio).
    - `rng`: gerador aleatório (só se passa nos testes, para o resultado ser previsível).

    Se restarem menos jogadores do que `quantidade`, devolve todos os que restam.
    """
    rng = rng or random
    ja_escolhidos = set(escolhidos)
    disponiveis = [nome for nome in nomes if nome not in ja_escolhidos]
    return rng.sample(disponiveis, min(quantidade, len(disponiveis)))


def equipa_completa(escolhidos: Sequence[str]) -> bool:
    """True quando já há os 7 jogadores."""
    return len(escolhidos) >= TAMANHO_EQUIPA
