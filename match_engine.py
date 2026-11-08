"""
match_engine.py — o motor de jogo do MODO ONLINE (Passo 7): futebol de 7, sem Flask nem Excel
=============================================================================================

`match_engine_online(config_a, config_b, jogadores, semente)` simula um jogo completo (2 partes de 25 minutos)
entre duas equipas e devolve o resultado, a tabela de estatísticas e o registo de TODOS os eventos (com
as posições de todos no campo: `q`, medidas no instante `tq`; mais `area`, `saiu` e `saida` em alguns). O Passo 8
(`visual.py`) usa esse registo para fazer o «filme» da simulação visual; o jogo em si não depende dele.

Como o jogo é decidido (nada é um «dado» solto: tudo passa pelos jogadores):

  - O campo tem 60 × 40 m. Em cada momento cada jogador está num sítio calculado a partir da TÁTICA (onde a
    tática o põe), da FUNÇÃO que o treinador lhe deu (sobe, fica atrás, abre para a ala, entra por dentro…),
    do ESTILO da equipa (linha subida ou baixa, largura), de quem tem a bola e de onde ela está, e do cansaço.
  - Quem tem a bola decide o que faz (passe curto, passe a progredir, bola longa, passe de rutura, cruzamento,
    drible, remate, alívio). As «vontades» vêm das funções, dos estilos e dos traços de cada jogador (por
    exemplo, o Extremo da equipa que joga pelas alas cruza muito mais do que um médio ala equilibrado).
  - O resultado de cada ação sai dos ATRIBUTOS dos jogadores envolvidos e da situação (distância, pressão dos
    adversários, linha de passe, cansaço). Uma função ou um estilo muda também o peso dos atributos na
    qualidade da ação (o Organizador passa mais pela Visão e pelo Passe do que o Recuperador).
  - Jogador fora da sua posição natural: todos os atributos −5 (como no modo offline).
  - Livres perigosos (cerca de 1,6 por jogo) e cantos: quem bate foi escolhido pelo treinador; o sucesso depende
    da Bola Parada de quem bate e, nos cantos e cruzamentos, dos atributos de quem vai à bola (Cabeceamento,
    Impulsão, Altura) contra os de quem defende.

Tudo é determinado pela `semente`: a mesma semente e as mesmas equipas dão exatamente o mesmo jogo.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

import funcoes as fun
import taticas

# --------------------------------------------------------------------------- #
# Campo e tempo (metros, segundos)
# --------------------------------------------------------------------------- #
COMPRIMENTO, LARGURA = 60.0, 40.0
ESCALA_TEMPO = 1.45        # segundos que dura cada ação, em relação ao «tempo base» (calibrado com Monte Carlo)
ZONA_LIVRE_U, ZONA_LIVRE_D = 44.0, 12.0   # onde uma falta dá livre perigoso (calibrado: ≈ 1,6 por jogo)
K_REMATE = 0.65
K_RHO_POSSE = 0.1          # quanto quem joga em posse valoriza manter a bola em cada passe (frente à baliza passa a rematar)
B_ALVO = 0.80             # tendência real de o remate ir à baliza (calibrado)
B_GOLO = -0.55            # tendência real de o remate à baliza ser golo (calibrado)
REF_ALVO, REF_GOLO = 0.80, -1.24   # leitura (subjetiva) que os jogadores fazem da jogada antes de rematar
K_CRUZ = 2.0               # quanto valorizam cruzar
B_DRIBLE = -0.006             # gosto geral por driblar
K_MARCACAO = 0.30          # quanto os defesas acompanham os adversários
K_LONGO = 0.02             # quanto a equipa direta valoriza a bola longa
K_GR_LONGO = 0.20          # quanto o estilo direto faz o guarda-redes jogar longo
K_RECUO = 6.0              # quanto os médios recuam por cada defesa em falta (calibrado)
K_ESTREITAR = 0.65         # quanto a equipa sem bola fecha o corredor central (1 = nada)
K_DESLIZE = 0.30           # quanto a equipa sem bola desliza para o lado da bola
K_REST = 0.85              # equilíbrio defensivo de quem joga em posse (menos espaço para o contra-ataque)
K_ESP_POSSE = 0.7          # quanto a circulação de bola desorganiza a defesa adversária, em quem joga em posse
K_CONTRA = 1.0             # quanto a pressa na saída para o ataque (ritmo) aumenta o espaço de um contra-ataque
K_BLOCO_BAIXO = 0.5        # quanto um bloco baixo fecha as linhas de remate
K_COMPACTO = 0.30          # quanto um bloco baixo e compacto atrasa a desorganização da defesa (circulação de bola do adversário)
K_MED_ATAQUE = 4.0         # quanto os médios sobem a mais quando a equipa ataca
K_AVA_RECUO = 3.0          # quanto os avançados recuam quando a equipa defende
K_FECHA_LINHA = 0.8        # quanto uma linha de dois jogadores sem ninguém ao centro fecha o espaço quando se defende
K_FALTA = 0.75             # frequência das faltas (calibrado)
ESCALA_TALENTO = 0.65       # quanto a diferença de atributos pesa em cada ação (1 = atributos a valer tudo; calibrado: plantel muito superior ≠ goleada)
ESCALA_MOV_FUNCAO = 0.4     # quanto de `funcoes._MOVIMENTO` se aplica (calibrado: o motor reage muito aos metros de cada jogador)
K_GESTAO = 0.12            # gestão do resultado: por cada golo de avanço (a partir do 2.º) quem ganha baixa o ritmo e rema menos à baliza
K_SOLIDEZ = 0.08            # cada defesa a mais que dois (3-1-2, 3-2-1) torna mais difícil abrir a defesa pela circulação de bola
K_PRESSAO_RESULTADO = 0.06  # quem perde por 2 ou mais aperta um pouco (mais circulação, mais espaço criado)
K_LARGURA = 1.1            # quanto jogar pelas alas abre a defesa adversária em cada passe (era 1,5: as alas marcavam demais)
COESAO = 0.5               # quanto o plano de jogo bem executado (tática e funções certas para o estilo) melhora passes e duelos
K_CRUZ_PLANO = 1.2         # idem para os cruzamentos de quem joga pelas alas
CY = LARGURA / 2
PARTE = 25 * 60
TOTAL = 2 * PARTE
MAX_JOGADORES_NA_AREA_CANTO = 3

ATRIBUTOS = (
    "Reflexos", "Comando de Área", "Jogo Aéreo", "Um para Um", "Pontapé de Baliza", "Lançamento", "Bola Parada",
    "Cruzamento", "Drible", "Finalização", "Cabeceamento", "Passe", "Primeiro Toque", "Técnica", "Desarme",
    "Marcação", "Antecipação", "Decisões", "Visão de Jogo", "Concentração", "Agressividade", "Bravura",
    "Compostura", "Índice de Trabalho", "Posicionamento", "Sem Bola", "Aceleração", "Velocidade", "Agilidade",
    "Equilíbrio", "Força", "Impulsão", "Resistência",
)
CANSAM = ("Velocidade", "Aceleração", "Agilidade", "Impulsão")        # o cansaço tira-lhes rendimento
PAPEL_DO_EXCEL = {"GR": taticas.GR, "D": taticas.DEF, "M": taticas.MED, "A": taticas.AVA}
PENALIZACAO_FORA_DE_POSICAO = 5

# «Vontades»: de que atributos depende cada comportamento. A vontade de um jogador é a média geométrica dos
# multiplicadores (função × estilo) desses atributos: quem tem a função «Extremo» (Cruzamento ×1,3) numa equipa
# que joga pelas alas (Cruzamento ×1,3) cruza 69 % mais vezes.
PROPENSOES = {
    "curto": ("Passe", "Primeiro Toque", "Técnica", "Compostura"),
    "prog": ("Passe", "Visão de Jogo", "Decisões"),
    "longo": ("Passe", "Visão de Jogo", "Força", "Pontapé de Baliza", "Lançamento"),
    "rutura": ("Visão de Jogo", "Passe", "Técnica"),
    "cruz": ("Cruzamento",),
    "drible": ("Drible", "Agilidade", "Aceleração"),
    "remate": ("Finalização", "Técnica", "Compostura"),
    "pressao": ("Agressividade", "Índice de Trabalho", "Desarme", "Antecipação"),
    "area": ("Sem Bola", "Posicionamento", "Finalização", "Cabeceamento"),
}

# Traços do Excel (coluna «Traços»): pequenos ajustes ao comportamento de cada jogador.
TRACOS = {
    "Fica Sempre na Defesa": {"mov": {"ataque": -5.0}, "prop": {"drible": 0.8, "remate": 0.7}},
    "Entra de Carrinho": {"prop": {"pressao": 1.25}, "falta": 0.06, "desarme": 0.04},
    "Sobe no Terreno": {"mov": {"ataque": 6.0}},
    "Remata com Força": {"prop": {"remate_longe": 1.5}, "potencia": 0.05},
    "Cruzamento Antecipado": {"prop": {"cruz": 1.25}},
    "Cai para as Alas": {"mov": {"largura": 4.0}},
    "Finta Frequentemente": {"prop": {"drible": 1.4}},
    "Vem Buscar Jogo Atrás": {"mov": {"ataque": -5.0}, "prop": {"curto": 1.1}},
    "Tenta Passes de Rutura": {"prop": {"rutura": 1.5}},
    "Dita o Ritmo do Jogo": {"prop": {"curto": 1.1, "prog": 1.1}},
    "Muda o Flanco": {"prop": {"longo": 1.2}},
    "Remata em Jeito": {"prop": {"remate": 1.1}, "jeito": 0.05},
    "Corta para Dentro": {"mov": {"largura": -4.0}, "prop": {"remate": 1.2}},
}

TRACOS_NORMALIZADOS = {nome.casefold(): dados for nome, dados in TRACOS.items()}

# Quanto cada tipo de posição acompanha a bola para a frente e para trás (a equipa move-se em bloco).
K_BLOCO = {taticas.DEF: 0.55, taticas.MED: 0.70, taticas.AVA: 0.50}


# --------------------------------------------------------------------------- #
# Pequenas funções
# --------------------------------------------------------------------------- #

def _sig(x: float) -> float:
    if x < -30:
        return 0.0
    if x > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def _lim(x: float, a: float, b: float) -> float:
    return a if x < a else b if x > b else x


def _gx(t: int, u: float) -> float:
    return u if t == 0 else COMPRIMENTO - u


def _gy(t: int, v: float) -> float:
    return v if t == 0 else LARGURA - v


def _tu(t: int, x: float) -> float:
    return x if t == 0 else COMPRIMENTO - x


def _tv(t: int, y: float) -> float:
    return y if t == 0 else LARGURA - y


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dist_segmento(p, a, b) -> tuple[float, float]:
    """(distância de p ao segmento ab, posição ao longo do segmento de 0 a 1)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    s = 0.0 if n == 0 else _lim(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n, 0.0, 1.0)
    return math.hypot(p[0] - (a[0] + s * dx), p[1] - (a[1] + s * dy)), s


