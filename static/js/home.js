/* ==========================================================================
   home.js — ecrã inicial: nome obrigatório + botões "Jogar Offline / Online"

   - Os botões de modo só aparecem (e só ficam clicáveis) com um nome válido.
   - A regra do nome é a MESMA de app.py (validar_nome); o servidor volta a validar sempre.
   - O nome vai aparecendo na camisola à medida que se escreve.
   ========================================================================== */

(function () {
  'use strict';

  const form = document.getElementById('form-entrada');
  if (!form) return;

  const campo = document.getElementById('campo-nome');
  const erro = document.getElementById('erro-nome');
  const acoes = document.getElementById('acoes');
  const primeiroBotao = acoes.querySelector('button');

  // Regras vindas do servidor (data-* no <form>): uma única fonte de verdade.
  const MIN = Number(form.dataset.min);
  const MSG = { curto: form.dataset.msgCurto, caracteres: form.dataset.msgCaracteres };

  const SO_PERMITIDOS = /^[\p{L}\p{N} ._'’-]+$/u;   // letras, números, espaço e . _ ' ’ -
  const TEM_LETRA_OU_NUMERO = /[\p{L}\p{N}]/u;

  const limpar = (valor) => valor.normalize('NFC').replace(/\s+/g, ' ').trim();

  /** Devolve { valido: true } ou { valido: false, tipo: 'curto' | 'caracteres' } */
  function avaliar(valor) {
    const nome = limpar(valor);
    if (nome && (!SO_PERMITIDOS.test(nome) || !TEM_LETRA_OU_NUMERO.test(nome))) {
      return { valido: false, tipo: 'caracteres' };
    }
    if (nome.length < MIN) return { valido: false, tipo: 'curto' };
    return { valido: true };
  }

  function mostrarErro(tipo) {
    erro.textContent = MSG[tipo];
    erro.hidden = false;
    campo.setAttribute('aria-invalid', 'true');
  }
  function esconderErro() {
    erro.hidden = true;
    erro.textContent = '';
    campo.setAttribute('aria-invalid', 'false');
  }

  /** Mostra/esconde os botões de modo. `inert` tira-os também do teclado e dos leitores de ecrã. */
  function abrirModos(abrir) {
    acoes.dataset.aberto = String(abrir);
    acoes.inert = !abrir;
  }

  function sincronizar() {
    const resultado = avaliar(campo.value);
    if (window.Camisola) window.Camisola.desenhar(limpar(campo.value));
    abrirModos(resultado.valido);
    return resultado;
  }

  // Ao escrever: erros de caracteres aparecem logo; "nome curto" só ao sair do campo ou ao carregar Enter.
  campo.addEventListener('input', () => {
    const r = sincronizar();
    if (r.valido || r.tipo === 'curto') esconderErro();
    else mostrarErro(r.tipo);
  });

  campo.addEventListener('blur', () => {
    const r = avaliar(campo.value);
    if (!r.valido && campo.value.trim() !== '') mostrarErro(r.tipo);
  });

  // Enter não escolhe um modo por ti: se o nome é válido, passa o foco para o 1.º botão.
  campo.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing) return;
    e.preventDefault();
    const r = avaliar(campo.value);
    if (r.valido) primeiroBotao.focus();
    else mostrarErro(r.tipo);
  });

  // Rede de segurança: nunca enviar um nome inválido (o servidor também valida).
  form.addEventListener('submit', (e) => {
    const r = avaliar(campo.value);
    if (!r.valido) {
      e.preventDefault();
      mostrarErro(r.tipo);
      campo.focus();
      return;
    }
    campo.value = limpar(campo.value);
  });

  // Arranque: o campo vem vazio (ou com o texto que o jogador escreveu, se o servidor recusou).
  // Não mexemos na mensagem de erro que o servidor possa ter enviado.
  sincronizar();
})();
