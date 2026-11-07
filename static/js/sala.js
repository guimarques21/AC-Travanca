/* ==========================================================================
   sala.js — a sala online: mantém o painel igual ao do servidor, sem recarregar a página.

   Como funciona:
     - O servidor desenha o «painel» (HTML) para QUEM está a pedir e dá-lhe uma «assinatura».
     - O browser só troca o painel quando a assinatura muda (assim não se perde um toque a meio).
     - Para saber que algo mudou: se houver SocketIO, o servidor toca a «campainha» («mudou») e o
       browser pergunta logo o estado; mesmo assim pergunta de 6 em 6 segundos. Sem SocketIO (ou se o
       WebSocket for bloqueado) pergunta de 2 em 2 segundos. Nada depende só do WebSocket.
     - Todas as jogadas são pedidos normais (POST JSON): o servidor valida tudo e devolve o painel novo.
     - A página nunca recarrega durante o jogo, por isso a música não é interrompida.
   ========================================================================== */

(function () {
  'use strict';

  const raiz = document.getElementById('sala');
  const painel = document.getElementById('painel');
  if (!raiz || !painel) return;

  const aviso = document.getElementById('aviso');
  const anuncio = document.getElementById('anuncio');
  const presenca = document.getElementById('presenca');
  const presencaTexto = document.getElementById('presenca-texto');
  const botaoSair = document.getElementById('sair');

  const salaId = raiz.dataset.sala;
  const urlEstado = raiz.dataset.urlEstado;
  const urlAcao = raiz.dataset.urlAcao;
  const tituloBase = document.title;
  const textoSair = botaoSair ? botaoSair.textContent : '';

  const ESPERA_SEM_SOCKET = 2000;      // ms entre perguntas ao servidor, sem campainha
  const ESPERA_COM_SOCKET = 6000;      // ms entre perguntas, com campainha (rede de segurança)
  const URL_SOCKETIO = 'https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js';

  let assinatura = raiz.dataset.assinatura || '';
  let contador = 0;                    // número de cada pedido (para ignorar respostas atrasadas)
  let ultimaAplicada = 0;
  let ocupado = false;                 // uma jogada em curso
  let aConsultar = false;
  let repetir = false;
  let acabou = false;                  // saiu da sala ou a sala deixou de existir
  let socketLigado = false;
  let falhas = 0;
  let temporizador = null;
  let temporizadorAviso = null;
  let temporizadorSair = null;
  let ultimoAnuncio = '';

  /* ---------- Mensagens ---------- */
  function mostrarAviso(texto, duracao) {
    if (!aviso) return;
    clearTimeout(temporizadorAviso);
    aviso.textContent = texto;
    aviso.hidden = false;
    if (duracao) temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, duracao);
  }

  function esconderAviso() {
    if (aviso) aviso.hidden = true;
  }

  /* ---------- Presença do adversário ---------- */
  function atualizarPresenca(dados, estado) {
    if (!presenca || !dados) return;
    const ver = Boolean(dados.adversario) && estado !== 'abandonada';
    presenca.hidden = !ver;
    if (!ver) return;
    presenca.classList.toggle('presenca--ligado', Boolean(dados.ligado));
    presencaTexto.textContent = dados.adversario + ': ' + (dados.ligado ? 'ligado' : 'sem ligação');
  }

  /* ---------- Desenhar o painel ---------- */
  const aspas = (texto) => String(texto).replace(/["\\]/g, '\\$&');

  function chaveDoFoco(elemento) {
    if (!elemento || !painel.contains(elemento)) return null;
    const d = elemento.dataset;
    if (d.acao) {
      return '[data-acao="' + aspas(d.acao) + '"]'
        + (d.jogador ? '[data-jogador="' + aspas(d.jogador) + '"]' : '')
        + (d.tatica ? '[data-tatica="' + aspas(d.tatica) + '"]' : '')
        + (d.posicao ? '[data-posicao="' + aspas(d.posicao) + '"]' : '')
        + (d.funcao ? '[data-funcao="' + aspas(d.funcao) + '"]' : '')
        + (d.estilo ? '[data-estilo="' + aspas(d.estilo) + '"]' : '');
    }
    if (d.posicao) return '[data-posicao="' + aspas(d.posicao) + '"]';
    if (elemento.tagName === 'SUMMARY' && elemento.parentElement.dataset.slot) {
      return 'details[data-slot="' + aspas(elemento.parentElement.dataset.slot) + '"] > summary';
    }
    return null;
  }

  /** Quais as funções (<details>) que estão abertas: não se fecham quando o painel é redesenhado. */
  function funcoesAbertas() {
    return Array.from(painel.querySelectorAll('details[data-slot][open]')).map((d) => d.dataset.slot);
  }

  function reabrirFuncoes(abertas) {
    abertas.forEach((slot) => {
      const d = painel.querySelector('details[data-slot="' + aspas(slot) + '"]');
      if (d) d.open = true;
    });
  }

  /** Troca o conteúdo de `alvo` mantendo o foco do teclado no mesmo botão (ou no título) e as funções abertas. */
  function trocarHtml(alvo, html) {
    const chaveFoco = chaveDoFoco(document.activeElement);
    const abertas = funcoesAbertas();
    alvo.innerHTML = html;
    reabrirFuncoes(abertas);
    if (chaveFoco !== null) {
      let novo = null;
      try { novo = painel.querySelector(chaveFoco); } catch (e) { novo = null; }
      if (!novo) {
        novo = painel.querySelector('h1');
        if (novo) novo.setAttribute('tabindex', '-1');
      }
      if (novo) novo.focus({ preventScroll: true });
    }
  }

  function prepararConvite() {
    // O link completo usa o endereço que o browser está a usar (funciona atrás de proxies e em HTTPS).
    painel.querySelectorAll('.convite').forEach((caixa) => {
      const campo = caixa.querySelector('.convite__link');
      if (campo && caixa.dataset.convite) campo.value = window.location.origin + caixa.dataset.convite;
      const partilhar = caixa.querySelector('[data-partilhar]');
      if (partilhar && typeof navigator.share === 'function') partilhar.hidden = false;
    });
  }

  function atualizarTitulo() {
    const minhaVez = painel.querySelector('[data-minha-vez="1"]');
    document.title = (minhaVez ? '● É a tua vez — ' : '') + tituloBase;
  }

  function anunciar() {
    const alvo = painel.querySelector('[data-anuncio]');
    const texto = alvo ? alvo.dataset.anuncio : '';
    if (anuncio && texto && texto !== ultimoAnuncio) anuncio.textContent = texto;
    ultimoAnuncio = texto;
  }

  function desenhar(html) {
    const marcado = painel.querySelector('.jogador[aria-pressed="true"]');
    const idMarcado = marcado ? marcado.dataset.posicao : null;

    trocarHtml(painel, html);                           // mantém o foco e as funções abertas

    if (window.EquipaCampo) {
      window.EquipaCampo.iniciar();
      if (idMarcado && window.EquipaCampo.selecionar) window.EquipaCampo.selecionar(idMarcado);
    }
    prepararConvite();
    if (window.JogoVisual) window.JogoVisual.iniciar();         // a simulação do jogo (Passo 8); a música não pára
    atualizarTitulo();
    anunciar();
  }

  /** Aplica uma resposta do servidor (se não for mais antiga do que algo que já foi aplicado). */
  function receber(dados, numero) {
    if (numero < ultimaAplicada) return;
    ultimaAplicada = numero;
    if (dados.assinatura) assinatura = dados.assinatura;
    if (typeof dados.html === 'string') desenhar(dados.html);
    atualizarPresenca(dados.presenca, dados.estado);
  }

  /** A sala deixou de existir (ou perdemos o lugar): mostra a mensagem e leva para o início das salas. */
  function terminar(dados) {
    acabou = true;
    clearTimeout(temporizador);
    mostrarAviso((dados && dados.mensagem) || 'A sala já não está disponível.');
    setTimeout(() => { window.location.href = (dados && dados.destino) || '/jogar/online'; }, 2200);
  }

  function tratarErro(dados, numero) {
    if (dados.destino) { terminar(dados); return; }
    if (dados.mensagem) mostrarAviso(dados.mensagem, 6000);
    if (typeof dados.html === 'string') receber(dados, numero);   // o painel verdadeiro, para nos pormos em dia
  }

  /* ---------- Perguntar o estado ---------- */
  async function pedirEstado() {
    const numero = ++contador;
    let resposta;
    try {
      resposta = await fetch(urlEstado + '?a=' + encodeURIComponent(assinatura), {
        credentials: 'same-origin', cache: 'no-store',
      });
    } catch (erro) {
      falhas += 1;
      if (falhas >= 2) mostrarAviso('Sem ligação ao servidor. A tentar de novo…');
      return;
    }
    let dados = null;
    try { dados = await resposta.json(); } catch (erro) { /* sem corpo */ }

    if (resposta.ok && dados) {
      if (falhas >= 2) esconderAviso();
      falhas = 0;
      receber(dados, numero);
    } else if (dados && dados.destino) {
      terminar(dados);
    } else {
      falhas += 1;                                      // 5xx ou resposta estranha: tenta outra vez
      if (falhas >= 2) mostrarAviso('O servidor não respondeu. A tentar de novo…');
    }
  }

  async function consultar() {
    if (acabou) return;
    if (aConsultar) { repetir = true; return; }         // já há uma pergunta a caminho: repete logo a seguir
    aConsultar = true;
    try {
      do {
        repetir = false;
        await pedirEstado();
      } while (repetir && !acabou);
    } finally {
      aConsultar = false;
    }
  }

  function agendar() {
    clearTimeout(temporizador);
    if (acabou) return;
    temporizador = setTimeout(async () => {
      await consultar();
      agendar();
    }, socketLigado ? ESPERA_COM_SOCKET : ESPERA_SEM_SOCKET);
  }

  /* ---------- Jogadas ---------- */
  async function enviar(corpo) {
    if (ocupado || acabou) return;
    ocupado = true;
    painel.setAttribute('aria-busy', 'true');
    const numero = ++contador;
    try {
      const resposta = await fetch(urlAcao, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(corpo),
      });
      let dados = null;
      try { dados = await resposta.json(); } catch (erro) { /* sem corpo */ }
      if (!dados) throw new Error('sem resposta');

      if (dados.saiu) {
        acabou = true;
        clearTimeout(temporizador);
        window.location.href = dados.destino || '/jogar/online';
        return;
      }
      if (!resposta.ok) { tratarErro(dados, numero); return; }
      esconderAviso();
      receber(dados, numero);
    } catch (erro) {
      mostrarAviso('Sem ligação ao servidor. Tenta outra vez.', 6000);
    } finally {
      ocupado = false;
      painel.removeAttribute('aria-busy');
    }
  }

  function aoPedirSair(botao) {
    if (botao.dataset.confirmar !== '1') {              // primeiro toque: pede confirmação
      botao.dataset.confirmar = '1';
      botao.textContent = 'Toca outra vez para sair';
      clearTimeout(temporizadorSair);
      temporizadorSair = setTimeout(() => {
        botao.dataset.confirmar = '0';
        botao.textContent = textoSair;
      }, 5000);
      return;
    }
    clearTimeout(temporizadorSair);
    botao.dataset.confirmar = '0';
    botao.textContent = textoSair;
    enviar({ acao: 'sair' });
  }

  /* ---------- Convite: copiar e partilhar ---------- */
  function dizerConvite(caixa, texto) {
    const estado = caixa.querySelector('.convite__estado');
    if (estado) estado.textContent = texto;
  }

  async function copiarConvite(caixa) {
    const campo = caixa.querySelector('.convite__link');
    if (!campo) return;
    try {
      await navigator.clipboard.writeText(campo.value);
      dizerConvite(caixa, 'Link copiado!');
      return;
    } catch (erro) { /* sem permissão ou contexto inseguro: tenta o método antigo */ }
    campo.focus();
    campo.select();
    campo.setSelectionRange(0, campo.value.length);
    let copiou = false;
    try { copiou = document.execCommand('copy'); } catch (erro) { copiou = false; }
    dizerConvite(caixa, copiou ? 'Link copiado!' : 'Seleciona o link e copia-o à mão.');
  }

  async function partilharConvite(caixa) {
    const campo = caixa.querySelector('.convite__link');
    if (!campo || typeof navigator.share !== 'function') return;
    const nome = document.querySelector('.sala__tu');
    try {
      await navigator.share({
        title: 'AC Travanca',
        text: (nome ? nome.textContent : 'Um amigo') + ' convidou-te para um jogo online de futebol de 7.',
        url: campo.value,
      });
    } catch (erro) { /* cancelado pelo utilizador */ }
  }

  /* ---------- Cliques ---------- */
  raiz.addEventListener('click', (evento) => {
    const copiar = evento.target.closest('[data-copiar]');
    if (copiar) { copiarConvite(copiar.closest('.convite')); return; }
    const partilhar = evento.target.closest('[data-partilhar]');
    if (partilhar) { partilharConvite(partilhar.closest('.convite')); return; }

    const botao = evento.target.closest('[data-acao]');
    if (!botao || botao === raiz || !raiz.contains(botao)) return;
    const acao = botao.dataset.acao;
    if (acao === 'sair') { aoPedirSair(botao); return; }

    const corpo = { acao };
    if (botao.dataset.jogador !== undefined) corpo.jogador = botao.dataset.jogador;
    if (botao.dataset.tatica !== undefined) corpo.tatica = botao.dataset.tatica;
    if (botao.dataset.posicao !== undefined) corpo.posicao = botao.dataset.posicao;
    if (botao.dataset.funcao !== undefined) corpo.funcao = botao.dataset.funcao;
    if (botao.dataset.estilo !== undefined) corpo.estilo = botao.dataset.estilo;
    enviar(corpo);
  });

  // Uma troca no campo (equipa.js): a página já mostra o resultado, só falta guardar a assinatura nova.
  document.addEventListener('equipa:trocada', (evento) => {
    ultimaAplicada = ++contador;                        // respostas de perguntas anteriores já não valem
    if (evento.detail && evento.detail.assinatura) assinatura = evento.detail.assinatura;
    // Os nomes na lista de funções e nos marcadores acompanham a troca (o campo já foi atualizado pelo equipa.js).
    const opcoes = document.getElementById('opcoes');
    if (opcoes && evento.detail && typeof evento.detail.opcoes === 'string') trocarHtml(opcoes, evento.detail.opcoes);
  });
  document.addEventListener('equipa:erro', (evento) => {
    if (evento.detail) tratarErro(evento.detail, ++contador);
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) consultar();                  // voltou ao separador: põe-se logo em dia
  });

  /* ---------- Tempo real (SocketIO), se existir ---------- */
  function ligarSocket() {
    if (typeof window.io !== 'function') return;
    let socket;
    try { socket = window.io(); } catch (erro) { return; }

    socket.on('connect', () => {
      socket.emit('entrar_sala', { sala: salaId }, (resposta) => {
        socketLigado = Boolean(resposta && resposta.ok);
        agendar();
        consultar();
      });
    });
    socket.on('disconnect', () => { socketLigado = false; agendar(); });
    socket.on('connect_error', () => { socketLigado = false; });
    socket.on('mudou', () => { consultar(); });
  }

  function iniciarTempoReal() {
    if (typeof window.io === 'function') { ligarSocket(); return; }
    if (raiz.dataset.tempoReal !== '1') return;         // o servidor não tem SocketIO: só consulta periódica
    const script = document.createElement('script');
    script.src = URL_SOCKETIO;
    script.async = true;
    script.onload = ligarSocket;
    script.onerror = () => { /* sem o cliente (rede bloqueada): continua a consulta periódica */ };
    document.head.appendChild(script);
  }

  /* ---------- Arranque ---------- */
  if (window.EquipaCampo) window.EquipaCampo.iniciar();
  prepararConvite();
  atualizarTitulo();
  anunciar();
  agendar();
  iniciarTempoReal();
})();
