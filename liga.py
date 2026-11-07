"""
liga.py — simulação rápida da liga do MODO OFFLINE
====================================================

`simular_liga_offline()` joga uma liga de 12 equipas (a do utilizador + as 11 do Excel),
em 2 voltas (22 jornadas, 2 jogos contra cada adversário), e devolve:
  - todos os resultados do utilizador, com quem marcou cada golo;
  - a tabela classificativa final (pontos, saldo de golos...);
  - os melhores marcadores da equipa do utilizador.

Só usa a FORÇA MÉDIA de cada equipa (o enunciado pede "cálculos rápidos baseados apenas na força
média"). A força nunca sai deste módulo para as páginas: o resultado só tem golos e nomes.

Como se decide um jogo (só 2 números mexem, ver as constantes abaixo):
  1. A diferença de força d = força(A) − força(B) decide como se reparte o total esperado de golos:
     a equipa A fica com a fração  p = 1 / (1 + e^(−SENSIBILIDADE × d))  de GOLOS_POR_JOGO.
  2. Cada equipa marca um nº de golos aleatório (distribuição de Poisson) com essa média.
Isto dá "força principalmente, com uma aleatoriedade baixa": com 5 pontos de diferença a equipa mais
forte ganha cerca de 77% dos jogos (e perde 12%); com forças iguais, 40% / 19% / 40%. Nunca saem resultados
absurdos, mesmo com diferenças enormes (o total esperado de golos é sempre o mesmo).

Os golos do utilizador são atribuídos aos seus jogadores conforme a posição onde jogam e a finalização
(Remate, Drible e Velocidade): avançados marcam mais, médios menos, defesas muito pouco, guarda-redes nunca.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

import forca
import taticas

NOME_EQUIPA_UTILIZADOR = "AC Travanca"

GOLOS_POR_JOGO = 4.6          # média de golos por jogo (as duas equipas somadas)
SENSIBILIDADE = 0.20          # quanto a diferença de força pesa (maior = menos aleatoriedade)
DURACAO_JOGO = 50             # minutos (futebol de 7: 2 partes de 25)

PESO_POR_PAPEL = {taticas.AVA: 1.0, taticas.MED: 0.45, taticas.DEF: 0.12, taticas.GR: 0.0}

PONTOS_VITORIA, PONTOS_EMPATE = 3, 1


# --------------------------------------------------------------------------- #
# Estruturas
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Jogo:
    jornada: int
    casa: str
    fora: str
    golos_casa: int
    golos_fora: int
    marcadores: tuple[tuple[str, int], ...] = ()    # (jogador, minuto): só os golos do utilizador


@dataclass
class LinhaTabela:
    equipa: str
    jogos: int = 0
    vitorias: int = 0
    empates: int = 0
    derrotas: int = 0
    golos_marcados: int = 0
    golos_sofridos: int = 0

    @property
    def pontos(self) -> int:
        return self.vitorias * PONTOS_VITORIA + self.empates * PONTOS_EMPATE

    @property
    def saldo(self) -> int:
        return self.golos_marcados - self.golos_sofridos


@dataclass
class ResultadoLiga:
    equipa_utilizador: str
    jogos_utilizador: list[Jogo]                 # os 22 jogos, por ordem de jornada
    tabela: list[LinhaTabela]                    # já ordenada: 1.º lugar primeiro
    marcadores: list[tuple[str, int]]            # (jogador, golos), melhores primeiro

    @property
    def linha_utilizador(self) -> LinhaTabela:
        return next(l for l in self.tabela if l.equipa == self.equipa_utilizador)

    @property
    def posicao_utilizador(self) -> int:
        return 1 + next(i for i, l in enumerate(self.tabela) if l.equipa == self.equipa_utilizador)

    def para_dict(self) -> dict:
        """Versão só com texto e números simples (para guardar em JSON e mostrar nas páginas)."""
        def resultado(jogo: Jogo) -> dict:
            em_casa = jogo.casa == self.equipa_utilizador
            meus, deles = (jogo.golos_casa, jogo.golos_fora) if em_casa else (jogo.golos_fora, jogo.golos_casa)
            return {
                "jornada": jogo.jornada,
                "casa": jogo.casa,
                "fora": jogo.fora,
                "golos_casa": jogo.golos_casa,
                "golos_fora": jogo.golos_fora,
                "adversario": jogo.fora if em_casa else jogo.casa,
                "resultado": "V" if meus > deles else "E" if meus == deles else "D",
                "pontos": PONTOS_VITORIA if meus > deles else PONTOS_EMPATE if meus == deles else 0,
                "marcadores": [{"nome": nome, "minuto": minuto} for nome, minuto in jogo.marcadores],
            }
        minha = self.linha_utilizador
        return {
            "equipa": self.equipa_utilizador,
            "jogos": [resultado(j) for j in self.jogos_utilizador],
            "tabela": [
                {"posicao": i, "equipa": l.equipa, "j": l.jogos, "v": l.vitorias, "e": l.empates, "d": l.derrotas,
                 "gm": l.golos_marcados, "gs": l.golos_sofridos, "sg": l.saldo, "pts": l.pontos}
                for i, l in enumerate(self.tabela, start=1)
            ],
            "marcadores": [{"nome": nome, "golos": golos} for nome, golos in self.marcadores],
            "resumo": {
                "posicao": self.posicao_utilizador,
                "pontos": minha.pontos,
                "saldo": minha.saldo,
                "golos_marcados": minha.golos_marcados,
                "vitorias": minha.vitorias,
                "empates": minha.empates,
                "derrotas": minha.derrotas,
            },
        }


# --------------------------------------------------------------------------- #
# Calendário
# --------------------------------------------------------------------------- #

def calendario(equipas: Sequence[str], rng: random.Random | None = None) -> list[list[tuple[str, str]]]:
    """Jornadas de uma liga a 2 voltas: lista de jornadas, cada uma com os jogos (casa, fora).

    Todas as equipas jogam em todas as jornadas e cada par joga duas vezes (uma em cada campo).
    A ordem das equipas é baralhada, para o utilizador não defrontar sempre os mesmos primeiro.
    """
    if len(equipas) % 2 or len(set(equipas)) != len(equipas):
        raise ValueError("São precisas equipas em número par e com nomes diferentes.")
    rng = rng or random
    rodas = list(equipas)
    rng.shuffle(rodas)

    n = len(rodas)
    primeira_volta = []
    for ronda in range(n - 1):
        jogos = []
        for i in range(n // 2):
            a, b = rodas[i], rodas[n - 1 - i]
            if i == 0 and ronda % 2 == 1:        # a equipa fixa alterna entre jogar em casa e fora
                a, b = b, a
            jogos.append((a, b))
        primeira_volta.append(jogos)
        rodas = [rodas[0], rodas[-1], *rodas[1:-1]]      # gira todas menos a primeira
    segunda_volta = [[(fora, casa) for casa, fora in jornada] for jornada in primeira_volta]
    return primeira_volta + segunda_volta


# --------------------------------------------------------------------------- #
# Um jogo
# --------------------------------------------------------------------------- #

def _poisson(media: float, rng: random.Random) -> int:
    limite, k, p = math.exp(-media), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def golos_esperados(forca_a: float, forca_b: float) -> tuple[float, float]:
    """Média de golos de cada equipa (só depende da diferença de força)."""
    parte_a = 1 / (1 + math.exp(-SENSIBILIDADE * (forca_a - forca_b)))
    return GOLOS_POR_JOGO * parte_a, GOLOS_POR_JOGO * (1 - parte_a)


def simular_jogo(forca_casa: float, forca_fora: float, rng: random.Random) -> tuple[int, int]:
    """(golos da casa, golos de fora)."""
    media_casa, media_fora = golos_esperados(forca_casa, forca_fora)
    return _poisson(media_casa, rng), _poisson(media_fora, rng)


# --------------------------------------------------------------------------- #
# Marcadores do utilizador
# --------------------------------------------------------------------------- #

def pesos_de_golo(
    tatica: taticas.Tatica,
    escalacao: Mapping[str, str],
    jogadores: pd.DataFrame,
) -> dict[str, float]:
    """Nome -> peso relativo para marcar golos, conforme a posição onde joga e a finalização.

    Usa os atributos efetivos (com o −5 / 40 de quem está fora de posição), por isso um defesa
    posto a avançado marca menos do que um avançado a sério.
    """
    ficha = forca.estatisticas_de(jogadores)
    pesos = {}
    for posicao in tatica.posicoes:
        nome = escalacao[posicao.id]
        natural, stats = ficha[nome]
        if posicao.papel == taticas.GR:
            pesos[nome] = 0.0
            continue
        ef = forca.atributos_efetivos(nome, natural, stats, posicao)
        finalizacao = 0.60 * ef["remate"] + 0.25 * ef["drible"] + 0.15 * ef["velocidade"]
        pesos[nome] = PESO_POR_PAPEL[posicao.papel] * (finalizacao / 75) ** 4
    return pesos


def _marcadores_do_jogo(golos: int, pesos: Mapping[str, float], rng: random.Random) -> tuple[tuple[str, int], ...]:
    if golos == 0:
        return ()
    nomes = list(pesos)
    pesos_lista = [pesos[n] for n in nomes]
    if sum(pesos_lista) <= 0:
        pesos_lista = [1.0] * len(nomes)
    golos_do_jogo = [
        (rng.choices(nomes, weights=pesos_lista)[0], rng.randint(1, DURACAO_JOGO))
        for _ in range(golos)
    ]
    return tuple(sorted(golos_do_jogo, key=lambda g: g[1]))


# --------------------------------------------------------------------------- #
# A liga
# --------------------------------------------------------------------------- #

def _ordem_tabela(linha: LinhaTabela):
    """Pontos, depois saldo de golos, depois golos marcados, depois nome (para ser sempre igual)."""
    return (-linha.pontos, -linha.saldo, -linha.golos_marcados, linha.equipa.casefold())


def simular_liga_offline(
    forcas: Mapping[str, float],
    pesos_marcadores: Mapping[str, float],
    equipa_utilizador: str = NOME_EQUIPA_UTILIZADOR,
    rng: random.Random | None = None,
) -> ResultadoLiga:
    """Simula a liga toda.

    - `forcas`: nome da equipa -> força média, incluindo a do utilizador (`equipa_utilizador`).
    - `pesos_marcadores`: jogador do utilizador -> peso para marcar (ver `pesos_de_golo`).
    """
    if equipa_utilizador not in forcas:
        raise ValueError("Falta a força da equipa do utilizador.")
    rng = rng or random.Random()

    tabela = {nome: LinhaTabela(nome) for nome in forcas}
    jogos_utilizador: list[Jogo] = []
    golos_por_jogador: dict[str, int] = {}

    for numero, jornada in enumerate(calendario(list(forcas), rng), start=1):
        for casa, fora in jornada:
            golos_casa, golos_fora = simular_jogo(forcas[casa], forcas[fora], rng)

            for equipa, marcou, sofreu in ((casa, golos_casa, golos_fora), (fora, golos_fora, golos_casa)):
                linha = tabela[equipa]
                linha.jogos += 1
                linha.golos_marcados += marcou
                linha.golos_sofridos += sofreu
                if marcou > sofreu:
                    linha.vitorias += 1
                elif marcou == sofreu:
                    linha.empates += 1
                else:
                    linha.derrotas += 1

            if equipa_utilizador in (casa, fora):
                meus_golos = golos_casa if casa == equipa_utilizador else golos_fora
                marcadores = _marcadores_do_jogo(meus_golos, pesos_marcadores, rng)
                for nome, _minuto in marcadores:
                    golos_por_jogador[nome] = golos_por_jogador.get(nome, 0) + 1
                jogos_utilizador.append(Jogo(numero, casa, fora, golos_casa, golos_fora, marcadores))

    melhores = sorted(golos_por_jogador.items(), key=lambda par: (-par[1], par[0].casefold()))
    return ResultadoLiga(
        equipa_utilizador=equipa_utilizador,
        jogos_utilizador=jogos_utilizador,
        tabela=sorted(tabela.values(), key=_ordem_tabela),
        marcadores=melhores,
    )
