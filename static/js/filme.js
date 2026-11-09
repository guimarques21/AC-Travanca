/* ==========================================================================
   filme.js — lê o «filme» do jogo (ver visual.py) e responde à pergunta «onde está cada coisa neste instante?».

   Não mexe no ecrã: só números. É usado por jogo_visual.js (que desenha) e é testável em Node.

   Formato (todos os números inteiros; ver visual.py):
     jog     [[equipa, nome, número, posição]] × 14        equipa 0 = quem vê (ataca para x = 60)
     tr      por jogador [t×100, x×10, y×10, …]            interpola-se com PCHIP (sem ressaltos)
     bola    [t0×100, t1×100, tipo, refA, refB, ax×10, ay×10, bx×10, by×10, h×10, z0×10, z1×10]
     an      [t×100, jogador, código, duração×100, a×10, b×10]
     tx      [t×100, texto, tipo]        pl [t×100, golos0, golos1]
     lances  [ini×100, fim×100, tipo, equipa, minuto]       mortos [ini×100, fim×100]
   ========================================================================== */

(function (raiz) {
  'use strict';

  const B = { PARADA: 0, CONDUZ: 1, RASTEIRA: 2, CHAPEU: 3, REMATE: 4, ROLA: 5, ESCONDIDA: 6 };
  const A = { CHUTA: 1, DESARMA: 2, CAI: 3, VOA: 4, CABECEIA: 5, FESTEJA: 6, LANCA: 7, FALTA: 8, DEFENDE: 9, LEVANTA: 10 };
  const COMPRIMENTO = 60, LARGURA = 40;
  const PE = 0.42;                       // a bola conduzida vai a esta distância (m) à frente do pé

  /* ---------- PCHIP: mesma conta do Python (visual.Traj) ---------- */
  function tangente(ts, ps, k, n) {
    if (n === 1) return 0;
    if (k === 0) return (ps[1] - ps[0]) / (ts[1] - ts[0]);
    if (k === n - 1) return (ps[k] - ps[k - 1]) / (ts[k] - ts[k - 1]);
    const h0 = ts[k] - ts[k - 1], h1 = ts[k + 1] - ts[k];
    const d0 = (ps[k] - ps[k - 1]) / h0, d1 = (ps[k + 1] - ps[k]) / h1;
    if (d0 * d1 <= 0) return 0;
    const w1 = 2 * h1 + h0, w2 = h1 + 2 * h0;
    return (w1 + w2) / (w1 / d0 + w2 / d1);
  }

  function hermite(h, u, p0, p1, m0, m1) {
    const u2 = u * u, u3 = u2 * u;
    return (2 * u3 - 3 * u2 + 1) * p0 + (u3 - 2 * u2 + u) * h * m0 + (-2 * u3 + 3 * u2) * p1 + (u3 - u2) * h * m1;
  }

  class Trajetoria {
    constructor(plano) {
      const n = plano.length / 3;
      this.n = n;
      this.t = new Float64Array(n);
      this.x = new Float64Array(n);
      this.y = new Float64Array(n);
      for (let k = 0; k < n; k++) {
        this.t[k] = plano[3 * k] / 100;
        this.x[k] = plano[3 * k + 1] / 10;
        this.y[k] = plano[3 * k + 2] / 10;
      }
      this.ultimo = 0;
    }

    indice(t) {                          // último k com t[k] <= t
      const ts = this.t, n = this.n;
      let k = this.ultimo;
      if (k >= n - 1 || ts[k] > t) k = 0;
      if (ts[k] <= t && (k + 1 >= n || ts[k + 1] > t)) return k;
      if (k + 2 < n && ts[k + 1] <= t && ts[k + 2] > t) { this.ultimo = k + 1; return k + 1; }
      let lo = 0, hi = n - 1;
      while (lo < hi) {
        const m = (lo + hi + 1) >> 1;
        if (ts[m] <= t) lo = m; else hi = m - 1;
      }
      this.ultimo = lo;
      return lo;
    }

    pos(t, out) {
      const ts = this.t, n = this.n;
      if (t <= ts[0]) { out[0] = this.x[0]; out[1] = this.y[0]; return out; }
      if (t >= ts[n - 1]) { out[0] = this.x[n - 1]; out[1] = this.y[n - 1]; return out; }
      const k = this.indice(t);
      const h = ts[k + 1] - ts[k], u = (t - ts[k]) / h;
      out[0] = hermite(h, u, this.x[k], this.x[k + 1], tangente(ts, this.x, k, n), tangente(ts, this.x, k + 1, n));
      out[1] = hermite(h, u, this.y[k], this.y[k + 1], tangente(ts, this.y, k, n), tangente(ts, this.y, k + 1, n));
      return out;
    }
  }

  const suave = (v, a, b) => { const u = Math.min(1, Math.max(0, (v - a) / (b - a))); return u * u * (3 - 2 * u); };

  class Filme {
    constructor(dados) {
      this.dados = dados;
      this.duracao = dados.dur / 100;
      this.parte = dados.parte / 100;
      this.pausa = (dados.pausa != null ? dados.pausa : Math.max(0, dados.dur - 300000)) / 100;     // o intervalo (s de filme)
      // relógio: pares [tempo de filme, segundos de jogo]; o tempo de jogo anda ao ritmo da ação, não ao da parede
      this.rel = (dados.rel || []).map((x) => [x[0] / 100, x[1] / 10]);
      this.resumo = (dados.resumo || []).map((x) => [x[0] / 100, x[1] / 100]);
      this.nomes = dados.nomes;
      this.jog = dados.jog;
      this.tr = dados.tr.map((p) => new Trajetoria(p));
      const b = dados.bola, n = b.length;
      this.nb = n;
      const f = (i, k) => { const a = new Float64Array(n); for (let j = 0; j < n; j++) a[j] = b[j][i] / k; return a; };
      this.bt0 = f(0, 100); this.bt1 = f(1, 100);
      this.btipo = new Int8Array(n); this.bra = new Int16Array(n); this.brb = new Int16Array(n);
      for (let j = 0; j < n; j++) { this.btipo[j] = b[j][2]; this.bra[j] = b[j][3]; this.brb[j] = b[j][4]; }
      this.bax = f(5, 10); this.bay = f(6, 10); this.bbx = f(7, 10); this.bby = f(8, 10);
      this.bh = f(9, 10); this.bz0 = f(10, 10); this.bz1 = f(11, 10);
      this.ultimaPeca = 0;
      // animações por jogador
      this.anims = Array.from({ length: 14 }, () => []);
      dados.an.forEach((a) => this.anims[a[1]].push({ t: a[0] / 100, cod: a[2], dur: a[3] / 100, a: a[4] / 10, b: a[5] / 10 }));
      this.anims.forEach((l) => l.sort((x, y) => x.t - y.t));
      this.textos = dados.tx.map((x) => ({ t: x[0] / 100, texto: x[1], tipo: x[2] }));
      this.placar = dados.pl.map((x) => ({ t: x[0] / 100, g: [x[1], x[2]] }));
      this.lances = dados.lances.map((x) => ({ ini: x[0] / 100, fim: x[1] / 100, tipo: x[2], eq: x[3], min: x[4] }));
      this.mortos = dados.mortos.map((x) => [x[0] / 100, x[1] / 100]);
      this._p = [0, 0]; this._q = [0, 0]; this._r = [0, 0];
    }

    /* ---- jogadores ---- */
    pos(f, t, out) { return this.tr[f].pos(t, out || [0, 0]); }

    /** Velocidade (m/s) numa janela de ±0.3 s. */
    velocidade(f, t, out) {
      const a = this.tr[f].pos(t - 0.3, this._p), ax = a[0], ay = a[1];
      const b = this.tr[f].pos(t + 0.3, this._q);
      out = out || [0, 0];
      out[0] = (b[0] - ax) / 0.6; out[1] = (b[1] - ay) / 0.6;
      return out;
    }

    /* ---- bola ---- */
    pecaEm(t) {
      const t0 = this.bt0, n = this.nb;
      let k = this.ultimaPeca;
      if (k >= n || t0[k] > t) k = 0;
      if (!(t0[k] <= t && (k + 1 >= n || t0[k + 1] > t))) {
        let lo = 0, hi = n - 1;
        while (lo < hi) { const m = (lo + hi + 1) >> 1; if (t0[m] <= t) lo = m; else hi = m - 1; }
        k = lo;
      }
      this.ultimaPeca = k;
      return k;
    }

    /** Direção para onde o jogador `f` olha em `t` (vetor unitário). */
    frente(f, t, out) {
      out = out || [0, 0];
      const v = this.velocidade(f, t, [0, 0]);
      const sp = Math.hypot(v[0], v[1]);
      const ataca = this.jog[f][0] === 0 ? 1 : -1;
      // para onde olha parado: o portador para a baliza, os outros para a bola
      let ax = ataca, ay = 0;
      const nucleo = this.bolaNucleo(t, [0, 0, 0, 1]);
      if (nucleo[3] > 0) {
        const p = this.pos(f, t, [0, 0]);
        const dx = nucleo[0] - p[0], dy = nucleo[1] - p[1], d = Math.hypot(dx, dy);
        if (d > 0.7) { ax = dx / d; ay = dy / d; }
      }
      const w = suave(sp, 0.5, 1.6);
      let x = (sp > 1e-6 ? v[0] / sp : 0) * w + ax * (1 - w), y = (sp > 1e-6 ? v[1] / sp : 0) * w + ay * (1 - w);
      const m = Math.hypot(x, y) || 1;
      out[0] = x / m; out[1] = y / m;
      return out;
    }

    ponteira(f, t, out) {                // posição da bola aos pés de `f`
      const p = this.pos(f, t, this._r);
      const px = p[0], py = p[1];
      const v = this.velocidade(f, t, [0, 0]);
      const sp = Math.hypot(v[0], v[1]);
      const ataca = this.jog[f][0] === 0 ? 1 : -1;
      let dx = ataca, dy = 0;
      if (sp > 0.45) { dx = v[0] / sp; dy = v[1] / sp; }
      else {
        const nucleo = this.bolaNucleo(t, [0, 0, 0, 1]);
        const ex = nucleo[0] - px, ey = nucleo[1] - py, d = Math.hypot(ex, ey);
        if (d > 0.7) { dx = ex / d; dy = ey / d; }
      }
      const k = PE * suave(sp, 0.0, 0.9) + 0.30 * (1 - suave(sp, 0.0, 0.9));
      out[0] = px + dx * k; out[1] = py + dy * k;
      return out;
    }

    /** Bola sem deslocamento do pé (usada para os jogadores olharem para ela). out = [x, y, z, visível]. */
    bolaNucleo(t, out) {
      const k = this.pecaEm(t);
      const tipo = this.btipo[k];
      out[2] = 0; out[3] = 1;
      if (tipo === B.ESCONDIDA) { out[3] = 0; return out; }
      if (tipo === B.PARADA) { out[0] = this.bax[k]; out[1] = this.bay[k]; return out; }
      if (tipo === B.CONDUZ) { const p = this.tr[this.bra[k]].pos(t, this._r); out[0] = p[0]; out[1] = p[1]; return out; }
      const dur = this.bt1[k] - this.bt0[k];
      const u = dur <= 1e-6 ? 1 : Math.min(1, Math.max(0, (t - this.bt0[k]) / dur));
      const a = this.bra[k] >= 0 ? this.tr[this.bra[k]].pos(this.bt0[k], this._r) : null;
      const ax = a ? a[0] : this.bax[k], ay = a ? a[1] : this.bay[k];
      const b = this.brb[k] >= 0 ? this.tr[this.brb[k]].pos(this.bt1[k], this._r) : null;
      const bx = b ? b[0] : this.bbx[k], by = b ? b[1] : this.bby[k];
      const s = tipo === B.ROLA ? 1 - (1 - u) * (1 - u) : (tipo === B.RASTEIRA ? 1 - Math.pow(1 - u, 1.35) : u);
      out[0] = ax + (bx - ax) * s; out[1] = ay + (by - ay) * s;
      return out;
    }

    /** Bola em `t`: out = [x, y, z, visível, tipo, portador(-1 se nenhum), refA, refB, t0, t1]. */
    bola(t, out) {
      out = out || [0, 0, 0, 1, 0, -1, -1, -1, 0, 0];
      const k = this.pecaEm(t);
      const tipo = this.btipo[k];
      out[4] = tipo; out[5] = -1; out[3] = 1; out[2] = 0;
      out[6] = this.bra[k]; out[7] = this.brb[k]; out[8] = this.bt0[k]; out[9] = this.bt1[k];
      if (tipo === B.ESCONDIDA) { out[3] = 0; return out; }
      if (tipo === B.PARADA) { out[0] = this.bax[k]; out[1] = this.bay[k]; out[2] = 0.11; return out; }
      const tmp = [0, 0];
      if (tipo === B.CONDUZ) {
        const f = this.bra[k];
        this.ponteira(f, t, tmp);
        out[0] = tmp[0]; out[1] = tmp[1]; out[2] = 0.11 + 0.05 * Math.abs(Math.sin(t * 7.0 + f));   // toques na bola
        out[5] = f;
        return out;
      }
      const dur = this.bt1[k] - this.bt0[k];
      const u = dur <= 1e-6 ? 1 : Math.min(1, Math.max(0, (t - this.bt0[k]) / dur));
      let ax, ay, bx, by;
      if (this.bra[k] >= 0) { this.ponteira(this.bra[k], this.bt0[k], tmp); ax = tmp[0]; ay = tmp[1]; } else { ax = this.bax[k]; ay = this.bay[k]; }
      if (this.brb[k] >= 0) { this.ponteira(this.brb[k], this.bt1[k], tmp); bx = tmp[0]; by = tmp[1]; } else { bx = this.bbx[k]; by = this.bby[k]; }
      const s = tipo === B.ROLA ? 1 - (1 - u) * (1 - u) : (tipo === B.RASTEIRA ? 1 - Math.pow(1 - u, 1.35) : u);
      out[0] = ax + (bx - ax) * s; out[1] = ay + (by - ay) * s;
      const h = this.bh[k], z0 = this.bz0[k], z1 = this.bz1[k];
      out[2] = 0.11 + z0 + (z1 - z0) * u + 4 * h * u * (1 - u);
      if (tipo === B.ROLA) out[2] = 0.11 + 0.0 + 4 * h * u * (1 - u) + z0 * (1 - u);
      if (this.brb[k] >= 0 && u > 0.97) out[5] = this.brb[k];
      return out;
    }

    /* ---- animações ---- */
    /** A animação em curso do jogador `f` em `t` (a mais recente que ainda não acabou) ou null. `extra`: segundos a mais. */
    animacao(f, t, extra) {
      const l = this.anims[f], e = extra || 0;
      let i = l.length - 1;
      while (i >= 0 && l[i].t > t) i--;
      for (let n = 0; i >= 0 && n < 6; i--, n++) {
        const a = l[i];
        if (t < a.t + a.dur + e) return a;
        if (t - a.t > 14) break;
      }
      return null;
    }

    /* ---- marcadores ---- */
    placarEm(t) {
      let g = [0, 0];
      for (const p of this.placar) { if (p.t <= t) g = p.g; else break; }
      return g;
    }

    textoEm(t, janela) {
      let r = null;
      for (let i = this.textos.length - 1; i >= 0; i--) {
        if (this.textos[i].t <= t) { r = this.textos[i]; break; }
      }
      return r && t - r.t <= (janela || 7) ? r : null;
    }

    /** Segundos de jogo (sem o intervalo) para escrever o relógio. */
    segundosDeJogo(t) {
      const R = this.rel;
      if (!R.length) {                                              // filme sem tabela: relógio linear
        const pausa = this.pausa;
        if (t <= this.parte) return Math.min(t, 1500);
        if (t <= this.parte + pausa) return 1500;
        return Math.min(3000, t - pausa);
      }
      if (t <= R[0][0]) return R[0][1];
      const n = R.length;
      if (t >= R[n - 1][0]) return R[n - 1][1];
      let lo = 0, hi = n - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (R[m][0] <= t) lo = m; else hi = m; }
      const a = R[lo], b = R[hi];
      return b[0] - a[0] < 1e-9 ? a[1] : a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0]);
    }

    emMorto(t) {
      for (const m of this.mortos) { if (t >= m[0] && t < m[1]) return m; if (m[0] > t) break; }
      return null;
    }
  }

  const exportar = { Filme, Trajetoria, B, A, COMPRIMENTO, LARGURA };
  if (typeof module !== 'undefined' && module.exports) module.exports = exportar;
  else raiz.FilmeJogo = exportar;
})(typeof window !== 'undefined' ? window : globalThis);
