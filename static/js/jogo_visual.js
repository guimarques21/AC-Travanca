/* ==========================================================================
   jogo_visual.js — o «comando» da simulação visual (Passo 8)

   Pede o filme ao servidor (/filme), põe-no a correr no canvas (cena.js) e trata dos botões:
   play/pausa, velocidades, «Lances principais» ou «Jogo completo», próximo lance, barra de tempo com os golos,
   pausa automática no intervalo e acelerar os tempos mortos.

   A página nunca recarrega (a música de fundo não pára). O resultado e as estatísticas ficam escondidos até a
   simulação acabar (ou o jogador saltar para o fim), para não estragar a surpresa.
   ========================================================================== */

(function (raiz) {
  'use strict';

  const memoria = {};            // por sala: o que sobrevive a um redesenho do painel (o filme, o instante, a velocidade…)
  let ativo = null;

  const ler = (chave) => { try { return JSON.parse(sessionStorage.getItem(chave)); } catch (e) { return null; } };
  const gravar = (chave, v) => { try { sessionStorage.setItem(chave, JSON.stringify(v)); } catch (e) { /* ignora */ } };

  const VELOCIDADES = [1, 2, 4, 10, 30];
  const pad = (n) => String(n).padStart(2, '0');

  class Visual {
    constructor(el) {
      this.el = el;
      this.fim = el.closest('.cena');
      this.sala = el.dataset.sala || 'sala';
      this.chave = 'actravanca.visual.' + this.sala;
      this.url = el.dataset.urlFilme;
      this.nomeEu = el.dataset.eu || 'Tu';
      this.nomeAdv = el.dataset.adv || 'Adversário';
      this.q = (s) => el.querySelector(s);
      this.cv = this.q('.visual__tela');
      this.f = null;
      this.t = 0;
      this.playing = false;
      this.acabou = false;
      this.vel = 1;
      this.modo = 'lances';
      this.corte = null;
      this.segs = [];
      this.seg = 0;
      this.intervaloFeito = false;
      this.reset = true;
      this.ultimo = 0;
      this.salvoEm = 0;
      this.vivo = true;
      this.bannerChave = '';
      this.ultimoTextoChave = '';
      this._quadro = this._quadro.bind(this);
      this._ligarBotoes();

      const guardado = ler(this.chave) || {};
      const mem = memoria[this.sala];
      if (mem) { this.vel = mem.vel; this.modo = mem.modo; }
      else { if (VELOCIDADES.includes(guardado.vel)) this.vel = guardado.vel; if (guardado.modo === 'completo') this.modo = 'completo'; }
      this.vista = !!guardado.vista || !!(mem && mem.vista);

      if (this.vista) {                                      // já viu: mostra tudo e deixa só «Rever a simulação»
        this._revelar(false);
        this.el.classList.add('visual--recolhido');
        return;
      }
      this._carregar(mem && mem.f ? mem.f : null, mem);
    }

    /* ------------------------------------------------------------------ carregar */
    async _carregar(filme, mem) {
      this.el.classList.add('visual--a-carregar');
      this.el.classList.remove('visual--erro');
      try {
        if (!filme) {
          const r = await fetch(this.url, { credentials: 'same-origin' });
          if (!r.ok) throw new Error('HTTP ' + r.status);
          const dados = await r.json();
          filme = new raiz.FilmeJogo.Filme(dados);
        }
      } catch (e) {
        if (!this.vivo) return;
        this.el.classList.remove('visual--a-carregar');
        this.el.classList.add('visual--erro');
        this._revelar(false);                                // se falhar, o resultado aparece na mesma
        return;
      }
      if (!this.vivo) return;
      this.f = filme;
      memoria[this.sala] = Object.assign(memoria[this.sala] || {}, { f: filme, vel: this.vel, modo: this.modo });
      this.cena = new raiz.CenaJogo.Cena(this.cv);
      this.cena.definirFilme(filme);
      this._preparar();
      this.el.classList.remove('visual--a-carregar');
      this.el.classList.add('visual--pronta');
      const guardado = ler(this.chave) || {};
      let t0 = 0;
      if (mem && typeof mem.t === 'number') t0 = mem.t; else if (typeof guardado.t === 'number') t0 = guardado.t;
      if (t0 > 0 && t0 < filme.duracao - 3) this._saltar(t0, false);
      this.intervaloFeito = this.t > filme.parte + 0.5;
      this.playing = !(mem && mem.playing === false);       // depois de um redesenho do painel, continua como estava
      this._atualizarBotoes();
      this.ultimo = performance.now();
      this.raf = requestAnimationFrame(this._quadro);
    }

    /* ------------------------------------------------------------------ preparar (segmentos, barra, marcas) */
    _preparar() {
      const F = this.f;
      const segs = [{ ini: 0, fim: 5.5, rot: 'Pontapé de saída', tipo: 'inicio' }];
      F.lances.forEach((l) => segs.push({ ini: l.ini, fim: l.fim, rot: l.min + "'", tipo: l.tipo }));
      const pausa = F.duracao - 3000;
      segs.push({ ini: F.parte - 2.0, fim: F.parte + Math.min(6, pausa * 0.45), rot: 'Intervalo', tipo: 'intervalo' });
      segs.push({ ini: Math.max(0, F.duracao - 6), fim: F.duracao, rot: 'Fim do jogo', tipo: 'fim' });
      segs.sort((a, b) => a.ini - b.ini);
      const fund = [];
      for (const s of segs) {
        const u = fund[fund.length - 1];
        if (u && s.ini <= u.fim + 1.2) { u.fim = Math.max(u.fim, s.fim); if (s.tipo === 'golo') u.tipo = 'golo'; if (u.tipo === 'inicio' || u.tipo === 'fim') u.rot = u.rot; }
        else fund.push(Object.assign({}, s));
      }
      this.segs = fund;
      // barra de tempo
      const barra = this.q('.visual__marcas');
      barra.innerHTML = '';
      const pc = (t) => (100 * t / F.duracao).toFixed(3) + '%';
      this.segs.forEach((s) => {
        if (s.tipo === 'inicio' || s.tipo === 'fim' || s.tipo === 'intervalo') return;
        const i = document.createElement('i'); i.className = 'marca marca--lance';
        i.style.left = pc(s.ini); i.style.width = (100 * (s.fim - s.ini) / F.duracao).toFixed(3) + '%';
        barra.appendChild(i);
      });
      const meio = document.createElement('i'); meio.className = 'marca marca--meio'; meio.style.left = pc(F.parte); barra.appendChild(meio);
      let anterior = [0, 0];
      F.placar.forEach((p, k) => {
        if (k === 0) return;
        const d = document.createElement('i'); d.className = 'marca marca--golo marca--golo-' + (p.g[0] > anterior[0] ? 'eu' : 'adv');
        d.style.left = pc(p.t); barra.appendChild(d); anterior = p.g;
      });
      this.q('.visual__slider').setAttribute('aria-valuemax', String(Math.round(F.duracao)));
      this.q('.visual__eq--eu').textContent = this.nomeEu;
      this.q('.visual__eq--adv').textContent = this.nomeAdv;
      this._escolherSegmento();
    }

    /* ------------------------------------------------------------------ botões */
    _ligarBotoes() {
      const on = (sel, fn) => { const b = this.el.querySelector(sel); if (b) b.addEventListener('click', fn); };
      on('[data-vis="play"]', () => this._alternar());
      on('[data-vis="proximo"]', () => this._proximoLance());
      on('[data-vis="fim"]', () => this._saltarParaOFim());
      on('[data-vis="rever"]', () => this._rever());
      on('[data-vis="continuar"]', () => { this._esconder('.visual__intervalo'); this.playing = true; this.ultimo = performance.now(); this._atualizarBotoes(); });
      on('[data-vis="resultado"]', () => this._irParaResultado());
      on('[data-vis="repetir"]', () => this._rever());
      on('[data-vis="tentar"]', () => { this.el.classList.remove('visual--erro'); this._carregar(null, null); });
      on('[data-vis="ver-so-resultado"]', () => this._revelar(true));
      this.el.querySelectorAll('[data-vis-vel]').forEach((b) => b.addEventListener('click', () => this._velocidade(+b.dataset.visVel)));
      this.el.querySelectorAll('[data-vis-modo]').forEach((b) => b.addEventListener('click', () => this._modo(b.dataset.visModo)));
      const slider = this.q('.visual__slider');
      if (slider) {
        const posicao = (ev) => {
          const r = slider.getBoundingClientRect();
          return Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)) * (this.f ? this.f.duracao : 0);
        };
        let arrasta = false;
        slider.addEventListener('pointerdown', (ev) => { if (!this.f) return; arrasta = true; slider.setPointerCapture(ev.pointerId); this._procurar(posicao(ev)); });
        slider.addEventListener('pointermove', (ev) => { if (arrasta) this._procurar(posicao(ev)); });
        const solta = () => { arrasta = false; };
        slider.addEventListener('pointerup', solta); slider.addEventListener('pointercancel', solta);
        slider.addEventListener('keydown', (ev) => this._tecla(ev));
      }
      const quadro = this.q('.visual__quadro');
      if (quadro) quadro.addEventListener('keydown', (ev) => this._tecla(ev));
      if (this.cv) this.cv.addEventListener('click', () => { if (this.f && !this.acabou) this._alternar(); });
      this._atualizarBotoes();
    }

    _tecla(ev) {
      if (!this.f || ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const k = ev.key;
      if (k === ' ' || k === 'k' || k === 'K') { if (ev.target.closest('button')) return; ev.preventDefault(); this._alternar(); }
      else if (k === 'ArrowRight') { ev.preventDefault(); this.modo === 'lances' ? this._proximoLance() : this._procurar(this.t + 10); }
      else if (k === 'ArrowLeft') { ev.preventDefault(); this.modo === 'lances' ? this._lanceAnterior() : this._procurar(this.t - 10); }
      else if (k === 'n' || k === 'N') { ev.preventDefault(); this._proximoLance(); }
      else if (k === 'Home') { ev.preventDefault(); this._procurar(0); }
      else if (k === 'End') { ev.preventDefault(); this._saltarParaOFim(); }
      else if (k >= '1' && k <= '5') { this._velocidade(VELOCIDADES[+k - 1]); }
    }

    _atualizarBotoes() {
      const play = this.q('[data-vis="play"]');
      if (play) {
        play.setAttribute('aria-label', this.playing ? 'Pausa' : (this.acabou ? 'Ver outra vez' : 'Continuar'));
        play.querySelector('.vb__texto').textContent = this.playing ? 'Pausa' : (this.acabou ? 'Outra vez' : 'Continuar');
        play.dataset.estado = this.playing ? 'a-tocar' : 'parado';
      }
      this.el.querySelectorAll('[data-vis-vel]').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.visVel === this.vel)));
      this.el.querySelectorAll('[data-vis-modo]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.visModo === this.modo)));
      const prox = this.q('[data-vis="proximo"]');
      if (prox) prox.disabled = !this.f || this.acabou;
    }

    _alternar() {
      if (!this.f) return;
      if (this.acabou) { this._rever(); return; }
      this._esconder('.visual__intervalo');
      this.playing = !this.playing;
      this.ultimo = performance.now();
      this._atualizarBotoes();
    }

    _velocidade(v) {
      if (!VELOCIDADES.includes(v)) return;
      this.vel = v;
      memoria[this.sala] = Object.assign(memoria[this.sala] || {}, { vel: v });
      this._atualizarBotoes();
      this._guardar(true);
    }

    _modo(m) {
      if (m !== 'lances' && m !== 'completo') return;
      this.modo = m;
      memoria[this.sala] = Object.assign(memoria[this.sala] || {}, { modo: m });
      if (this.f) { this._escolherSegmento(); if (m === 'lances') this._entrarNoSegmento(); }
      this._atualizarBotoes();
      this._guardar(true);
    }

    /* ------------------------------------------------------------------ navegação no tempo */
    _escolherSegmento() {
      // o segmento em que estamos (ou o próximo)
      let i = 0;
      while (i < this.segs.length - 1 && this.t > this.segs[i].fim) i++;
      this.seg = i;
    }

    _entrarNoSegmento() {
      // em «Lances principais», se estamos entre dois lances salta para o próximo
      const s = this.segs[this.seg];
      if (s && this.t < s.ini - 0.01) this._cortarPara(this.seg);
    }

    _saltar(t, esconder) {
      this.t = Math.min(this.f.duracao, Math.max(0, t));
      this.reset = true;
      if (this.cena) this.cena.reiniciar();
      this._escolherSegmento();
      this.intervaloFeito = this.t > this.f.parte + 0.5;
      this.acabou = false;
      this.el.classList.remove('visual--terminada');
      this._esconder('.visual__intervalo');
      if (esconder !== false) this.corte = null;
    }

    _procurar(t) {
      if (!this.f) return;
      this.corte = null;
      this._saltar(t);
      if (this.modo === 'lances') this._entrarNoSegmento();
      this._atualizarBotoes();
      this._guardar(true);
    }

    _cortarPara(idx) {
      const s = this.segs[idx];
      if (!s) return;
      this.corte = { fase: 0, dur: 0.22, idx, rot: s.rot, mostrar: 0 };
    }

    _proximoLance() {
      if (!this.f || this.acabou) return;
      this._esconder('.visual__intervalo');
      let i = this.segs.findIndex((s) => s.ini > this.t + 0.8 && s.tipo !== 'inicio');
      if (i < 0) { this._saltarParaOFim(); return; }
      if (this.segs[i].tipo === 'fim') { this._saltarParaOFim(); return; }
      this.playing = true; this.ultimo = performance.now();
      this._cortarPara(i);
      this._atualizarBotoes();
    }

    _lanceAnterior() {
      if (!this.f) return;
      let i = this.seg;
      if (this.t - this.segs[i].ini < 3 && i > 0) i--;
      this._esconder('.visual__intervalo');
      this._cortarPara(i);
    }

    _saltarParaOFim() {
      if (!this.f) { this.vista = true; this._guardar(true, true); this._revelar(true); return; }
      this.t = this.f.duracao;
      this.cena.reiniciar();
      this._terminar(true);
    }

    _rever() {
      if (this.el.classList.contains('visual--recolhido')) {
        this.el.classList.remove('visual--recolhido');
        if (!this.f) { this._carregar(memoria[this.sala] && memoria[this.sala].f, null); return; }
      }
      if (!this.f) return;
      this.corte = null;
      this._saltar(0);
      this.playing = true; this.ultimo = performance.now();
      this.q('.visual__fimjogo').hidden = true;
      this._esconder('.visual__intervalo');
      this._atualizarBotoes();
      if (!this.raf) this.raf = requestAnimationFrame(this._quadro);
      this.el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }

    _terminar(saltou) {
      this.playing = false;
      this.acabou = true;
      this.el.classList.add('visual--terminada');
      this.q('.visual__fimjogo').hidden = false;
      this._atualizarBotoes();
      this._revelar(false);
      this._guardar(true, true);
      const an = document.getElementById('anuncio');
      if (an && this.fim && this.fim.dataset.resultado) an.textContent = this.fim.dataset.resultado;
      if (saltou) this._irParaResultado();
    }

    _irParaResultado() {
      const alvo = this.fim && this.fim.querySelector('.fim__topo');
      if (!alvo) return;
      const reduz = raiz.matchMedia && raiz.matchMedia('(prefers-reduced-motion: reduce)').matches;
      alvo.scrollIntoView({ block: 'start', behavior: reduz ? 'auto' : 'smooth' });
      const h = alvo.querySelector('h1');
      if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    }

    /** Mostra o resultado e as estatísticas (que estavam escondidos). */
    _revelar(ir) {
      if (this.fim) this.fim.classList.add('cena--vista');
      if (ir) this._irParaResultado();
    }

    /* ------------------------------------------------------------------ estado guardado */
    _guardar(ja, vista) {
      const agora = performance.now();
      if (!ja && agora - this.salvoEm < 1500) return;
      this.salvoEm = agora;
      const v = !!vista || this.vista || this.acabou;
      if (v) this.vista = true;
      gravar(this.chave, { t: this.acabou ? 0 : Math.round(this.t * 10) / 10, vel: this.vel, modo: this.modo, vista: v });
      memoria[this.sala] = Object.assign(memoria[this.sala] || {}, { t: this.acabou ? 0 : this.t, vel: this.vel, modo: this.modo, vista: v, playing: this.playing });
    }

    _esconder(sel) { const e = this.q(sel); if (e) e.hidden = true; }

    /* ------------------------------------------------------------------ o relógio do filme */
    _avancar(dt) {
      const F = this.f;
      if (this.corte) { this._passoDoCorte(dt); return; }
      let fator = this.vel;
      if (this.modo === 'completo' && this.vel <= 2 && F.emMorto(this.t)) fator *= 4;     // tempos mortos passam depressa
      let novo = this.t + dt * fator;

      // intervalo: pára sozinho
      if (!this.intervaloFeito && this.t < F.parte && novo >= F.parte) {
        this.t = F.parte; this.intervaloFeito = true; this.playing = false;
        const p = F.placarEm(F.parte);
        this.q('.visual__intervalo-placar').textContent = `${this.nomeEu} ${p[0]} – ${p[1]} ${this.nomeAdv}`;
        this.q('.visual__intervalo').hidden = false;
        this._atualizarBotoes();
        const b = this.q('[data-vis="continuar"]'); if (b) b.focus({ preventScroll: true });
        return;
      }
      if (this.modo === 'lances') {
        const s = this.segs[this.seg];
        if (s && novo > s.fim) {
          if (this.seg >= this.segs.length - 1 || s.tipo === 'fim') { this.t = F.duracao; this._terminar(false); return; }
          this._cortarPara(this.seg + 1);
          return;
        }
      }
      if (novo >= F.duracao) { this.t = F.duracao; this._terminar(false); return; }
      this.t = novo;
      if (this.modo === 'completo') this._escolherSegmento();
    }

    _passoDoCorte(dt) {
      const c = this.corte;
      c.fase += dt;
      if (c.fase < c.dur) { c.opac = c.fase / c.dur; return; }
      if (!c.feito) {
        c.feito = true;
        const s = this.segs[c.idx];
        this.seg = c.idx;
        this.t = s.ini;
        if (!this.intervaloFeito && s.ini >= this.f.parte) this.intervaloFeito = true;
        if (s.tipo === 'intervalo') this.intervaloFeito = false;
        this.reset = true; this.cena.reiniciar();
        c.rotulo = s.rot; c.mostrar = 1.0;
      }
      const depois = c.fase - c.dur;
      if (depois < c.dur) { c.opac = 1 - depois / c.dur; return; }
      this.corte = null;
      const el = this.q('.visual__corte'); el.style.opacity = '0';
    }

    /* ------------------------------------------------------------------ cada fotograma */
    _quadro(agora) {
      if (!this.vivo) return;
      this.raf = requestAnimationFrame(this._quadro);
      if (!this.el.isConnected) { this.destruir(); return; }
      const F = this.f;
      if (!F) return;
      let dtReal = (agora - this.ultimo) / 1000;
      this.ultimo = agora;
      if (!(dtReal > 0)) dtReal = 0;
      dtReal = Math.min(dtReal, 0.1);
      const antes = this.t;
      if (this.playing && !this.acabou) this._avancar(dtReal);
      else if (this.corte) this._passoDoCorte(dtReal);
      const dtFilme = Math.max(0, Math.min(2.5, this.t - antes));
      const reset = this.reset || this.t < antes - 0.001 || (dtFilme > 2.0);
      this.reset = false;
      this.cena.desenhar(this.t, dtFilme, reset);
      this._hud();
      this._guardar(false);
    }

    _hud() {
      const F = this.f, t = this.t;
      const g = F.placarEm(t);
      const gEu = this.q('.visual__g--eu'), gAdv = this.q('.visual__g--adv');
      if (gEu.textContent !== String(g[0])) gEu.textContent = g[0];
      if (gAdv.textContent !== String(g[1])) gAdv.textContent = g[1];
      // relógio
      const s = F.segundosDeJogo(t);
      const rel = `${pad(Math.floor(s / 60))}:${pad(Math.floor(s % 60))}`;
      const pausa = F.duracao - 3000;
      let parte = t < F.parte ? '1.ª parte' : (t < F.parte + pausa ? 'Intervalo' : '2.ª parte');
      if (this.acabou) parte = 'Fim do jogo';
      const relEl = this.q('.visual__relogio'), parteEl = this.q('.visual__parte');
      if (relEl.textContent !== rel) relEl.textContent = rel;
      if (parteEl.textContent !== parte) parteEl.textContent = parte;
      // comentário
      const tx = F.textoEm(t, 7);
      const chaveT = tx ? tx.t + '|' + tx.texto : '';
      if (chaveT !== this.ultimoTextoChave) {
        this.ultimoTextoChave = chaveT;
        const el = this.q('.visual__texto');
        el.textContent = tx ? tx.texto : '';
        el.dataset.tipo = tx ? tx.tipo : '0';
      }
      // golos: letreiro e festa na bancada
      let golo = null;
      for (let i = F.placar.length - 1; i >= 1; i--) { if (F.placar[i].t <= t) { golo = F.placar[i]; break; } }
      const emGolo = golo && t - golo.t < 5.0 ? golo : null;
      const chaveB = emGolo ? String(emGolo.t) : '';
      if (chaveB !== this.bannerChave) {
        this.bannerChave = chaveB;
        const b = this.q('.visual__banner');
        if (emGolo) {
          const ant = F.placar[F.placar.indexOf(emGolo) - 1] || { g: [0, 0] };
          const meu = emGolo.g[0] > ant.g[0];
          const texto = F.textos.find((x) => x.tipo === 1 && x.texto.startsWith('GOLO!') && Math.abs(x.t - emGolo.t) < 0.5);
          b.querySelector('.visual__banner-sub').textContent = texto ? texto.texto.replace(/^GOLO!\s*/, '') : '';
          b.dataset.lado = meu ? 'eu' : 'adv';
          b.hidden = false;
          b.classList.remove('visual__banner--anima'); void b.offsetWidth; b.classList.add('visual__banner--anima');
          const an = document.getElementById('anuncio');
          if (an && texto) an.textContent = texto.texto;
        } else b.hidden = true;
      }
      this.cena.festa(golo && t - golo.t < 7 ? golo.t + 7 : -1);
      // corte (fade) e legenda do minuto
      const corte = this.q('.visual__corte');
      if (this.corte) {
        const c = this.corte;
        corte.style.opacity = String(Math.min(1, Math.max(0, c.opac || 0)));
        const rot = this.q('.visual__corte-texto');
        if (c.rotulo && rot.textContent !== c.rotulo) rot.textContent = c.rotulo;
        if (!c.rotulo) rot.textContent = '';
      }
      // barra de tempo
      const pc = 100 * t / F.duracao;
      this.q('.visual__prog').style.width = pc.toFixed(2) + '%';
      const sl = this.q('.visual__slider');
      sl.setAttribute('aria-valuenow', String(Math.round(t)));
      sl.setAttribute('aria-valuetext', `${rel}, ${parte}`);
    }

    destruir() {
      this.vivo = false;
      if (this.raf) cancelAnimationFrame(this.raf);
      this.raf = 0;
      this._guardar(true);
    }
  }

  const JogoVisual = {
    /** Procura a simulação no painel e põe-na a funcionar (chamada sempre que o painel é redesenhado). */
    iniciar() {
      const el = document.querySelector('.visual[data-url-filme]');
      if (!el) { if (ativo) { ativo.destruir(); ativo = null; } return; }
      if (ativo && ativo.el === el) return;
      if (ativo) ativo.destruir();
      try { ativo = new Visual(el); }
      catch (e) {
        if (raiz.console) console.warn('Simulação visual indisponível:', e);
        const c = el.closest('.cena'); if (c) c.classList.add('cena--vista');
      }
    },
    depurar() { return ativo; },
  };

  raiz.JogoVisual = JogoVisual;
  const arranque = () => JogoVisual.iniciar();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arranque); else arranque();
  raiz.addEventListener('pagehide', () => { if (ativo) ativo._guardar(true); });
})(window);
