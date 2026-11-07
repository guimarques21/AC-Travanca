"""
salas.py — as salas privadas do MODO ONLINE (Passo 5): lógica pura, sem Flask nem Excel
=======================================================================================

Uma sala é um jogo entre DOIS utilizadores. O primeiro (lugar "A") cria a sala e envia o link
de convite; o segundo (lugar "B") abre o link e entra. A sala passa por estas fases:

    espera   → o anfitrião criou a sala e ainda ninguém entrou
    sorteio  → sorteio à vez: cada um escolhe 7 jogadores (14 escolhas, de um conjunto comum)
    taticas  → cada um escolhe a tática, põe os jogadores no campo, escolhe as funções, o estilo de jogo e
               quem bate livres e cantos (Passo 6), e carrega em "Estou pronto"
    pronta   → os dois estão prontos: o jogo é simulado (Passo 7, `match_engine.py`) e os dois veem o fim do jogo
    abandonada → alguém saiu da sala

Regras do sorteio (como no enunciado):
  - Um utilizador de cada vez; começa um dos dois à sorte e depois alternam.
  - Em cada vez sorteiam-se 5 jogadores de entre os que NINGUÉM escolheu ainda (nem ele nem o
    adversário). Os sorteados e não escolhidos podem voltar a aparecer.
  - Um jogador escolhido por um utilizador nunca mais aparece nas opções de nenhum dos dois.
  - A oferta fica guardada: atualizar a página não volta a sortear.

Segurança:
  - Cada lugar tem um `token` secreto (aleatório). Só quem o tem (fica no cookie de sessão de
    quem criou ou entrou) pode agir nesse lugar. Os ids das salas são UUID4 (impossíveis de adivinhar).
  - Esta lógica nunca vê atributos nem forças: só nomes de jogadores, números de tática e posições.
  - A tática de um utilizador NÃO é mostrada ao adversário antes de o jogo começar (só se já escolheu).
    O mesmo vale para as funções, o estilo e os marcadores: o adversário nunca os vê.

As salas vivem na memória do servidor (precisam de um único processo, ver README). Uma sala
sem atividade durante `ttl` segundos é apagada.

Todos os métodos têm um trinco (`Lock`): vários pedidos ao mesmo tempo não se atropelam.
"""

from __future__ import annotations

import json
import random
import secrets
import threading
import time
import uuid
import zlib
from dataclasses import dataclass, field

import draft
import funcoes as fun
import taticas
import visual

# Fases
ESPERA = "espera"
SORTEIO = "sorteio"
TATICAS = "taticas"
PRONTA = "pronta"
ABANDONADA = "abandonada"

LUGARES = ("A", "B")

TTL_SEGUNDOS = 3 * 3600          # uma sala sem atividade durante 3 horas é apagada
MAXIMO_SALAS = 500               # limite de salas abertas ao mesmo tempo
LIMITE_PRESENCA = 12.0           # sem sinal durante tanto tempo = "desligado"


class ErroSala(Exception):
    """Algo que o utilizador não pode fazer agora. `codigo` serve ao código; `mensagem` vai para o ecrã."""

    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


@dataclass
class Lugar:
    letra: str                        # "A" ou "B"
    token: str                        # segredo deste lugar
    nome: str                         # nome do treinador
    equipa: list[str] = field(default_factory=list)   # jogadores escolhidos, por ordem de escolha
    oferta: list[str] = field(default_factory=list)   # as 5 opções atuais (só quando é a vez deste lugar)
    tatica: int | None = None
    escalacao: dict[str, str] = field(default_factory=dict)   # "p1".."p7" -> nome
    funcoes: dict[str, str] = field(default_factory=dict)     # "p1".."p7" -> função (ver funcoes.py)
    estilo: str | None = None                                 # estilo de jogo da equipa (obrigatório: não há por defeito)
    livres: str | None = None         # quem bate os livres (nome de um jogador de campo)
    cantos: str | None = None         # quem bate os cantos
    a_mudar_tatica: bool = False      # está a ver os cartões de tática para mudar
    pronto: bool = False
    saiu: bool = False                # saiu da sala depois do jogo (o outro continua a ver o fim do jogo)
    visto: float = 0.0                # último sinal de vida (relógio do servidor)


