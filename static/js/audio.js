/* ==========================================================================
   audio.js — música de fundo (static/musica.mp3) em loop

   O problema: os browsers bloqueiam áudio automático. Só deixam tocar depois de
   o utilizador fazer alguma coisa na página (clicar, tocar, carregar numa tecla).

   A solução:
     1. Ao abrir a página tentamos tocar. Se o browser deixar (ex.: o jogador
        já interagiu com o site na página anterior), ótimo.
     2. Se bloquear, ficamos à escuta do PRIMEIRO gesto (clicar no campo do nome,
        tocar no ecrã, carregar numa tecla, clicar num botão...) e tocamos nessa
        altura. Quando a música arranca, deixamos de escutar.
     3. A posição da música é guardada, para continuar de onde ia ao mudar de página.
     4. O botão "Música" no canto liga/desliga. A escolha é lembrada.

   Funciona igual em localhost e no Render (usa caminhos relativos ao site).
   ========================================================================== */

(function () {
  'use strict';

  const audio = document.getElementById('musica-fundo');
  const botao = document.getElementById('botao-musica');
  const texto = document.getElementById('musica-texto');
  if (!audio || !botao) return;

  const VOLUME = 0.35;                              // música de fundo: baixinho
  const CHAVE_PREFERENCIA = 'actravanca.musica';    // localStorage: 'sim' | 'nao'
  const CHAVE_POSICAO = 'actravanca.musica.pos';    // sessionStorage: segundos

  // localStorage/sessionStorage podem falhar (janela privada, bloqueados...): nunca partem a página.
  const ler = (loja, chave) => { try { return loja.getItem(chave); } catch (e) { return null; } };
  const gravar = (loja, chave, valor) => { try { loja.setItem(chave, String(valor)); } catch (e) { /* ignora */ } };

  audio.volume = VOLUME;
  let queroMusica = ler(localStorage, CHAVE_PREFERENCIA) !== 'nao';

  /* ---------- Botão ---------- */
  function atualizarBotao() {
    const aTocar = !audio.paused;
    botao.dataset.tocando = String(aTocar);
    botao.setAttribute('aria-pressed', String(aTocar));
    texto.textContent = aTocar ? 'Música ligada' : 'Música desligada';
  }

  /* ---------- Tocar ---------- */
  function tentarTocar() {
    if (!queroMusica || !audio.paused) return;
    const promessa = audio.play();
    if (promessa && typeof promessa.catch === 'function') {
      promessa.catch(() => { /* bloqueado pelo browser: esperamos o próximo gesto */ });
    }
  }

  /* ---------- Escutar o primeiro gesto do utilizador ---------- */
  // pointerdown/pointerup/touchend/click/keydown cobrem rato, toque (incl. iPhone) e teclado.
  const EVENTOS_GESTO = ['pointerdown', 'pointerup', 'touchend', 'click', 'keydown'];
  let aEscutar = false;

  function aoInteragir(evento) {
    // O botão da música trata de si próprio (senão o 1.º clique nele ligava e desligava logo a seguir).
    if (botao.contains(evento.target)) return;
    tentarTocar();
  }
  function escutar() {
    if (aEscutar) return;
    aEscutar = true;
    EVENTOS_GESTO.forEach((e) => document.addEventListener(e, aoInteragir, { capture: true, passive: true }));
  }
  function deixarDeEscutar() {
    if (!aEscutar) return;
    aEscutar = false;
    EVENTOS_GESTO.forEach((e) => document.removeEventListener(e, aoInteragir, { capture: true }));
  }

  audio.addEventListener('playing', () => { deixarDeEscutar(); atualizarBotao(); });
  audio.addEventListener('pause', () => {
    atualizarBotao();
    if (queroMusica) escutar();     // parou sem o jogador pedir (ex.: o telemóvel interrompeu): volta a esperar um gesto
  });

  /* ---------- Continuar de onde ia (ao mudar de página) ---------- */
  function restaurarPosicao() {
    const guardada = Number(ler(sessionStorage, CHAVE_POSICAO));
    if (Number.isFinite(guardada) && guardada > 0 && audio.duration) {
      audio.currentTime = guardada % audio.duration;
    }
  }
  if (audio.readyState >= 1) restaurarPosicao();
  else audio.addEventListener('loadedmetadata', restaurarPosicao, { once: true });

  // Só guarda depois de haver posição: se a página mudar antes de o áudio carregar (currentTime = 0),
  // não apagamos a posição que já estava guardada.
  const guardarPosicao = () => {
    if (audio.currentTime > 0) gravar(sessionStorage, CHAVE_POSICAO, audio.currentTime);
  };
  audio.addEventListener('timeupdate', guardarPosicao);
  window.addEventListener('pagehide', guardarPosicao);

  /* ---------- Botão liga/desliga ---------- */
  botao.addEventListener('click', () => {
    if (audio.paused) {
      queroMusica = true;
      gravar(localStorage, CHAVE_PREFERENCIA, 'sim');
      tentarTocar();
    } else {
      queroMusica = false;
      gravar(localStorage, CHAVE_PREFERENCIA, 'nao');
      audio.pause();
    }
  });

  /* ---------- Se o ficheiro não carregar, não deixamos um botão inútil ---------- */
  audio.addEventListener('error', () => {
    botao.hidden = true;
    console.warn('[AC Travanca] Não foi possível carregar a música:', audio.currentSrc);
  });

  /* ---------- Arranque ---------- */
  atualizarBotao();
  if (queroMusica) {
    escutar();        // 1) fica à espera do primeiro gesto...
    tentarTocar();    // 2) ...e tenta já (funciona se o browser já deixar)
  }
})();
