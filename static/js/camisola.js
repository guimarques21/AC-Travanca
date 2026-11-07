/* ==========================================================================
   camisola.js — escreve o nome nas costas da camisola (SVG), ao vivo.

   Uso:  Camisola.desenhar('Guilherme')
   Na página "Em breve" o nome vem do servidor, em data-nome no <text>.
   ========================================================================== */

(function () {
  'use strict';

  const nomeSvg = document.getElementById('camisola-nome');
  const guia = document.getElementById('camisola-guia');
  if (!nomeSvg) return;

  const LARGURA_MAX = 150;   // largura útil do tronco, em unidades do SVG

  // Num SVG escondido (display:none) o Firefox não consegue medir o texto: nesse caso não há nada a apertar.
  function larguraDoTexto() {
    try { return nomeSvg.getComputedTextLength(); } catch (e) { return 0; }
  }

  function desenhar(nome) {
    const texto = (nome || '').trim().toLocaleUpperCase('pt-PT');   // nas camisolas escreve-se em maiúsculas
    nomeSvg.textContent = texto;

    // Nomes compridos são apertados para caber, como numa estampagem a sério.
    nomeSvg.removeAttribute('textLength');
    nomeSvg.removeAttribute('lengthAdjust');
    if (texto && larguraDoTexto() > LARGURA_MAX) {
      nomeSvg.setAttribute('textLength', LARGURA_MAX);
      nomeSvg.setAttribute('lengthAdjust', 'spacingAndGlyphs');
    }

    if (guia) guia.style.opacity = texto ? '0' : '1';   // a linha tracejada só aparece sem nome
  }

  window.Camisola = { desenhar };

  desenhar(nomeSvg.dataset.nome || '');

  // Quando a fonte do Google acaba de carregar a largura muda: recalcula.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => desenhar(nomeSvg.textContent));
  }
})();
