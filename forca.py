"""
forca.py — força de cada jogador e da equipa (modo offline)
===========================================================

A força NUNCA vai para o browser nem para o cookie da sessão: só é calculada no servidor,
no momento em que for precisa (a simulação da liga, no próximo passo).

Regras do enunciado:
  - A força de um jogador é a soma dos atributos × pesos da posição onde joga (taticas.PERFIS).
  - Jogador fora da sua posição: todos os atributos baixam 5.
  - Não-guarda-redes a jogar a guarda-redes: habilidade de guarda-redes = 40.
  - Guarda-redes a jogar no campo: Defesa, Drible, Remate, Físico, Passe e Velocidade = 40.
  - Força da equipa = média da força dos 7 jogadores.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

import taticas

PENALIZACAO_FORA_DE_POSICAO = 5
VALOR_FORA_DE_POSICAO_GR = 40     # guarda-redes sem ser guarda-redes, ou guarda-redes no campo

# Colunas do Excel offline -> nomes curtos usados nos perfis
COLUNAS = {
    "gr": "Habilidade como Guarda-Redes",
    "defesa": "Habilidade Defesa",
    "drible": "Habilidade Drible",
    "remate": "Habilidade Remate",
    "fisico": "Habilidade Físico",
    "passe": "Habilidade Passe",
    "velocidade": "Habilidade Velocidade",
}


def _atributo(stats: Mapping[str, float], chave: str, nome: str) -> float:
    valor = stats.get(chave)
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        raise ValueError(f"Falta o atributo '{chave}' de {nome} no Excel.")
    return float(valor)


def atributos_efetivos(
    nome: str,
    posicao_natural: str,
    stats: Mapping[str, float],
    posicao: taticas.Posicao,
) -> dict[str, float]:
    """Os atributos que contam quando o jogador joga NESTA posição (já com as regras do enunciado).

    - Na baliza: só conta "gr" (a habilidade de guarda-redes, ou 40 se não for guarda-redes).
    - No campo: os seis atributos; guarda-redes a jogar no campo tem 40 a tudo;
      jogador fora da sua posição tem todos os atributos −5.
    `stats` tem as chaves de taticas.ATRIBUTOS (valores em falta = NaN ou ausentes).
    """
    papeis = taticas.papeis_do_jogador(posicao_natural)

    if posicao.papel == taticas.GR:
        if taticas.GR in papeis:
            return {"gr": _atributo(stats, "gr", nome)}
        return {"gr": float(VALOR_FORA_DE_POSICAO_GR)}

    campo = [a for a in taticas.ATRIBUTOS if a != "gr"]
    if taticas.GR in papeis:
        # Guarda-redes a jogar no campo (mesmo que também tivesse outra posição no Excel,
        # o enunciado diz 40 a tudo).
        return {a: float(VALOR_FORA_DE_POSICAO_GR) for a in campo}

    desconto = 0 if posicao.papel in papeis else PENALIZACAO_FORA_DE_POSICAO
    return {a: max(0.0, _atributo(stats, a, nome) - desconto) for a in campo}


def forca_jogador(
    nome: str,
    posicao_natural: str,
    stats: Mapping[str, float],
    posicao: taticas.Posicao,
) -> float:
    """Força de um jogador colocado numa posição: atributos efetivos × pesos da posição."""
    efetivos = atributos_efetivos(nome, posicao_natural, stats, posicao)
    pesos = taticas.PERFIS[posicao.perfil]
    return sum(peso * efetivos[atributo] for atributo, peso in pesos.items())


def estatisticas_de(jogadores: pd.DataFrame) -> dict[str, tuple[str, dict[str, float]]]:
    """nome -> (posição natural, atributos) a partir do DataFrame do Excel offline."""
    resultado = {}
    for _, linha in jogadores.iterrows():
        stats = {chave: linha[coluna] for chave, coluna in COLUNAS.items()}
        resultado[linha["Nome"]] = (linha["Posição"], stats)
    return resultado


def forca_equipa(
    tatica: taticas.Tatica,
    escalacao: Mapping[str, str],
    jogadores: pd.DataFrame,
) -> float:
    """Média da força dos 7 jogadores. `escalacao` é posição -> nome (ver taticas.distribuir)."""
    ficha = estatisticas_de(jogadores)
    total = 0.0
    for posicao in tatica.posicoes:
        nome = escalacao[posicao.id]
        natural, stats = ficha[nome]
        total += forca_jogador(nome, natural, stats, posicao)
    return total / len(tatica.posicoes)
