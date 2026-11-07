/* ==========================================================================
   liga.js — os jogos da liga aparecem um a um (rápido), com os marcadores.

   O resultado já está todo calculado e guardado no servidor: isto só controla
   quando cada jogo se mostra. "Saltar para o fim" mostra o resto logo.
   No fim aparece o botão "Ver classificação". Se esta liga já foi vista nesta
   sessão (o utilizador voltou a esta página), aparece tudo de uma vez.
   ========================================================================== */

(function () {
  'use strict';

  const liga = document.getElementById('liga');
  const lista = document.getElementById('jogos');
  if (!liga || !lista) return;
  window.__ligaPronta = true;                 // avisa a rede de segurança da página

  if (!liga.classList.contains('liga--animar')) return;   // já vista: está tudo visível

  const ATRASO_MS = 480;                      // 22 jogos em cerca de 10 segundos
  const itens = Array.from(lista.querySelectorAll('.jogo'));
  const saltar = document.getElementById('saltar');
  const ver = document.getElementById('ver-tabela');
  const fim = document.getElementById('fim-liga');
  const campos = {
    jogos: document.getElementById('r-jogos'),
    v: document.getElementById('r-v'),
    e: document.getElementById('r-e'),
    d: document.getElementById('r-d'),
    pts: document.getElementById('r-pts'),
    jogosTxt: document.getElementById('r-jogos-txt'),
    ptsTxt: document.getElementById('r-pts-txt'),
  };
  const semMovimento = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let mostrados = 0;
  let temporizador = null;
  const total = { jogos: 0, V: 0, E: 0, D: 0, pts: 0 };

  function atualizarResumo() {
    campos.jogos.textContent = total.jogos;
    campos.v.textContent = total.V;
    campos.e.textContent = total.E;
    campos.d.textContent = total.D;
    campos.pts.textContent = total.pts;
    campos.jogosTxt.textContent = total.jogos === 1 ? 'jogo' : 'jogos';
    campos.ptsTxt.textContent = total.pts === 1 ? 'ponto' : 'pontos';
  }

  function mostrar(item, seguir) {
    item.classList.add('jogo--visto');
    total.jogos += 1;
    total[item.dataset.res] += 1;
    total.pts += Number(item.dataset.pts) || 0;
    mostrados += 1;
    if (seguir) item.scrollIntoView({ block: 'nearest', behavior: semMovimento ? 'auto' : 'smooth' });
  }

  function terminar() {
    window.clearTimeout(temporizador);
    while (mostrados < itens.length) mostrar(itens[mostrados], false);
    atualizarResumo();
    liga.classList.add('liga--fim');
    fim.hidden = false;
    try { sessionStorage.setItem('liga-vista-' + lista.dataset.liga, '1'); } catch (e) { /* sem armazenamento: ao voltar, repete-se */ }
    ver.focus({ preventScroll: true });
    ver.scrollIntoView({ block: 'nearest', behavior: semMovimento ? 'auto' : 'smooth' });
  }

  function passo() {
    if (mostrados >= itens.length) return terminar();
    mostrar(itens[mostrados], true);
    atualizarResumo();
    temporizador = window.setTimeout(passo, ATRASO_MS);
  }

  saltar.addEventListener('click', terminar);
  atualizarResumo();                           // começa a zeros (o CSS só mostra o resumo a partir daqui)
  liga.classList.add('liga--a-correr');
  temporizador = window.setTimeout(passo, 700);
})();