# --------------------------------------------------------------------------- #
# Jogadores e equipas
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Ficha:
    """O que o Excel diz de um jogador (só no servidor)."""
    nome: str
    papeis: frozenset
    altura: float
    atributos: dict
    tracos: tuple


def fichas_de(jogadores) -> dict[str, Ficha]:
    """nome -> Ficha, a partir do DataFrame do Excel ONLINE."""
    fichas = {}
    for _, linha in jogadores.iterrows():
        papeis = frozenset(PAPEL_DO_EXCEL[p.strip()] for p in str(linha["Posição(ões)"]).split("/"))
        bruto = linha.get("Traços")
        tracos = tuple(x.strip() for x in str(bruto).split(";") if x.strip()) if isinstance(bruto, str) else ()
        fichas[linha["Nome"]] = Ficha(
            nome=linha["Nome"], papeis=papeis, altura=float(linha["Altura(m)"]),
            atributos={a: float(linha[a]) for a in ATRIBUTOS}, tracos=tracos,
        )
    return fichas


@dataclass(eq=False)
class Jog:
    nome: str
    eq: int
    slot: str
    papel: str
    posicao_nome: str
    funcao: str
    a: dict
    altura: float
    tracos: tuple
    mult: dict
    mov: dict
    base_u: float
    base_v: float
    ref: dict = field(default_factory=dict)
    prop: dict = field(default_factory=dict)
    falta_extra: float = 0.0
    desarme_extra: float = 0.0
    potencia: float = 0.0
    jeito: float = 0.0
    fad: float = 0.0
    forma: float = 1.0
    fecha: float = 1.0               # fecho da linha quando defende (ver K_FECHA_LINHA)
    st: Counter = field(default_factory=Counter)

    def v(self, atributo: str) -> float:
        x = self.a[atributo] / 100.0
        return x * self.forma if atributo in CANSAM else x

    def q(self, pesos: dict) -> float:
        """Qualidade (0 a 1) numa ação.

        Parte da média dos atributos que a ação pede (nível «normal» de quem tem os atributos médios do plantel) e soma
        o quanto o jogador está acima ou abaixo dessa média, dando mais peso aos atributos que a função e o estilo
        pedem. Assim função e estilo não são um bónus grátis para todos: só ajudam quem é mesmo bom no que eles pedem
        (e custam a quem é fraco nisso), e escolher bem a função e o estilo para os jogadores que se tem é que conta."""
        base = total = soma = 0.0
        ref = self.ref
        mult = self.mult
        for atributo, peso in pesos.items():
            r = ref[atributo] * 0.01
            base += peso * r
            p = peso * mult.get(atributo, 1.0)
            total += p * (self.v(atributo) - r * (self.forma if atributo in CANSAM else 1.0))
            soma += p
        return base / sum(pesos.values()) + ESCALA_TALENTO * total / soma

    @property
    def aereo(self) -> float:
        h = _lim((self.altura - 1.55) / 0.40, 0.2, 1.0)
        return self.q({"Cabeceamento": 0.40, "Impulsão": 0.22, "Bravura": 0.08, "Força": 0.08}) * 0.78 + h * 0.22


def referencias(fichas: dict[str, Ficha]) -> dict[str, dict]:
    """Atributos médios do plantel, para guarda-redes e para jogadores de campo (o «jogador normal» de cada grupo)."""
    grupos = {"gr": [f for f in fichas.values() if f.papeis == {taticas.GR}],
              "campo": [f for f in fichas.values() if taticas.GR not in f.papeis]}
    return {nome: {a: sum(f.atributos[a] for f in lista) / len(lista) for a in ATRIBUTOS} for nome, lista in grupos.items()}


class Equipa:
    def __init__(self, indice: int, cfg: dict, fichas: dict[str, Ficha], refs: dict[str, dict]):
        self.i = indice
        self.treinador = cfg["nome"]
        self.tatica = taticas.obter_tatica(cfg["tatica"])
        self.estilo = fun.obter_estilo(cfg["estilo"])
        self.tend = {k: float(self.estilo.tendencias.get(k, 0.0)) for k in fun.TENDENCIAS}
        # eficácia do plano: quanto a tática e as funções escolhidas conseguem pôr o estilo em prática (1 = neutro)
        self.ef = fun.eficacia_do_plano(cfg["tatica"], cfg["funcoes"], cfg["estilo"])
        self.jog: list[Jog] = []
        for p in self.tatica.posicoes:
            ficha = fichas[cfg["escalacao"][p.id]]
            fora = p.papel not in ficha.papeis
            atributos = {a: max(1.0, v - (PENALIZACAO_FORA_DE_POSICAO if fora else 0)) for a, v in ficha.atributos.items()}
            funcao = fun.obter_funcao(self.tatica, p.id, cfg["funcoes"][p.id])
            mult = fun.multiplicadores(self.tatica, p.id, funcao.id, self.estilo.id)
            mov = {k: v * ESCALA_MOV_FUNCAO for k, v in funcao.mov.items()}
            prop = {}
            for comportamento, lista in PROPENSOES.items():
                prop[comportamento] = math.exp(sum(math.log(mult.get(a, 1.0)) for a in lista) / len(lista))
            prop["remate_longe"] = 1.0
            falta = desarme = potencia = jeito = 0.0
            for traco in ficha.tracos:
                dados = TRACOS_NORMALIZADOS.get(traco.casefold())
                if not dados:
                    continue
                for k, v in dados.get("mov", {}).items():
                    mov[k] = mov.get(k, 0.0) + v
                for k, v in dados.get("prop", {}).items():
                    prop[k] = prop.get(k, 1.0) * v
                falta += dados.get("falta", 0.0)
                desarme += dados.get("desarme", 0.0)
                potencia += dados.get("potencia", 0.0)
                jeito += dados.get("jeito", 0.0)
            carga = 0.9 + 0.3 * _lim((mult.get("Resistência", 1.0) + mult.get("Índice de Trabalho", 1.0)) / 2 - 0.9, 0, 0.6) / 0.6
            j = Jog(
                nome=ficha.nome, eq=indice, slot=p.id, papel=p.papel, posicao_nome=p.nome, funcao=funcao.id, a=atributos,
                altura=ficha.altura, tracos=ficha.tracos, mult=mult, mov=mov,
                base_u=3.0 + (83.0 - p.y) / 70.0 * 40.0, base_v=p.x * LARGURA / 100.0,
                ref=refs["gr" if p.papel == taticas.GR else "campo"], prop=prop,
                falta_extra=falta, desarme_extra=desarme, potencia=potencia, jeito=jeito,
            )
            intensidade = 1.0 + 0.35 * max(0.0, self.tend["linha"]) + 0.30 * max(0.0, self.tend["ritmo"])
            j.fad = 0.30 * (1.0 - atributos["Resistência"] / 100.0) * carga * intensidade
            self.jog.append(j)
        por_nome = {j.nome: j for j in self.jog}
        self.gr = next(j for j in self.jog if j.papel == taticas.GR)
        self.livres = por_nome[cfg["livres"]]
        self.cantos = por_nome[cfg["cantos"]]
        self.campo = [j for j in self.jog if j.papel != taticas.GR]
        self.n_def = sum(1 for j in self.jog if j.papel == taticas.DEF)
        for papel in (taticas.DEF, taticas.MED):
            linha = [j for j in self.campo if j.papel == papel]
            sem_centro = all(abs(j.base_v - CY) > 5.0 for j in linha)
            for j in linha:
                j.fecha = K_FECHA_LINHA if (len(linha) == 2 and sem_centro) else 1.0

    def media(self, pesos: dict) -> float:
        return sum(j.q(pesos) for j in self.campo) / len(self.campo)


# --------------------------------------------------------------------------- #
# O jogo
# --------------------------------------------------------------------------- #

