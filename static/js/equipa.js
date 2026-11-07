/* ==========================================================================
   equipa.js — trocar dois jogadores de posição, no campo.

   Toca num jogador (fica marcado) e depois noutro: trocam de posição.
   Quem decide é sempre o servidor: o browser pede a troca (POST JSON) e desenha
   o que o servidor devolve. Assim não há como ficar com uma equipa inválida,
   e a página não recarrega (a música não é interrompida).

   Serve o modo offline (corre sozinho ao carregar a página) e o modo online (sala.js volta a chamar
   EquipaCampo.iniciar() sempre que troca o painel e o campo é desenhado de novo).
   Quando a troca é feita, avisa com o evento «equipa:trocada» (detail: {lugares, assinatura}).
   Se o servidor responder com um erro que traz o estado atual (modo online), o evento «equipa:erro»
   leva a resposta para o sala.js se pôr em dia, sem recarregar a página.
   ========================================================================== */

(function () {
  'use strict';

  let ocupado = false;       // há um pedido ao servidor em curso
  let escolhido = null;      // id da posição marcada (ou null) — do campo que está na página
  let campo = null;
  let dica = null;
  let botoes = new Map();
  let textoPadrao = '';
  let urlTrocar = '';
  let teclaLigada = false;

  const nomeDe = (id) => botoes.get(id).querySelector('.jogador__nome').textContent;

  function dizer(texto) {
    if (dica) dica.textContent = texto;
  }

  function marcar(id) {
    escolhido = id;
    botoes.forEach((b, posicao) => b.setAttribute('aria-pressed', String(posicao === id)));
  }

  function desenhar(lugares) {
    Object.keys(lugares).forEach((id) => {
      const botao = botoes.get(id);
      const lugar = lugares[id];
      if (!botao) return;
      botao.querySelector('.jogador__nome').textContent = lugar.jogador;
      botao.querySelector('.jogador__natural').textContent = lugar.natural;
      botao.querySelector('.jogador__aviso').hidden = !lugar.fora;
      botao.querySelector('.jogador__so-fora').hidden = !lugar.fora;
      botao.classList.toggle('jogador--fora', lugar.fora);
    });
  }

  function destacar(...ids) {
    ids.forEach((id) => {
      const botao = botoes.get(id);
      botao.classList.remove('jogador--trocou');
      void botao.offsetWidth;                       // reinicia a animação
      botao.classList.add('jogador--trocou');
    });
  }

  async function trocar(a, b) {
    const noCampo = campo;                          // se o painel for trocado a meio, não mexe no campo novo
    ocupado = true;
    const nomeA = nomeDe(a);
    const nomeB = nomeDe(b);
    try {
      const resposta = await fetch(urlTrocar, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ a, b }),
      });
      let dados = null;
      try { dados = await resposta.json(); } catch (e) { /* sem corpo */ }

      if (!resposta.ok) {
        // Modo online: o erro leva o estado atual (ou um destino): o sala.js trata disso.
        if (dados && (dados.html || dados.destino)) {
          document.dispatchEvent(new CustomEvent('equipa:erro', { detail: dados }));
          return;
        }
        throw new Error('resposta ' + resposta.status);
      }
      if (noCampo !== campo) return;                // o painel mudou entretanto: já não há nada a desenhar
      desenhar(dados.lugares);
      marcar(null);
      destacar(a, b);
      dizer('Trocaste ' + nomeA + ' com ' + nomeB + '.');
      document.dispatchEvent(new CustomEvent('equipa:trocada', { detail: dados }));
    } catch (erro) {
      // Sessão perdida ou servidor em baixo: recarrega para mostrar o estado verdadeiro.
      dizer('Não foi possível trocar. A atualizar…');
      setTimeout(() => window.location.reload(), 900);
    } finally {
      if (noCampo === campo) marcar(null);
      ocupado = false;
    }
  }

  function aoClicar(evento) {
    const botao = evento.target.closest('.jogador');
    if (!botao || botao.disabled || ocupado) return;
    const id = botao.dataset.posicao;

    if (escolhido === null) {
      marcar(id);
      dizer('A mover ' + nomeDe(id) + '. Toca noutro jogador para trocar.');
    } else if (escolhido === id) {
      marcar(null);
      dizer(textoPadrao);
    } else {
      trocar(escolhido, id);
    }
  }

  /** Liga-se ao campo que estiver na página (pode ser chamado de novo depois de o campo ser redesenhado). */
  function iniciar() {
    campo = document.getElementById('relvado');
    dica = document.getElementById('dica');
    botoes = new Map();
    escolhido = null;
    if (!campo || !dica) return;

    urlTrocar = campo.dataset.trocar || '';
    textoPadrao = dica.dataset.padrao || '';
    campo.querySelectorAll('.jogador').forEach((b) => botoes.set(b.dataset.posicao, b));
    if (urlTrocar) campo.addEventListener('click', aoClicar);     // campo bloqueado (sem URL): só se vê

    if (!teclaLigada) {                                           // uma só vez, mesmo com vários campos
      teclaLigada = true;
      document.addEventListener('keydown', (evento) => {
        if (evento.key === 'Escape' && escolhido !== null && !ocupado) {
          marcar(null);
          dizer(textoPadrao);
        }
      });
    }
  }

  /** Volta a marcar um jogador (o sala.js usa isto quando o campo é redesenhado a meio de uma troca). */
  function selecionar(id) {
    const botao = botoes.get(id);
    if (!botao || botao.disabled || ocupado) return;
    marcar(id);
    dizer('A mover ' + nomeDe(id) + '. Toca noutro jogador para trocar.');
  }

  window.EquipaCampo = { iniciar, selecionar };
  // No modo offline o campo já está na página; no online o sala.js chama iniciar() quando o desenha.
  if (!document.getElementById('sala')) iniciar();
})();
