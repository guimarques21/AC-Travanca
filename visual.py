"""
visual.py — o «realizador» da simulação visual (Passo 8)
=========================================================

O motor (`match_engine.py`) simula o jogo por decisões (um passe, um remate, um desarme…) e regista, em cada
evento, onde estava cada jogador. Isso chega para saber *o que* aconteceu, mas não para *ver* o jogo:
entre dois eventos a bola não anda sozinha, um livre ou um canto precisam de gente no sítio, depois de um
golo há festejo e pontapé de saída do meio-campo, etc. Este módulo faz de realizador: lê os eventos e
constrói um «filme» — trajetórias dos jogadores, trajetória da bola (voos, rasteiros, em posse de quem),
animações (remate, defesa, desarme, queda, cabeceamento, festejo), comentários e os «lances principais».

Nada aqui altera o jogo: o resultado, as estatísticas e os eventos são os do motor. O filme só os mostra.

Regras de realismo (o que foi pedido):
  * a bola nunca salta de um sítio para outro: cada peça do filme começa onde a anterior acabou
    (as exceções são o pontapé de baliza, o canto e a saída: a bola velha fica fora, desaparece, e outra
    é reposta no ponto de reposição, como num jogo a sério);
  * quando a bola sai, repõe a outra equipa no sítio por onde saiu: lançamento lateral no ponto da linha,
    canto no canto, pontapé de baliza na pequena área;
  * depois de um golo a bola vai buscar-se à rede e a equipa que sofreu bate a saída do meio-campo;
  * os jogadores correm ao ritmo possível: as chegadas à bola, aos cantos e às barreiras são calculadas
    com a velocidade de um jogador, nunca com saltos.

Coordenadas do filme: campo 60 × 40 m, a equipa de quem vê (equipa 0 do filme) ataca para x = 60.
Se quem vê jogou como equipa B do motor, o campo é espelhado para que se veja sempre a si à esquerda.

Formato do filme (números inteiros para ser pequeno):
  jog    [[equipa, nome, número, posição(0 GR,1 DEF,2 MED,3 AVA)] × 14]   (equipa 0 = quem vê)
  tr     por jogador, [t×100, x×10, y×10, t×100, …] (chaves de movimento; entre elas interpola-se com PCHIP)
  bola   peças [t0×100, t1×100, tipo, refA, refB, ax×10, ay×10, bx×10, by×10, h×10, z0×10, z1×10]
           tipo 0 parada em (a) · 1 conduzida pelo jogador refA · 2 rasteira A→B · 3 «chapéu» A→B com arco h ·
           4 remate A→B · 5 a rolar e a parar A→B · 6 escondida
           refA/refB ≥ 0 → ponto = pé desse jogador nesse instante; −1 → ponto fixo (a, b)
  an     [[t×100, jogador, código, duração×100, a×10, b×10]]
  tx     [[t×100, texto, tipo]]       pl [[t×100, golos0, golos1]]
  lances [[ini×100, fim×100, tipo, equipa, minuto]]       mortos [[ini×100, fim×100]]
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right

W, H = 60.0, 40.0
CY = H / 2
TRAVE = 3.0                      # meia largura da baliza (m)
ALTURA_BALIZA = 2.0
TOTAL = 3000.0
PAUSA_INTERVALO = 14.0           # o intervalo não existe no motor: o filme acrescenta uns segundos para as equipas se recomporem

# códigos de animação
A_CHUTA, A_DESARMA, A_CAI, A_VOA, A_CABECEIA, A_FESTEJA, A_LANCA, A_FALTA, A_DEFENDE, A_LEVANTA = range(1, 11)
# tipos de peça da bola
B_PARADA, B_CONDUZ, B_RASTEIRA, B_CHAPEU, B_REMATE, B_ROLA, B_ESCONDIDA = range(7)

OUTRO_LADO = {"intercecao", "desarme", "falta", "drible", "defesa", "corte"}
V_PASSE = {"curto": 11.0, "prog": 13.0, "rutura": 14.0, "longo": 15.0}
V_REMATE = 23.0


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _lim(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _unit(a, b):
    d = _d(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 1e-6 else (1.0, 0.0)


# --------------------------------------------------------------------------- #
# Trajetórias (PCHIP: sem ressaltos nem «moonwalk» quando o jogador está parado)
# --------------------------------------------------------------------------- #

def _tangente(ts, ps, k):
    n = len(ts)
    if n == 1:
        return 0.0
    if k == 0:
        return (ps[1] - ps[0]) / (ts[1] - ts[0])
    if k == n - 1:
        return (ps[k] - ps[k - 1]) / (ts[k] - ts[k - 1])
    h0, h1 = ts[k] - ts[k - 1], ts[k + 1] - ts[k]
    d0, d1 = (ps[k] - ps[k - 1]) / h0, (ps[k + 1] - ps[k]) / h1
    if d0 * d1 <= 0.0:
        return 0.0
    w1, w2 = 2.0 * h1 + h0, h1 + 2.0 * h0
    return (w1 + w2) / (w1 / d0 + w2 / d1)


def _hermite(h, u, p0, p1, m0, m1):
    u2 = u * u
    u3 = u2 * u
    return (2 * u3 - 3 * u2 + 1) * p0 + (u3 - 2 * u2 + u) * h * m0 + (-2 * u3 + 3 * u2) * p1 + (u3 - u2) * h * m1


class Traj:
    """Chaves (t, x, y) de um jogador; `pos(t)` interpola. As chaves «protegidas» são encontros marcados
    (chegar à bola, ficar parado a bater um livre…) e não são alteradas pelo limitador de velocidade."""

    def __init__(self):
        self.t, self.x, self.y = [], [], []
        self.prot = set()

    def pos(self, t):
        ts = self.t
        if t <= ts[0]:
            return (self.x[0], self.y[0])
        if t >= ts[-1]:
            return (self.x[-1], self.y[-1])
        k = bisect_right(ts, t) - 1
        h = ts[k + 1] - ts[k]
        u = (t - ts[k]) / h
        return (_hermite(h, u, self.x[k], self.x[k + 1], _tangente(ts, self.x, k), _tangente(ts, self.x, k + 1)),
                _hermite(h, u, self.y[k], self.y[k + 1], _tangente(ts, self.y, k), _tangente(ts, self.y, k + 1)))

    def inserir(self, t, p, tol=0.06, prot=False):
        """Põe uma chave em `t` (se já há uma a menos de `tol`, substitui-a)."""
        p = (min(59.8, max(0.2, p[0])), min(39.8, max(0.2, p[1])))
        ts = self.t
        k = bisect_right(ts, t)
        for j in (k - 1, k):
            if 0 <= j < len(ts) and abs(ts[j] - t) < tol:
                self.prot.discard(round(ts[j] * 100))
                if j not in (0, len(ts) - 1):
                    self.t[j] = t
                self.x[j], self.y[j] = p[0], p[1]
                if prot:
                    self.prot.add(round(self.t[j] * 100))
                return
        self.t.insert(k, t)
        self.x.insert(k, p[0])
        self.y.insert(k, p[1])
        if prot:
            self.prot.add(round(t * 100))

    def limpar(self, a, b):
        """Tira as chaves com a < t <= b."""
        i = bisect_right(self.t, a)
        j = bisect_right(self.t, b)
        if j > i:
            for k in range(i, j):
                self.prot.discard(round(self.t[k] * 100))
            del self.t[i:j], self.x[i:j], self.y[i:j]

    def limitar(self, t_from, vmax):
        """A partir de `t_from`, nenhuma chave não protegida exige mais do que `vmax` m/s em relação à anterior:
        quem tem de voltar de longe chega mais tarde (como um jogador a sério) em vez de «teletransportar-se»."""
        ts = self.t
        k0 = max(1, bisect_right(ts, t_from))
        for k in range(k0, len(ts)):
            if round(ts[k] * 100) in self.prot:
                continue
            dt = ts[k] - ts[k - 1]
            dx, dy = self.x[k] - self.x[k - 1], self.y[k] - self.y[k - 1]
            d = math.hypot(dx, dy)
            lim = vmax * dt
            if d > lim:
                s = lim / d
                self.x[k], self.y[k] = self.x[k - 1] + dx * s, self.y[k - 1] + dy * s


    def limitar_tudo(self, vmax):
        """Última rede de segurança: mesmo as chaves protegidas não podem exigir mais do que `vmax` m/s em relação à
        anterior (casos raros em que o motor «teletransporta» alguém, por exemplo um marcador de canto)."""
        ts = self.t
        for k in range(1, len(ts)):
            dt = ts[k] - ts[k - 1]
            dx, dy = self.x[k] - self.x[k - 1], self.y[k] - self.y[k - 1]
            d = math.hypot(dx, dy)
            lim = vmax * dt
            if d > lim:
                s = lim / d
                self.x[k], self.y[k] = self.x[k - 1] + dx * s, self.y[k - 1] + dy * s


# --------------------------------------------------------------------------- #
# O realizador
# --------------------------------------------------------------------------- #

class Realizador:
    def __init__(self, res: dict, ordem: list, eventos: list, lugar: int):
        self.res = res
        self.swap = (lugar == 1)
        self.ysw = -1.0 if self.swap else 1.0           # as escolhas ao acaso em y são feitas no campo «real»: os dois lados veem o mesmo jogo
        self.ev = []
        passou = False
        for e0 in eventos:
            e = dict(e0)
            if passou:
                e["t"] = round(e["t"] + PAUSA_INTERVALO, 1)
                if "tq" in e:
                    e["tq"] = round(e["tq"] + PAUSA_INTERVALO, 1)
            if e["tipo"] == "intervalo":
                passou = True
            self.ev.append(e)
        self.total = TOTAL + (PAUSA_INTERVALO if passou else 0.0)
        self.rnd = random.Random((res.get("semente") or 1) ^ 0x5EED)
        self.dbg = {"corr": 0, "meet_rapido": 0, "sem_fora": 0}
        self.idx = {}
        self.jog = [None] * 14
        self.mi = [0] * 14                    # filme -> índice do motor
        nums = self._numeros(res)
        for i, (t, slot, nome) in enumerate(ordem):
            ft = self._ft(t)
            f = ft * 7 + (i % 7)
            self.idx[(ft, nome)] = f
            self.mi[f] = i
            self.jog[f] = [ft, nome, nums.get((t, nome), 0), self._papel(res, t, nome)]
        self.nomes = [res["equipas"][self._ft(0)]["treinador"], res["equipas"][self._ft(1)]["treinador"]]
        self.tr = [Traj() for _ in range(14)]
        self.pecas = []
        self.anims = []
        self.textos = []
        self.placar = [[0.0, 0, 0]]
        self.mortos = []
        self.marcos = []
        self.est = ("pt", (W / 2, CY))
        self.bt = 0.0
        self.fora = None                      # (t, ponto, tipo) se a bola está fora de jogo à espera de reposição
        self.reinicio = None                  # ("lateral"|"livre"|…, jogador) para o próximo passe
        self.cab = None                       # (t, jogador) cabeceamento que é um remate
        self.reb = None                       # (jogador, ponto, t) ressalto à espera do segundo remate
        self.livre_ctx = None
        self.golos = [0, 0]
        self.t_intervalo = None
        self.t_ultimo_festejo = None
        self._construir()

    # ---- coordenadas e equipas
    def _ft(self, t):
        return t ^ 1 if self.swap else t

    def F(self, p):
        return (W - p[0], H - p[1]) if self.swap else (p[0], p[1])

    def x_golo(self, ft):
        """x da baliza que a equipa `ft` ataca."""
        return W if ft == 0 else 0.0

    def x_proprio(self, ft):
        return 0.0 if ft == 0 else W

    def ux(self, ft, u):
        """x a `u` metros da linha de fundo da própria baliza de `ft` (u cresce para o ataque)."""
        return u if ft == 0 else W - u

    def sinal(self, ft):
        """+1 se `ft` ataca para x crescente."""
        return 1.0 if ft == 0 else -1.0

    @staticmethod
    def _papel(res, t, nome):
        for j in res["equipas"][t]["jogadores"]:
            if j["nome"] == nome:
                p = j["posicao"]
                return 0 if p.startswith("Guarda") else 1 if p.startswith("Defesa") else 3 if p.startswith("Avan") else 2
        return 2

    @staticmethod
    def _numeros(res):
        out = {}
        lista = {0: [1], 1: [2, 3, 4, 5], 2: [6, 8, 10, 11], 3: [7, 9, 11, 17]}
        for t in (0, 1):
            usados = {0: 0, 1: 0, 2: 0, 3: 0}
            for j in res["equipas"][t]["jogadores"]:
                p = Realizador._papel(res, t, j["nome"])
                out[(t, j["nome"])] = lista[p][usados[p] % len(lista[p])]
                usados[p] += 1
        return out

    def J(self, e, campo):
        nome = e.get(campo)
        if nome is None:
            return None
        t = e["eq"]
        if campo == "jog2" and e["tipo"] in OUTRO_LADO:
            t = 1 - t
        return self.idx[(self._ft(t), nome)]

    def eq_de(self, e):
        """Equipa do filme a que pertence o evento."""
        return self._ft(e["eq"]) if e["eq"] is not None else None

    # ------------------------------------------------------------------ construção
    def _construir(self):
        ev = self.ev
        n = len(ev)
        self.passos = []
        self.passo_de = [0] * n
        for i, e in enumerate(ev):
            if "q" not in e:
                self.passo_de[i] = max(0, len(self.passos) - 1)
                continue
            if self.passos and abs(self.passos[-1]["ts"] - e["tq"]) < 0.05:
                self.passos[-1]["ev"].append(i)
            else:
                q = [self.F(p) for p in e["q"]]
                ts = float(e["tq"])
                if self.passos and ts <= self.passos[-1]["ts"] + 0.05:
                    ts = self.passos[-1]["ts"] + 0.06
                self.passos.append({"ts": ts, "q": q, "ev": [i], "feito": False})
            self.passo_de[i] = len(self.passos) - 1
        for p in self.passos:
            for f in range(14):
                tr = self.tr[f]
                tr.t.append(p["ts"])
                tr.x.append(p["q"][self.mi[f]][0])
                tr.y.append(p["q"][self.mi[f]][1])
        for f in range(14):
            tr = self.tr[f]
            if tr.t[0] > 0.0:
                tr.t.insert(0, 0.0), tr.x.insert(0, tr.x[0]), tr.y.insert(0, tr.y[0])
            if tr.t[-1] < self.total:
                tr.t.append(self.total), tr.x.append(tr.x[-1]), tr.y.append(tr.y[-1])
        for p in self.passos:
            p["holder"] = self._portador_do_passo(p)
        self.i = 0
        while self.i < n:
            i = self.i
            self.i += 1
            self._tratar(i)
        self._fechar(self.total)
        for tr in self.tr:
            tr.limitar_tudo(self.VMAX + 3.0)
        self._lances()

    def _portador_do_passo(self, p):
        for i in p["ev"]:
            e = self.ev[i]
            tp = e["tipo"]
            if tp in ("passe", "drible", "remate", "alivio", "cruzamento", "saida", "golo"):
                return self.J(e, "jog")
            if tp in ("desarme", "falta", "intercecao", "defesa"):
                return self.J(e, "jog2")
        return None

    # ------------------------------------------------------------------ tempos
    def pos(self, f, t):
        return self.tr[f].pos(t)

    def ts(self, i):
        return self.passos[self.passo_de[i]]["ts"]

    def tn(self, i):
        k = self.passo_de[i]
        return self.passos[k + 1]["ts"] if k + 1 < len(self.passos) else self.total

    def holder_seguinte(self, i):
        """Quem tem a bola quando começa o passo seguinte ao de `i` (None se não se sabe)."""
        k = self.passo_de[i] + 1
        while k < len(self.passos):
            h = self.passos[k]["holder"]
            if h is not None:
                return h
            if any(self.ev[j]["tipo"] in ("intervalo", "fim") for j in self.passos[k]["ev"]):
                return None
            k += 1
        return None

    def ponto_bola(self, t):
        if self.est[0] == "j":
            return self.pos(self.est[1], t)
        if self.est[0] == "pt":
            return self.est[1]
        return (W / 2, CY)

    # ------------------------------------------------------------------ bola
    def _peca(self, t0, t1, tipo, ra=-1, rb=-1, a=(0.0, 0.0), b=(0.0, 0.0), h=0.0, z0=0.0, z1=0.0):
        self.pecas.append([t0, max(t0, t1), tipo, ra, rb, a[0], a[1], b[0], b[1], h, z0, z1])

    def _fechar(self, t):
        """Mantém a bola onde está (parada, conduzida ou escondida) até `t`."""
        if t <= self.bt + 1e-6:
            return
        k = self.est[0]
        if k == "j":
            self._peca(self.bt, t, B_CONDUZ, ra=self.est[1])
        elif k == "pt":
            self._peca(self.bt, t, B_PARADA, a=self.est[1])
        else:
            self._peca(self.bt, t, B_ESCONDIDA)
        self.bt = t

    def _mov(self, tipo, destino, t_chega, dur, h=0.0, z0=0.0, z1=0.0, t_sai=None):
        """A bola sai de onde está e chega a `destino` ('j', f) / ('pt', (x, y)) em `t_chega`."""
        dur = max(0.14, dur)
        t_sai = (t_chega - dur) if t_sai is None else t_sai
        t_sai = max(t_sai, self.bt)
        if t_chega < t_sai + 0.14:
            t_chega = t_sai + 0.14
        self._fechar(t_sai)
        if self.est[0] == "j":
            ra, a = self.est[1], (0.0, 0.0)
        elif self.est[0] == "pt":
            ra, a = -1, self.est[1]
        else:
            ra, a = -1, (W / 2, CY)
        rb, b = (destino[1], (0.0, 0.0)) if destino[0] == "j" else (-1, destino[1])
        self._peca(t_sai, t_chega, tipo, ra, rb, a, b, h, z0, z1)
        self.bt = t_chega
        self.est = destino
        return t_sai, t_chega

    def _aparece(self, t, destino):
        """Reposição: a bola velha desapareceu; escondida até `t`, depois em `destino`."""
        if self.est[0] != "esc":
            self.est = ("esc",)
        self._fechar(t)
        self.est = destino

    def _esconde(self, t):
        self._fechar(t)
        self.est = ("esc",)

    # ------------------------------------------------------------------ jogadores
    VMAX = 6.5

    def _fixar(self, f, t_a, t_b, p):
        """O jogador `f` fica parado em `p` entre `t_a` e `t_b`."""
        if t_b <= t_a + 0.05:
            return
        tr = self.tr[f]
        tr.limpar(t_a, t_b + 0.05)
        tr.inserir(t_a, p, prot=True)
        tr.inserir(t_b, p, prot=True)
        tr.limitar(t_b, self.VMAX)

    def _chega(self, f, t, ponto, t_ini):
        """O jogador `f` está em `ponto` no instante `t` (parte da sua posição em `t_ini`)."""
        tr = self.tr[f]
        t_ini = min(t_ini, t - 0.2)
        p0 = tr.pos(t_ini)
        tr.limpar(t_ini, t + 0.4)
        tr.inserir(t_ini, p0)
        tr.inserir(t, ponto, prot=True)
        if _d(p0, ponto) / max(0.3, t - t_ini) > 9.5:
            self.dbg["meet_rapido"] += 1
        tr.limitar(t, self.VMAX)

    def _estagiar(self, f, t_a, pontos, t_limpa=None):
        """A partir de `t_a`, o jogador `f` passa por `pontos` [(t, (x, y)), …]."""
        tr = self.tr[f]
        p0 = tr.pos(t_a)
        tr.limpar(t_a, max(t_limpa if t_limpa is not None else 0.0, pontos[-1][0]) + 0.05)
        tr.inserir(t_a, p0)
        for t, p in pontos:
            tr.inserir(t, (_lim(p[0], 0.5, W - 0.5), _lim(p[1], 0.5, H - 0.5)), prot=True)
        tr.limitar(pontos[-1][0], self.VMAX)

    def _anim(self, t, f, cod, dur=0.5, a=0.0, b=0.0):
        self.anims.append([t, f, cod, dur, a, b])

    def _texto(self, t, s, tipo=0):
        self.textos.append([t, s, tipo])

    def _marco(self, t_rel, t_res, tipo, ft, minuto, imp, t_ini=None):
        self.marcos.append({"rel": t_rel, "res": t_res, "tipo": tipo, "ft": ft, "min": minuto, "imp": imp, "ini": t_ini})

    # ------------------------------------------------------------------ olhar para a frente
    def _depois(self, i):
        """O que se segue (no mesmo passo) a um lance que pode pôr a bola fora: ('lateral'|'baliza'|'canto', índice, índice2)."""
        k = self.passo_de[i]
        for j in range(i + 1, min(i + 4, len(self.ev))):
            if self.passo_de[j] != k:
                break
            tp = self.ev[j]["tipo"]
            if tp == "lateral":
                return ("lateral", j, None)
            if tp == "pontape_de_baliza":
                return ("baliza", j, None)
            if tp == "canto_conquistado":
                for m in range(j + 1, min(j + 3, len(self.ev))):
                    if self.ev[m]["tipo"] == "canto":
                        return ("canto", m, j)
                return None
            if tp in ("passe", "remate", "cruzamento", "drible", "alivio", "golo", "defesa"):
                break
        return None

    def _ponto_fora(self, dep, dica=None):
        tp, j, _ = dep
        e = self.ev[j]
        if tp == "lateral":
            return self.F(e["de"])
        ft = self._ft(e["eq"])
        if tp == "baliza":
            if "saiu" in e:
                return self.F(e["saiu"])
            y = dica[1] if dica else CY + self.ysw * self.rnd.uniform(-9, 9)
            return (self.x_proprio(ft), _lim(y, 1.5, H - 1.5))
        canto = self.F(e["de"])                          # canto: a bola sai junto à linha de fundo, do lado do canto
        lado0 = canto[1] < CY
        y = self.rnd.uniform(4.0, 9.0) if lado0 else H - self.rnd.uniform(4.0, 9.0)
        return (self.x_golo(ft), y)

    @staticmethod
    def _para_la_da_linha(p):
        x, y = p
        if y <= 0.01 or y >= H - 0.01:
            return (x, -0.6 if y <= 0.01 else H + 0.6)
        if x <= 0.01 or x >= W - 0.01:
            return (-0.9 if x <= 0.01 else W + 0.9, y)
        return p

    def _sair(self, dep, t_sai, t_max, tipo=B_RASTEIRA, h=0.0, dica=None, vel=11.0, z0=0.0):
        """A bola sai do campo pelo ponto certo e fica parada fora (`self.fora`)."""
        ponto = self._ponto_fora(dep, dica)
        t_sai = max(t_sai, self.bt)
        origem = self.ponto_bola(t_sai)
        d = _d(origem, ponto)
        dur = max(0.5, d / vel)
        t_chega = max(min(t_sai + dur, max(t_max, t_sai + 0.5)), t_sai + d / (vel * 1.7))
        fora = self._para_la_da_linha(ponto)
        self._mov(tipo, ("pt", fora), t_chega, t_chega - t_sai, h=h, z0=z0, t_sai=t_sai)
        self.fora = (t_chega, fora, dep[0])
        return t_chega

    def _garantir(self, i):
        """No começo de cada passo, o portador do motor tem a bola. Se não for assim, corrige (e conta)."""
        p = self.passos[self.passo_de[i]]
        if p["feito"]:
            return
        p["feito"] = True
        h = p["holder"]
        if h is None or self.est == ("j", h) or any(self.ev[j]["tipo"] == "saida" for j in p["ev"]):
            return
        ts = p["ts"]
        pos_h = self.pos(h, ts)
        if self.est[0] == "pt" and _d(self.est[1], pos_h) < 3.5:                  # reposição: o jogador chega e pega na bola
            self._fechar(max(self.bt, ts - 0.35))
            self.est = ("j", h)
            self.fora = None
            return
        if self.est[0] == "esc":
            self._aparece(max(self.bt, ts - 0.05), ("j", h))
            return
        self.dbg["corr"] += 1
        self._mov(B_ROLA, ("j", h), ts + 0.3, 0.5)

    # ------------------------------------------------------------------ despacho
    def _interrompido(self, i):
        """A reposição de `i` nunca chega a acontecer porque o intervalo ou o fim do jogo vêm antes."""
        k = self.passo_de[i]
        return any(self.ev[j]["tipo"] in ("intervalo", "fim") and self.passo_de[j] == k for j in range(i + 1, min(i + 6, len(self.ev))))

    def _tratar(self, i):
        e = self.ev[i]
        if "q" in e:
            self._garantir(i)
        if e["tipo"] in ("lateral", "pontape_de_baliza", "canto", "livre") and self._interrompido(i):
            return
        fn = getattr(self, "_ev_" + e["tipo"], None)
        if fn:
            fn(i, e)

    def _consumir(self, j):
        """Marca o evento `j` como tratado (se estiver à frente do cursor)."""
        if j >= self.i:
            self.i = j + 1

    # ---- arranque, intervalo, fim
    def _ev_inicio(self, i, e):
        self._texto(0.0, "Começa o jogo!", 2)

    def _ev_intervalo(self, i, e):
        self.t_intervalo = e["t"]
        self._texto(e["t"], "Intervalo", 2)
        self._esconde(max(self.bt, e["t"]))
        self.mortos.append([e["t"] + 1.0, e["t"] + PAUSA_INTERVALO])

    def _ev_fim(self, i, e):
        self._texto(self.total, "Fim do jogo!", 2)

    def _ev_saida(self, i, e):
        """Pontapé de saída: bola no ponto central, adversários fora do círculo, cada equipa na sua metade."""
        ts = self.ts(i)
        ft = self.eq_de(e)
        tk = self.J(e, "jog")
        centro = (W / 2, CY)
        tn = self.tn(i)
        self._legalizar_saida(ft, tk, ts, tn)
        if self.est[0] != "esc":
            self._esconde(max(self.bt, ts - 0.02))
        self._aparece(max(ts, self.bt), ("j", tk))
        self.fora = None
        if self.placar[-1][0] > 0 and ts - self.t_ultimo_festejo > 1:
            self.mortos.append([max(0.0, self.t_ultimo_festejo), ts])

    def _legalizar_saida(self, ft_bate, tk, ts, tn):
        centro = (W / 2, CY)
        lim = W / 2 - 0.7
        for f in range(14):
            ft = f // 7
            tr = self.tr[f]
            for tt in (ts, tn):
                tr.inserir(tt, tr.pos(tt))
            for k in range(len(tr.t)):
                if abs(tr.t[k] - ts) < 0.07 or abs(tr.t[k] - tn) < 0.07:
                    x, y = tr.x[k], tr.y[k]
                    if f == tk:
                        x, y = centro[0] - self.sinal(ft) * 0.5, centro[1]
                    else:
                        x = min(x, lim) if ft == 0 else max(x, W - lim)
                        if ft != ft_bate:
                            dx, dy = x - centro[0], y - centro[1]
                            r = math.hypot(dx, dy)
                            if r < 5.6:
                                if r < 0.05:
                                    dx, dy, r = -self.sinal(ft), 0.0, 1.0
                                x, y = centro[0] + dx / r * 5.9, centro[1] + dy / r * 5.9
                                x = min(x, lim) if ft == 0 else max(x, W - lim)
                    tr.x[k], tr.y[k] = x, y
                    tr.prot.add(round(tr.t[k] * 100))
            tr.limitar(tn, self.VMAX)

    # ---- passes
    def _dur_passe(self, d, tipo, v=None):
        v = v or V_PASSE.get(tipo, 12.0)
        return max(0.30, d / v)

    def _lancar(self, C, destino, ts, tn, de, para, tipo, res, lanc=False):
        """Passe de `C` (que o segura desde `ts`) para `destino`; devolve (t_sai, t_chega)."""
        d = _d(de, para)
        v = 9.5 if lanc else V_PASSE.get(tipo, 12.0)
        dur = max(0.30, d / v)
        k = B_CHAPEU if (tipo == "longo" or lanc) else B_RASTEIRA
        h = 1.6 if lanc else (_lim(0.9 + 0.11 * d, 2.0, 5.5) if tipo == "longo" else 0.0)
        if destino[0] == "j":                                     # a distância que conta é a do filme
            d = _d(self.pos(C, ts), self.pos(destino[1], tn - 0.3))
            dur = max(0.30, d / v)
        dur = max(dur, d / 24.0)
        t_alvo = tn - 0.30
        t_sai = _lim(t_alvo - dur, ts + 0.12, ts + 2.4)
        t_ch = t_sai + dur
        if t_ch > tn - 0.05:
            t_ch = tn - 0.05
            t_sai = min(t_sai, t_ch - 0.25)
            if (t_ch - t_sai) < d / 24.0 and t_ch + 0.4 < self.total:
                t_ch = t_sai + d / 24.0                           # chega um pouco depois do começo do passo seguinte
            elif (t_ch - t_sai) < d / 24.0:
                return ts, ts                                     # fim do jogo: já não há tempo para este passe
        t_sai = max(t_sai, self.bt, ts + 0.05)
        self._fixar(C, ts, t_sai, self.pos(C, ts))
        self._mov(k, destino, t_ch, t_ch - t_sai, h=h, z0=0.0, z1=0.0, t_sai=t_sai)
        self._anim(t_sai - 0.2, C, A_LANCA if lanc else A_CHUTA, 0.45)
        return t_sai, t_ch

    def _ev_passe(self, i, e):
        C = self.J(e, "jog")
        m = self.J(e, "jog2")
        ts, tn = self.ts(i), self.tn(i)
        res, tipo = e["res"], e.get("tipo_passe", "curto")
        de, para = self.F(e["de"]), self.F(e["para"])
        lanc = bool(self.reinicio and self.reinicio[0] == "lateral" and self.reinicio[1] == C)
        self.reinicio = None
        if res == "ok":
            perde = i + 1 < len(self.ev) and self.ev[i + 1]["tipo"] == "bola_perdida" and self.passo_de[i + 1] == self.passo_de[i]
            adv = self.holder_seguinte(i) if perde else None
            tn_eff = tn - 0.9 if perde else tn
            self._lancar(C, ("j", m), ts, tn_eff, de, para, tipo, res, lanc)
            if perde and adv is not None:                             # o recetor perde a bola: o adversário apanha-a
                self._consumir(i + 1)
                self._mov(B_ROLA, ("j", adv), tn - 0.12, 0.6)
                self._texto(self.bt - 0.5, f"{self.jog[m][1]} perde a bola", 0)
            return
        if res == "falhado" or res == "disputado":
            dep = self._depois(i)
            if dep:
                t_e = self.ev[dep[1]]["t"]
                d = _d(de, para)
                v = V_PASSE.get(tipo, 12.0)
                t_sai = _lim(t_e - 0.3 - max(0.5, d / v), ts + 0.12, ts + 2.4)
                self._fixar(C, ts, t_sai, self.pos(C, ts))
                self._sair(dep, t_sai, t_e - 0.1, B_CHAPEU if tipo == "longo" else B_RASTEIRA,
                           h=_lim(0.9 + 0.11 * d, 2.0, 5.5) if tipo == "longo" else 0.0, dica=para, vel=v)
                self._anim(t_sai - 0.2, C, A_CHUTA, 0.45)
                return
            X = self.holder_seguinte(i)
            if X is None:
                X = m
            t_alvo = tn - (0.45 if res == "disputado" else 0.25)
            d = _d(de, para)
            v = V_PASSE.get(tipo, 12.0)
            dur = max(0.3, d / v)
            t_sai = _lim(t_alvo - dur, ts + 0.12, ts + 2.4)
            t_ch = max(t_sai + dur, t_sai + 0.3)
            if t_ch > tn - 0.05:
                t_ch = tn - 0.05
                t_sai = min(t_sai, t_ch - 0.25)
            if X != m:
                self._chega(X, t_ch, para, ts)
            self._fixar(C, ts, t_sai, self.pos(C, ts))
            self._mov(B_CHAPEU if tipo == "longo" else B_RASTEIRA, ("j", X), t_ch, t_ch - t_sai,
                      h=_lim(0.9 + 0.11 * d, 2.0, 5.5) if tipo == "longo" else 0.0, t_sai=t_sai)
            self._anim(t_sai - 0.2, C, A_CHUTA, 0.45)
            if res == "disputado":
                self._anim(t_ch - 0.35, X, A_CABECEIA, 0.7)
                if X != m:
                    self._anim(t_ch - 0.35, m, A_CABECEIA, 0.7)
            return
        # intercetado: tratado a partir do evento `intercecao` (que vem antes) — se chegou aqui, ignora
        return

    def _ev_intercecao(self, i, e):
        """A interceção vem sempre antes do passe que a sofre: trata os dois."""
        if not (i + 1 < len(self.ev) and self.ev[i + 1]["tipo"] == "passe" and self.ev[i + 1].get("res") == "intercetado"):
            return
        D = self.J(e, "jog")
        C = self.J(e, "jog2")
        ts, tn = self.ts(i), self.tn(i)
        de, P = self.F(e["de"]), self.F(e["para"])
        tipo = e.get("tipo_passe", "curto")
        self._consumir(i + 1)
        d = _d(de, P)
        dur = max(0.30, d / V_PASSE.get(tipo, 12.0))
        t_sai = _lim(ts + 0.5, ts + 0.12, tn - dur - 0.25)
        t_sai = max(t_sai, self.bt, ts + 0.05)
        t_ch = min(t_sai + dur, tn - 0.05)
        self._chega(D, t_ch, P, ts)
        self._fixar(C, ts, t_sai, self.pos(C, ts))
        self._mov(B_CHAPEU if tipo == "longo" else B_RASTEIRA, ("j", D), t_ch, t_ch - t_sai, t_sai=t_sai,
                  h=_lim(0.9 + 0.11 * d, 2.0, 5.5) if tipo == "longo" else 0.0)
        self._anim(t_sai - 0.2, C, A_CHUTA, 0.45)
        self._anim(t_ch - 0.3, D, A_DEFENDE, 0.5)

    def _ev_bola_perdida(self, i, e):
        pass                                                    # tratada em _ev_passe

    # ---- alívio
    def _ev_alivio(self, i, e):
        C = self.J(e, "jog")
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        res = e["res"]
        de, para = self.F(e["de"]), self.F(e["para"])
        d = _d(de, para)
        h = _lim(2.5 + 0.1 * d, 3.0, 7.0)
        t_e = max(t_e, ts + 1.0)
        if res == "fora":
            dep = self._depois(i)
            if dep:
                dur = max(0.8, d / 16.0)
                t_sai = max(ts + 0.3, t_e - dur)
                self._fixar(C, ts, t_sai, self.pos(C, ts))
                self._sair(dep, t_sai, max(t_e, t_sai + 0.8), B_CHAPEU, h=h, dica=para, vel=16.0)
                self._anim(t_sai - 0.2, C, A_CHUTA, 0.5)
            return
        X = self.J(e, "jog2") if res == "ok" else self.holder_seguinte(i)
        if X is None:
            return
        dur = max(0.8, d / 16.0)
        t_ch = min(max(t_e, ts + dur + 0.3), tn - 0.05)
        t_sai = max(ts + 0.2, t_ch - dur)
        if res != "ok":
            self._chega(X, t_ch, para, ts)
        self._fixar(C, ts, t_sai, self.pos(C, ts))
        self._mov(B_CHAPEU, ("j", X), t_ch, t_ch - t_sai, h=h, t_sai=t_sai)
        self._anim(t_sai - 0.2, C, A_CHUTA, 0.5)

    # ---- drible, desarme, falta
    def _ev_drible(self, i, e):
        C = self.J(e, "jog")
        D = self.J(e, "jog2")
        ts, t_e = self.ts(i), e["t"]
        res = e["res"]
        if res == "ok":
            self._anim(t_e - 1.2, D, A_DEFENDE, 0.6)
            self._texto(t_e - 0.8, f"{self.jog[C][1]} passa por {self.jog[D][1]}", 0)
            return
        if res == "perdido":
            return                                              # o `desarme` seguinte trata da bola
        if res == "falta":
            self._falta_com(i, D, C, t_e)

    def _ev_desarme(self, i, e):
        D = self.J(e, "jog")
        C = self.J(e, "jog2")
        ts, tn = self.ts(i), self.tn(i)
        k = self.passo_de[i]
        em_drible = i > 0 and self.ev[i - 1]["tipo"] == "drible" and self.passo_de[i - 1] == k
        if em_drible:
            t_tk = max(self.ev[i - 1]["t"], ts + 1.0)
        else:
            d1 = _d(self.pos(D, ts), self.pos(C, ts))
            t_tk = ts + max(0.5, d1 / 6.0)
        t_tk = min(t_tk, tn - 0.45)
        t_tk = max(t_tk, ts + 0.25)
        self._fixar(C, ts, t_tk - 0.05, self.pos(C, ts))
        pc = self.pos(C, t_tk)
        self._chega(D, t_tk, (pc[0] - 0.25 * self.sinal(self.jog[D][0]), pc[1]), ts)
        self._mov(B_ROLA, ("j", D), min(t_tk + 0.30, tn - 0.02), 0.35, t_sai=t_tk - 0.02)
        self._anim(t_tk - 0.25, D, A_DESARMA, 0.6)
        self._anim(t_tk, C, A_CAI if self.rnd.random() < 0.35 else A_DEFENDE, 0.7 if True else 0.4)
        self._texto(t_tk, f"Desarme de {self.jog[D][1]}", 0)

    def _ev_falta(self, i, e):
        autor = self.J(e, "jog")
        vit = self.J(e, "jog2")
        if i > 0 and self.ev[i - 1]["tipo"] == "drible" and self.passo_de[i - 1] == self.passo_de[i]:
            return                                              # já tratada a partir do drible
        self._falta_com(i, autor, vit, self.ts(i) + 0.6)

    def _falta_com(self, i, autor, vit, t_e):
        """`autor` comete falta sobre `vit` (que tem a bola). A bola pára onde ele estava; depois repõe-se."""
        ts, tn = self.ts(i), self.tn(i)
        local = self.F(self.ev[i]["de"]) if self.ev[i]["tipo"] == "falta" else self.pos(vit, ts)
        t_f = _lim(max(t_e, ts + _d(self.pos(autor, ts), local) / 6.0), ts + 0.4, tn - 0.5)
        self._chega(autor, t_f, (local[0] - 0.3 * self.sinal(self.jog[autor][0]), local[1] + 0.2), ts)
        self._mov(B_ROLA, ("pt", (local[0] + 0.0, local[1] + 0.0)), min(t_f + 0.9, tn - 0.05), 0.9, t_sai=t_f)
        self.fora = None
        self._anim(t_f - 0.25, autor, A_FALTA, 0.6)
        self._anim(t_f, vit, A_CAI, 1.8)
        self._anim(t_f + 2.2, vit, A_LEVANTA, 0.8)
        self._texto(t_f, f"Falta de {self.jog[autor][1]} sobre {self.jog[vit][1]}", 0)
        # reposição rápida: os adversários afastam-se (3 m) quando o livre vai ser batido
        j = i + 1
        livre = j < len(self.ev) and self.ev[j]["tipo"] == "livre" and self.passo_de[j] == self.passo_de[i]
        if not livre:
            self._afastar(self.jog[autor][0], local, 3.2, [tn], excluir=(autor,))
            self.reinicio = ("livre_curto", vit)

    def _afastar(self, ft_ficam_fora, ponto, r, instantes, excluir=()):
        """Os jogadores da equipa `ft_ficam_fora` afastam-se do `ponto` pelo menos `r` metros nos `instantes`."""
        for f in range(14):
            if f // 7 != ft_ficam_fora or f in excluir:
                continue
            tr = self.tr[f]
            for tt in instantes:
                p = tr.pos(tt)
                dd = _d(p, ponto)
                if dd < r:
                    ux, uy = _unit(ponto, p) if dd > 0.05 else (self.sinal(self.jog[f][0]), 0.0)
                    tr.inserir(tt, (_lim(ponto[0] + ux * (r + 0.2), 0.5, W - 0.5), _lim(ponto[1] + uy * (r + 0.2), 0.5, H - 0.5)))

    # ---- bolas paradas: lançamento lateral, pontapé de baliza
    def _ev_lateral(self, i, e):
        taker = self.J(e, "jog")
        ft = self.eq_de(e)
        L = self.F(e["de"])
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        if self.fora is None:                                     # a bola ainda não tinha saído (não devia acontecer)
            self.dbg["sem_fora"] += 1
            self._mov(B_ROLA, ("pt", self._para_la_da_linha(L)), max(t_e, self.bt + 0.4), 0.8)
            self.fora = (self.bt, self._para_la_da_linha(L), "lateral")
        t_fora = self.fora[0]
        t_pega = max(tn - 0.9, t_fora + 0.5)
        pt_fora = self.fora[1]
        self._chega(taker, t_pega - 0.15, (L[0], L[1] + (0.35 if L[1] < CY else -0.35)), max(ts, t_fora - 1.5))
        self._fechar(t_pega)
        self._mov(B_ROLA, ("j", taker), t_pega + 0.35, 0.35, t_sai=t_pega)
        self._afastar(1 - ft, L, 3.2, [tn - 1.2, tn])
        self.reinicio = ("lateral", taker)
        self.fora = None
        self.mortos.append([t_fora + 0.8, t_pega - 0.5])
        self._texto(t_fora, "Lançamento lateral", 0)

    def _ev_pontape_de_baliza(self, i, e):
        gr = self.J(e, "jog")
        ft = self.eq_de(e)
        spot = self.F(e["de"])
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        if self.fora is None:
            self.dbg["sem_fora"] += 1
            dep = ("baliza", i, None)
            self._sair(dep, max(self.bt, t_e - 0.8), t_e, B_ROLA)
        t_fora = self.fora[0]
        # a bola velha desaparece atrás da linha, o guarda-redes repõe outra na pequena área
        t_esc = max(t_fora + 1.0, self.bt)
        self._esconde(t_esc)
        t_pega = max(tn - 0.6, t_esc + 0.3)
        self._chega(gr, t_pega - 0.2, (spot[0] - self.sinal(ft) * 0.5, spot[1]), max(ts, t_fora - 1.0))
        self._aparece(t_pega, ("j", gr))
        self.fora = None
        self.mortos.append([t_esc, t_pega - 0.5])
        self._texto(t_fora, "Pontapé de baliza", 0)

    # ---- cantos e livres
    def _spots_area(self, ft_atq):
        s = self.sinal(ft_atq)
        xa = lambda u: self.ux(ft_atq, u)
        atq = [(xa(54.0), CY), (xa(52.4), CY - 3.0), (xa(52.0), CY + 2.8), (xa(49.5), CY + 0.5)]
        return atq

    def _area_players(self, ft_atq, area):
        """(atacantes, defensores) como índices de filme, a partir dos nomes que o motor registou."""
        A = [self.idx[(ft_atq, n)] for n in area[0]]
        D = [self.idx[(1 - ft_atq, n)] for n in area[1]]
        return A, D

    def _estagiar_area(self, ft_atq, area, alvo, marc, t_a, t_pronto, t_fim):
        """Põe atacantes e defensores nos sítios da área (o alvo do cruzamento no ponto de queda)."""
        A, D = self._area_players(ft_atq, area)
        if alvo is not None and alvo not in A:
            A = [alvo] + A[:-1] if A else [alvo]
        if alvo is not None:
            A = [alvo] + [a for a in A if a != alvo]
        spots = self._spots_area(ft_atq)
        s = self.sinal(ft_atq)
        pos_a = {}
        for k, a in enumerate(A):
            pos_a[a] = spots[k % len(spots)]
        if marc is not None and marc not in D:
            D = [marc] + D[:-1] if D else [marc]
        if marc is not None:
            D = [marc] + [d for d in D if d != marc]
        pos_d = {}
        for k, d in enumerate(D):
            if k < len(A):
                sx, sy = pos_a[A[k]]
                pos_d[d] = (sx + s * 0.95, sy + (0.5 if sy >= CY else -0.5))
            else:
                pos_d[d] = (self.ux(ft_atq, 56.0), CY + (3.6 if k % 2 else -3.6))
        for f, p in list(pos_a.items()) + list(pos_d.items()):
            self._estagiar(f, t_a, [(t_pronto, p), (t_fim, p)])

    def _primeiro_aereo(self, i):
        """Índice do primeiro evento da disputa da bola na área, depois de `i` (gr_sai | cabeceamento | corte | canto_mal_batido)."""
        k = self.passo_de[i]
        for j in range(i + 1, min(i + 6, len(self.ev))):
            if self.passo_de[j] != k:
                break
            if self.ev[j]["tipo"] in ("gr_sai", "cabeceamento", "corte", "canto_mal_batido"):
                return j
        return None

    def _ev_canto(self, i, e):
        T = self.J(e, "jog")
        ft = self.eq_de(e)
        K = self.F(e["de"])
        ts, tn = self.ts(i), self.tn(i)
        area = e.get("area") or [[], []]
        if self.fora is None:
            self.dbg["sem_fora"] += 1
            pt = self._para_la_da_linha((self.x_golo(ft), K[1] + (4.0 if K[1] < CY else -4.0)))
            self._mov(B_ROLA, ("pt", pt), self.bt + 0.6, 0.6)
            self.fora = (self.bt, pt, "canto")
        t_fora = self.fora[0]
        j = self._primeiro_aereo(i)
        self._texto(t_fora, f"Canto para {self.nomes[ft]}", 1 if False else 0)
        t_out = self.ev[j]["t"] if j is not None else max(tn - 0.5, t_fora + 8.0)
        tipo_j = self.ev[j]["tipo"] if j is not None else None
        xg = self.x_golo(ft)
        s = self.sinal(ft)
        Pa = (self.ux(ft, 54.0), CY)
        if tipo_j == "canto_mal_batido":
            # a bola vai para fora (pelo fundo) ou é apanhada por um adversário no meio da área
            dep2 = self._depois(j)
            alvo_pt = (self.ux(ft, 52.0), CY)
            dest_f = self.holder_seguinte(j) if not dep2 else None
            dist = _d(K, alvo_pt)
            dur = max(0.9, dist / 14.0)
            t_kick = t_out - dur
        else:
            dist = _d(K, Pa)
            dur = max(0.9, dist / 14.0)
            t_kick = t_out - dur
        t_kick = max(t_kick, t_fora + 4.0)
        t_taker = t_kick - 1.1
        # o marcador do cabeceamento (se for o caso) e o alvo
        alvo = self.J(self.ev[j], "jog") if tipo_j == "cabeceamento" else (self.J(self.ev[j], "jog2") if tipo_j == "corte" else None)
        marc = self.J(self.ev[j], "jog") if tipo_j == "corte" else None
        # o guarda-redes que sai tem de ser o da equipa adversária
        # 1) bola velha desaparece, outra aparece no canto
        t_esc = max(t_fora + 1.0, self.bt)
        self._esconde(t_esc)
        # 2) jogadores: batedor para o canto, área
        pt_T = (K[0] - s * 0.6, K[1] + (0.6 if K[1] < CY else -0.6))
        self._estagiar(T, max(ts, t_fora - 1.0), [(t_taker, pt_T), (t_kick + 0.6, pt_T)], t_limpa=tn - 0.2)
        t_fim_area = min(tn - 0.15, t_out + 0.8)
        self._estagiar_area(ft, area, alvo, marc, max(ts, t_fora - 1.0), t_kick - 0.7, t_fim_area)
        self._aparece(t_taker, ("pt", (K[0] - s * 0.1, K[1] + (0.1 if K[1] < CY else -0.1))))
        self._fechar(t_kick - 0.25)
        self.est = ("j", T)
        self._anim(t_kick - 0.3, T, A_CHUTA, 0.5)
        self.fora = None
        self.mortos.append([t_esc, t_kick - 1.5])
        # 3) o voo
        if tipo_j == "canto_mal_batido":
            dep2 = self._depois(j)
            self._consumir(j)
            if dep2:
                self._sair(dep2, t_kick, t_out, B_CHAPEU, h=3.0, dica=Pa, vel=14.0)
            else:
                X = self.holder_seguinte(j)
                if X is not None:
                    self._chega(X, t_out, alvo_pt, max(ts, t_kick - 1.0))
                    self._mov(B_CHAPEU, ("j", X), t_out, t_out - t_kick, h=3.0, t_sai=t_kick)
            return
        self._voo_para_area(i, j, t_kick, t_out, K, h=_lim(3.2 + 0.05 * dist, 3.5, 5.5), t_comeco=t_fora)

    def _voo_para_area(self, i, j, t_sai, t_ch, origem, h, t_comeco=None):
        """A bola entra na área e é disputada: `j` é o primeiro evento da disputa. Trata a bola até ao fim da disputa."""
        if j is None:
            return
        e2 = self.ev[j]
        tp = e2["tipo"]
        Pa = self.F(e2["de"]) if e2.get("de") else self.ponto_bola(t_ch)
        if tp == "gr_sai":
            gr = self.J(e2, "jog")
            ft_gr = self.eq_de(e2)
            self._consumir(j)
            self._chega(gr, t_ch, Pa, max(self.ts(j), t_ch - 3.0))
            self._mov(B_CHAPEU, ("j", gr), t_ch, t_ch - t_sai, h=h, z1=1.8, t_sai=t_sai)
            self._anim(t_ch - 0.5, gr, A_VOA, 0.8, 0.0, 1.0)
            self._texto(t_ch, f"{self.jog[gr][1]} sai da baliza e agarra a bola", 0)
            return
        if tp == "cabeceamento":
            alvo = self.J(e2, "jog")
            self._consumir(j)
            self._mov(B_CHAPEU, ("j", alvo), t_ch, t_ch - t_sai, h=h, z1=1.9, t_sai=t_sai)
            self._anim(t_ch - 0.4, alvo, A_CABECEIA, 0.8)
            self.cab = (t_ch, alvo)
            return
        if tp == "corte":
            marc = self.J(e2, "jog")
            alvo = self.J(e2, "jog2")
            self._consumir(j)
            self._mov(B_CHAPEU, ("j", marc), t_ch, t_ch - t_sai, h=h, z1=1.9, t_sai=t_sai)
            self._anim(t_ch - 0.4, marc, A_CABECEIA, 0.8)
            self._anim(t_ch - 0.4, alvo, A_CABECEIA, 0.8)
            self._texto(t_ch, f"{self.jog[marc][1]} corta", 0)
            dep = self._depois(j)
            if dep:
                self._sair(dep, t_ch + 0.1, t_ch + 1.4, B_CHAPEU, h=2.0, dica=Pa, vel=12.0, z0=1.9)
            return

    def _ev_cabeceamento(self, i, e):
        pass                                                    # tratado em _voo_para_area

    def _ev_gr_sai(self, i, e):
        pass

    def _ev_corte(self, i, e):
        """Corte numa bola longa disputada (passe `disputado`): o defesa cabeceia."""
        pass

    def _ev_canto_mal_batido(self, i, e):
        pass

    def _ev_canto_conquistado(self, i, e):
        pass

    def _ev_cruzamento(self, i, e):
        C = self.J(e, "jog")
        ft = self.eq_de(e)
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        res = e["res"]
        de, para = self.F(e["de"]), self.F(e["para"])
        d = _d(de, para)
        dur = max(0.9, d / 14.0)
        h = _lim(2.6 + 0.07 * d, 3.0, 5.5)
        t_e = max(t_e, ts + dur + 0.5)
        t_sai = t_e - dur
        self._fixar(C, ts, t_sai, self.pos(C, ts))
        self._anim(t_sai - 0.25, C, A_CHUTA, 0.5)
        if res == "ok":
            j = self._primeiro_aereo(i)
            if j is None:
                return
            e2 = self.ev[j]
            alvo = self.J(e2, "jog") if e2["tipo"] == "cabeceamento" else (self.J(e2, "jog2") if e2["tipo"] == "corte" else None)
            marc = self.J(e2, "jog") if e2["tipo"] == "corte" else None
            if alvo is not None:
                self._chega(alvo, t_e, self.F(e2["de"]), ts)
            if marc is not None:
                self._chega(marc, t_e, (self.F(e2["de"])[0] + self.sinal(ft) * 0.9, self.F(e2["de"])[1] + 0.5), ts)
            self._voo_para_area(i, j, t_sai, t_e, de, h)
            return
        # falhado: a bola cai fora do alcance de quem ataca
        dep = self._depois(i)
        if dep:
            self._sair(dep, t_sai, t_e + 0.2, B_CHAPEU, h=h, dica=para, vel=14.0)
            return
        X = self.holder_seguinte(i)
        if X is not None:
            self._chega(X, min(t_e, tn - 0.05), para, ts)
            self._mov(B_CHAPEU, ("j", X), min(t_e, tn - 0.05), dur, h=h, t_sai=t_sai)

    # ---- livre
    def _ev_livre(self, i, e):
        T = self.J(e, "jog")
        vit = self.J(e, "jog2")
        ft = self.eq_de(e)
        L = self.F(e["de"])
        ts, tn = self.ts(i), self.tn(i)
        area = e.get("area") or [[], []]
        s = self.sinal(ft)
        xg = self.x_golo(ft)
        gol = (xg, CY)
        k = self.passo_de[i]
        # evento seguinte (resultado do livre)
        j = i + 1
        seg = self.ev[j] if j < len(self.ev) and self.passo_de[j] == k else None
        t_out = seg["t"] if seg is not None else tn - 1.0
        t_start = ts + 0.9
        direto = e["dist"] <= 14.0 or abs(L[1] - CY) <= 9.0
        t_kick = t_out - (self._remate_dur(L, gol) if direto and seg is not None and seg["tipo"] in ("remate", "golo", "defesa") else 0.0 if direto else 1.3)
        t_kick = max(t_kick, t_start + 4.0)
        # bola parada no sítio da falta
        self._fechar(max(self.bt, ts))
        self.est = ("pt", L)
        # 1) barreira, guarda-redes, batedor, atacantes
        _, dgol = L, _d(L, gol)
        u = _unit(L, gol)
        adv_f = 1 - ft
        gr = adv_f * 7
        defs = [self.idx[(adv_f, n)] for n in area[1] if self.idx[(adv_f, n)] != gr][:3]
        n_bar = 3 if direto and dgol < 24 else 0
        barreira = defs[:n_bar]
        bar_pts = {}
        nx, ny = -u[1], u[0]
        for q, f in enumerate(barreira):
            off = (q - (len(barreira) - 1) / 2) * 0.95
            bar_pts[f] = (L[0] + u[0] * 4.2 + nx * off, L[1] + u[1] * 4.2 + ny * off)
        t_pronto = t_kick - 1.2
        for f, p in bar_pts.items():
            self._estagiar(f, t_start, [(t_pronto - 0.5, p), (t_kick + 0.8, p)], t_limpa=min(tn - 0.1, t_kick + 0.8))
        # guarda-redes: na linha, do lado da bola
        if direto:
            gp = (self.ux(adv_f, 1.4), CY + (L[1] - CY) * 0.28)
            self._estagiar(gr, t_start, [(t_pronto, gp), (t_kick + 0.5, gp)], t_limpa=min(tn - 0.1, t_kick + 0.5))
        # batedor (se não for a vítima, que está no chão)
        if T != vit:
            back = (L[0] - u[0] * 2.0 - nx * 0.6, L[1] - u[1] * 2.0 - ny * 0.6)
            pk = (L[0] - u[0] * 0.7, L[1] - u[1] * 0.7)
            self._estagiar(T, t_start, [(t_pronto, back), (t_kick - 0.35, pk), (t_kick + 0.5, pk)], t_limpa=min(tn - 0.1, t_kick + 0.5))
        else:
            pk = (L[0] - u[0] * 0.7, L[1] - u[1] * 0.7)
            self._estagiar(T, t_start + 2.5, [(t_pronto, (L[0] - u[0] * 1.5, L[1] - u[1] * 1.5)), (t_kick - 0.3, pk), (t_kick + 0.5, pk)], t_limpa=min(tn - 0.1, t_kick + 0.5))
        # atacantes para a área (livre lateral) ou ressalto (livre direto)
        aereo = seg is not None and seg["tipo"] in ("gr_sai", "cabeceamento", "corte")
        if aereo:
            alvo = self.J(seg, "jog") if seg["tipo"] == "cabeceamento" else (self.J(seg, "jog2") if seg["tipo"] == "corte" else None)
            marc = self.J(seg, "jog") if seg["tipo"] == "corte" else None
            self._estagiar_area(ft, area, alvo if alvo != T else None, marc if marc != T else None, t_start, t_kick - 0.5, min(tn - 0.15, t_out + 0.8))
        else:
            At = [self.idx[(ft, nme)] for nme in area[0] if self.idx[(ft, nme)] not in (T, vit)][:2]
            for q, f in enumerate(At):
                p = (self.ux(ft, 47.5 - 1.0 * q), CY + (3.5 if q == 0 else -3.5))
                self._estagiar(f, t_start, [(t_pronto, p), (t_kick + 1.0, p)], t_limpa=min(tn - 0.1, t_kick + 1.0))
        self._texto(ts + 0.8, f"Livre perigoso para {self.nomes[ft]}: {self.jog[T][1]} vai bater", 0)
        self.mortos.append([t_start + 1.5, t_pronto - 1.0])
        self.livre_ctx = {"T": T, "L": L, "t_kick": t_kick, "barreira": barreira, "ft": ft, "t_start": t_start}
        self._anim(t_kick - 0.35, T, A_CHUTA, 0.5)
        # 2) a bola passa para os pés de quem bate
        self._fechar(t_kick - 0.3)
        self.est = ("j", T)
        if aereo:
            dist = _d(L, (self.ux(ft, 54.0), CY))
            dur = max(0.9, dist / 14.0)
            self._voo_para_area(i, self._primeiro_aereo(i), t_out - dur, t_out, L, h=_lim(3.0 + 0.05 * dist, 3.5, 5.5))
            self.livre_ctx = None
        elif seg is None:
            X = self.holder_seguinte(i)
            self.livre_ctx = None
            if X is not None:
                self._chega(X, tn - 0.1, L, ts)
                self._mov(B_CHAPEU, ("j", X), tn - 0.1, 1.0, h=2.5)

    # ---- remates
    def _alvo_golo(self, ft, y_lado, alt):
        """Ponto de chegada (fixo) de um remate à baliza de `ft` atacar: (x, y, z)."""
        xg = self.x_golo(ft)
        return (xg - self.sinal(ft) * 0.2, CY + y_lado, alt)

    def _remate_dur(self, de, alvo):
        return max(0.30, _d(de, alvo) / V_REMATE)

    def _dar_remate(self, C, ft, pa, t_rel, alvo_pt, z_fim, dest=None, h=0.6, z0=0.4, dur=None):
        """`C` remata de `pa` em `t_rel`; devolve t_chegada. A bola vai de C para `dest` ('pt', …) ou ('j', f)."""
        if dur is None:
            dur = self._remate_dur(pa, alvo_pt)
        t_ch = t_rel + dur
        destino = dest if dest is not None else ("pt", alvo_pt)
        self._mov(B_REMATE, destino, t_ch, dur, h=h, z0=z0, z1=z_fim, t_sai=t_rel)
        self._anim(t_rel - 0.22, C, A_CHUTA, 0.5, 1.0, 0.0)
        return t_ch

    def _lance_remate(self, i, e, C, gk_f, tipo_res, t_fin=None, alvo_dist=None):
        """Prepara o remate: `C` conduz a bola até ao momento do remate. Devolve (t_rel, pa, cabeça).
        `t_fin`: instante máximo em que o remate pode estar resolvido (para sobrar tempo à bola seguinte)."""
        ft = self.eq_de(e) if tipo_res != "defesa" else 1 - self.eq_de(e)
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        cab = bool(e.get("cabeca")) and self.cab is not None and self.cab[1] == C
        xg = self.x_golo(ft)
        if cab:
            t_rel = self.cab[0] + 0.12
            self.cab = None
            return t_rel, self.pos(C, t_rel), True
        t_res = t_e if t_fin is None else min(t_e, t_fin)
        livre = self.livre_ctx is not None and e.get("origem") == "livre"
        if livre:
            pa = self.livre_ctx["L"]
            dur = self._remate_dur(pa, (xg, CY))
            return max(self.bt, t_res - dur), pa, False
        if self.reb is not None and self.reb[0] == C and e.get("origem") == "ressalto":
            _, pa_real, t_in = self.reb
            self.reb = None
            dur = self._remate_dur(pa_real, (xg, CY))
            t_rel = max(t_in + 0.25, t_res - dur, self.bt)
            self._fixar(C, t_in, t_rel, pa_real)
            return t_rel, pa_real, False
        pa_real = self.pos(C, ts)
        dur = self._remate_dur(pa_real, (xg, CY)) if alvo_dist is None else alvo_dist
        t_rel = max(ts + 0.25, t_res - dur, self.bt)
        self._fixar(C, ts, t_rel, pa_real)
        return t_rel, pa_real, False

    def _ev_golo(self, i, e):
        C = self.J(e, "jog")
        ft = self.eq_de(e)
        xg = self.x_golo(ft)
        s = self.sinal(ft)
        gk = (1 - ft) * 7
        t_rel, pa, cab = self._lance_remate(i, e, C, gk, "golo")
        lado = self.ysw * self.rnd.choice([-1, 1]) * self.rnd.uniform(1.3, 2.7)
        z = self.rnd.uniform(0.35, 1.7)
        alvo = (xg + s * 1.1, CY + lado)
        # a bola entra na baliza (para lá da linha) e vai à rede
        dur = self._remate_dur(pa, alvo)
        t_net = t_rel + dur
        pre_dest = self._mov(B_REMATE, ("pt", alvo), t_net, dur, h=0.5, z0=0.4, z1=z, t_sai=max(t_rel, self.bt))
        self._anim(t_rel - 0.22, C, A_CHUTA, 0.5)
        self._anim(t_net - 0.55, gk, A_VOA, 0.9, 1.0 if lado > 0 else -1.0, 1.0)
        self._golo_festejo(i, e, C, ft, t_net, alvo, lado)

    def _golo_festejo(self, i, e, C, ft, t_net, alvo, lado):
        s = self.sinal(ft)
        xg = self.x_golo(ft)
        self.golos[ft] += 1
        self.placar.append([t_net, self.golos[0], self.golos[1]])
        tx = f"GOLO! {self.jog[C][1]} marca para {self.nomes[ft]}"
        ass = self.J(e, "jog2")
        if ass is not None:
            tx += f" (assistência de {self.jog[ass][1]})"
        self._texto(t_net, tx, 1)
        self._marco_golo = (t_net, ft, e["min"])
        # a bola fica na rede e depois é retirada
        self._fechar(t_net + 2.2)
        self._esconde(t_net + 2.3)
        # festejo: o marcador corre para a linha lateral, os colegas juntam-se
        pc = self.pos(C, t_net)
        y_borda = 3.0 if pc[1] < CY else H - 3.0
        cp = (xg - s * 13.5, y_borda)
        t_chega = t_net + max(3.0, _d(pc, cp) / 5.4)
        self._estagiar(C, t_net, [(t_chega, cp), (t_net + 8.5, (cp[0] - s * 0.4, cp[1]))], t_limpa=t_net + 8.5)
        self._anim(t_net + 0.5, C, A_FESTEJA, 7.5)
        colegas = [f for f in range(ft * 7 + 1, ft * 7 + 7) if f != C]
        for q, f in enumerate(colegas):
            ang = math.pi * (0.55 + 0.9 * q / max(1, len(colegas) - 1))
            r = 1.6 + 0.35 * (q % 2)
            dx, dy = math.cos(ang) * r * (-s), math.sin(ang) * r * (1 if y_borda < CY else -1) * -1
            p = (cp[0] + dx, cp[1] + dy * 0.9)
            tf = t_net + max(3.6, _d(self.pos(f, t_net), p) / 5.2)
            self._estagiar(f, t_net, [(tf, p), (t_net + 8.5, p)], t_limpa=t_net + 8.5)
            self._anim(tf, f, A_FESTEJA, 4.5)
        self.t_ultimo_festejo = t_net + 8.5
        self._marco(None, t_net, "golo", ft, e["min"], 100)
        self.marcos[-1]["rel"] = t_net - 0.6
        self.marcos[-1]["res"] = t_net
        self.marcos[-1]["cauda"] = 8.5

    def _ev_defesa(self, i, e):
        gk = self.J(e, "jog")
        C = self.J(e, "jog2")
        ft = self.eq_de(e)                                        # equipa do guarda-redes
        ft_atq = 1 - ft
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        dep = self._depois(i)
        ress = i + 1 < len(self.ev) and self.ev[i + 1]["tipo"] == "ressalto" and self.passo_de[i + 1] == self.passo_de[i]
        X = None if (dep or ress) else self.holder_seguinte(i)
        if X == gk:
            X = None
        t_fin = None
        needed = 0.0
        if X is not None:
            needed = 0.5 + _d(self.pos(gk, tn), self.pos(X, tn)) / 16.0
            t_fin = tn - 0.05 - needed
        t_rel, pa, cab = self._lance_remate(i, e, C, gk, "defesa", t_fin=t_fin)
        xg = self.x_golo(ft_atq)
        s = self.sinal(ft_atq)
        lado = self.ysw * self.rnd.choice([-1, 1]) * self.rnd.uniform(0.5, 2.3)
        ponto = (xg - s * 1.5, CY + lado)
        dur = self._remate_dur(pa, ponto)
        t_res = t_rel + dur
        self._chega(gk, t_res, ponto, max(ts, t_rel - 0.6))
        self._mov(B_REMATE, ("j", gk), t_res, dur, h=0.5, z0=0.4, z1=0.5 + abs(lado) * 0.2, t_sai=max(t_rel, self.bt))
        self._anim(t_rel - 0.22, C, A_CHUTA, 0.5)
        self._anim(t_res - 0.55, gk, A_VOA, 0.9, 1.0 if lado > 0 else -1.0, 1.0 if e.get("dificil") else 0.0)
        self._texto(t_res, ("Grande defesa de " if e.get("dificil") else "Defesa de ") + self.jog[gk][1], 2 if e.get("dificil") else 0)
        self._marco(t_rel, t_res, "defesa", ft_atq, e["min"], 60 if e.get("dificil") else 45)
        if dep and dep[0] == "canto":
            self._sair(dep, t_res + 0.05, t_res + 1.2, B_ROLA, h=1.5, vel=9.0, z0=0.6)
        elif X is not None:
            t_arr = max(tn - 0.05, t_res + 0.05 + needed)
            self._mov(B_ROLA if needed < 1.2 else B_CHAPEU, ("j", X), t_arr, t_arr - (t_res + 0.05),
                      h=0.0 if needed < 1.2 else 1.5, t_sai=t_res + 0.05)

    def _ev_ressalto(self, i, e):
        """A bola sobra da defesa para a zona do remate: quem rematou corre a ela para voltar a rematar."""
        C = self.J(e, "jog")
        ft = self.eq_de(e)
        ts, tn = self.ts(i), self.tn(i)
        gol = (self.x_golo(ft), CY)
        t0 = self.bt
        pc = self.pos(C, t0)
        u = _unit(gol, pc)
        r = self.rnd.uniform(4.5, 6.5)
        P = (gol[0] + u[0] * r, _lim(gol[1] + u[1] * r, CY - 6.5, CY + 6.5))
        P = (P[0], P[1] + (0.0 if abs(P[1] - CY) > 1.0 else self.ysw * self.rnd.choice([-1, 1]) * 1.5))
        d = _d(self.ponto_bola(t0), P)
        t_arr = t0 + 0.3 + max(0.7, d / 7.0)
        self._chega(C, t_arr, P, max(ts, t0 - 1.0))
        self._mov(B_ROLA, ("j", C), t_arr, t_arr - (t0 + 0.05), t_sai=t0 + 0.05)
        self._texto(t0, "Ressalto!", 0)
        self.reb = (C, P, t_arr)

    def _ev_remate(self, i, e):
        C = self.J(e, "jog")
        ft = self.eq_de(e)
        res = e["res"]
        t_rel, pa, cab = self._lance_remate(i, e, C, (1 - ft) * 7, res)
        xg = self.x_golo(ft)
        s = self.sinal(ft)
        gk = (1 - ft) * 7
        ts, t_e, tn = self.ts(i), e["t"], self.tn(i)
        origem = e.get("origem", "jogo")
        if res == "barreira":
            ctx = self.livre_ctx
            W0 = ctx["barreira"][len(ctx["barreira"]) // 2] if ctx and ctx["barreira"] else None
            bpt = self.pos(W0, t_rel + 0.3) if W0 is not None else (pa[0] + s * 4.0, pa[1])
            dur = max(0.25, _d(pa, bpt) / 20.0)
            X = self.holder_seguinte(i)
            if W0 is not None:
                self._mov(B_REMATE, ("j", W0), t_rel + dur, dur, h=0.4, z0=0.2, z1=0.6, t_sai=max(t_rel, self.bt))
                self._anim(t_rel + dur - 0.25, W0, A_DEFENDE, 0.5)
            self._anim(t_rel - 0.22, C, A_CHUTA, 0.5)
            self._texto(t_rel + dur, "A barreira bloqueia", 0)
            if X is not None:
                self._chega(X, min(tn - 0.05, t_rel + dur + 1.0), bpt, ts)
                self._mov(B_ROLA, ("j", X), min(tn - 0.05, t_rel + dur + 1.0), 1.0, t_sai=t_rel + dur + 0.05)
            self._marco(t_rel, t_rel + dur, "remate_livre", ft, e["min"], 30)
            self.livre_ctx = None
            return
        if res == "bloqueado":
            dep = self._depois(i)
            d_b = self.rnd.uniform(1.8, 3.2)
            Pb = (pa[0] + s * d_b * 0.9, pa[1] + (CY - pa[1]) * 0.1)
            dur = max(0.2, d_b / 18.0)
            cand = [f for f in range((1 - ft) * 7 + 1, (1 - ft) * 7 + 7)]
            if dep is None:
                X = self.holder_seguinte(i)
                B = X if (X is not None and X // 7 == 1 - ft) else min(cand, key=lambda f: _d(self.pos(f, t_rel + dur), Pb))
            else:
                B = min(cand, key=lambda f: _d(self.pos(f, t_rel), Pb))
            self._chega(B, t_rel + dur, Pb, max(ts, t_rel - 1.2))
            self._mov(B_REMATE, ("j", B), t_rel + dur, dur, h=0.3, z0=0.3, z1=0.5, t_sai=max(t_rel, self.bt))
            self._anim(t_rel - 0.22, C, A_CHUTA, 0.5)
            self._anim(t_rel + dur - 0.3, B, A_DEFENDE, 0.5)
            self._texto(t_rel + dur, f"{self.jog[B][1]} bloqueia o remate", 0)
            self._marco(t_rel, t_rel + dur, "remate_bloqueado", ft, e["min"], 20)
            if dep:
                self._sair(dep, t_rel + dur + 0.05, t_rel + dur + 1.1, B_ROLA, h=0.8, vel=10.0)
            return
        # fora
        dep = self._depois(i)
        k_alto = self.rnd.random() < 0.35
        if dep and dep[0] == "canto":
            ponto = self._ponto_fora(dep)
            alvo = (xg + s * 0.6, ponto[1])
            z = 0.8
        elif k_alto:
            alvo = (xg + s * 1.2, CY + self.ysw * self.rnd.uniform(-2.0, 2.0))
            z = ALTURA_BALIZA + self.rnd.uniform(0.9, 2.0)
        else:
            alvo = (xg + s * 1.2, CY + self.ysw * self.rnd.choice([-1, 1]) * self.rnd.uniform(3.4, 7.5))
            z = self.rnd.uniform(0.3, 1.5)
        dur = self._remate_dur(pa, alvo)
        t_res = t_rel + dur
        self._mov(B_REMATE, ("pt", self._para_la_da_linha((alvo[0] if abs(alvo[0] - xg) > 0 else xg, alvo[1]))), t_res, dur,
                  h=0.6 if not k_alto else 1.2, z0=0.4, z1=z, t_sai=max(t_rel, self.bt))
        self._anim(t_rel - 0.22, C, A_CHUTA, 0.5)
        self.fora = (t_res, self.est[1], "baliza" if not (dep and dep[0] == "canto") else "canto")
        self._texto(t_res, f"{self.jog[C][1]} remata ao lado" if not k_alto else f"{self.jog[C][1]} remata por cima", 0)
        self._marco(t_rel, t_res, "remate_fora", ft, e["min"], 35 if origem in ("contra", "livre", "canto") else 25)

    # ---- sem efeito visual próprio
    def _ev_contra_ataque(self, i, e):
        f = self.J(e, "jog")
        self._texto(e["t"], f"Contra-ataque de {self.nomes[self.eq_de(e)]}!", 0)

    # ------------------------------------------------------------------ lances principais
    def _lances(self, orcamento=330.0):
        cand = []
        for m in self.marcos:
            cauda = m.get("cauda", 3.2)
            ini = m["ini"] if m["ini"] is not None else m["rel"] - 11.0
            fim = m["res"] + cauda
            cand.append([max(0.0, ini), min(self.total, fim), m["tipo"], m["ft"], m["min"], m["imp"]])
        cand.sort(key=lambda c: -c[5])
        escolhidos, total = [], 0.0
        for c in cand:
            dur = c[1] - c[0]
            if c[5] >= 100 or total + dur <= orcamento:
                escolhidos.append(c)
                total += dur
        escolhidos.sort(key=lambda c: c[0])
        fundidos = []
        for c in escolhidos:
            if fundidos and c[0] <= fundidos[-1][1] + 2.5:
                u = fundidos[-1]
                u[1] = max(u[1], c[1])
                if c[5] > u[5]:
                    u[2], u[3], u[4], u[5] = c[2], c[3], c[4], c[5]
            else:
                fundidos.append(list(c))
        self.lances = fundidos

    # ------------------------------------------------------------------ saída
    def filme(self):
        r = lambda v, k: int(round(v * k))
        tr = []
        for f in range(14):
            t = self.tr[f]
            out = []
            for k in range(len(t.t)):
                out += [r(t.t[k], 100), r(t.x[k], 10), r(t.y[k], 10)]
            tr.append(out)
        bola = [[r(p[0], 100), r(p[1], 100), p[2], p[3], p[4], r(p[5], 10), r(p[6], 10), r(p[7], 10), r(p[8], 10), r(p[9], 10), r(p[10], 10), r(p[11], 10)]
                for p in self.pecas]
        return {
            "v": 1, "dur": int(self.total * 100), "parte": r(self.t_intervalo or self.total / 2, 100),
            "nomes": self.nomes, "jog": self.jog, "tr": tr, "bola": bola,
            "an": [[r(a[0], 100), a[1], a[2], r(a[3], 100), r(a[4], 10), r(a[5], 10)] for a in sorted(self.anims, key=lambda a: a[0])],
            "tx": [[r(t[0], 100), t[1], t[2]] for t in sorted(self.textos, key=lambda t: t[0])],
            "pl": [[r(p[0], 100), p[1], p[2]] for p in self.placar],
            "lances": [[r(l[0], 100), r(l[1], 100), l[2], l[3], l[4]] for l in self.lances],
            "mortos": [[r(m[0], 100), r(m[1], 100)] for m in self.mortos if m[1] > m[0] + 1.0],
        }


def construir(publico: dict, eventos: dict, lugar: int) -> dict:
    """`publico`: o resultado sem eventos (equipas, placar, semente…); `eventos`: {"ordem": …, "eventos": …};
    `lugar`: 0 se quem vê foi a equipa A do motor, 1 se foi a B (o campo é espelhado)."""
    return Realizador(publico, eventos["ordem"], eventos["eventos"], lugar).filme()