class Jogo:
    def __init__(self, configs, fichas, semente: int):
        self.r = random.Random(semente)
        self.semente = semente
        refs = referencias(fichas)
        self.eq = [Equipa(0, configs[0], fichas, refs), Equipa(1, configs[1], fichas, refs)]
        self.ordem = [j for e in self.eq for j in e.jog]      # a ordem dos jogadores em cada «quadro» (q) dos eventos
        self.t = 0.0
        self.parte = 1                      # 1.ª ou 2.ª parte
        self.golos = [0, 0]
        self.est = [Counter(), Counter()]
        self.tempo_posse = [0.0, 0.0]
        self.eventos: list[dict] = []
        self.fase = ["A", "A"]
        self.pendente = [None, None]
        self.bola = (COMPRIMENTO / 2, CY)
        self.posse = 0
        self.portador: Jog | None = None
        self.pos: dict[Jog, tuple[float, float]] = {}
        self.alvo: dict[Jog, tuple[float, float]] = {}
        self.t_pos = 0.0
        self.esp = 0.0                      # espaço criado pelo ataque (desorganização da defesa), de 0 a 1
        self.dribles_seguidos = 0
        self.ganhou = None                  # (equipa, instante, u) de quando ganhou a bola
        self.contra_ativo = [False, False]
        self.ultimo_passe = None            # (jogador, instante) para a assistência
        self.alivio_pressao = 0.0
        self.trab = [e.media({"Índice de Trabalho": 0.5, "Resistência": 0.2, "Velocidade": 0.15, "Aceleração": 0.15}) for e in self.eq]

    # ------------------------------------------------------------------ registo
    def minuto(self) -> int:
        """Minuto do jogo (1 a 50): a 1.ª parte nunca passa do 25 e a 2.ª começa no 26, mesmo que o último lance
        da parte acabe uns segundos depois do apito."""
        m = int(self.t // 60) + 1
        return min(m, 25) if self.parte == 1 else max(26, min(m, 50))

    def ev(self, tipo, eq, jog=None, jog2=None, de=None, para=None, **extra):
        e = {"t": round(min(self.t, TOTAL), 1), "min": self.minuto(), "tipo": tipo, "eq": eq}
        if jog is not None:
            e["jog"] = jog.nome
        if jog2 is not None:
            e["jog2"] = jog2.nome
        if de is not None:
            e["de"] = (round(de[0], 1), round(de[1], 1))
        if para is not None:
            e["para"] = (round(para[0], 1), round(para[1], 1))
        e.update(extra)
        if self.pos:                                   # onde estava cada jogador (para a simulação visual do Passo 8)
            e["q"] = [[round(self.pos[j][0], 1), round(self.pos[j][1], 1)] for j in self.ordem if j in self.pos]
            e["bola"] = (round(self.bola[0], 1), round(self.bola[1], 1))
            e["tq"] = round(min(self.t_pos, TOTAL), 1)     # instante a que se referem as posições `q` (o último `atualizar`)
        self.eventos.append(e)

    def dt(self, base: float, t: int) -> float:
        tend = self.eq[t].tend
        return max(1.0, base * ESCALA_TEMPO * (1.0 - 0.24 * tend["ritmo"]) * (1.0 + 0.12 * tend["posse"]) * self.r.uniform(0.8, 1.25))

    # ------------------------------------------------------------------ posições
    def atualizar(self):
        """Põe o jogo em dia: cansaço, fases (a defesa demora a reorganizar-se) e posições.

        Cada jogador quer estar num sítio (`alvo`: tática, função, estilo, bola) mas só chega lá à velocidade
        a que corre (Velocidade, Aceleração, cansaço): por isso as transições e as bolas longas apanham
        equipas desposicionadas, e os mais rápidos chegam primeiro."""
        dt = self.t - self.t_pos
        self.t_pos = self.t
        andamento = self.t / TOTAL
        for e in self.eq:
            for j in e.jog:
                j.forma = 1.0 - j.fad * andamento
        for t in (0, 1):
            p = self.pendente[t]
            if p and self.t >= p[1]:
                self.fase[t] = p[0]
                self.pendente[t] = None
        self.calcular_alvos()
        primeira = not self.pos
        for e in self.eq:
            for j in e.jog:
                if primeira or j not in self.pos:
                    self.pos[j] = self.alvo[j]
                    continue
                p0, a = self.pos[j], self.alvo[j]
                d = _dist(p0, a)
                passo = (1.1 + 2.7 * j.v("Velocidade")) * (0.7 + 0.3 * j.v("Aceleração")) * dt
                if d <= passo:
                    self.pos[j] = a
                elif d > 0:
                    k = passo / d
                    self.pos[j] = (p0[0] + (a[0] - p0[0]) * k, p0[1] + (a[1] - p0[1]) * k)
        if self.portador is not None:
            self.pos[self.portador] = self.bola

    def calcular_alvos(self):
        bx, by = self.bola
        for t in (0, 1):
            eq = self.eq[t]
            ataque = self.fase[t] == "A"
            bu, bv = _tu(t, bx), _tv(t, by)
            lin, lar = eq.tend["linha"], eq.tend["largura"]
            for j in eq.jog:
                m = j.mov.get("ataque" if ataque else "defesa", 0.0)
                if j.papel == taticas.GR:
                    u = _lim(2.5 + 0.04 * max(0.0, bu - 10.0) + m, 1.5, 22.0)
                    v = CY + (bv - CY) * 0.12
                else:
                    u = j.base_u + (bu - 28.0) * K_BLOCO[j.papel] + lin * (1.5 if ataque else 6.0) + m
                    if ataque and j.papel == taticas.MED:
                        u += K_MED_ATAQUE                               # os médios sobem com a equipa e chegam à área
                    if not ataque and j.papel == taticas.AVA:
                        u -= K_AVA_RECUO                                # os avançados também recuam um pouco quando se defende
                    if not ataque and j.papel == taticas.MED:
                        u -= K_RECUO * max(0, 3 - eq.n_def)          # com menos defesas, os médios ajudam a defender
                    if not ataque and j.papel != taticas.AVA:
                        u = min(u, max(bu - 1.0, 4.0))
                    u = _lim(u, 4.0, 56.0)
                    v = j.base_v + (bv - CY) * (0.25 if ataque else K_DESLIZE)
                    esticar = (1.0 if ataque else K_ESTREITAR * j.fecha) + (0.28 if ataque else 0.12) * lar
                    v = CY + (v - CY) * esticar
                    v += (1 if j.base_v >= CY else -1) * j.mov.get("largura", 0.0)
                    v = _lim(v, 1.5, LARGURA - 1.5)
                self.alvo[j] = (_gx(t, u), _gy(t, v))
        # Marcação: quem defende acompanha o adversário que lhe fica mais perto, por isso o alargamento do ataque abre a defesa
        for t in (0, 1):
            if self.fase[t] != "D":
                continue
            ataque_o = [j for j in self.eq[1 - t].campo]
            for j in self.eq[t].campo:
                if j.papel == taticas.AVA:
                    continue
                ax, ay = self.alvo[j]
                adv = min(ataque_o, key=lambda a_: _dist(self.alvo[a_], (ax, ay)))
                px, py = self.pos.get(adv, self.alvo[adv])
                w = K_MARCACAO * (0.7 + 0.6 * j.v("Marcação"))
                self.alvo[j] = (ax + (px - ax) * 0.5 * w, ay + (py - ay) * w)
        # Quem está perto da bola reage a ela: pressiona (equipa sem bola, já reorganizada) ou dá apoio (equipa com bola).
        for t in (0, 1):
            eq = self.eq[t]
            if self.posse != t and self.fase[t] == "D":
                ordem = sorted(eq.campo, key=lambda j: _dist(self.pos.get(j, self.alvo[j]), self.bola))
                for rank, j in enumerate(ordem[:2]):
                    f = (0.62 if rank == 0 else 0.30) * (0.75 + 0.5 * j.prop["pressao"]) * (1.0 + 0.25 * eq.tend["linha"])
                    self.alvo[j] = self._aproximar(self.alvo[j], self.bola, _lim(f, 0.08, 0.92), 2.0)
            elif self.posse == t and self.portador is not None:
                ordem = sorted((j for j in eq.campo if j is not self.portador),
                               key=lambda j: _dist(self.pos.get(j, self.alvo[j]), self.bola))
                for j in ordem[:2]:
                    self.alvo[j] = self._aproximar(self.alvo[j], self.bola, 0.25, 7.0)

    @staticmethod
    def _aproximar(p0, alvo, fracao: float, parar_a: float):
        d = _dist(p0, alvo)
        if d <= parar_a:
            return p0
        k = fracao * (d - parar_a) / d
        return (p0[0] + (alvo[0] - p0[0]) * k, p0[1] + (alvo[1] - p0[1]) * k)

    def mais_perto(self, ponto, t: int, n: int = 3, gr: bool = False):
        lista = [(_dist(self.pos[j], ponto), j) for j in self.eq[t].jog if gr or j.papel != taticas.GR]
        lista.sort(key=lambda x: x[0])
        return lista[:n]

    def pressao(self, j: Jog) -> tuple[float, Jog | None]:
        """Pressão (0 a 1) dos adversários sobre `j`: o mais próximo aperta mais quanto mais pressionar a equipa."""
        o = 1 - j.eq
        proximos = self.mais_perto(self.pos[j], o, 2)
        aperto = []
        for d, adv in proximos:
            f = 1.0 - 0.35 * _lim(adv.prop["pressao"] - 0.6, 0.0, 1.0) - 0.08 * self.eq[o].tend["linha"]
            aperto.append(d * f)
        p = 0.8 * max(0.0, 1.0 - aperto[0] / 6.5) + 0.3 * max(0.0, 1.0 - aperto[1] / 6.5)
        comp = j.q({"Compostura": 0.45, "Técnica": 0.2, "Primeiro Toque": 0.2, "Decisões": 0.15})
        p *= 1.0 - 0.55 * _lim(comp - 0.55, 0.0, 0.45) / 0.45
        p *= 1.0 - 0.80 * self.esp
        return _lim(p - self.alivio_pressao, 0.0, 1.0), (proximos[0][1] if proximos else None)

    # ------------------------------------------------------------------ posse
    def atraso(self, t: int) -> float:
        a = 7.5 * (1.25 - self.trab[t]) * (1.0 - 0.2 * self.eq[t].tend["linha"])
        return _lim(a, 2.0, 8.0)

    def ganhar_bola(self, t: int, j: Jog, ponto, contra_possivel: bool = True):
        velha = self.posse
        self.posse, self.portador, self.bola = t, j, ponto
        self.pos[j] = ponto
        self.alivio_pressao = 0.0
        if velha != t or self.ganhou is None:
            self.fase[t] = "A"
            self.pendente[t] = None
            self.pendente[1 - t] = ("D", self.t + self.atraso(1 - t))
            self.ganhou = (t, self.t, _tu(t, ponto[0])) if contra_possivel else None
            self.contra_ativo = [False, False]
            self.ultimo_passe = None
            ritmo = self.eq[t].tend["ritmo"]
            self.esp = _lim(self.espaco_de_transicao(t, ponto) * (1.0 + K_CONTRA * max(0.0, ritmo) * (self.eq[t].ef if ritmo > 0 else 1.0)), 0.0, 0.85)
            self.dribles_seguidos = 0

    def espaco_de_transicao(self, t: int, ponto) -> float:
        """Ao ganhar a bola, quantos adversários ficaram para trás dela: se poucos, há um contra-ataque aberto."""
        bu = _tu(t, ponto[0])
        atras = sum(1 for j in self.eq[1 - t].campo if _tu(t, self.pos.get(j, ponto)[0]) > bu + 1.0)
        base = {0: 0.55, 1: 0.35, 2: 0.15}.get(atras, 0.0)
        # equilíbrio defensivo: quem constrói em posse deixa sempre gente atrás da bola e fecha logo o espaço
        return base * (1.0 - K_REST * max(0.0, self.eq[1 - t].tend["posse"]))

    def gestao(self, t: int) -> float:
        """Gestão do resultado (futebol a sério): quem vai à frente por vários golos baixa o ritmo (circula, remata menos) e quem
        perde aperta. Devolve um fator: < 1 para quem ganha por 2+, > 1 para quem perde por 2+, 1 se o jogo está discutido."""
        d = self.golos[t] - self.golos[1 - t]
        if d >= 2:
            return max(0.40, 1.0 - K_GESTAO * (d - 1))
        if d <= -2:
            return min(1.30, 1.0 + K_PRESSAO_RESULTADO * (-d - 1))
        return 1.0

    def ganha_espaco(self, ganho: float, t: int):
        """A circulação de bola vai desorganizando a defesa; uma defesa baixa e compacta desorganiza-se mais devagar."""
        o = 1 - t
        eq_t = self.eq[t]
        lar, pos = eq_t.tend["largura"], eq_t.tend["posse"]
        ganho *= max(0.4, 1.0 + K_LARGURA * lar * (eq_t.ef if lar > 0 else 1.0)) * max(0.4, 1.0 + K_ESP_POSSE * pos * (eq_t.ef if pos > 0 else 1.0))
        ganho *= self.gestao(t)
        ganho *= 1.0 - K_SOLIDEZ * max(0, self.eq[o].n_def - 2)
        ganho *= 1.0 - K_COMPACTO * max(0.0, -self.eq[o].tend["linha"]) * self.eq[o].ef
        self.esp = _lim(self.esp + ganho, 0.0, 0.85)

    def credito(self, t: int, segundos: float):
        self.tempo_posse[t] += segundos
        self.t += segundos
        self.esp = max(0.0, self.esp - 0.008 * (1.0 - 0.3 * self.eq[t].tend["posse"]) * segundos)

    def morto(self, segundos: float):
        self.t += segundos

    # ------------------------------------------------------------------ o ciclo
    def correr(self):
        self.atualizar()                                # posições iniciais (a simulação visual precisa de um quadro em t = 0)
        self.ev("inicio", None)
        inicial = self.r.randrange(2)
        self.pontape_de_saida(inicial)
        meio = False
        while self.t < TOTAL:
            if not meio and self.t >= PARTE:
                meio = True
                self.ev("intervalo", None)
                self.parte = 2
                self.pontape_de_saida(1 - inicial)
            self.passo()
        self.t = TOTAL
        self.ev("fim", None)

    def pontape_de_saida(self, t: int):
        self.ganhou = None
        self.ultimo_passe = None
        self.bola = (COMPRIMENTO / 2, CY)
        self.fase = ["A", "A"]
        self.pendente = [None, None]
        self.portador = None
        self.posse = t
        self.atualizar()
        cand = [j for j in self.eq[t].campo if j.papel in (taticas.MED, taticas.AVA)]
        j = min(cand, key=lambda x: _dist(self.pos[x], self.bola))
        self.ganhar_bola(t, j, self.bola, contra_possivel=False)
        self.ev("saida", t, j, de=self.bola)
        self.morto(6.0)

    def passo(self):
        self.atualizar()
        C, t = self.portador, self.posse
        if C.papel == taticas.GR:
            self.gr_distribui()
            return
        if self.desafio():
            return
        self.atualizar()
        op, ctx = self.escolher_acao()
        acao = op["acao"]
        if acao == "remate":
            self.acao_remate(C, ctx)
        elif acao == "cruz":
            self.acao_cruzamento(C, ctx)
        elif acao == "drible":
            self.acao_drible(C, ctx)
        elif acao == "alivio":
            self.acao_alivio(C, ctx)
        elif acao == "passe":
            self.executar_passe(C, op["info"], ctx)
        else:
            self.credito(t, self.dt(2.0, t))
        self.verificar_contra()

    def verificar_contra(self):
        if self.portador is None or not self.ganhou or self.ganhou[0] != self.posse:
            return
        t = self.posse
        if (not self.contra_ativo[t] and self.t - self.ganhou[1] <= 11.0 and self.ganhou[2] <= 30.0
                and _tu(t, self.bola[0]) >= 42.0 and _tu(t, self.bola[0]) - self.ganhou[2] >= 18.0):
            self.contra_ativo[t] = True
            self.est[t]["contra_ataques"] += 1
            self.ev("contra_ataque", t, self.portador, de=self.bola)

    # ------------------------------------------------------------------ contexto de decisão
    # ------------------------------------------------------------------ decisão: o que faz quem tem a bola
    @staticmethod
    def valor_zona(u: float, v: float) -> float:
        """Quanto vale ter a bola aqui (0,01 a ~0,22): a hipótese de acabar em golo, para quem ataca para u = 60."""
        f = (_lim(u, 0.0, COMPRIMENTO) / COMPRIMENTO) ** 2.4
        central = 1.0 - (0.25 * min(abs(v - CY) / 20.0, 1.0) if u > 36.0 else 0.0)
        return 0.01 + 0.21 * f * central

    @staticmethod
    def custo_perda(u: float) -> float:
        """Quanto custa perder a bola aqui: o adversário fica com ela neste sítio (visto por ele, u' = 60 − u)."""
        return 0.6 * Jogo.valor_zona(COMPRIMENTO - u, CY)

    def ultima_linha(self, t: int) -> float:
        """u (nas coordenadas de `t`) do defesa adversário mais recuado, sem contar o guarda-redes."""
        return max(_tu(t, self.pos[j][0]) for j in self.eq[1 - t].campo)

    def info_passe(self, C: Jog, m: Jog, ctx: dict) -> dict:
        """Tipo de passe para `m`, onde chega e a hipótese de correr bem: sem sair da interceção, execução e disputa."""
        t, o = C.eq, 1 - C.eq
        eq_o = self.eq[o]
        pa, pm = self.pos[C], self.pos[m]
        cu, mu = ctx["u"], _tu(t, pm[0])
        df = mu - cu
        d = _dist(pa, pm)
        tipo = "curto"
        if d >= 22.0:
            tipo = "longo"
        elif df >= 6.0 and mu > self.ultima_linha(t) + 1.0 and m.papel != taticas.GR:
            tipo = "rutura"
        elif df >= 4.0:
            tipo = "prog"
        if tipo == "rutura":
            pm = (_gx(t, min(58.0, mu + 4.0)), pm[1])
            mu = _tu(t, pm[0])
            d = _dist(pa, pm)
        interc = []
        sobrevive = 1.0
        for D in eq_o.jog:
            dl, s_ = _dist_segmento(self.pos[D], pa, pm)
            if dl <= 4.5 and 0.05 < s_ < 0.97:
                pi = self.prob_intercetar(D, dl)
                if tipo == "rutura":
                    pi *= 1.0 - 0.25 * eq_o.tend["linha"]
                interc.append((s_, pi, D))
                sobrevive *= 1.0 - pi
        interc.sort(key=lambda x: x[0])
        sk = C.q({"Passe": 0.45, "Técnica": 0.15, "Visão de Jogo": 0.10, "Decisões": 0.10, "Compostura": 0.10, "Primeiro Toque": 0.10})
        if tipo == "longo":
            sk = 0.6 * sk + 0.4 * C.q({"Passe": 0.5, "Força": 0.2, "Visão de Jogo": 0.3})
        rc = m.q({"Primeiro Toque": 0.5, "Técnica": 0.2, "Compostura": 0.15, "Equilíbrio": 0.15})
        pena = {"curto": 0.0, "prog": 0.45, "longo": 1.4, "rutura": 1.3}[tipo]
        if tipo in ("rutura", "longo"):
            pena -= (0.9 if tipo == "rutura" else 0.5) * eq_o.tend["linha"]      # linha subida deixa espaço nas costas
        logit = 2.95 - 0.35 * self.eq[t].tend["ritmo"] + 6.0 * (sk - 0.72) + 2.0 * (rc - 0.72) - 0.045 * max(0.0, d - 6.0) - 1.9 * ctx["p"] - pena
        logit += COESAO * (self.eq[t].ef - 1.0)
        if tipo == "longo":
            logit += 1.0 * (self.eq[t].ef - 1.0) * max(0.0, self.eq[t].tend["jogo_direto"])
        if tipo == "rutura":
            dd, adv = self.mais_perto(pm, o, 1)[0]
            vm = m.q({"Velocidade": 0.35, "Aceleração": 0.30, "Sem Bola": 0.35})
            vd = adv.q({"Velocidade": 0.35, "Aceleração": 0.30, "Antecipação": 0.35})
            logit += 3.5 * (vm - vd) + 0.12 * (dd - 4.0)
        p_exec = _sig(logit)
        duelo, p_duelo = None, 1.0
        if tipo == "longo" and m.papel != taticas.GR:
            dd, adv = self.mais_perto(pm, o, 1)[0]
            if dd < 7.0:
                duelo = (dd, adv)
                p_duelo = _sig(4.5 * (m.aereo - adv.aereo) - 0.45 + 0.10 * (dd - 3.0) + 0.8 * (self.eq[t].ef - 1.0) * max(0.0, self.eq[t].tend["jogo_direto"]))
        return {"m": m, "tipo": tipo, "pa": pa, "pm": pm, "d": d, "mu": mu, "mv": _tv(t, pm[1]), "interc": interc,
                "p_exec": p_exec, "rc": rc, "duelo": duelo, "p_duelo": p_duelo, "ps": sobrevive * p_exec * p_duelo}

    def prob_remate(self, C: Jog, pa, dgol: float, p: float, cabeca: bool = False, qual_extra: float = 0.0,
                    percebido: bool = False):
        """(hipótese de ir à baliza, hipótese de ser golo se for à baliza, qualidade do guarda-redes).

        «percebido» é a leitura que o jogador faz da jogada para decidir se remata (não depende da calibração do
        resultado real: decidir rematar é uma coisa, acertar é outra)."""
        b_alvo, b_golo = (REF_ALVO, REF_GOLO) if percebido else (B_ALVO, B_GOLO)
        o = 1 - C.eq
        gr = self.eq[o].gr
        if cabeca:
            acc = C.q({"Cabeceamento": 0.55, "Compostura": 0.2, "Impulsão": 0.1, "Sem Bola": 0.15})
            pot = C.q({"Cabeceamento": 0.5, "Força": 0.15, "Impulsão": 0.2, "Compostura": 0.15})
        else:
            acc = C.q({"Finalização": 0.40, "Técnica": 0.20, "Compostura": 0.25, "Primeiro Toque": 0.05, "Sem Bola": 0.10}) + C.jeito
            pot = C.q({"Finalização": 0.45, "Técnica": 0.15, "Compostura": 0.15, "Força": 0.15, "Sem Bola": 0.10}) + C.potencia
        acc += qual_extra
        pot += qual_extra
        lado = abs(pa[1] - CY)
        ang = 1.0 / (1.0 + 1.2 * lado / max(dgol, 3.0))
        cob = 0.0 if cabeca else float(self.cobertura(pa, C.eq)) * (1.0 - 0.7 * self.esp)
        folga = 0.0 if cabeca else 0.5 * self.esp           # a defesa desorganizada deixa o avançado à vontade
        fecha = K_BLOCO_BAIXO * max(0.0, -self.eq[o].tend["linha"]) * self.eq[o].ef      # bloco baixo e compacto: poucas linhas de remate livres
        no_alvo = _sig(b_alvo + 4.2 * (acc - 0.72) - 0.06 * (dgol - 8.0) - 1.1 * p + 0.6 * (ang - 0.7) - 0.28 * cob + folga - fecha)
        gr_q = gr.q({"Reflexos": 0.30, "Posicionamento": 0.20, "Agilidade": 0.15, "Um para Um": 0.15 if dgol < 12 else 0.05,
                     "Concentração": 0.10, "Comando de Área": 0.10, "Jogo Aéreo": 0.10 if cabeca else 0.0})
        logit = (b_golo + 3.6 * (pot - 0.72) - 4.0 * (gr_q - 0.78) + 1.5 * max(0.0, (10.0 - dgol) / 10.0)
                 - 0.09 * max(0.0, dgol - 8.0) - 0.8 * p + 0.5 * (ang - 0.7) - 0.22 * cob + folga - fecha)
        return no_alvo, _sig(logit), gr_q

    def bloqueadores(self, pa, t: int):
        """Defesas adversários na linha do remate (número e o mais bem colocado)."""
        golo = (COMPRIMENTO if t == 0 else 0.0, CY)
        n, melhor = 0, None
        for D in self.eq[1 - t].campo:
            dl, s_ = _dist_segmento(self.pos[D], pa, golo)
            if dl < 2.2 and 0.1 < s_ < 0.9:
                n += 1
                melhor = melhor or D
        return n, melhor

    def cobertura(self, pa, t: int) -> int:
        """Quantos defesas adversários fecham a baliza a quem remata (estão entre ele e a baliza, num corredor largo)."""
        golo = (COMPRIMENTO if t == 0 else 0.0, CY)
        return sum(1 for D in self.eq[1 - t].campo
                   if (lambda r: r[0] < 3.8 and 0.08 < r[1] < 0.97)(_dist_segmento(self.pos[D], pa, golo)))

    def opcoes(self, C: Jog, ctx: dict) -> list[dict]:
        """Todas as coisas que o portador pode fazer, cada uma com a sua «utilidade» (quanto melhora a posição da equipa).

        A utilidade soma: o que se ganha se correr bem × a hipótese de correr bem, menos o que se perde se correr mal;
        o estilo muda o que a equipa valoriza (reter a bola, ganhar terreno depressa, abrir para as alas, arriscar) e a
        função muda o gosto de cada jogador por cada tipo de ação."""
        t = C.eq
        eq = self.eq[t]
        tend = eq.tend
        pr = C.prop
        cu, cv, p = ctx["u"], ctx["v"], ctx["p"]
        zc = self.valor_zona(cu, cv)
        aversao = 1.0 - 0.45 * tend["risco"]
        rho = 0.018 * (1.0 + K_RHO_POSSE * tend["posse"])
        out = []
        candidatos = [m for m in eq.campo if m is not C]
        if cu < 30.0:
            candidatos.append(eq.gr)
        for m in candidatos:
            if _dist(self.pos[C], self.pos[m]) < 2.5:
                continue
            info = self.info_passe(C, m, ctx)
            tipo, ps = info["tipo"], info["ps"]
            zm = self.valor_zona(info["mu"], info["mv"])
            ganho = zm - zc
            if ganho > 0:
                ganho *= (1.0 + 0.35 * tend["ritmo"]) * (1.0 + 1.0 * self.esp)
            u_ = ps * ganho - (1.0 - ps) * (self.custo_perda(info["mu"]) + zc) * aversao + rho * ps
            if tipo == "longo":
                u_ += K_LONGO * tend["jogo_direto"] - 0.002
            elif tipo == "rutura":
                u_ += 0.006 * tend["risco"] + 0.004 * tend["ritmo"]
            if info["mu"] >= 25.0 and abs(info["mv"] - CY) > 12.0:
                u_ += 0.012 * tend["largura"]
            u_ += 0.02 * math.log(pr[tipo])
            out.append({"acao": "passe", "U": u_, "info": info})
        dgol = ctx["dgol"]
        if dgol < 30.0 and C.papel != taticas.GR:
            pa = self.pos[C]
            no_alvo, p_golo, _ = self.prob_remate(C, pa, dgol, p, percebido=True)
            n_bloq, _b = self.bloqueadores(pa, t)
            p_sai = 1.0 - _lim(0.05 + 0.13 * n_bloq + 0.06 * p, 0.0, 0.5)
            pg = no_alvo * p_golo * p_sai
            u_ = K_REMATE * min(1.0, self.gestao(t)) * pg - 0.8 * zc + 0.006 * (1.0 + tend["risco"]) - 0.004
            u_ += 0.02 * math.log(pr["remate"] * (pr["remate_longe"] if dgol > 14.0 else 1.0))
            out.append({"acao": "remate", "U": u_})
        if cu >= 38.0 and abs(cv - CY) > 9.0 and C.papel != taticas.GR:
            sk = C.q({"Cruzamento": 0.55, "Técnica": 0.15, "Passe": 0.15, "Decisões": 0.05, "Compostura": 0.10})
            ps = _sig(0.15 + 5.0 * (sk - 0.72) - 1.6 * p + K_CRUZ_PLANO * (eq.ef - 1.0) * max(0.0, tend["largura"]))
            atq, dfs = self.jogadores_na_area(t)
            dif = sum(a_.aereo for a_ in atq) / len(atq) - sum(d_.aereo for d_ in dfs) / len(dfs)
            zx = K_CRUZ * (0.07 + 0.08 * _lim(dif + 0.2, 0.0, 1.0))
            u_ = ps * (zx - zc) - (1.0 - ps) * (self.custo_perda(55.0) + zc) * aversao + 0.012 * tend["largura"] + 0.02 * math.log(pr["cruz"])
            out.append({"acao": "cruz", "U": u_})
        D = ctx["def"]
        if D is not None and C.papel != taticas.GR and _dist(self.pos[D], self.pos[C]) < 9.0 and cu < 54.0:
            att = C.q({"Drible": 0.40, "Agilidade": 0.20, "Aceleração": 0.15, "Velocidade": 0.10, "Equilíbrio": 0.10, "Técnica": 0.05})
            dfn = D.q({"Desarme": 0.30, "Marcação": 0.20, "Agilidade": 0.15, "Antecipação": 0.15, "Velocidade": 0.10, "Equilíbrio": 0.10})
            ps = _sig(5.5 * (att - dfn) - 0.30)
            ganho = self.valor_zona(cu + 5.0, cv) - zc + 0.010
            u_ = ps * ganho - (1.0 - ps) * (self.custo_perda(cu) + zc) * aversao + 0.006 * tend["risco"] + B_DRIBLE - 0.02 * self.dribles_seguidos + 0.02 * math.log(pr["drible"])
            out.append({"acao": "drible", "U": u_})
        if cu < 18.0 and p > 0.45:
            u_ = 0.5 * (self.valor_zona(cu + 26.0, CY) - zc) - 0.5 * self.custo_perda(cu + 26.0) + 0.012 * tend["jogo_direto"] - 0.003
            out.append({"acao": "alivio", "U": u_})
        return out

    def escolher_acao(self):
        C, t = self.portador, self.posse
        cu, cv = _tu(t, self.bola[0]), _tv(t, self.bola[1])
        dgol = math.hypot(COMPRIMENTO - cu, cv - CY)
        p, defensor = self.pressao(C)
        ctx = {"u": cu, "v": cv, "dgol": dgol, "p": p, "def": defensor}
        ops = self.opcoes(C, ctx)
        if not ops:
            return {"acao": "segurar"}, ctx
        dq = C.q({"Decisões": 0.5, "Visão de Jogo": 0.3, "Compostura": 0.2})
        tau = _lim(0.014 + 0.03 * (0.80 - dq), 0.008, 0.030)
        mx = max(o_["U"] for o_ in ops)
        pesos = [math.exp((o_["U"] - mx) / tau) for o_ in ops]
        return self.r.choices(ops, weights=pesos)[0], ctx

    # ------------------------------------------------------------------ desafio defensivo (desarmes e faltas)
    def desafio(self) -> bool:
        C, t = self.portador, self.posse
        o = 1 - t
        proximos = self.mais_perto(self.bola, o, 1)
        d1, D = proximos[0]
        if d1 > 5.5:
            return False
        tend_o = self.eq[o].tend
        prob = 0.28 * max(0.0, 1.0 - d1 / 5.5) ** 1.3 * (0.55 + 0.6 * D.prop["pressao"]) * (1.0 + 0.4 * tend_o["linha"])
        prob *= (0.7 + 0.5 * D.forma) * (1.0 - 0.7 * self.esp)
        if self.r.random() >= prob:
            return False
        qt = D.q({"Desarme": 0.40, "Marcação": 0.15, "Agressividade": 0.10, "Antecipação": 0.12, "Força": 0.08, "Velocidade": 0.08, "Agilidade": 0.07}) + D.desarme_extra
        qh = C.q({"Primeiro Toque": 0.20, "Drible": 0.18, "Equilíbrio": 0.14, "Força": 0.14, "Compostura": 0.14, "Agilidade": 0.10, "Técnica": 0.10})
        ganha = self.r.random() < _sig(5.0 * (qt - qh) - 0.35 + COESAO * (self.eq[o].ef - self.eq[t].ef))
        pf = _lim(0.045 + 0.20 * D.v("Agressividade") - 0.07 * D.v("Marcação") + D.falta_extra, 0.02, 0.32) * (1.0 if not ganha else 0.3)
        if not ganha:
            pf *= 1.5
        if self.r.random() < pf * K_FALTA:
            self.falta(D, C)
            return True
        if ganha:
            D.st["desarmes"] += 1
            self.est[o]["desarmes"] += 1
            self.ev("desarme", o, D, C, de=self.bola)
            self.ganhar_bola(o, D, self.pos[C])
            self.credito(t, self.dt(1.5, t))
            return True
        D.st["desarmes_perdidos"] += 1
        self.alivio_pressao = 0.45
        return False

    def falta(self, autor: Jog, vitima: Jog):
        t, o = vitima.eq, autor.eq
        local = self.pos[vitima]
        self.est[o]["faltas"] += 1
        autor.st["faltas"] += 1
        self.ev("falta", o, autor, vitima, de=local)
        u, v = _tu(t, local[0]), _tv(t, local[1])
        dgol = math.hypot(COMPRIMENTO - u, v - CY)
        if u >= ZONA_LIVRE_U and dgol <= ZONA_LIVRE_D:
            self.livre_perigoso(t, local, vitima)
        else:
            self.ganhar_bola(t, vitima, local, contra_possivel=False)
            self.pos[vitima] = local
            self.credito(t, 0.0)
            self.morto(self.r.uniform(5.0, 9.0))

    # ------------------------------------------------------------------ passes
    def risco_linha(self, a, b, o: int) -> float:
        total = 1.0
        for D in self.eq[o].jog:
            dl, s = _dist_segmento(self.pos[D], a, b)
            if dl > 4.5 or s <= 0.05 or s >= 0.97:
                continue
            total *= 1.0 - self.prob_intercetar(D, dl)
        return 1.0 - total

    def prob_intercetar(self, D: Jog, dl: float) -> float:
        alcance = max(0.0, 1.0 - dl / 4.5) ** 1.5
        leitura = D.q({"Antecipação": 0.35, "Posicionamento": 0.25, "Concentração": 0.15, "Velocidade": 0.10, "Agilidade": 0.075, "Marcação": 0.075})
        return _lim(0.34 * alcance * (0.30 + 1.0 * leitura) * (1.0 - 0.60 * self.esp), 0.0, 0.55)

    def executar_passe(self, C: Jog, info: dict, ctx: dict):
        t, o = C.eq, 1 - C.eq
        m, tipo, pa, pm, d = info["m"], info["tipo"], info["pa"], info["pm"], info["d"]
        self.est[t]["passes"] += 1
        C.st["passes"] += 1
        if tipo == "longo":
            self.est[t]["passes_longos"] += 1
        self.ultimo_passe = None
        # 1) interceção, por ordem ao longo do caminho da bola
        for s_, pi, D in info["interc"]:
            if self.r.random() < pi:
                ponto = (pa[0] + (pm[0] - pa[0]) * s_, pa[1] + (pm[1] - pa[1]) * s_)
                D.st["intercecoes"] += 1
                self.est[o]["intercecoes"] += 1
                self.ev("intercecao", o, D, C, de=pa, para=ponto, tipo_passe=tipo)
                self.ev("passe", t, C, m, de=pa, para=ponto, res="intercetado", tipo_passe=tipo)
                self.ganhar_bola(o, D, ponto)
                self.credito(t, self.dt(2.2, t))
                return
        # 2) execução
        if self.r.random() >= info["p_exec"]:
            self.ev("passe", t, C, m, de=pa, para=pm, res="falhado", tipo_passe=tipo)
            self.credito(t, self.dt(3.0, t))
            self.perder_bola_solta(t, pm, _lim(0.10 + 0.018 * max(0.0, d - 12.0), 0.08, 0.40))
            return
        # 3) bola longa: disputa da bola entre o recetor e o adversário mais próximo
        if info["duelo"] is not None and self.r.random() >= info["p_duelo"]:
            dd, adv = info["duelo"]
            self.ev("passe", t, C, m, de=pa, para=pm, res="disputado", tipo_passe=tipo)
            self.credito(t, self.dt(4.5, t))
            if self.r.random() < 0.40:                           # segunda bola: fica com quem estiver mais perto
                dm = _dist(self.pos[m], pm)
                if self.r.random() < _sig(0.6 * (dd - dm)):
                    self.portador, self.bola = m, pm
                    return
            self.ev("corte", o, adv, m, de=pm)
            adv.st["cortes"] += 1
            self.est[o]["cortes"] += 1
            self.ganhar_bola(o, adv, pm)
            return
        # 4) o recetor domina a bola (sob pressão pode perdê-la)
        rc = info["rc"]
        pm_press, _ = self.pressao_de(m, pm)
        perde = 0.02 + 0.10 * pm_press * (1.0 - _lim(rc - 0.5, 0.0, 0.5) / 0.5)
        self.est[t]["passes_ok"] += 1
        C.st["passes_ok"] += 1
        self.ev("passe", t, C, m, de=pa, para=pm, res="ok", tipo_passe=tipo)
        self.ultimo_passe = (C, self.t)
        self.credito(t, self.dt({"curto": 3.0, "prog": 3.6, "longo": 4.5, "rutura": 4.0}[tipo], t))
        if info["mu"] >= 26.0 and tipo in ("curto", "prog"):
            ganho = 0.07 if tipo == "curto" else 0.09
            if abs(info["mv"] - _tv(t, pa[1])) >= 16.0:             # inversão de flanco: obriga a defesa a deslocar-se
                ganho += 0.12
            self.ganha_espaco(ganho, t)
        if self.r.random() < perde:
            adv = self.mais_perto(pm, o, 1)[0][1]
            self.ev("bola_perdida", t, m, de=pm)
            self.ganhar_bola(o, adv, pm)
            return
        self.portador, self.bola = m, pm

    def pressao_de(self, m: Jog, ponto):
        proximos = self.mais_perto(ponto, 1 - m.eq, 1)
        d1 = proximos[0][0]
        return 0.8 * max(0.0, 1.0 - d1 / 6.5), proximos[0][1]

    def perder_bola_solta(self, t: int, ponto, prob_sair: float):
        """A bola perdeu-se sem nenhum adversário a apanhá-la: pode sair do campo ou ficar com o adversário mais próximo."""
        o = 1 - t
        x = _lim(ponto[0], -2.0, COMPRIMENTO + 2.0)
        y = ponto[1]
        if self.r.random() < prob_sair or not (0.5 < y < LARGURA - 0.5) or not (0.5 < x < COMPRIMENTO - 0.5):
            self.bola_fora(t, ponto)
            return
        adv = self.mais_perto(ponto, o, 1)[0][1]
        self.ganhar_bola(o, adv, ponto)

    def bola_fora(self, t_culpado: int, ponto, tipo: str | None = None):
        """A bola saiu (tocada em último lugar por `t_culpado`): lateral, pontapé de baliza ou canto.
        `tipo`: "fundo" (pela linha de fundo), "lateral" (pela linha lateral) ou None (decide-se pelo sítio onde saiu)."""
        o = 1 - t_culpado
        x, y = ponto
        u = _tu(t_culpado, _lim(x, 0.0, COMPRIMENTO))          # 60 = baliza adversária de quem tocou por último
        if tipo is None:
            if u >= 50.0:
                tipo = "fundo" if self.r.random() < 0.55 else "lateral"
            elif u <= 10.0:
                tipo = "fundo" if self.r.random() < 0.45 else "lateral"
            else:
                tipo = "lateral"
        if tipo == "fundo":
            if u >= 30.0:                                       # saiu pela linha de fundo adversária: pontapé de baliza
                self.pontape_de_baliza(o, saiu=(_gx(t_culpado, COMPRIMENTO), _lim(y, 0.0, LARGURA)))
            else:                                               # saiu pela sua própria linha de fundo: canto para `o`
                self.ev("canto_conquistado", o, de=(_gx(t_culpado, 0.0), _lim(y, 0.0, LARGURA)))
                self.bola = (_gx(t_culpado, 0.0), 0.0 if y < CY else LARGURA)
                self.canto(o)
            return
        y = 0.0 if y < CY else LARGURA
        local = (_lim(x, 3.0, COMPRIMENTO - 3.0), y)
        j = min(self.eq[o].campo, key=lambda k: _dist(self.pos[k], local))
        self.ev("lateral", o, j, de=local)
        self.ganhar_bola(o, j, local, contra_possivel=False)
        self.morto(self.r.uniform(6.0, 11.0))

    def pontape_de_baliza(self, t: int, saiu=None):
        gr = self.eq[t].gr
        local = (_gx(t, 3.0), CY)
        extra = {"saiu": (round(saiu[0], 1), round(saiu[1], 1))} if saiu is not None else {}
        self.ev("pontape_de_baliza", t, gr, de=local, **extra)
        self.ganhar_bola(t, gr, local, contra_possivel=False)
        self.morto(self.r.uniform(6.0, 10.0))

    def gr_distribui(self):
        gr = self.portador
        t = gr.eq
        o = 1 - t
        eq = self.eq[t]
        tend = eq.tend
        p_longo = _lim(0.30 + K_GR_LONGO * tend["jogo_direto"] - 0.40 * tend["posse"] + 0.3 * (gr.prop["longo"] - 1.0), 0.04, 0.92)
        self.atualizar()
        pg = self.pos[gr]
        alvos = [m for m in eq.campo]
        if self.r.random() < p_longo:
            m = max(alvos, key=lambda k: _tu(t, self.pos[k][0]) * 0.02 + k.aereo * 1.1 + self.r.random() * 0.5)
            ctx = {"u": _tu(t, pg[0]), "v": _tv(t, pg[1]), "p": 0.0, "dgol": 60.0}
            self.gr_passe(gr, m, "longo")
        else:
            m = min((k for k in alvos if k.papel == taticas.DEF), key=lambda k: self.mais_perto(self.pos[k], o, 1)[0][0] * -1,
                    default=alvos[0])
            self.gr_passe(gr, m, "curto")

    def gr_passe(self, gr: Jog, m: Jog, tipo: str):
        t, o = gr.eq, 1 - gr.eq
        pa, pm = self.pos[gr], self.pos[m]
        d = _dist(pa, pm)
        self.est[t]["passes"] += 1
        gr.st["passes"] += 1
        if tipo == "longo":
            self.est[t]["passes_longos"] += 1
        sk = gr.q({"Pontapé de Baliza": 0.5, "Lançamento": 0.2, "Decisões": 0.15, "Compostura": 0.15}) if tipo == "longo" else gr.q({"Lançamento": 0.35, "Decisões": 0.3, "Compostura": 0.25, "Pontapé de Baliza": 0.1})
        if tipo == "longo":
            # bola aérea: o recetor disputa com o adversário mais próximo
            adv = self.mais_perto(pm, o, 1)[0][1]
            chegou = _sig(2.0 + 5.0 * (sk - 0.78) - 0.03 * max(0.0, d - 20.0))
            if self.r.random() < chegou:
                aer = _sig(4.5 * (m.aereo - adv.aereo) + 0.05)
                if self.r.random() < aer:
                    self.est[t]["passes_ok"] += 1
                    gr.st["passes_ok"] += 1
                    self.ev("passe", t, gr, m, de=pa, para=pm, res="ok", tipo_passe="longo")
                    self.credito(t, self.dt(5.5, t))
                    self.portador, self.bola = m, pm
                    return
                self.ev("passe", t, gr, m, de=pa, para=pm, res="falhado", tipo_passe="longo")
                self.credito(t, self.dt(5.5, t))
                self.ganhar_bola(o, adv, pm)
                return
            self.ev("passe", t, gr, m, de=pa, para=pm, res="falhado", tipo_passe="longo")
            self.credito(t, self.dt(5.5, t))
            self.perder_bola_solta(t, pm, 0.35)
            return
        pi = self.risco_linha(pa, pm, o)
        ok = self.r.random() > pi and self.r.random() < _sig(2.6 + 6.0 * (sk - 0.72))
        if ok:
            self.est[t]["passes_ok"] += 1
            gr.st["passes_ok"] += 1
            self.ev("passe", t, gr, m, de=pa, para=pm, res="ok", tipo_passe="curto")
            self.credito(t, self.dt(5.0, t))
            self.portador, self.bola = m, pm
        else:
            self.ev("passe", t, gr, m, de=pa, para=pm, res="falhado", tipo_passe="curto")
            self.credito(t, self.dt(5.0, t))
            adv = self.mais_perto(pm, o, 1)[0][1]
            self.ganhar_bola(o, adv, pm)

    # ------------------------------------------------------------------ alívio, drible
    def acao_alivio(self, C: Jog, ctx: dict):
        t, o = C.eq, 1 - C.eq
        self.est[t]["alivios"] += 1
        self.credito(t, self.dt(2.5, t))
        pa = self.pos[C]
        destino = (_gx(t, min(52.0, ctx["u"] + self.r.uniform(18.0, 34.0))), self.r.uniform(6.0, LARGURA - 6.0))
        m = max(self.eq[t].campo, key=lambda k: -_dist(self.pos[k], destino))
        adv = self.mais_perto(destino, o, 1)[0][1]
        bom = _sig(0.2 + 3.0 * (C.q({"Passe": 0.4, "Força": 0.3, "Decisões": 0.3}) - 0.72) + 3.5 * (m.aereo - adv.aereo) * 0.5)
        if self.r.random() < 0.25:
            self.ev("alivio", t, C, de=pa, para=destino, res="fora")
            self.bola_fora(t, destino)
        elif self.r.random() < bom * 0.55:
            self.ev("alivio", t, C, m, de=pa, para=destino, res="ok")
            self.portador, self.bola = m, self.pos[m]
        else:
            self.ev("alivio", t, C, de=pa, para=destino, res="adversario")
            self.ganhar_bola(o, adv, destino)

    def acao_drible(self, C: Jog, ctx: dict):
        t, o = C.eq, 1 - C.eq
        D = ctx["def"]
        self.credito(t, self.dt(3.2, t))
        if D is None:
            return
        self.est[t]["dribles"] += 1
        C.st["dribles"] += 1
        att = C.q({"Drible": 0.40, "Agilidade": 0.20, "Aceleração": 0.15, "Velocidade": 0.10, "Equilíbrio": 0.10, "Técnica": 0.05})
        dfn = D.q({"Desarme": 0.30, "Marcação": 0.20, "Agilidade": 0.15, "Antecipação": 0.15, "Velocidade": 0.10, "Equilíbrio": 0.10})
        pa = self.bola
        if self.r.random() < _sig(5.5 * (att - dfn) - 0.30):
            self.est[t]["dribles_ok"] += 1
            C.st["dribles_ok"] += 1
            avanco = self.r.uniform(3.0, 7.0)
            u = min(56.0, _tu(t, pa[0]) + avanco)
            v = _lim(_tv(t, pa[1]) + self.r.uniform(-3.0, 3.0), 1.5, LARGURA - 1.5)
            novo = (_gx(t, u), _gy(t, v))
            self.ev("drible", t, C, D, de=pa, para=novo, res="ok")
            self.bola = novo
            self.pos[C] = novo
            self.alivio_pressao = 0.35
            self.ganha_espaco(0.12, t)
            self.dribles_seguidos += 1
            return
        if self.r.random() < _lim(0.05 + 0.18 * D.v("Agressividade") + D.falta_extra, 0.03, 0.3) * K_FALTA:
            self.ev("drible", t, C, D, de=pa, res="falta")
            self.falta(D, C)
            return
        D.st["desarmes"] += 1
        self.est[o]["desarmes"] += 1
        self.ev("drible", t, C, D, de=pa, res="perdido")
        self.ev("desarme", o, D, C, de=pa)
        self.ganhar_bola(o, D, pa)

    # ------------------------------------------------------------------ cruzamentos, cantos, livres
    def acao_cruzamento(self, C: Jog, ctx: dict):
        t, o = C.eq, 1 - C.eq
        self.est[t]["cruzamentos"] += 1
        C.st["cruzamentos"] += 1
        self.credito(t, self.dt(3.8, t))
        pa = self.bola
        sk = C.q({"Cruzamento": 0.55, "Técnica": 0.15, "Passe": 0.15, "Decisões": 0.05, "Compostura": 0.10})
        p = ctx["p"]
        ok = _sig(0.15 + 5.0 * (sk - 0.72) - 1.6 * p + K_CRUZ_PLANO * (self.eq[t].ef - 1.0) * max(0.0, self.eq[t].tend["largura"]))
        alvo = (_gx(t, 54.0), CY + self.r.uniform(-4, 4))
        if self.r.random() >= ok:
            self.ev("cruzamento", t, C, de=pa, para=alvo, res="falhado")
            adv = self.mais_perto(pa, o, 1)[0][1]
            r = self.r.random()
            if r < 0.20:
                self.ev("canto_conquistado", t, de=pa)      # desvio: canto para a equipa que cruzou
                self.canto(t)
            elif r < 0.30:
                self.bola_fora(t, (_gx(t, 59.0), pa[1]), 'fundo')
            else:
                self.ganhar_bola(o, adv, alvo)
            return
        self.ev("cruzamento", t, C, de=pa, para=alvo, res="ok")
        self.bola_na_area(t, C, "cruzamento", 0.0)

    def jogadores_na_area(self, t: int):
        """Quem vai à bola nos cruzamentos e cantos (até 3 atacantes e os defensores que os marcam)."""
        eq, o = self.eq[t], self.eq[1 - t]
        atq = sorted(eq.campo, key=lambda j: (j.papel == taticas.AVA) * 2.0 + j.prop["area"] * 0.6 + (j.papel == taticas.MED) * 0.4 + j.aereo * 0.3, reverse=True)
        atq = atq[:MAX_JOGADORES_NA_AREA_CANTO]
        dfs = sorted(o.campo, key=lambda j: (j.papel == taticas.DEF) * 2.0 + (j.papel == taticas.MED) * 0.8 + j.aereo * 0.3, reverse=True)
        return atq, dfs[:max(2, MAX_JOGADORES_NA_AREA_CANTO)]

    def area_dos(self, t: int) -> list:
        """[atacantes, defensores] que vão à bola nos cruzamentos e cantos de `t` (nomes; só para a simulação visual)."""
        atq, dfs = self.jogadores_na_area(t)
        return [[j.nome for j in atq], [j.nome for j in dfs]]

    def bola_na_area(self, t: int, bateu: Jog, origem: str, qualidade_entrega: float):
        """A bola chega à área: o guarda-redes pode sair, os atacantes disputam-na com os defensores."""
        o = 1 - t
        gr = self.eq[o].gr
        atq, dfs = self.jogadores_na_area(t)
        pa = (_gx(t, 54.0), CY)
        # guarda-redes
        sai = _sig(-0.4 + 4.0 * (gr.q({"Comando de Área": 0.4, "Jogo Aéreo": 0.35, "Bravura": 0.1, "Impulsão": 0.1, "Decisões": 0.05}) - 0.78) - 1.2 * qualidade_entrega)
        if self.r.random() < sai * 0.55:
            self.ev("gr_sai", o, gr, de=pa, area=self.area_dos(t))
            self.ganhar_bola(o, gr, (_gx(o, 4.0), CY))
            self.credito(o, 0.0)
            self.morto(2.5)
            return
        # disputa aérea: o atacante que ataca melhor a bola contra o melhor marcador
        pesos = [max(0.05, a.aereo * a.prop["area"]) ** 4 for a in atq]
        alvo = self.r.choices(atq, weights=pesos)[0]
        marc = self.r.choices(dfs, weights=[max(0.05, d.aereo * (0.6 + 0.4 * d.v("Marcação"))) ** 4 for d in dfs])[0]
        vantagem = 4.5 * (alvo.aereo - marc.aereo) + 1.6 * (qualidade_entrega - 0.5) - 0.55
        if self.r.random() < _sig(vantagem):
            self.ev("cabeceamento", t, alvo, bateu, de=pa, res="ganhou", area=self.area_dos(t))
            self.acao_remate(alvo, {"u": 54.0, "v": CY, "dgol": 7.5 + self.r.uniform(0, 4), "p": 0.35, "def": marc}, cabeca=True, origem=origem)
            return
        marc.st["cortes"] += 1
        self.est[o]["cortes"] += 1
        self.ev("corte", o, marc, alvo, de=pa, area=self.area_dos(t))
        r = self.r.random()
        if r < 0.10:
            self.ev("canto_conquistado", t, de=pa)
            self.canto(t)
        elif r < 0.30:
            self.bola_fora(o, (_gx(o, 1.0), self.bola[1]), 'fundo')
        else:
            self.ganhar_bola(o, marc, pa)
            self.credito(o, 0.0)
            self.morto(2.0)

    def canto(self, t: int):
        self.est[t]["cantos"] += 1
        eq = self.eq[t]
        tir = eq.cantos
        lado = 0.0 if self.bola[1] < CY else LARGURA
        pa = (_gx(t, COMPRIMENTO), lado)
        bp = tir.q({"Bola Parada": 0.70, "Cruzamento": 0.15, "Técnica": 0.10, "Compostura": 0.05})
        entrega = _sig(0.35 + 5.0 * (bp - 0.72))
        self.ev("canto", t, tir, de=pa, para=(_gx(t, 54.0), CY), area=self.area_dos(t))
        self.morto(self.r.uniform(8.0, 14.0))
        if self.r.random() > entrega:
            adv = self.mais_perto((_gx(t, 54.0), CY), 1 - t, 1)[0][1]
            self.ev("canto_mal_batido", t, tir, de=pa)
            if self.r.random() < 0.3:
                self.bola_fora(t, (_gx(t, 59.5), lado), 'fundo')
            else:
                self.ganhar_bola(1 - t, adv, (_gx(t, 52.0), CY))
            return
        self.bola_na_area(t, tir, "canto", entrega)

    def livre_perigoso(self, t: int, local, vitima: Jog):
        o = 1 - t
        eq = self.eq[t]
        tir = eq.livres
        gr = self.eq[o].gr
        self.est[t]["livres"] += 1
        u, v = _tu(t, local[0]), _tv(t, local[1])
        dgol = math.hypot(COMPRIMENTO - u, v - CY)
        bp = tir.q({"Bola Parada": 0.70, "Técnica": 0.12, "Finalização": 0.10, "Compostura": 0.08})
        self.ev("livre", t, tir, vitima, de=local, dist=round(dgol, 1), area=self.area_dos(t))
        self.morto(self.r.uniform(10.0, 16.0))
        if abs(v - CY) > 9.0 and dgol > 14.0:
            # livre lateral: bola para a área, como um canto
            entrega = _sig(0.0 + 5.0 * (bp - 0.72))
            if self.r.random() > entrega:
                self.ganhar_bola(o, self.mais_perto(local, o, 1)[0][1], local)
                return
            self.bola_na_area(t, tir, "livre", entrega * 0.9)
            return
        # remate direto
        pt = (self.pos[tir] if tir in self.pos else local)
        if self.r.random() < _lim(0.34 - 0.9 * (bp - 0.72), 0.12, 0.5):
            tir.st["remates"] += 1
            self.est[t]["remates"] += 1
            self.est[t]["remates_bloqueados"] += 1
            self.ev("remate", t, tir, de=local, res="barreira", origem="livre")
            self.ganhar_bola(o, self.mais_perto(local, o, 1)[0][1], local)
            return
        self.disparo(tir, local, dgol, "livre", p=0.0, cabeca=False, qual_extra=0.9 * (bp - 0.72))

    # ------------------------------------------------------------------ remate
    def acao_remate(self, C: Jog, ctx: dict, cabeca: bool = False, origem: str = "jogo"):
        t, o = C.eq, 1 - C.eq
        pa = self.pos[C] if not cabeca else (_gx(t, ctx["u"]), _gy(t, ctx["v"]))
        dgol = ctx["dgol"]
        if origem == "jogo" and self.contra_ativo[t]:
            origem = "contra"
        golo = (COMPRIMENTO if t == 0 else 0.0, CY)
        bloqueadores, melhor_bloq = self.bloqueadores(pa, t)
        C.st["remates"] += 1
        self.est[t]["remates"] += 1
        if self.ultimo_passe and self.ultimo_passe[0] is not C and self.t - self.ultimo_passe[1] <= 8.0:
            self.ultimo_passe[0].st["passes_chave"] += 1                  # o passe que deixou o colega a rematar
        self.credito(t, self.dt(2.5, t))
        if not cabeca and self.r.random() < _lim(0.05 + 0.13 * bloqueadores + 0.06 * ctx["p"], 0.0, 0.5):
            self.est[t]["remates_bloqueados"] += 1
            if melhor_bloq:
                melhor_bloq.st["bloqueios"] += 1
            self.ev("remate", t, C, de=pa, para=golo, res="bloqueado", origem=origem)
            if self.r.random() < 0.26:
                self.ev("canto_conquistado", t, de=pa)
                self.canto(t)
            else:
                adv = melhor_bloq or self.mais_perto(pa, o, 1)[0][1]
                self.ganhar_bola(o, adv, self.pos[adv])
            return
        self.disparo(C, pa, dgol, origem, p=ctx["p"], cabeca=cabeca)

    def disparo(self, C: Jog, pa, dgol: float, origem: str, p: float, cabeca: bool, qual_extra: float = 0.0):
        """Depois de o remate sair (já não foi bloqueado): fora, defesa ou golo."""
        t, o = C.eq, 1 - C.eq
        gr = self.eq[o].gr
        golo_xy = (COMPRIMENTO if t == 0 else 0.0, CY)
        if origem == "livre":
            C.st["remates"] += 1
            self.est[t]["remates"] += 1
        no_alvo, p_golo, _gr_q = self.prob_remate(C, pa, dgol, p, cabeca, qual_extra)
        if self.r.random() >= no_alvo:
            self.ev("remate", t, C, de=pa, para=golo_xy, res="fora", origem=origem, cabeca=cabeca)
            if self.r.random() < 0.20:
                self.canto_ou_baliza_pos_remate(t, pa)
            else:
                self.pontape_de_baliza(o)
            return
        C.st["remates_baliza"] += 1
        self.est[t]["remates_baliza"] += 1
        if self.r.random() < p_golo:
            self.golo(C, pa, origem, cabeca)
            return
        gr.st["defesas"] += 1
        self.est[o]["defesas"] += 1
        dificil = p_golo > 0.38
        self.ev("defesa", o, gr, C, de=pa, res="defesa", origem=origem, dificil=dificil)
        r = self.r.random()
        if r < 0.50:
            self.ganhar_bola(o, gr, (_gx(o, 3.0), CY))
            self.morto(1.5)
        elif r < 0.78:
            self.ev("canto_conquistado", t, de=pa)
            self.canto(t)
        else:
            if self.r.random() < 0.5 and origem != "ressalto":
                self.ev("ressalto", t, C, de=pa)
                self.acao_remate(C, {"u": min(56.0, _tu(t, pa[0])), "v": _tv(t, pa[1]), "dgol": max(3.0, dgol - 1.0), "p": 0.5, "def": None}, origem="ressalto")
            else:
                adv = self.mais_perto(pa, o, 1)[0][1]
                self.ganhar_bola(o, adv, self.pos[adv])

    def canto_ou_baliza_pos_remate(self, t: int, pa):
        if self.r.random() < 0.7:
            self.ev("canto_conquistado", t, de=pa)
            self.canto(t)
        else:
            self.pontape_de_baliza(1 - t)

    def golo(self, C: Jog, pa, origem: str, cabeca: bool):
        t, o = C.eq, 1 - C.eq
        self.golos[t] += 1
        self.est[t]["golos"] += 1
        C.st["golos"] += 1
        assist = None
        if self.ultimo_passe and self.ultimo_passe[0] is not C and self.t - self.ultimo_passe[1] <= 8.0 and origem in ("jogo", "contra", "ressalto"):
            assist = self.ultimo_passe[0]
            assist.st["assistencias"] += 1
        if origem in ("livre", "canto"):
            self.est[t]["golos_bola_parada"] += 1
        if origem == "contra":
            self.est[t]["golos_contra"] += 1
        self.ev("golo", t, C, assist, de=pa, para=(COMPRIMENTO if t == 0 else 0.0, CY), origem=origem, cabeca=cabeca,
                placar=list(self.golos))
        self.morto(20.0)
        self.pontape_de_saida(o)

    # ------------------------------------------------------------------ notas dos jogadores
    NOTA_BASE = 5.8

    def notas(self) -> tuple[list[dict], dict]:
        """A nota (0–10) de cada jogador e o MVP. Só conta o que cada um FEZ no jogo (golos, assistências, passes, defesas,
        desarmes…) e o que a equipa sofreu: nunca os atributos. Um jogo normal dá cerca de 6,5; acima de 8,0 é um grande jogo."""
        golos = list(self.golos)
        out = [{}, {}]
        melhor = None
        for t, eq in enumerate(self.eq):
            sofridos = golos[1 - t]
            dif = golos[t] - golos[1 - t]
            for j in eq.jog:
                s = j.st
                gr, defesa, medio = j.papel == taticas.GR, j.papel == taticas.DEF, j.papel == taticas.MED
                n = self.NOTA_BASE + (0.15 if gr else 0.25 if defesa else 0.0 if medio else -0.10)
                n += (0.90 if (gr or defesa) else 0.75) * s["golos"] + 0.55 * s["assistencias"] + 0.12 * s["passes_chave"]
                n += 0.08 * max(0, s["remates_baliza"] - s["golos"]) - 0.03 * (s["remates"] - s["remates_baliza"])
                n += 0.03 * (s["passes_ok"] - 0.78 * s["passes"])
                n += 0.12 * s["dribles_ok"] - 0.08 * (s["dribles"] - s["dribles_ok"])
                n += 0.12 * s["desarmes"] + 0.07 * s["intercecoes"] + 0.06 * s["cortes"] + 0.10 * s["bloqueios"]
                n -= 0.06 * s["desarmes_perdidos"] + 0.12 * s["faltas"]
                if gr:
                    n += 0.25 * s["defesas"] - 0.25 * sofridos + (0.50 if sofridos == 0 else 0.0)
                elif defesa:
                    n += -0.08 * sofridos + (0.25 if sofridos == 0 else 0.0)
                elif medio:
                    n += -0.03 * sofridos + (0.10 if sofridos == 0 else 0.0)
                n += 0.06 * max(-4, min(4, dif)) + (0.15 if dif > 0 else -0.10 if dif < 0 else 0.0)
                if n > 7.5:
                    n = 7.5 + (n - 7.5) * 0.55                      # os grandes jogos sobem devagar: o 10 é de um jogo histórico
                n = round(max(3.0, min(10.0, n)), 1)
                destaques = []
                for chave, un, pl in (("golos", "golo", "golos"), ("assistencias", "assistência", "assistências"),
                                      ("defesas", "defesa", "defesas"), ("passes_chave", "passe para remate", "passes para remate"),
                                      ("desarmes", "desarme", "desarmes"), ("intercecoes", "interceção", "interceções"),
                                      ("dribles_ok", "drible certo", "dribles certos"), ("cortes", "corte", "cortes")):
                    v = s[chave]
                    if v:
                        destaques.append(f"{v} {un if v == 1 else pl}")
                out[t][j.nome] = {"nota": n, "destaques": destaques[:3]}
                chave_mvp = (n, s["golos"], s["assistencias"], 1 if dif > 0 else 0)
                if melhor is None or chave_mvp > melhor[0]:
                    melhor = (chave_mvp, t, j.nome)
        mvp = {"eq": melhor[1], "nome": melhor[2], "nota": out[melhor[1]][melhor[2]]["nota"]}
        return out, mvp

    # ------------------------------------------------------------------ resultado
    def resultado(self, configs) -> dict:
        total_posse = sum(self.tempo_posse) or 1.0
        estat = []
        for t in (0, 1):
            e = self.est[t]
            estat.append({
                "golos": e["golos"], "posse": round(100.0 * self.tempo_posse[t] / total_posse),
                "remates": e["remates"], "remates_baliza": e["remates_baliza"], "defesas": e["defesas"],
                "passes": e["passes"], "passes_ok": e["passes_ok"],
                "passes_pc": round(100.0 * e["passes_ok"] / e["passes"]) if e["passes"] else 0,
                "desarmes": e["desarmes"], "intercecoes": e["intercecoes"],
                "faltas": e["faltas"], "cantos": e["cantos"], "livres": e["livres"], "cruzamentos": e["cruzamentos"],
                "passes_longos": e["passes_longos"], "dribles": e["dribles"], "dribles_ok": e["dribles_ok"],
                "contra_ataques": e["contra_ataques"], "remates_bloqueados": e["remates_bloqueados"],
                "golos_bola_parada": e["golos_bola_parada"], "golos_contra": e["golos_contra"],
            })
        # a posse soma 100
        estat[1]["posse"] = 100 - estat[0]["posse"]
        marcadores = [[], []]
        for e in self.eventos:
            if e["tipo"] == "golo":
                marcadores[e["eq"]].append({"jogador": e["jog"], "minuto": e["min"], "origem": e["origem"], "assistencia": e.get("jog2")})
        notas, mvp = self.notas()
        equipas = []
        for t, eq in enumerate(self.eq):
            equipas.append({
                "treinador": eq.treinador, "tatica": eq.tatica.id, "esquema": eq.tatica.esquema,
                "estilo": eq.estilo.id, "estilo_nome": eq.estilo.nome,
                "livres": eq.livres.nome, "cantos": eq.cantos.nome,
                "jogadores": [{"slot": j.slot, "nome": j.nome, "posicao": j.posicao_nome, "funcao": j.funcao,
                               "nota": notas[t][j.nome]["nota"], "destaques": notas[t][j.nome]["destaques"],
                               "mvp": (mvp["eq"] == t and mvp["nome"] == j.nome),
                               "funcao_nome": next(f.nome for f in fun.funcoes_da_posicao(eq.tatica, next(p for p in eq.tatica.posicoes if p.id == j.slot)) if f.id == j.funcao)} for j in eq.jog],
            })
        return {
            "semente": self.semente,
            "placar": list(self.golos),
            "equipas": equipas,
            "estatisticas": estat,
            "marcadores": marcadores,
            "mvp": mvp,
            "relato": self.relato(),
            "por_jogador": [{j.nome: dict(j.st) for j in eq.jog} for eq in self.eq],
            "ordem": [[j.eq, j.slot, j.nome] for j in self.ordem],
            "eventos": self.eventos,
        }

    def relato(self) -> list[dict]:
        linhas = []
        nomes = [e.treinador for e in self.eq]
        for e in self.eventos:
            tp, t = e["tipo"], e["eq"]
            texto = None
            if tp == "inicio":
                texto = "Começou o jogo!"
            elif tp == "intervalo":
                texto = f"Intervalo: {self.placar_em(e['t'])[0]}–{self.placar_em(e['t'])[1]}."
            elif tp == "fim":
                texto = f"Fim do jogo: {self.golos[0]}–{self.golos[1]}."
            elif tp == "golo":
                como = {"livre": "num livre direto", "canto": "na sequência de um canto", "contra": "num contra-ataque",
                        "cruzamento": "de cabeça, após um cruzamento", "ressalto": "no ressalto"}.get(e["origem"], "")
                if e["origem"] == "livre" and not e.get("cabeca"):
                    como = "num livre direto"
                ass = f" Assistência de {e['jog2']}." if e.get("jog2") else ""
                texto = f"GOLO! {e['jog']} ({nomes[t]}) marca{(' ' + como) if como else ''}. {e['placar'][0]}–{e['placar'][1]}.{ass}"
            elif tp == "defesa" and e.get("dificil"):
                texto = f"Grande defesa de {e['jog']} a remate de {e['jog2']}."
            elif tp == "livre":
                texto = f"Livre perigoso para a equipa de {nomes[t]}: {e['jog']} vai bater."
            elif tp == "canto":
                texto = f"Canto para a equipa de {nomes[t]}, bate {e['jog']}."
            elif tp == "remate" and e.get("res") == "fora" and e.get("origem") in ("contra", "livre"):
                texto = f"{e['jog']} remata ao lado."
            if texto:
                linhas.append({"min": e["min"], "eq": t, "tipo": tp, "texto": texto})
        return linhas

    def placar_em(self, instante: float):
        g = [0, 0]
        for e in self.eventos:
            if e["tipo"] == "golo" and e["t"] <= instante:
                g[e["eq"]] += 1
        return g




def match_engine_online(config_a: dict, config_b: dict, jogadores, semente: int | None = None) -> dict:
    """Simula um jogo. `config_*`: {"nome", "tatica", "escalacao", "funcoes", "estilo", "livres", "cantos"};
    `jogadores`: o DataFrame do Excel ONLINE (ou um dict nome -> Ficha, de `fichas_de`)."""
    fichas = jogadores if isinstance(jogadores, dict) else fichas_de(jogadores)
    if semente is None:
        semente = random.SystemRandom().getrandbits(48)
    jogo = Jogo([config_a, config_b], fichas, semente)
    jogo.correr()
    return jogo.resultado([config_a, config_b])