@dataclass
class Sala:
    id: str
    jogadores: tuple[str, ...]        # todos os nomes disponíveis no sorteio (fixos desde a criação)
    criada: float
    atividade: float
    estado: str = ESPERA
    lugares: dict[str, Lugar] = field(default_factory=dict)
    vez: str | None = None            # de quem é a vez de escolher
    primeiro: str | None = None       # quem começou o sorteio
    saiu: str | None = None           # quem saiu (se abandonada)
    semente: int | None = None        # semente do jogo (sorteada quando os dois ficam prontos): o jogo é sempre o mesmo
    resultado: dict | None = None     # o resultado PÚBLICO do jogo (sem posições nem atributos), calculado uma só vez
    eventos_z: bytes | None = None    # todos os eventos do jogo (com posições, para o Passo 8), em JSON comprimido
    filmes: dict[int, bytes] = field(default_factory=dict, repr=False)   # o «filme» (visual.py) já comprimido, por lugar (0 = A, 1 = B)
    calculo: threading.Lock = field(default_factory=threading.Lock, repr=False)   # só um pedido calcula o jogo


class Salas:
    """Todas as salas abertas."""

    def __init__(self, rng: random.Random | None = None, relogio=time.time,
                 ttl: float = TTL_SEGUNDOS, maximo: int = MAXIMO_SALAS):
        self._salas: dict[str, Sala] = {}
        self._trinco = threading.RLock()
        self.rng = rng or random.Random()
        self.relogio = relogio
        self.ttl = ttl
        self.maximo = maximo

    # ------------------------------------------------------------------ utilitários

    @staticmethod
    def _outro(letra: str) -> str:
        return "B" if letra == "A" else "A"

    def _purgar(self) -> None:
        limite = self.relogio() - self.ttl
        for sala_id in [i for i, s in self._salas.items() if s.atividade < limite]:
            del self._salas[sala_id]

    def total(self) -> int:
        with self._trinco:
            return len(self._salas)

    def existe(self, sala_id: str) -> bool:
        with self._trinco:
            return sala_id in self._salas

    def _sala(self, sala_id: str) -> Sala:
        sala = self._salas.get(sala_id) if isinstance(sala_id, str) else None
        if sala is not None and sala.atividade < self.relogio() - self.ttl:
            del self._salas[sala_id]                      # expirou
            sala = None
        if sala is None:
            raise ErroSala("sala_inexistente", "Esta sala já não existe.")
        return sala

    def _lugar(self, sala: Sala, token: str) -> Lugar:
        if isinstance(token, str):
            for lugar in sala.lugares.values():
                if secrets.compare_digest(lugar.token, token):
                    lugar.visto = self.relogio()
                    sala.atividade = self.relogio()
                    return lugar
        raise ErroSala("sem_lugar", "Não tens lugar nesta sala.")

    def _oferecer(self, sala: Sala) -> None:
        """Sorteia as 5 opções para quem tem a vez (de entre os jogadores que ninguém escolheu)."""
        lugar = sala.lugares[sala.vez]
        escolhidos = [n for l in sala.lugares.values() for n in l.equipa]
        lugar.oferta = draft.sortear_opcoes(sala.jogadores, escolhidos, rng=self.rng)

    # ------------------------------------------------------------------ criar e entrar

    def criar(self, nome: str, jogadores: list[str]) -> tuple[str, str]:
        """Cria uma sala com o utilizador no lugar A. Devolve (id da sala, token do lugar)."""
        with self._trinco:
            self._purgar()
            if len(self._salas) >= self.maximo:
                raise ErroSala("cheio", "Há demasiadas salas abertas neste momento. Tenta daqui a pouco.")
            agora = self.relogio()
            # Precisa de pelo menos 14 jogadores (2 equipas de 7), senão o sorteio não acaba.
            if len(set(jogadores)) < 2 * draft.TAMANHO_EQUIPA:
                raise ErroSala("poucos_jogadores", "Não há jogadores suficientes para duas equipas.")
            sala = Sala(id=str(uuid.uuid4()), jogadores=tuple(dict.fromkeys(jogadores)),
                        criada=agora, atividade=agora)
            token = secrets.token_urlsafe(16)
            sala.lugares["A"] = Lugar(letra="A", token=token, nome=nome, visto=agora)
            self._salas[sala.id] = sala
            return sala.id, token

    def entrar(self, sala_id: str, nome: str) -> str:
        """O convidado entra no lugar B. Devolve o token. O sorteio começa logo."""
        with self._trinco:
            self._purgar()
            sala = self._sala(sala_id)
            if sala.estado == ABANDONADA:
                raise ErroSala("abandonada", "Esta sala já não está disponível.")
            if "B" in sala.lugares:
                raise ErroSala("sala_cheia", "Esta sala já tem dois jogadores.")
            agora = self.relogio()
            token = secrets.token_urlsafe(16)
            sala.lugares["B"] = Lugar(letra="B", token=token, nome=nome, visto=agora)
            sala.atividade = agora
            sala.estado = SORTEIO
            sala.primeiro = self.rng.choice(LUGARES)       # quem escolhe primeiro é à sorte
            sala.vez = sala.primeiro
            self._oferecer(sala)
            return token

    def convite(self, sala_id: str) -> dict | None:
        """O que a página do convite pode mostrar a quem ainda não entrou: quem convida, se há lugar e se já fechou."""
        with self._trinco:
            try:
                sala = self._sala(sala_id)
            except ErroSala:
                return None
            return {"anfitriao": sala.lugares["A"].nome, "livre": "B" not in sala.lugares and sala.estado == ESPERA,
                    "fechada": sala.estado == ABANDONADA}

    def lugar_de(self, sala_id: str, token: str) -> str | None:
        """A letra do lugar deste token na sala ('A'/'B'), ou None. Conta como sinal de vida."""
        with self._trinco:
            try:
                return self._lugar(self._sala(sala_id), token).letra
            except ErroSala:
                return None

    # ------------------------------------------------------------------ sorteio

    def escolher(self, sala_id: str, token: str, jogador: str) -> None:
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            if sala.estado != SORTEIO:
                raise ErroSala("fora_do_sorteio", "O sorteio já terminou.")
            if sala.vez != lugar.letra:
                raise ErroSala("nao_e_a_tua_vez", "Ainda não é a tua vez.")
            if jogador not in lugar.oferta:
                raise ErroSala("jogador_invalido", "Esse jogador não estava no sorteio.")
            lugar.equipa.append(jogador)
            lugar.oferta = []
            outro = sala.lugares[self._outro(lugar.letra)]
            if not draft.equipa_completa(outro.equipa):
                sala.vez = outro.letra
            elif not draft.equipa_completa(lugar.equipa):
                sala.vez = lugar.letra
            else:
                sala.vez = None
                sala.estado = TATICAS
            if sala.vez:
                self._oferecer(sala)

    # ------------------------------------------------------------------ tática e equipa no campo

    def _em_taticas(self, sala: Sala, lugar: Lugar, *, editar: bool = True) -> None:
        if sala.estado != TATICAS:
            raise ErroSala("fora_das_taticas", "Esta fase já terminou." if sala.estado == PRONTA
                           else "Ainda não é altura de escolher a tática.")
        if editar and lugar.pronto:
            raise ErroSala("ja_pronto", "Já estás pronto. Carrega em «Editar» para mudar alguma coisa.")

    def escolher_tatica(self, sala_id: str, token: str, tatica_id, posicoes: dict[str, str]) -> None:
        """Escolhe (ou muda) a tática. `posicoes`: nome -> posição natural, para colocar os jogadores."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar)
            nova = taticas.obter_tatica(tatica_id)
            if nova is None:
                raise ErroSala("tatica_invalida", "Essa tática não existe.")
            antiga = taticas.obter_tatica(lugar.tatica)
            atual_valida = antiga is not None and taticas.escalacao_valida(antiga, lugar.escalacao, lugar.equipa)
            mesma = atual_valida and antiga.id == nova.id
            if mesma:
                pass                                        # a mesma tática: tudo fica como estava
            elif atual_valida:
                papeis = taticas.papeis_da_escalacao(antiga, lugar.escalacao)
                lugar.escalacao = taticas.distribuir(nova, lugar.equipa, posicoes, papeis)
            else:
                lugar.escalacao = taticas.distribuir(nova, lugar.equipa, posicoes)
            lugar.tatica = nova.id
            lugar.a_mudar_tatica = False
            # As posições mudam de uma tática para outra, por isso as funções voltam às normais.
            # O estilo e quem bate livres e cantos (que são jogadores) mantêm-se.
            if not mesma or not fun.funcoes_validas(nova, lugar.funcoes):
                lugar.funcoes = fun.funcoes_padrao(nova)
            self._acertar_marcadores(lugar, nova)

    def mudar_tatica(self, sala_id: str, token: str, mudar: bool) -> None:
        """Abre/fecha os cartões de tática (para mudar a que já escolheu)."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar)
            if lugar.tatica is None:
                raise ErroSala("sem_tatica", "Escolhe primeiro uma tática.")
            lugar.a_mudar_tatica = bool(mudar)

    def trocar(self, sala_id: str, token: str, a: str, b: str) -> None:
        """Troca dois jogadores de posição no campo."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar)
            tatica_ = taticas.obter_tatica(lugar.tatica)
            if tatica_ is None or not taticas.escalacao_valida(tatica_, lugar.escalacao, lugar.equipa):
                raise ErroSala("sem_tatica", "Escolhe primeiro uma tática.")
            ids = {p.id for p in tatica_.posicoes}
            if not (isinstance(a, str) and isinstance(b, str) and a in ids and b in ids):
                raise ErroSala("posicao_invalida", "Posição inválida.")
            lugar.escalacao = taticas.trocar(lugar.escalacao, a, b)
            self._acertar_marcadores(lugar, tatica_)        # o guarda-redes não bate livres nem cantos

    # ------------------------------------------------------------------ funções, estilo, livres e cantos

    @staticmethod
    def _acertar_marcadores(lugar: Lugar, tatica_: taticas.Tatica) -> None:
        """Quem bate livres e cantos tem de ser um jogador de campo: senão volta ao jogador por defeito."""
        for tipo in fun.TIPOS_BOLA_PARADA:
            if not fun.marcador_valido(tatica_, lugar.escalacao, getattr(lugar, tipo)):
                setattr(lugar, tipo, fun.marcador_padrao(tatica_, lugar.escalacao))

    def _tatica_do_lugar(self, lugar: Lugar) -> taticas.Tatica:
        """A tática do lugar, só se já está com a equipa toda no campo (senão: «escolhe primeiro uma tática»)."""
        tatica_ = taticas.obter_tatica(lugar.tatica)
        if tatica_ is None or not taticas.escalacao_valida(tatica_, lugar.escalacao, lugar.equipa):
            raise ErroSala("sem_tatica", "Escolhe primeiro uma tática.")
        return tatica_

    def escolher_funcao(self, sala_id: str, token: str, posicao_id, funcao_id) -> None:
        """Escolhe a função do jogador que está nesta posição do campo."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar)
            tatica_ = self._tatica_do_lugar(lugar)
            if not isinstance(posicao_id, str) or posicao_id not in {p.id for p in tatica_.posicoes}:
                raise ErroSala("posicao_invalida", "Posição inválida.")
            if fun.obter_funcao(tatica_, posicao_id, funcao_id) is None:
                raise ErroSala("funcao_invalida", "Essa função não existe para esta posição.")
            lugar.funcoes[posicao_id] = funcao_id

    def escolher_estilo(self, sala_id: str, token: str, estilo_id) -> None:
        """Escolhe o estilo de jogo da equipa."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar)
            self._tatica_do_lugar(lugar)
            if fun.obter_estilo(estilo_id) is None:
                raise ErroSala("estilo_invalido", "Esse estilo de jogo não existe.")
            lugar.estilo = estilo_id

    def escolher_marcador(self, sala_id: str, token: str, tipo, jogador) -> None:
        """Escolhe quem bate os livres (`tipo` = "livres") ou os cantos (`tipo` = "cantos")."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar)
            tatica_ = self._tatica_do_lugar(lugar)
            if tipo not in fun.TIPOS_BOLA_PARADA:
                raise ErroSala("pedido_invalido", "Pedido inválido.")
            if not fun.marcador_valido(tatica_, lugar.escalacao, jogador):
                raise ErroSala("marcador_invalido", "Só os jogadores de campo batem livres e cantos.")
            setattr(lugar, tipo, jogador)

    def pronto(self, sala_id: str, token: str, pronto: bool) -> None:
        """«Estou pronto» (ou «Editar», que desfaz). Com os dois prontos, a sala fica `pronta`."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            self._em_taticas(sala, lugar, editar=False)
            if pronto:
                tatica_ = self._tatica_do_lugar(lugar)
                self._acertar_marcadores(lugar, tatica_)
                if not fun.funcoes_validas(tatica_, lugar.funcoes):
                    lugar.funcoes = fun.funcoes_padrao(tatica_)
                if fun.obter_estilo(lugar.estilo) is None:
                    raise ErroSala("sem_estilo", "Escolhe o estilo de jogo da tua equipa antes de ficares pronto.")
                lugar.pronto = True
                lugar.a_mudar_tatica = False
                if len(sala.lugares) == 2 and all(l.pronto for l in sala.lugares.values()):
                    sala.estado = PRONTA
                    if sala.semente is None:
                        sala.semente = self.rng.getrandbits(31)
            else:
                lugar.pronto = False

    # ------------------------------------------------------------------ o jogo (Passo 7)

    @staticmethod
    def _configuracao(lugar: Lugar) -> dict:
        """O que o motor precisa de saber de uma equipa: só nomes, tática, funções, estilo e marcadores."""
        return {"nome": lugar.nome, "tatica": lugar.tatica, "escalacao": dict(lugar.escalacao),
                "funcoes": dict(lugar.funcoes), "estilo": lugar.estilo, "livres": lugar.livres, "cantos": lugar.cantos}

    def resultado(self, sala_id: str, token: str, calcular) -> dict:
        """O resultado público do jogo desta sala. Calcula-o (uma só vez) com `calcular(config_A, config_B, semente)`.

        `calcular` devolve o resultado completo do motor; aqui separa-se o que é público (golos, estatísticas,
        marcadores, relato, equipas) dos eventos com as posições de todos, que ficam guardados comprimidos à parte.
        O cálculo (cerca de meio segundo) faz-se fora do trinco geral para não parar as outras salas, e só um
        pedido de cada vez o faz: o outro jogador espera e usa o mesmo resultado. A mesma semente dá sempre o
        mesmo jogo, por isso nenhum dos dois pode ver um resultado diferente."""
        with self._trinco:
            sala = self._sala(sala_id)
            self._lugar(sala, token)
            if sala.estado != PRONTA or sala.semente is None:
                raise ErroSala("jogo_nao_pronto", "O jogo ainda não começou: os dois têm de estar prontos.")
            if sala.resultado is not None:
                return sala.resultado
            configs = [self._configuracao(sala.lugares[l]) for l in LUGARES]
            semente = sala.semente
        with sala.calculo:
            with self._trinco:
                if sala.resultado is not None:
                    return sala.resultado
            bruto = calcular(configs[0], configs[1], semente)
            publico = {k: v for k, v in bruto.items() if k not in ("eventos", "ordem")}
            eventos = zlib.compress(json.dumps({"ordem": bruto["ordem"], "eventos": bruto["eventos"]},
                                               separators=(",", ":")).encode("utf8"), 6)
            with self._trinco:
                if sala.resultado is None:
                    sala.resultado, sala.eventos_z = publico, eventos
                return sala.resultado

    def eventos(self, sala_id: str, token: str) -> bytes:
        """Os eventos do jogo (JSON comprimido com zlib) para quem tem lugar na sala, depois de o jogo estar calculado."""
        with self._trinco:
            sala = self._sala(sala_id)
            self._lugar(sala, token)
            if sala.eventos_z is None:
                raise ErroSala("jogo_nao_pronto", "O jogo ainda não foi simulado.")
            return sala.eventos_z

    def filme(self, sala_id: str, token: str) -> bytes:
        """O «filme» do jogo (JSON comprimido com zlib) visto de quem pede: quem vê joga sempre da esquerda para a
        direita, por isso o campo vem espelhado para o lugar B. É feito uma só vez por lugar (cerca de meio segundo)
        e fica guardado; o jogo em si (resultado, estatísticas, eventos) não muda: o filme só o mostra."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            if sala.eventos_z is None or sala.resultado is None:
                raise ErroSala("jogo_nao_pronto", "O jogo ainda não foi simulado.")
            i = LUGARES.index(lugar.letra)
            if i in sala.filmes:
                return sala.filmes[i]
            publico, eventos_z = sala.resultado, sala.eventos_z
        with sala.calculo:                                   # um filme de cada vez: não pesa no resto do servidor
            with self._trinco:
                if i in sala.filmes:
                    return sala.filmes[i]
            filme = visual.construir(publico, json.loads(zlib.decompress(eventos_z)), i)
            comprimido = zlib.compress(json.dumps(filme, separators=(",", ":"), ensure_ascii=False).encode("utf8"), 6)
            with self._trinco:
                return sala.filmes.setdefault(i, comprimido)

    # ------------------------------------------------------------------ sair

    def sair(self, sala_id: str, token: str) -> None:
        """Sai da sala. A sala desaparece se o adversário ainda não tinha entrado ou se já tinha saído.
        Depois do jogo, quem sai deixa de contar mas o outro continua a ver o fim do jogo (a sala fecha quando os dois saem)."""
        with self._trinco:
            sala = self._sala(sala_id)
            lugar = self._lugar(sala, token)
            if sala.estado == PRONTA:                # o jogo já se fez: sair não estraga o fim do jogo ao outro
                lugar.saiu = True
                if all(l.saiu for l in sala.lugares.values()):
                    del self._salas[sala_id]
                return
            if len(sala.lugares) < 2 or (sala.estado == ABANDONADA and sala.saiu != lugar.letra):
                del self._salas[sala_id]            # já não sobra ninguém
                return
            if sala.estado != ABANDONADA:
                sala.estado = ABANDONADA
                sala.saiu = lugar.letra
                sala.vez = None

    # ------------------------------------------------------------------ o que cada lugar vê

    def vista(self, sala_id: str, token: str) -> dict:
        """Tudo o que ESTE lugar pode ver da sala (e nada mais): é isto que se desenha no ecrã.

        Não inclui a presença do adversário (ligado/desligado), que muda sem a sala mudar: vem à parte
        em `presenca()`. Levanta ErroSala se a sala não existe ou o token não é de nenhum lugar.
        """
        with self._trinco:
            sala = self._sala(sala_id)
            eu = self._lugar(sala, token)
            adv = sala.lugares.get(self._outro(eu.letra))
            minha_vez = sala.estado == SORTEIO and sala.vez == eu.letra
            return {
                "sala": sala.id,
                "estado": sala.estado,
                "lugar": eu.letra,
                "nome": eu.nome,
                "adversario": adv.nome if adv else None,
                "equipa": list(eu.equipa),
                "equipa_adversario": list(adv.equipa) if adv else [],
                "sorteio": {
                    "minha_vez": minha_vez,
                    "oferta": list(eu.oferta) if minha_vez else [],
                    "comeco_eu": sala.primeiro == eu.letra,
                },
                "tatica": {
                    "escolhida": eu.tatica,
                    "a_mudar": eu.a_mudar_tatica,
                    "escalacao": dict(eu.escalacao),
                    "funcoes": dict(eu.funcoes),
                    "estilo": eu.estilo,
                    "livres": eu.livres,
                    "cantos": eu.cantos,
                    "pronto": eu.pronto,
                    "adversario_escolheu": bool(adv and adv.tatica),
                    "adversario_pronto": bool(adv and adv.pronto),
                },
                "jogo": {"calculado": sala.resultado is not None},
                "saiu_eu": sala.saiu == eu.letra,
            }

    def presenca(self, sala_id: str, token: str) -> dict:
        """Se o adversário está ligado (deu sinal nos últimos `LIMITE_PRESENCA` segundos)."""
        with self._trinco:
            sala = self._sala(sala_id)
            eu = self._lugar(sala, token)
            adv = sala.lugares.get(self._outro(eu.letra))
            ligado = bool(adv) and self.relogio() - adv.visto <= LIMITE_PRESENCA
            return {"adversario": adv.nome if adv else None, "ligado": ligado}

    def nomes_em_uso(self, sala_id: str) -> set[str]:
        """Todos os jogadores já escolhidos na sala (para validar contra o Excel)."""
        with self._trinco:
            sala = self._sala(sala_id)
            return {n for l in sala.lugares.values() for n in l.equipa}
