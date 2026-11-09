/* ==========================================================================
   cena.js — desenha o jogo (campo, bancada, jogadores, árbitro e bola) num <canvas>.

   Recebe o «filme» (filme.js) e um instante t e desenha esse instante. Não tem relógio nem botões:
   quem manda é jogo_visual.js.

   Vista de câmara de televisão (de um dos lados, ligeiramente de cima): é uma projeção em perspetiva a
   sério, por isso os jogadores mais perto são maiores e a bola levanta-se do chão em vez de «subir no ecrã».
   Os jogadores não são bolinhas: cada um é um boneco com cabeça, tronco, braços e pernas calculados em 3D
   (corrida com passada, remate, desarme com deslize, queda, voo do guarda-redes, cabeceamento, festejo…).
   ========================================================================== */

(function (raiz) {
  'use strict';

  const FJ = raiz.FilmeJogo;
  const COMP = 60, LARG = 40, CY = 20;
  const TRAVE = 3.0, ALT_BAL = 2.0, PROF_REDE = 1.6;
  const A = FJ.A, B = FJ.B;
  const TAU = Math.PI * 2;

  /* ---------- cores ---------- */
  const COR = {
    relva: ['#2f8a3c', '#37963f'], fora: '#24682f', linha: 'rgba(255,255,255,0.9)',
    ceu: ['#050f36', '#0a1d63'], bancada: '#0a1c63', muro: '#061246',
    pub: ['#1b3fae', '#ffcf1f'],
    pele: ['#f1c9a5', '#e0ac82', '#c68a5e', '#9a643f', '#6e4328'],
    cabelo: ['#1d1710', '#3b2a1b', '#6b4a2a', '#c9a14a', '#0f0f12', '#7a3b1e'],
    bola: '#ffffff', sombra: 'rgba(0,0,0,0.38)',
  };
  const KITS = [
    { camisola: '#ffcf1f', mangas: '#ffcf1f', calcoes: '#1b3fae', meias: '#ffcf1f', num: '#1b3fae', gola: '#1b3fae' },   // quem vê
    { camisola: '#2f5ae6', mangas: '#2f5ae6', calcoes: '#f4f7ff', meias: '#2f5ae6', num: '#f4f7ff', gola: '#f4f7ff' },   // adversário
  ];
  const KITS_GR = [
    { camisola: '#ff7a1a', mangas: '#ff7a1a', calcoes: '#1a2a6c', meias: '#ff7a1a', num: '#1a2a6c', gola: '#1a2a6c', luvas: '#ffffff' },
    { camisola: '#e8458b', mangas: '#e8458b', calcoes: '#20243a', meias: '#e8458b', num: '#ffffff', gola: '#ffffff', luvas: '#ffffff' },
  ];
  const KIT_ARB = { camisola: '#15171f', mangas: '#15171f', calcoes: '#15171f', meias: '#15171f', num: '#d8dcec', gola: '#d8dcec' };

  const lim = (v, a, b) => (v < a ? a : v > b ? b : v);
  const suave = (v, a, b) => { const u = lim((v - a) / (b - a), 0, 1); return u * u * (3 - 2 * u); };
  const angDif = (a, b) => { let d = (b - a) % TAU; if (d > Math.PI) d -= TAU; if (d < -Math.PI) d += TAU; return d; };
  const hash = (n) => { let x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

  /* ---------- câmara em perspetiva ---------- */
  class Camara {
    constructor() {
      this.D = 72; this.Hc = 46;
      this.camY = CY + this.D;
      this.L = Math.hypot(this.D, this.Hc);
      this.c = this.D / this.L; this.s = this.Hc / this.L;
      this.camX = COMP / 2; this.F = 1000; this.cx = 0; this.sy0 = 0;
    }

    /** `janela`: largura (m) vista ao centro do campo; `ancora`: onde fica a linha lateral de baixo (fração da altura). */
    ajustar(W, H, janela, camX, ancora) {
      this.W = W; this.H = H; this.camX = camX;
      this.F = W * this.L / janela; this.cx = W / 2;
      const yc = (LARG - this.camY) * (-this.s) - this.Hc * this.c;
      const zc = (this.camY - LARG) * this.c + this.Hc * this.s;
      this.sy0 = H * ancora + this.F * yc / zc;
    }

    p(x, y, z, o) {
      const zc = (this.camY - y) * this.c + (this.Hc - z) * this.s;
      const yc = (y - this.camY) * (-this.s) + (z - this.Hc) * this.c;
      const k = this.F / zc;
      o[0] = this.cx + (x - this.camX) * k;
      o[1] = this.sy0 - yc * k;
      o[2] = k;
      return o;
    }
  }

  /* ---------- estado de cada figura (jogador ou árbitro) ---------- */
  class Ator {
    constructor(i, kit, papel, numero, nome, equipa) {
      this.i = i; this.kit = kit; this.papel = papel; this.numero = numero; this.nome = nome; this.equipa = equipa;
      this.pele = COR.pele[Math.floor(hash(i * 3 + 1) * COR.pele.length)];
      this.cabelo = COR.cabelo[Math.floor(hash(i * 5 + 2) * COR.cabelo.length)];
      this.altura = 0.97 + hash(i * 7 + 3) * 0.08;
      this.ang = equipa === 0 ? 0 : Math.PI;
      this.fase = hash(i * 11) * TAU;
      this.vel = 0;
      this.x = 0; this.y = 0;
      this.passos = hash(i * 13) * 3;
    }
  }

  const P = [0, 0, 0];     // pontos temporários (projeção)
  const Q = [0, 0, 0];
  const R = [0, 0, 0];

  class Cena {
    constructor(canvas) {
      this.cv = canvas;
      this.ctx = canvas.getContext('2d');
      this.cam = new Camara();
      this.W = 0; this.H = 0; this.dpr = 1;
      this.camX = COMP / 2;
      this.janela = 46; this.janelaBase = 46;
      this.filme = null;
      this.atores = [];
      this.arbitro = null;
      this.arb = { x: 30, y: 6, ang: 0, vel: 0 };
      this.bolaEst = { rot: 0, ultimoX: 0, ultimoY: 0, trilho: [], vis: true };
      this.festaAte = -1;
      this.multidao = this._gerarMultidao();
      this.mostrarNomes = true;
      this._sujo = true;
      if (typeof ResizeObserver !== 'undefined') { this._ro = new ResizeObserver(() => { this._sujo = true; }); this._ro.observe(canvas); }
      this._o = [0, 0, 0, 1, 0, -1, -1, -1, 0, 0];
      this._bn = [0, 0, 0, 1];
      this._v = [0, 0]; this._f = [0, 0]; this._pp = [0, 0];
    }

    definirFilme(F) {
      this.filme = F;
      this.atores = F.jog.map((j, i) => {
        const eq = j[0], gr = j[3] === 0;
        const kit = gr ? KITS_GR[eq] : KITS[eq];
        return new Ator(i, kit, j[3], j[2], j[1], eq);
      });
      this.arbitro = new Ator(99, KIT_ARB, 2, 0, 'Árbitro', 2);
      this.arbitro.altura = 1.0;
      this.reiniciar();
    }

    reiniciar() { this._reset = true; this.bolaEst.trilho.length = 0; }

    redimensionar() {
      if (!this._sujo && this.W) return;
      this._sujo = false;
      const r = this.cv.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(160, Math.round(r.width)), h = Math.max(120, Math.round(r.height));
      if (this.W === w && this.H === h && this.dpr === dpr) return;
      this.W = w; this.H = h; this.dpr = dpr;
      this.cv.width = Math.round(w * dpr); this.cv.height = Math.round(h * dpr);
      this.janelaBase = w < 640 ? 34 : 46;
    }

    /* ------------------------------------------------------------------ multidão (posições fixas) */
    _gerarMultidao() {
      const linhas = [];
      const paleta = ['#ffcf1f', '#ffcf1f', '#8fb0ff', '#f4f7ff', '#1b3fae', '#2f5ae6', '#ffdd57', '#9fb3ee', '#0e2a8a'];
      for (let r = 0; r < 8; r++) {
        const fas = [];
        const n = 250;
        for (let k = 0; k < n; k++) {
          const u = (k + hash(r * 100 + k) * 0.8) / n;
          fas.push({ x: -40 + u * (COMP + 80), cor: paleta[Math.floor(hash(r * 31 + k * 7) * paleta.length)], ph: hash(k * 3 + r) * TAU });
        }
        linhas.push({ y: -3.2 - r * 1.15, z: 1.2 + r * 0.78, fas });
      }
      return linhas;
    }

    /* ------------------------------------------------------------------ utilitários de desenho */
    _quad(a, b, c, d, cor) {
      const ctx = this.ctx;
      ctx.fillStyle = cor;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(c[0], c[1]); ctx.lineTo(d[0], d[1]);
      ctx.closePath(); ctx.fill();
    }

    _pt(x, y, z) { const o = [0, 0, 0]; this.cam.p(x, y, z, o); return o; }

    _poligonoChao(pts, cor) {
      const ctx = this.ctx, cam = this.cam;
      ctx.fillStyle = cor;
      ctx.beginPath();
      for (let i = 0; i < pts.length; i++) {
        cam.p(pts[i][0], pts[i][1], 0, P);
        if (i) ctx.lineTo(P[0], P[1]); else ctx.moveTo(P[0], P[1]);
      }
      ctx.closePath(); ctx.fill();
    }

    _linhaChao(pts, fechar) {
      const ctx = this.ctx, cam = this.cam;
      ctx.beginPath();
      for (let i = 0; i < pts.length; i++) {
        cam.p(pts[i][0], pts[i][1], 0, P);
        if (i) ctx.lineTo(P[0], P[1]); else ctx.moveTo(P[0], P[1]);
      }
      if (fechar) ctx.closePath();
      ctx.stroke();
    }

    /* ------------------------------------------------------------------ cenário */
    _fundo(t) {
      const ctx = this.ctx, cam = this.cam, W = this.W, H = this.H;
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, COR.ceu[0]); g.addColorStop(1, COR.ceu[1]);
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

      // bancada do lado de lá: degraus a subir, com gente (azul e amarelo)
      const x0 = -40, x1 = COMP + 40;
      const a = this._pt(x0, -2.6, 0), b = this._pt(x1, -2.6, 0), c = this._pt(x1, -11.6, 8.6), d = this._pt(x0, -11.6, 8.6);
      this._quad(a, b, c, d, COR.bancada);
      const festa = t < this.festaAte;
      const bob = festa ? 1 : 0;
      for (let r = 0; r < this.multidao.length; r++) {
        const L = this.multidao[r];
        cam.p(0, L.y, L.z, P);
        const k = P[2];
        if (k < 3) continue;
        const w = Math.max(1.6, 0.52 * k), h = Math.max(2.2, 0.8 * k);
        for (let i = 0; i < L.fas.length; i++) {
          const f = L.fas[i];
          const salto = bob ? Math.abs(Math.sin(t * 5.2 + f.ph)) * 0.35 : 0;
          cam.p(f.x, L.y, L.z + salto, P);
          if (P[0] < -8 || P[0] > W + 8) continue;
          this.ctx.fillStyle = f.cor;
          this.ctx.fillRect(P[0] - w / 2, P[1] - h, w, h);
          this.ctx.fillStyle = '#e6c4a0';
          this.ctx.fillRect(P[0] - w * 0.3, P[1] - h - w * 0.62, w * 0.6, w * 0.6);
        }
        // faixa escura entre degraus (dá profundidade)
        cam.p(x0, L.y + 0.5, L.z - 0.7, P); cam.p(x1, L.y + 0.5, L.z - 0.7, Q);
        this.ctx.fillStyle = 'rgba(4,10,40,0.28)';
        this.ctx.fillRect(Math.min(P[0], Q[0]), P[1] - 1.5, Math.abs(Q[0] - P[0]), 2);
      }

      // painéis de publicidade do lado de lá
      this._painel(-1.6, 0.95, -40, COMP + 40, 0);
    }

    _painel(y, alt, x0, x1, desl) {
      const ctx = this.ctx, cam = this.cam;
      const passo = 6;
      for (let x = x0, n = 0; x < x1; x += passo, n++) {
        const par = (n + desl) % 2 === 0;
        const a = this._pt(x, y, 0), b = this._pt(x + passo, y, 0), c = this._pt(x + passo, y, alt), d = this._pt(x, y, alt);
        this._quad(a, b, c, d, par ? COR.pub[0] : COR.pub[1]);
        const k = (a[2] + b[2]) / 2;
        if (k > 9) {
          ctx.fillStyle = par ? '#ffcf1f' : '#1b3fae';
          ctx.font = `800 ${Math.max(7, 0.42 * k)}px "Big Shoulders Display", "Arial Narrow", Impact, sans-serif`;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('AC TRAVANCA', (a[0] + b[0]) / 2, (a[1] + d[1]) / 2);
        }
      }
    }

    _relva() {
      const ctx = this.ctx, cam = this.cam;
      this._poligonoChao([[-40, -2.6], [COMP + 40, -2.6], [COMP + 40, LARG + 8], [-40, LARG + 8]], COR.fora);
      const listras = 12, w = COMP / listras;
      for (let i = 0; i < listras; i++) {
        this._poligonoChao([[i * w, 0], [(i + 1) * w, 0], [(i + 1) * w, LARG], [i * w, LARG]], COR.relva[i % 2]);
      }
      // linhas
      const k = cam.p(30, 20, 0, P)[2];
      ctx.strokeStyle = COR.linha; ctx.lineWidth = Math.max(1.4, 0.15 * k); ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      this._linhaChao([[0, 0], [COMP, 0], [COMP, LARG], [0, LARG]], true);
      this._linhaChao([[COMP / 2, 0], [COMP / 2, LARG]]);
      const circ = (cx, cy, r, a0, a1) => {
        const pts = [];
        for (let i = 0; i <= 40; i++) { const a = a0 + (a1 - a0) * i / 40; pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); }
        this._linhaChao(pts);
      };
      circ(COMP / 2, CY, 5, 0, TAU);
      // áreas (grande 10 × 22, pequena 4 × 11, marca a 6 m)
      for (const s of [0, 1]) {
        const x = s ? COMP : 0, d = s ? -1 : 1;
        this._linhaChao([[x, 9], [x + d * 10, 9], [x + d * 10, 31], [x, 31]]);
        this._linhaChao([[x, 14.5], [x + d * 4, 14.5], [x + d * 4, 25.5], [x, 25.5]]);
        circ(x + d * 6, CY, 5, s ? Math.PI - 0.93 : -0.93 + 0.0, s ? Math.PI + 0.93 : 0.93);
        // marca do penálti
        cam.p(x + d * 6, CY, 0, P);
        ctx.fillStyle = COR.linha; ctx.beginPath(); ctx.arc(P[0], P[1], Math.max(1.4, 0.2 * P[2]), 0, TAU); ctx.fill();
      }
      cam.p(COMP / 2, CY, 0, P);
      ctx.fillStyle = COR.linha; ctx.beginPath(); ctx.arc(P[0], P[1], Math.max(1.6, 0.22 * P[2]), 0, TAU); ctx.fill();
      // cantos
      for (const [cx, cy, ax, ay] of [[0, 0, 1, 1], [COMP, 0, -1, 1], [0, LARG, 1, -1], [COMP, LARG, -1, -1]]) {
        const pts = [];
        for (let i = 0; i <= 8; i++) {
          const a = (i / 8) * Math.PI / 2;
          pts.push([cx + ax * Math.cos(a) * 1.0, cy + ay * Math.sin(a) * 1.0]);
        }
        this._linhaChao(pts);
      }
    }

    _bandeirolas() {
      const ctx = this.ctx;
      for (const [x, y] of [[0, 0], [COMP, 0], [0, LARG], [COMP, LARG]]) {
        this.cam.p(x, y, 0, P); this.cam.p(x, y, 1.6, Q);
        ctx.strokeStyle = '#f4f7ff'; ctx.lineWidth = Math.max(1, 0.05 * P[2]);
        ctx.beginPath(); ctx.moveTo(P[0], P[1]); ctx.lineTo(Q[0], Q[1]); ctx.stroke();
        const dir = x === 0 ? 1 : -1;
        this.cam.p(x + dir * 0.55, y, 1.45, R);
        this.cam.p(x, y, 1.25, P);
        ctx.fillStyle = '#ffcf1f';
        ctx.beginPath(); ctx.moveTo(Q[0], Q[1]); ctx.lineTo(R[0], R[1]); ctx.lineTo(P[0], P[1]); ctx.closePath(); ctx.fill();
      }
    }

    /** Rede da baliza (atrás dos jogadores) e, depois, a moldura (à frente). */
    _rede(x) {
      const ctx = this.ctx, cam = this.cam;
      const d = x === 0 ? -1 : 1;                              // a rede fica para lá da linha de fundo
      const y0 = CY - TRAVE, y1 = CY + TRAVE;
      const f0 = this._pt(x, y0, 0), f1 = this._pt(x, y1, 0), f2 = this._pt(x, y1, ALT_BAL), f3 = this._pt(x, y0, ALT_BAL);
      const xb = x + d * PROF_REDE;
      const b0 = this._pt(xb, y0, 0), b1 = this._pt(xb, y1, 0), b2 = this._pt(xb, y1, ALT_BAL * 0.82), b3 = this._pt(xb, y0, ALT_BAL * 0.82);
      ctx.fillStyle = 'rgba(244,247,255,0.10)';
      this._quad(b0, b1, b2, b3, 'rgba(244,247,255,0.13)');
      this._quad(f3, f2, b2, b3, 'rgba(244,247,255,0.10)');
      this._quad(f0, b0, b3, f3, 'rgba(244,247,255,0.09)');
      this._quad(f1, b1, b2, f2, 'rgba(244,247,255,0.09)');
      ctx.strokeStyle = 'rgba(244,247,255,0.35)'; ctx.lineWidth = 1;
      ctx.beginPath();
      const malha = 8;
      for (let i = 1; i < malha; i++) {
        const u = i / malha;
        const ya = y0 + (y1 - y0) * u;
        const ab = this._pt(xb, ya, 0), at = this._pt(xb, ya, ALT_BAL * 0.82);
        ctx.moveTo(ab[0], ab[1]); ctx.lineTo(at[0], at[1]);
        const fa = this._pt(x, ya, ALT_BAL), ba = this._pt(xb, ya, ALT_BAL * 0.82);
        ctx.moveTo(fa[0], fa[1]); ctx.lineTo(ba[0], ba[1]);
      }
      for (let i = 1; i < 5; i++) {
        const z = (ALT_BAL * 0.82) * i / 5;
        const l = this._pt(xb, y0, z), r = this._pt(xb, y1, z);
        ctx.moveTo(l[0], l[1]); ctx.lineTo(r[0], r[1]);
      }
      ctx.stroke();
    }

    _moldura(x) {
      const ctx = this.ctx;
      const y0 = CY - TRAVE, y1 = CY + TRAVE;
      const a = this._pt(x, y0, 0), b = this._pt(x, y0, ALT_BAL), c = this._pt(x, y1, ALT_BAL), d = this._pt(x, y1, 0);
      ctx.strokeStyle = '#f7f9ff'; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.lineWidth = Math.max(2, 0.14 * (a[2] + d[2]) / 2);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(c[0], c[1]); ctx.lineTo(d[0], d[1]); ctx.stroke();
    }

    /* ------------------------------------------------------------------ jogadores */
    _animar(a, F, t, dt, reset) {
      const i = a.i;
      const p = F.pos(i, t, this._pp);
      a.x = p[0]; a.y = p[1];
      const v = F.velocidade(i, t, this._v);
      const sp = Math.hypot(v[0], v[1]);
      const fr = F.frente(i, t, this._f);
      const alvo = Math.atan2(fr[1], fr[0]);
      if (reset) { a.ang = alvo; a.vel = sp; }
      else {
        const d = angDif(a.ang, alvo), max = 15 * dt;
        a.ang += lim(d * Math.min(1, 16 * dt), -max, max);
        a.vel += (sp - a.vel) * Math.min(1, 14 * dt);
        a.fase += Math.min(a.vel, 9) * Math.min(dt, 0.1) * 2.3;
      }
      a.vx = v[0]; a.vy = v[1]; a.sp = sp;
    }

    /**
     * Calcula a pose (pontos 3D) de uma figura. `an`: animação em curso (ou null); `u`: progresso (0–1).
     * Devolve um objeto reutilizado.
     */
    _pose(a, an, t) {
      const po = a._pose || (a._pose = {});
      const dx = Math.cos(a.ang), dy = Math.sin(a.ang);          // frente (chão)
      const sx = -dy, sy = dx;                                    // lado
      const run = suave(a.vel, 0.4, 5.5);
      const ph = a.fase;
      let amp = (0.18 + 0.50 * run) * (a.vel < 0.4 ? 0 : 1);
      let hz = 0.90 * a.altura, tilt = 0.10 * run + (a.vel > 6 ? 0.06 : 0);          // inclinação do tronco para a frente
      let tx = dx, ty = dy;                                        // para onde o tronco se inclina
      let pernas = [Math.sin(ph) * amp, Math.sin(ph + Math.PI) * amp];
      let bracos = [-Math.sin(ph) * amp * 1.15, -Math.sin(ph + Math.PI) * amp * 1.15];
      let levantaB = [0, 0], abreB = [0.25, 0.25];                // braços: levantar e afastar
      let kneeB = [Math.max(0, Math.cos(ph)) * run, Math.max(0, Math.cos(ph + Math.PI)) * run];
      let saltoZ = 0, luvasAltas = false, deitado = 0, cabeca_extra = 0;
      let modo = 0;
      const gr = a.papel === 0;
      if (gr && a.vel < 2.0) { levantaB = [0.35, 0.35]; abreB = [0.55, 0.55]; pernas[0] *= 0.4; pernas[1] *= 0.4; hz -= 0.06; tilt = 0.12; }
      if (!an) {
        // pose natural: parado, braços ligeiramente afastados
        if (run < 0.05) { pernas = [0.05, -0.05]; bracos = [0.03, -0.03]; }
      } else {
        const dur = an.dur;
        let u = (t - an.t) / Math.max(0.01, dur);
        const ate = an.cod;
        if (ate === A.CHUTA) {
          const forte = an.a > 0.5;
          const e = lim(u, 0, 1);
          // perna de remate: balanço para trás, estalo, acompanhamento
          const th = e < 0.38 ? -1.0 * suave(e, 0, 0.38) : (e < 0.55 ? -1.0 + 2.55 * suave(e, 0.38, 0.55) : 1.55 - 0.45 * suave(e, 0.55, 1));
          pernas = [th, 0.12];
          bracos = [0.5 * th * -1, 0.7 * th];
          kneeB = [e < 0.5 ? 0.9 : 0.15, 0];
          tilt = forte ? -0.22 * Math.sin(Math.PI * lim(e, 0, 1)) + 0.1 : 0.05;
          hz -= 0.03;
          abreB = [0.4, 0.4];
        } else if (ate === A.LANCA) {
          const e = lim(u, 0, 1);
          const braco = e < 0.45 ? -2.6 * suave(e, 0, 0.45) : -2.6 + 3.6 * suave(e, 0.45, 0.9);   // para trás da cabeça e para a frente
          bracos = [braco, braco]; levantaB = [1, 1]; abreB = [0.12, 0.12];
          pernas = [0.35, -0.55];
          tilt = e < 0.45 ? -0.2 : 0.4 * suave(e, 0.45, 0.8);
          modo = 1;
        } else if (ate === A.DESARMA || ate === A.FALTA) {
          const e = lim(u, 0, 1);
          const k = Math.sin(Math.PI * Math.min(1, e * 1.15));                // desce e volta a levantar-se
          deitado = (ate === A.DESARMA ? 1.15 : 0.5) * k;                    // inclinação para trás (deslize)
          tx = -dx; ty = -dy;
          pernas = [1.15 * k, 0.15]; bracos = [0.6, -0.6]; abreB = [0.9 * k + 0.25, 0.9 * k + 0.25];
          kneeB = [0.2, 0.2];
        } else if (ate === A.CAI) {
          const e = lim(u, 0, 1);
          const baixo = suave(e, 0, 0.18);
          const sobe = 1 - suave(e, 0.88, 1);
          deitado = 1.45 * baixo * (an.dur > 1.0 ? 1 : sobe);
          const lado = hash(a.i * 17 + Math.floor(an.t * 10)) < 0.5 ? 1 : -1;
          const ang2 = a.ang + Math.PI * (0.55 * lado + 0.45);                 // cai para trás/de lado
          tx = Math.cos(ang2); ty = Math.sin(ang2);
          pernas = [0.3, -0.2]; bracos = [1.0, 0.6]; abreB = [1.0, 1.0]; levantaB = [0.6, 0.4];
        } else if (ate === A.LEVANTA) {
          const e = lim(u, 0, 1);
          deitado = 1.45 * (1 - suave(e, 0, 1));
          const ang2 = a.ang + Math.PI;
          tx = Math.cos(ang2); ty = Math.sin(ang2);
          pernas = [0.2, -0.2]; bracos = [0.4, 0.3]; abreB = [0.6, 0.6];
        } else if (ate === A.VOA) {
          const e = lim(u, 0, 1);
          const lado = an.a >= 0 ? 1 : -1;                                      // +1 = para y crescente
          const forte = an.b > 0.5;
          const voo = suave(e, 0, 0.32);
          const chao = 1 - suave(e, 0.78, 1.0);
          deitado = (forte ? 1.38 : 0.55) * voo * chao;
          tx = 0; ty = lado;
          saltoZ = forte ? 0.55 * Math.sin(Math.PI * Math.min(1, e * 1.25)) : 0.1 * Math.sin(Math.PI * e);
          levantaB = [1, 1]; abreB = [0.1 + 0.2 * (1 - voo), 0.1 + 0.2 * (1 - voo)]; bracos = [0.3, 0.3];
          pernas = [0.35, -0.45]; luvasAltas = true;
          if (deitado > 0.3) { levantaB = [1.1, 1.1]; }
        } else if (ate === A.CABECEIA) {
          const e = lim(u, 0, 1);
          saltoZ = 0.50 * Math.sin(Math.PI * e);
          tilt = e < 0.5 ? -0.25 * suave(e, 0.1, 0.5) : -0.25 + 0.75 * suave(e, 0.5, 0.78);
          pernas = [0.5 * Math.sin(Math.PI * e), -0.5 * Math.sin(Math.PI * e)]; kneeB = [1, 0.6];
          bracos = [0.8, 0.8]; abreB = [1.0, 1.0]; levantaB = [0.7, 0.7];
        } else if (ate === A.FESTEJA) {
          const quique = Math.abs(Math.sin(t * 6.2 + a.i));
          saltoZ = a.vel < 2.5 ? 0.22 * quique : 0.05 * quique;
          levantaB = [1.25, 1.25]; abreB = [0.55, 0.55]; bracos = [0.2, 0.2];
          if (a.vel < 1.0) pernas = [0.2 * Math.sin(t * 6.2), -0.2 * Math.sin(t * 6.2)];
          tilt = a.vel > 3 ? 0.08 : -0.05;
          luvasAltas = false; cabeca_extra = -0.04;
        } else if (ate === A.DEFENDE) {
          const e = lim(u, 0, 1);
          const k = Math.sin(Math.PI * e);
          abreB = [0.9 * k + 0.2, 0.9 * k + 0.2]; levantaB = [0.4 * k, 0.4 * k];
          bracos = [0.3, 0.3];
          hz -= 0.08 * k; tilt = -0.18 * k;
          if (!gr) { tx = -dx; ty = -dy; deitado = 0.18 * k; }
        }
      }
      po.dx = dx; po.dy = dy; po.sx = sx; po.sy = sy;
      po.run = run; po.fase = ph;
      // eixo do tronco (hip -> ombros)
      const inc = tilt + deitado;
      const sInc = Math.sin(inc), cInc = Math.cos(inc);
      let ax = tx * sInc, ay = ty * sInc, az = cInc;
      if (deitado > 0) { /* já está em tx,ty */ }
      po.ax = ax; po.ay = ay; po.az = az;
      // anca
      const alt = hz;
      let hzz = alt * cInc + 0.20 * Math.sin(Math.min(inc, Math.PI / 2)) + saltoZ;
      if (inc > 0.6) hzz = Math.max(hzz, 0.22);
      po.hz = hzz;
      po.pernas = pernas; po.bracos = bracos; po.levantaB = levantaB; po.abreB = abreB; po.kneeB = kneeB;
      po.gr = gr; po.luvasAltas = luvasAltas; po.deitado = deitado; po.cabeca_extra = cabeca_extra; po.modo = modo;
      po.sp = a.vel;
      return po;
    }

    /** Desenha uma figura na posição (x, y) com a pose calculada. */
    _figura(a, po, opc) {
      const ctx = this.ctx, cam = this.cam, kit = a.kit;
      const x = a.x, y = a.y;
      const hx = x, hy = y, hz = po.hz;
      const alt = a.altura;
      const sombra = opc && opc.sombra !== false;
      cam.p(x, y, 0, P);
      const k = P[2], base = [P[0], P[1]];

      // sombra no chão (uma elipse)
      if (sombra) {
        ctx.fillStyle = COR.sombra;
        ctx.beginPath();
        const rx = (0.38 + 0.5 * po.deitado * 0.4) * k, ry = rx * 0.38;
        ctx.ellipse(base[0] + k * 0.05, base[1] + k * 0.02, rx * (1 + po.deitado * 0.6), ry * (1 + po.deitado * 0.2), 0, 0, TAU);
        ctx.fill();
      }

      const dx = po.dx, dy = po.dy, sx = po.sx, sy = po.sy;
      const ax = po.ax, ay = po.ay, az = po.az;
      const ombroL = 0.52 * alt;                       // comprimento do tronco
      const perna = 0.90 * alt;

      // pontos 3D
      const quadril = (s) => [hx + sx * 0.10 * s, hy + sy * 0.10 * s, hz];
      const ombrosC = [hx + ax * ombroL, hy + ay * ombroL, hz + az * ombroL];
      const ombro = (s) => [ombrosC[0] + sx * 0.21 * s, ombrosC[1] + sy * 0.21 * s, ombrosC[2] - 0.02];
      const cabeca = [ombrosC[0] + ax * 0.22 * alt + dx * 0.02, ombrosC[1] + ay * 0.22 * alt + dy * 0.02, ombrosC[2] + az * 0.22 * alt + po.cabeca_extra];

      const membros = [];
      // pernas
      for (let i = 0; i < 2; i++) {
        const s = i === 0 ? -1 : 1;
        const hj = quadril(s);
        const th = po.pernas[i];
        const lx = -ax * Math.cos(th) + dx * Math.sin(th), ly = -ay * Math.cos(th) + dy * Math.sin(th), lz = -az * Math.cos(th);
        const lm = Math.hypot(lx, ly, lz) || 1;
        let fx = hj[0] + lx / lm * perna, fy = hj[1] + ly / lm * perna, fz = hj[2] + lz / lm * perna;
        fz = Math.max(0.03, fz);
        const kb = po.kneeB[i];
        const joelho = [hj[0] + (fx - hj[0]) * 0.5 + dx * 0.16 * kb, hj[1] + (fy - hj[1]) * 0.5 + dy * 0.16 * kb, Math.max(0.1, hj[2] + (fz - hj[2]) * 0.5 + 0.05 * kb)];
        const pe = [fx, fy, fz];
        membros.push({ tipo: 'perna', d: (hj[1] + fy) / 2, hj, joelho, pe, s });
      }
      // braços
      for (let i = 0; i < 2; i++) {
        const s = i === 0 ? -1 : 1;
        const om = ombro(s);
        const th = po.bracos[i];
        const lev = po.levantaB[i], ab = po.abreB[i];
        // direção do braço: para baixo (−eixo) rodada para a frente/trás (th), levantada (lev) e afastada (ab)
        let vx = -ax * Math.cos(th) + dx * Math.sin(th), vy = -ay * Math.cos(th) + dy * Math.sin(th), vz = -az * Math.cos(th);
        // levantar: mistura com o eixo do tronco (para cima)
        vx = vx * (1 - lev) + ax * lev + dx * 0.25 * lev * (th > 0 ? 1 : 0); vy = vy * (1 - lev) + ay * lev + dy * 0.25 * lev * (th > 0 ? 1 : 0); vz = vz * (1 - lev) + az * lev;
        // afastar do corpo
        vx += sx * s * ab; vy += sy * s * ab;
        const vm = Math.hypot(vx, vy, vz) || 1;
        const La = 0.60 * alt;
        const mao = [om[0] + vx / vm * La, om[1] + vy / vm * La, Math.max(0.05, om[2] + vz / vm * La)];
        const cot = [om[0] + (mao[0] - om[0]) * 0.52 + dx * 0.05, om[1] + (mao[1] - om[1]) * 0.52 + dy * 0.05, om[2] + (mao[2] - om[2]) * 0.52];
        membros.push({ tipo: 'braco', d: (om[1] + mao[1]) / 2, om, cot, mao, s });
      }

      const torsoD = (hy + ombrosC[1]) / 2;
      const proj = (p) => cam.p(p[0], p[1], p[2], [0, 0, 0]);

      // limbs mais ao fundo primeiro
      membros.sort((m, n) => m.d - n.d);
      const antes = membros.filter((m) => m.d <= torsoD), depois = membros.filter((m) => m.d > torsoD);
      const desenharMembro = (m) => {
        if (m.tipo === 'perna') {
          const h = proj(m.hj), j = proj(m.joelho), p = proj(m.pe);
          const w = Math.max(1.8, 0.19 * k * 0.95);
          ctx.lineCap = 'round'; ctx.lineJoin = 'round';
          // coxa (calções) e perna (meia)
          const m1 = [h[0] + (j[0] - h[0]) * 0.8, h[1] + (j[1] - h[1]) * 0.8];
          ctx.strokeStyle = kit.calcoes; ctx.lineWidth = w * 1.18;
          ctx.beginPath(); ctx.moveTo(h[0], h[1]); ctx.lineTo(m1[0], m1[1]); ctx.stroke();
          ctx.strokeStyle = kit.meias; ctx.lineWidth = w * 0.85;
          ctx.beginPath(); ctx.moveTo(m1[0], m1[1]); ctx.lineTo(j[0], j[1]); ctx.lineTo(p[0], p[1]); ctx.stroke();
          // chuteira
          ctx.strokeStyle = '#10121c'; ctx.lineWidth = w * 0.95;
          const bx = p[0] + (p[0] - j[0]) * 0.0, by = p[1];
          const dirx = Math.sign(proj([m.pe[0] + dx * 0.2, m.pe[1] + dy * 0.2, m.pe[2]])[0] - p[0]);
          ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx + dirx * 0.14 * k, by + 0.01 * k); ctx.stroke();
        } else {
          const o = proj(m.om), c = proj(m.cot), mm = proj(m.mao);
          const w = Math.max(1.4, 0.12 * k);
          ctx.lineCap = 'round'; ctx.lineJoin = 'round';
          ctx.strokeStyle = kit.mangas; ctx.lineWidth = w * 1.25;
          ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(c[0], c[1]); ctx.stroke();
          ctx.strokeStyle = po.gr ? kit.mangas : a.pele; ctx.lineWidth = w * 0.95;
          ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(mm[0], mm[1]); ctx.stroke();
          if (po.gr) { ctx.fillStyle = kit.luvas || '#fff'; ctx.beginPath(); ctx.arc(mm[0], mm[1], Math.max(1.5, 0.095 * k), 0, TAU); ctx.fill(); }
        }
      };
      for (const m of antes) desenharMembro(m);

      // tronco: quadrilátero entre as ancas e os ombros
      const h0 = proj(quadril(-1)), h1 = proj(quadril(1));
      const o0 = proj(ombro(-1)), o1 = proj(ombro(1));
      ctx.fillStyle = kit.camisola;
      ctx.beginPath(); ctx.moveTo(h0[0], h0[1]); ctx.lineTo(h1[0], h1[1]); ctx.lineTo(o1[0], o1[1]); ctx.lineTo(o0[0], o0[1]); ctx.closePath(); ctx.fill();
      // calções (da anca para baixo)
      const c0 = proj([hx + sx * -0.11, hy + sy * -0.11, hz - 0.14 * alt]), c1 = proj([hx + sx * 0.11, hy + sy * 0.11, hz - 0.14 * alt]);
      ctx.fillStyle = kit.calcoes;
      ctx.beginPath(); ctx.moveTo(h0[0], h0[1]); ctx.lineTo(h1[0], h1[1]); ctx.lineTo(c1[0], c1[1]); ctx.lineTo(c0[0], c0[1]); ctx.closePath(); ctx.fill();
      // ombros arredondados (tapam a junção dos braços)
      ctx.fillStyle = kit.camisola;
      const rS = Math.max(1.2, 0.085 * k);
      ctx.beginPath(); ctx.arc(o0[0], o0[1], rS, 0, TAU); ctx.arc(o1[0], o1[1], rS, 0, TAU); ctx.fill();

      // número nas costas (quando de costas para a câmara)
      const costas = -(dy * cam.c + 0) + 0;      // dy < 0 → de costas para quem vê
      if (opc && opc.numero !== false && po.dy < -0.2 && k > 11 && po.deitado < 0.4 && a.numero) {
        const cx = (o0[0] + o1[0] + h0[0] + h1[0]) / 4, cyy = (o0[1] + o1[1] + h0[1] + h1[1]) / 4;
        ctx.fillStyle = kit.num; ctx.font = `800 ${Math.max(7, 0.30 * k)}px "Big Shoulders Display", "Arial Narrow", Impact, sans-serif`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(String(a.numero), cx, cyy);
      }

      // pescoço e cabeça
      const hd = proj(cabeca), oc = proj(ombrosC);
      ctx.strokeStyle = a.pele; ctx.lineWidth = Math.max(1.2, 0.09 * k); ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(oc[0], oc[1]); ctx.lineTo(hd[0], hd[1]); ctx.stroke();
      const rc = Math.max(2.2, 0.125 * k);
      ctx.fillStyle = a.pele; ctx.beginPath(); ctx.arc(hd[0], hd[1], rc, 0, TAU); ctx.fill();
      // cabelo: cobre mais a cabeça quando está de costas
      const cobre = lim(0.5 + 0.7 * (-po.dy), 0.45, 1.0);
      ctx.fillStyle = a.cabelo;
      ctx.beginPath();
      if (cobre >= 0.98) ctx.arc(hd[0], hd[1], rc * 1.02, 0, TAU);
      else { ctx.arc(hd[0], hd[1], rc * 1.03, Math.PI, TAU); ctx.quadraticCurveTo(hd[0], hd[1] - rc * (1 - cobre * 2.0 + 0.6), hd[0] - rc * 1.03, hd[1]); }
      ctx.fill();

      for (const m of depois) desenharMembro(m);

      return base;
    }

    /* ------------------------------------------------------------------ bola */
    _bola(F, t, dt, reset) {
      const o = F.bola(t, this._o);
      const est = this.bolaEst;
      est.vis = o[3] > 0;
      if (!est.vis) { est.trilho.length = 0; return null; }
      let x = o[0], y = o[1], z = o[2];
      // bola nas mãos (guarda-redes que a segura / lançamento lateral): à altura das mãos
      const tipo = o[4];
      let seguraPor = -1, mix = 0;
      if (tipo === B.CONDUZ && o[5] >= 0 && F.jog[o[5]][3] === 0) {
        const f = o[5];
        const sp = Math.hypot(this.atores[f].vx || 0, this.atores[f].vy || 0);
        if (sp < 3.2) { seguraPor = f; mix = 1; }
      } else if (tipo !== B.CONDUZ && tipo !== B.PARADA && tipo !== B.ESCONDIDA) {
        const dt0 = t - o[8], dt1 = o[9] - t;
        if (o[6] >= 0 && F.jog[o[6]][3] === 0 && dt0 < 0.3) { seguraPor = o[6]; mix = 1 - dt0 / 0.3; }
        else if (o[7] >= 0 && F.jog[o[7]][3] === 0 && dt1 < 0.22) { seguraPor = o[7]; mix = 1 - dt1 / 0.22; }
      }
      if (seguraPor >= 0) {
        const a = this.atores[seguraPor];
        const fx = Math.cos(a.ang), fy = Math.sin(a.ang);
        const mx = a.x + fx * 0.28, my = a.y + fy * 0.28;
        x = x + (mx - x) * mix * 0.9; y = y + (my - y) * mix * 0.9;
        z = z + (1.12 - z) * mix;
      }
      // lançamento lateral: a bola vai por cima da cabeça
      for (let f = 0; f < 14; f++) {
        const an = F.animacao(f, t);
        if (an && an.cod === A.LANCA) {
          const a = this.atores[f];
          if (Math.hypot(a.x - x, a.y - y) < 1.2) {
            const e = lim((t - an.t) / an.dur, 0, 1);
            const alt = e < 0.45 ? 1.5 + 0.7 * suave(e, 0, 0.45) : 2.1 - 0.9 * suave(e, 0.45, 0.85);
            x = a.x + Math.cos(a.ang) * (e < 0.45 ? -0.1 : 0.15 + 0.6 * suave(e, 0.45, 0.85)); y = a.y + Math.sin(a.ang) * (e < 0.45 ? -0.1 : 0.15 + 0.6 * suave(e, 0.45, 0.85));
            z = alt;
          }
          break;
        }
      }
      // rotação e trilho
      const dxm = x - est.ultimoX, dym = y - est.ultimoY;
      const dist = reset ? 0 : Math.hypot(dxm, dym);
      est.rot += Math.min(dist, 3) * 2.6;
      est.ultimoX = x; est.ultimoY = y;
      const vel = dt > 0 && !reset ? dist / dt : 0;
      est.vel = vel;
      return [x, y, z, vel];
    }

    _desenharBola(b, t, dt) {
      if (!b) return;
      const ctx = this.ctx, cam = this.cam, est = this.bolaEst;
      const [x, y, z, vel] = b;
      cam.p(x, y, 0, Q);       // chão
      cam.p(x, y, z, P);       // bola
      const k = P[2];
      // sombra: fica no chão, encolhe e esbate-se com a altura
      const alt = Math.max(0, z - 0.11);
      ctx.fillStyle = `rgba(0,0,0,${Math.max(0.12, 0.38 - alt * 0.06)})`;
      ctx.beginPath(); ctx.ellipse(Q[0] + alt * 0.04 * k, Q[1] + 0.01 * k, Math.max(2, 0.17 * k) * (1 + alt * 0.12), Math.max(1, 0.07 * k) * (1 + alt * 0.12), 0, 0, TAU); ctx.fill();
      // trilho (rápido)
      est.trilho.push([P[0], P[1]]);
      if (est.trilho.length > 6) est.trilho.shift();
      if (vel > 14 && est.trilho.length > 2) {
        ctx.strokeStyle = 'rgba(255,255,255,0.28)'; ctx.lineCap = 'round';
        for (let i = 1; i < est.trilho.length; i++) {
          ctx.lineWidth = Math.max(1, 0.11 * k * (i / est.trilho.length));
          ctx.beginPath(); ctx.moveTo(est.trilho[i - 1][0], est.trilho[i - 1][1]); ctx.lineTo(est.trilho[i][0], est.trilho[i][1]); ctx.stroke();
        }
      } else if (vel <= 14 && est.trilho.length > 1) est.trilho.splice(0, est.trilho.length - 1);
      const r = Math.max(3.8, 0.15 * k);
      ctx.fillStyle = COR.bola; ctx.strokeStyle = 'rgba(15,20,50,0.85)'; ctx.lineWidth = Math.max(0.8, r * 0.16);
      ctx.beginPath(); ctx.arc(P[0], P[1], r, 0, TAU); ctx.fill(); ctx.stroke();
      // gomos: dois pontos escuros que rodam
      ctx.fillStyle = 'rgba(20,28,70,0.9)';
      for (let i = 0; i < 3; i++) {
        const a = est.rot + i * 2.1;
        ctx.beginPath(); ctx.arc(P[0] + Math.cos(a) * r * 0.5, P[1] + Math.sin(a) * r * 0.42, r * 0.26, 0, TAU); ctx.fill();
      }
    }

    /* ------------------------------------------------------------------ nomes */
    _nome(a, base, k) {
      const ctx = this.ctx;
      const px = lim(0.55 * k, 9, 13);
      ctx.font = `700 ${px}px "Public Sans", system-ui, sans-serif`;
      const txt = a.nome;
      const w = ctx.measureText(txt).width + 10;
      const x = base[0] - w / 2, y = base[1] + 4;
      ctx.fillStyle = a.equipa === 0 ? 'rgba(255,207,31,0.92)' : 'rgba(47,90,230,0.94)';
      const r = (px + 5) / 2;
      ctx.beginPath();
      ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.arc(x + w - r, y + r, r, -Math.PI / 2, Math.PI / 2);
      ctx.lineTo(x + r, y + px + 5); ctx.arc(x + r, y + r, r, Math.PI / 2, Math.PI * 1.5);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = a.equipa === 0 ? '#0a1c63' : '#ffffff';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(txt, base[0], y + r + 0.5);
    }

    /* ------------------------------------------------------------------ árbitro */
    _atualizarArbitro(F, t, dt, reset, bx, by) {
      const r = this.arb;
      let ax = bx - 5 * Math.sign(bx - 30) * 0.0, ay = by;
      let alvoX = lim(bx * 0.92 + 2.4, 3, COMP - 3);
      let alvoY = by < 24 ? by + 9 : by - 9;
      alvoY = lim(alvoY, 4, LARG - 4);
      if (reset) { r.x = alvoX; r.y = alvoY; r.vel = 0; r.ang = 0; return; }
      const dxm = alvoX - r.x, dym = alvoY - r.y, d = Math.hypot(dxm, dym);
      const vmax = 5.4;
      const v = Math.min(vmax, d * 1.6);
      const passo = Math.min(d, v * Math.min(dt, 0.1));
      if (d > 1e-6) { r.x += dxm / d * passo; r.y += dym / d * passo; }
      r.vel += (v * (d > 0.6 ? 1 : 0) - r.vel) * Math.min(1, 6 * dt);
      const alvoAng = Math.atan2(by - r.y, bx - r.x);
      r.ang += angDif(r.ang, alvoAng) * Math.min(1, 6 * dt);
    }

    /* ------------------------------------------------------------------ quadro completo */
    desenhar(t, dt, reset) {
      const F = this.filme;
      if (!F) return;
      this.redimensionar();
      const ctx = this.ctx, W = this.W, H = this.H;
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      if (reset || this._reset) { reset = true; this._reset = false; }
      // posições e animações
      for (const a of this.atores) this._animar(a, F, t, dt, reset);
      const bola = this._bola(F, t, dt, reset);
      const bx = bola ? bola[0] : 30, by = bola ? bola[1] : 20;

      // câmara de televisão: segue a bola (olhando um pouco para onde ela vai); se o quadro for baixo, mostra mais campo
      this.janela = Math.min(COMP + 6, Math.max(this.janelaBase, this.W * this.cam.L / (3.0 * this.H)));
      let alvoCam = COMP / 2;
      if (this.janela < COMP + 4) {
        const fut = F.bolaNucleo(t + 0.35, this._bn);
        const fx = fut[3] > 0 ? fut[0] : bx;
        alvoCam = lim(0.62 * bx + 0.38 * fx, this.janela / 2 - 2.5, COMP - this.janela / 2 + 2.5);
      }
      if (reset) this.camX = alvoCam;
      else this.camX += (alvoCam - this.camX) * Math.min(1, 5.0 * Math.min(dt, 0.1));
      this.cam.ajustar(W, H, this.janela, this.camX, 0.885);

      this._atualizarArbitro(F, t, dt, reset, bx, by);

      this._fundo(t);
      this._relva();
      this._rede(0); this._rede(COMP);
      this._bandeirolas();

      // entidades por profundidade (mais longe primeiro)
      const lista = [];
      for (const a of this.atores) lista.push({ y: a.y, a });
      lista.push({ y: this.arb.y, arb: true });
      if (bola) lista.push({ y: bola[1] - 0.001, bola });
      lista.sort((m, n) => m.y - n.y);

      // sombra da bola primeiro quando está no ar? (já é desenhada com a bola)
      let portador = bola ? this._o[5] : -1;
      const etiquetas = [];
      for (const e of lista) {
        if (e.bola) { this._desenharBola(e.bola, t, dt); continue; }
        if (e.arb) {
          const ar = this.arbitro; ar.x = this.arb.x; ar.y = this.arb.y; ar.ang = this.arb.ang; ar.vel = this.arb.vel; ar.fase += Math.min(ar.vel, 9) * Math.min(dt, 0.1) * 2.3;
          const po = this._pose(ar, null, t);
          this._figura(ar, po, { numero: false });
          continue;
        }
        const a = e.a;
        const an = F.animacao(a.i, t, a.papel === 0 ? 0.45 : 0.0);
        const po = this._pose(a, an, t);
        const base = this._figura(a, po, {});
        if (this.mostrarNomes && a.i === portador && po.deitado < 0.5) etiquetas.push([a, base, this.cam.p(a.x, a.y, 0, R)[2]]);
      }

      this._moldura(0); this._moldura(COMP);
      for (const e of etiquetas) this._nome(e[0], e[1], e[2]);
      this._painel(LARG + 3.1, 0.8, -40, COMP + 40, 1);
    }

    /** Define até quando a bancada «salta» (golo). */
    festa(ate) { this.festaAte = ate; }
  }

  raiz.CenaJogo = { Cena };
})(typeof window !== 'undefined' ? window : globalThis);
