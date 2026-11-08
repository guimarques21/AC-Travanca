"""
funcoes.py — funções por posição, estilos de jogo e bolas paradas (Passo 6, modo online)
=========================================================================================

Este módulo é só dados e lógica: não sabe nada de Flask, de salas nem de Excel (só valida os nomes dos
atributos contra as colunas do Excel ONLINE, quando o servidor arranca).

O que o utilizador escolhe, antes de carregar em «Estou pronto»:
  - uma FUNÇÃO para cada jogador no campo (a lista de funções depende da posição e da tática);
  - o ESTILO de jogo da equipa;
  - quem bate os LIVRES e quem bate os CANTOS.

Tudo o que o utilizador vê são nomes e descrições em linguagem de futebol. Os números (multiplicadores
de atributos e tendências) ficam aqui, no servidor, e só o motor da simulação (Passo 7) os usa:

  - `pesos` de uma função: {atributo do Excel: multiplicador}. 1,0 é o normal; 1,3 quer dizer que esse
    atributo conta 30 % mais na fórmula da posição; 0,9 que conta 10 % menos. Os atributos que não
    aparecem contam como sempre (as funções e os estilos «puxam» para um lado, não deitam fora o resto).
  - `pesos` de um estilo: o mesmo, mas por tipo de posição (gr, def, med, ava).
  - `tendencias` de um estilo: de -1 a +1 (0 é o normal), como a equipa se comporta com a bola. São
    valores iniciais que o Passo 7 afina quando houver simulação para ver o efeito.

A função «normal» (a que fica escolhida por defeito) não mexe em nada: com ela a simulação usa só a
fórmula da posição. O estilo de jogo, pelo contrário, NÃO tem valor por defeito: cada treinador tem de
escolher o seu (decisão do autor), por isso todos os estilos têm uma identidade própria.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import taticas

# --------------------------------------------------------------------------- #
# Limites dos multiplicadores (confirmados nos testes)
# --------------------------------------------------------------------------- #
PESO_MIN = 0.85
PESO_MAX = 1.35

# --------------------------------------------------------------------------- #
# Funções
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Funcao:
    id: str
    nome: str
    descricao: str                                   # para o utilizador: linguagem de futebol, sem números
    pesos: Mapping[str, float] = field(default_factory=dict)   # só no servidor
    padrao: bool = False
    # Onde o jogador se coloca em campo (só no servidor, usado pelo motor de jogo): metros a mais (+) ou a menos (−)
    # para a frente quando a equipa tem a bola ("ataque") ou não ("defesa"), e para a linha lateral (+) ou o
    # meio (−) ("largura").
    mov: Mapping[str, float] = field(default_factory=dict)


def _f(id_, nome, descricao, pesos=None, padrao=False) -> Funcao:
    return Funcao(id_, nome, descricao, dict(pesos or {}), padrao)


# Listas de funções. A chave diz que opções tem cada tipo de posição (ver `lista_da_posicao`).
LISTAS: dict[str, tuple[Funcao, ...]] = {
    "guarda_redes": (
        _f("tradicional", "Tradicional",
           "Fica na baliza e na área: defende remates, sai aos cruzamentos e às bolas nas costas da defesa.",
           padrao=True),
        _f("libero", "Líbero",
           "Joga adiantado, também com os pés: sai da área para cortar bolas longas e começa o ataque com a bola.",
           {"Decisões": 1.25, "Lançamento": 1.3, "Pontapé de Baliza": 1.3, "Agilidade": 1.2,
            "Compostura": 1.2, "Comando de Área": 1.1}),
    ),
    "defesa": (
        _f("equilibrado", "Equilibrado",
           "Defende a sua zona, marca o adversário e, quando pode, ajuda a sair a jogar.", padrao=True),
        _f("posicional", "Posicional",
           "Fica sempre atrás, perto da baliza: marca de perto e corta tudo o que passa por ele.",
           {"Marcação": 1.25, "Posicionamento": 1.25, "Concentração": 1.2, "Desarme": 1.15, "Cabeceamento": 1.1}),
        _f("cobertura", "De cobertura",
           "Anda uns metros atrás dos colegas: corre para tapar buracos e apanhar as bolas nas costas.",
           {"Antecipação": 1.3, "Velocidade": 1.25, "Aceleração": 1.2, "Decisões": 1.15, "Posicionamento": 1.1}),
        _f("construtor", "Sai a jogar",
           "Rouba a bola e começa o ataque com passes curtos e longos, sem pressa e sem a perder.",
           {"Passe": 1.3, "Visão de Jogo": 1.25, "Primeiro Toque": 1.2, "Técnica": 1.15, "Compostura": 1.15,
            "Decisões": 1.1, "Marcação": 0.9}),
        _f("sobe", "Sobe no terreno",
           "Aproveita os espaços e sobe, com ou sem bola, para apoiar o meio-campo. Deixa mais espaço atrás.",
           {"Sem Bola": 1.2, "Resistência": 1.25, "Drible": 1.15, "Índice de Trabalho": 1.2, "Velocidade": 1.1,
            "Marcação": 0.9, "Posicionamento": 0.9}),
    ),
    "defesa_lateral": (
        _f("equilibrado", "Equilibrado", "Defende a sua ala e sobe quando há espaço.", padrao=True),
        _f("defensivo", "Defensivo",
           "Fica atrás e fecha a ala: só sobe quando é seguro.",
           {"Marcação": 1.25, "Desarme": 1.2, "Posicionamento": 1.25, "Concentração": 1.15, "Cruzamento": 0.9}),
        _f("ofensivo", "Ofensivo (ala)",
           "Corre a ala toda, vai à linha e cruza. Ajuda muito no ataque, mas deixa a ala das costas aberta.",
           {"Cruzamento": 1.3, "Velocidade": 1.25, "Resistência": 1.3, "Aceleração": 1.2, "Drible": 1.15,
            "Índice de Trabalho": 1.15, "Marcação": 0.9, "Posicionamento": 0.9}),
        _f("interior", "Entra por dentro",
           "Fecha para o meio quando a equipa tem a bola e ajuda a construir o jogo com passes.",
           {"Passe": 1.25, "Visão de Jogo": 1.2, "Técnica": 1.2, "Primeiro Toque": 1.15, "Decisões": 1.15,
            "Sem Bola": 1.1}),
    ),
    "medio": (
        _f("equilibrado", "Equilibrado", "Joga em todo o lado: ajuda a defender e a atacar.", padrao=True),
        _f("recuperador", "Recuperador",
           "Protege a defesa: rouba bolas e entrega-as, simples, a quem joga.",
           {"Desarme": 1.3, "Marcação": 1.2, "Antecipação": 1.25, "Posicionamento": 1.2, "Agressividade": 1.15,
            "Força": 1.1, "Drible": 0.9, "Finalização": 0.85}),
        _f("organizador", "Organizador",
           "Pede sempre a bola, dita o ritmo e distribui o jogo pelos colegas.",
           {"Passe": 1.3, "Visão de Jogo": 1.3, "Decisões": 1.2, "Primeiro Toque": 1.15, "Compostura": 1.15,
            "Técnica": 1.1}),
        _f("criativo", "Criativo",
           "Procura o passe de rutura, o um para um e o remate de fora da área.",
           {"Drible": 1.25, "Técnica": 1.25, "Visão de Jogo": 1.2, "Finalização": 1.2, "Passe": 1.1,
            "Desarme": 0.9, "Marcação": 0.9}),
        _f("area_a_area", "De área a área",
           "Corre o jogo todo: defende e chega à área adversária para finalizar.",
           {"Resistência": 1.3, "Índice de Trabalho": 1.3, "Sem Bola": 1.2, "Finalização": 1.15,
            "Velocidade": 1.1}),
    ),
    "medio_ala": (
        _f("equilibrado", "Equilibrado", "Ocupa a ala, ajuda a defender e a atacar.", padrao=True),
        _f("extremo", "Extremo",
           "Fica na linha, ganha metros com a velocidade e cruza para a área.",
           {"Velocidade": 1.3, "Aceleração": 1.25, "Cruzamento": 1.3, "Drible": 1.2, "Resistência": 1.15,
            "Desarme": 0.9, "Marcação": 0.9}),
        _f("corta_para_dentro", "Corta para dentro",
           "Parte da ala, vai para o meio com a bola e remata ou combina com os colegas.",
           {"Drible": 1.3, "Finalização": 1.25, "Técnica": 1.2, "Aceleração": 1.15, "Agilidade": 1.15,
            "Cruzamento": 0.9}),
        _f("trabalhador", "Trabalhador",
           "Corre a ala toda, para trás e para a frente: ajuda os defesas a defender e sobe no contra-ataque.",
           {"Resistência": 1.3, "Índice de Trabalho": 1.3, "Desarme": 1.2, "Marcação": 1.15, "Velocidade": 1.1,
            "Posicionamento": 1.1, "Finalização": 0.9, "Drible": 0.9}),
        _f("interior", "Joga por dentro",
           "Entra para o centro do campo, junta-se ao médio e cria jogo com passes.",
           {"Passe": 1.25, "Visão de Jogo": 1.25, "Técnica": 1.2, "Primeiro Toque": 1.15, "Decisões": 1.15,
            "Sem Bola": 1.1, "Cruzamento": 0.9}),
    ),
    "avancado": (
        _f("equilibrado", "Equilibrado", "Joga de frente para a baliza, pede a bola e finaliza.", padrao=True),
        _f("pivo", "Pivô",
           "Segura a bola de costas para a baliza, protege-a e solta-a para os colegas que chegam.",
           {"Força": 1.3, "Primeiro Toque": 1.25, "Equilíbrio": 1.25, "Cabeceamento": 1.2, "Passe": 1.15,
            "Técnica": 1.1, "Velocidade": 0.9}),
        _f("finalizador", "Finalizador",
           "Vive na área: procura sempre o espaço certo para marcar.",
           {"Finalização": 1.3, "Sem Bola": 1.3, "Posicionamento": 1.25, "Antecipação": 1.2, "Compostura": 1.2,
            "Cabeceamento": 1.1, "Passe": 0.9, "Índice de Trabalho": 0.9}),
        _f("apoio", "De apoio",
           "Recua para buscar jogo, liga o meio-campo ao ataque e serve os colegas.",
           {"Passe": 1.25, "Visão de Jogo": 1.25, "Técnica": 1.2, "Primeiro Toque": 1.2, "Drible": 1.1,
            "Finalização": 0.9}),
        _f("profundidade", "Em profundidade",
           "Corre nas costas da defesa, à espera do passe longo ou da bola em profundidade.",
           {"Velocidade": 1.3, "Aceleração": 1.3, "Sem Bola": 1.25, "Antecipação": 1.15, "Finalização": 1.1,
            "Passe": 0.9, "Força": 0.95}),
    ),
}

# Quando há dois avançados (táticas 2 e 3 são «centro/extremos») pode haver um que joga pela ala.
LISTAS["avancado_dupla"] = LISTAS["avancado"] + (
    _f("de_ala", "De ala",
       "Abre para a ala, ganha a linha e cruza, ou corta para o meio para rematar.",
       {"Velocidade": 1.25, "Drible": 1.25, "Aceleração": 1.2, "Cruzamento": 1.15, "Finalização": 1.1,
        "Cabeceamento": 0.9}),
)


# Movimento em campo de cada função (metros). As funções «normais» não aparecem: ficam onde a tática as põe.
_MOVIMENTO: dict[tuple[str, str], dict[str, float]] = {
    # Valores calibrados com centenas de jogos simulados: o motor reage muito à posição dos avançados (metros a mais
    # ou a menos mudam bastante os remates), por isso nenhuma função pode decidir o jogo só por onde põe o jogador.
    ("guarda_redes", "libero"): {"ataque": 2.8, "defesa": 2.1},
    ("defesa", "posicional"): {"ataque": -1.0, "defesa": -1.0},
    ("defesa", "cobertura"): {"ataque": -0.7, "defesa": -1.4},
    ("defesa", "construtor"): {"ataque": 0.7},
    ("defesa", "sobe"): {"ataque": 2.8, "defesa": 0.7},
    ("defesa_lateral", "defensivo"): {"ataque": -1.0, "defesa": -0.4},
    ("defesa_lateral", "ofensivo"): {"ataque": 4.2, "defesa": 1.0, "largura": 1.0},
    ("defesa_lateral", "interior"): {"ataque": 1.4, "largura": -2.1},
    ("medio", "recuperador"): {"ataque": -1.0, "defesa": -0.7},
    ("medio", "criativo"): {"ataque": 1.4},
    ("medio", "area_a_area"): {"ataque": 2.1, "defesa": -0.7},
    ("medio_ala", "extremo"): {"ataque": 2.1, "largura": 1.4},
    ("medio_ala", "corta_para_dentro"): {"ataque": 1.4, "largura": 0.4},
    ("medio_ala", "trabalhador"): {"ataque": 0.7, "defesa": -1.75},
    ("medio_ala", "interior"): {"ataque": 1.0, "largura": -2.8},
    ("avancado", "pivo"): {"ataque": 0.3, "defesa": 0.2},
    ("avancado", "finalizador"): {"ataque": 0.6},
    ("avancado", "apoio"): {"ataque": -0.6, "defesa": -0.3},
    ("avancado", "profundidade"): {"ataque": 0.6},
    ("avancado_dupla", "de_ala"): {"largura": 3.0},
}


def _juntar_movimento() -> None:
    for chave, lista in list(LISTAS.items()):
        base = "avancado" if chave == "avancado_dupla" else chave
        LISTAS[chave] = tuple(
            replace(f, mov=_MOVIMENTO.get((chave, f.id)) or _MOVIMENTO.get((base, f.id)) or {}) for f in lista
        )


_juntar_movimento()


def lista_da_posicao(tatica: taticas.Tatica, posicao: taticas.Posicao) -> str:
    """A chave de `LISTAS` que diz que funções esta posição desta tática pode ter."""
    perfil = posicao.perfil
    if perfil == "guarda_redes":
        return "guarda_redes"
    if perfil == "defesa_lateral":
        return "defesa_lateral"
    if perfil in ("defesa", "defesa_central"):
        return "defesa"
    if perfil == "medio_ala":
        return "medio_ala"
    if perfil in ("medio_central", "medio"):
        return "medio"
    if perfil == "avancado":
        avancados = sum(1 for p in tatica.posicoes if p.papel == taticas.AVA)
        return "avancado_dupla" if avancados == 2 else "avancado"
    raise ValueError(f"Perfil sem lista de funções: {perfil!r}")


def funcoes_da_posicao(tatica: taticas.Tatica, posicao: taticas.Posicao) -> tuple[Funcao, ...]:
    return LISTAS[lista_da_posicao(tatica, posicao)]


def funcao_padrao(tatica: taticas.Tatica, posicao: taticas.Posicao) -> str:
    return next(f.id for f in funcoes_da_posicao(tatica, posicao) if f.padrao)


def obter_funcao(tatica: taticas.Tatica, posicao_id, funcao_id) -> Funcao | None:
    """A função com esse id nessa posição (None se a posição ou a função não existirem aí)."""
    if not isinstance(posicao_id, str) or not isinstance(funcao_id, str):
        return None
    for posicao in tatica.posicoes:
        if posicao.id == posicao_id:
            return next((f for f in funcoes_da_posicao(tatica, posicao) if f.id == funcao_id), None)
    return None


def funcoes_padrao(tatica: taticas.Tatica) -> dict[str, str]:
    """posição -> função por defeito, para todas as posições da tática."""
    return {p.id: funcao_padrao(tatica, p) for p in tatica.posicoes}


def funcoes_validas(tatica: taticas.Tatica, funcoes: Mapping[str, str]) -> bool:
    """True se há exatamente uma função válida para cada posição da tática."""
    return (
        set(funcoes) == {p.id for p in tatica.posicoes}
        and all(obter_funcao(tatica, posicao_id, funcao_id) is not None for posicao_id, funcao_id in funcoes.items())
    )


# --------------------------------------------------------------------------- #
# Estilos de jogo
# --------------------------------------------------------------------------- #

TENDENCIAS = ("posse", "jogo_direto", "ritmo", "largura", "linha", "risco")
#   posse        > 0 segura mais a bola       jogo_direto > 0 mais passes longos para a frente
#   ritmo        > 0 transições mais rápidas   largura     > 0 mais jogo pelas alas e cruzamentos
#   linha        > 0 equipa mais subida/pressão, < 0 bloco baixo         risco  > 0 arrisca mais o passe


@dataclass(frozen=True)
class Estilo:
    id: str
    nome: str
    descricao: str                                          # para o utilizador
    pesos: Mapping[str, Mapping[str, float]] = field(default_factory=dict)   # só no servidor: papel -> atributo -> multiplicador
    tendencias: Mapping[str, float] = field(default_factory=dict)             # só no servidor


ESTILOS: tuple[Estilo, ...] = (
    Estilo("bola_longa", "Bola longa",
           "Sai da defesa com passes longos para a frente e luta pela segunda bola. Joga mais direto, com menos posse.",
           {taticas.GR: {"Pontapé de Baliza": 1.3, "Lançamento": 1.25},
            taticas.DEF: {"Passe": 1.15, "Cabeceamento": 1.1, "Força": 1.1},
            taticas.MED: {"Força": 1.15, "Resistência": 1.1, "Agressividade": 1.1},
            taticas.AVA: {"Força": 1.25, "Cabeceamento": 1.25, "Impulsão": 1.2, "Primeiro Toque": 1.15,
                          "Equilíbrio": 1.1}},
           {"posse": -0.5, "jogo_direto": 0.8, "ritmo": 0.3, "largura": 0.0, "linha": 0.1, "risco": 0.3}),
    Estilo("posse", "Posse de bola",
           "Troca de passes curtos e tem paciência para rodar a bola até abrir espaço. Fica mais tempo com a bola.",
           {taticas.GR: {"Decisões": 1.2, "Compostura": 1.2, "Lançamento": 1.1},
            taticas.DEF: {"Passe": 1.25, "Primeiro Toque": 1.2, "Técnica": 1.2, "Compostura": 1.15,
                          "Visão de Jogo": 1.15},
            taticas.MED: {"Passe": 1.2, "Primeiro Toque": 1.18, "Técnica": 1.15, "Visão de Jogo": 1.18,
                          "Decisões": 1.1, "Resistência": 1.1},
            taticas.AVA: {"Primeiro Toque": 1.2, "Passe": 1.15, "Técnica": 1.15, "Sem Bola": 1.15, "Drible": 1.1}},
           {"posse": 0.8, "jogo_direto": -0.2, "ritmo": -0.1, "largura": 0.0, "linha": 0.3, "risco": -0.1}),
    Estilo("contra_ataque", "Contra-ataque",
           "Fecha-se bem, rouba a bola e sai rápido, com poucos passes, para a baliza adversária.",
           {taticas.GR: {"Lançamento": 1.2, "Decisões": 1.15},
            taticas.DEF: {"Antecipação": 1.2, "Desarme": 1.15, "Velocidade": 1.15, "Passe": 1.1,
                          "Posicionamento": 1.1},
            taticas.MED: {"Velocidade": 1.2, "Aceleração": 1.2, "Antecipação": 1.15, "Passe": 1.15,
                          "Sem Bola": 1.15, "Resistência": 1.1},
            taticas.AVA: {"Velocidade": 1.3, "Aceleração": 1.3, "Sem Bola": 1.25, "Finalização": 1.15,
                          "Compostura": 1.1}},
           {"posse": -0.3, "jogo_direto": 0.4, "ritmo": 0.6, "largura": 0.0, "linha": -0.2, "risco": 0.2}),
    Estilo("alas", "Jogar pelas alas",
           "Abre o jogo para as laterais, ganha a linha e cruza para a área.",
           {taticas.GR: {"Lançamento": 1.1},
            taticas.DEF: {"Cruzamento": 1.18, "Velocidade": 1.1, "Resistência": 1.1},
            taticas.MED: {"Cruzamento": 1.2, "Velocidade": 1.12, "Drible": 1.12, "Resistência": 1.12,
                          "Aceleração": 1.1},
            taticas.AVA: {"Cabeceamento": 1.12, "Finalização": 1.06, "Sem Bola": 1.08, "Impulsão": 1.08,
                          "Posicionamento": 1.05}},
           {"posse": 0.0, "jogo_direto": 0.1, "ritmo": 0.1, "largura": 0.7, "linha": 0.1, "risco": 0.1}),
    Estilo("autocarro", "Park the bus",
           "Todos atrás da bola, as linhas juntas, e só se sai em lances isolados. Defende muito e ataca pouco.",
           {taticas.GR: {"Reflexos": 1.15, "Um para Um": 1.15, "Comando de Área": 1.15, "Concentração": 1.15},
            taticas.DEF: {"Marcação": 1.25, "Desarme": 1.2, "Posicionamento": 1.25, "Concentração": 1.25,
                          "Cabeceamento": 1.15, "Bravura": 1.15, "Força": 1.1},
            taticas.MED: {"Marcação": 1.25, "Desarme": 1.25, "Posicionamento": 1.2, "Índice de Trabalho": 1.25,
                          "Concentração": 1.2, "Antecipação": 1.15},
            taticas.AVA: {"Índice de Trabalho": 1.2, "Resistência": 1.15, "Velocidade": 1.15, "Finalização": 1.1, "Compostura": 1.1}},
           {"posse": -1.0, "jogo_direto": 0.5, "ritmo": 0.3, "largura": -0.2, "linha": -0.6, "risco": -0.2}),
)
def obter_estilo(id_) -> Estilo | None:
    if not isinstance(id_, str):
        return None
    return next((e for e in ESTILOS if e.id == id_), None)


# --------------------------------------------------------------------------- #
# Ajuste entre tática, estilo e funções (só no servidor; o motor de jogo usa-o)
# --------------------------------------------------------------------------- #
# Um estilo é um plano de jogo e só funciona na medida em que a tática e os jogadores o conseguem executar:
#   * a tática dá (ou não) os jogadores nos sítios que o plano pede (jogar pelas alas precisa de gente nas alas;
#     «Park the bus» precisa de muitos jogadores atrás da bola; a posse precisa de médios para triangular...);
#   * as funções dão (ou não) os comportamentos que o plano pede (o Extremo e o lateral Ofensivo abrem o jogo pelas
#     alas; o Organizador e o «Sai a jogar» sustentam a posse; o Recuperador e o Posicional fecham o bloco baixo...).
# Nada disto é um bónus de força: só decide QUANTO do plano de jogo se consegue pôr em prática (ver `adequacao` e
# `Equipa.ef` no motor). Escolher o que não combina custa; escolher o que combina compensa.

# Tática (1 = 2-3-1, 2 = 3-1-2, 3 = 2-2-2, 4 = 3-2-1) que melhor sustenta cada estilo, de -1 (mal) a +1 (muito bem).
# Os valores são centrados em código: para cada estilo a média das 4 táticas dá 0 (nenhuma tática é «melhor» no geral).
_AJUSTE_TATICA_BRUTO: dict[str, dict[int, float]] = {
    # posse: precisa de médios para triangular. 2-3-1 tem 3; 3-2-1 tem 2 e 3 defesas a construir; 3-1-2 só tem 1 médio.
    "posse":         {1: 0.6, 2: -0.9, 3: 0.0, 4: 0.5},
    # bola longa: precisa de avançados para ganhar a bola no ar e a segunda bola; com 1 só avançado fica isolado.
    "bola_longa":    {1: -0.5, 2: 0.7, 3: 0.6, 4: -0.3},
    # contra-ataque: bloco compacto atrás e avançados rápidos para sair; os dois avançados da 3-1-2 e da 2-2-2 ajudam.
    "contra_ataque": {1: 0.3, 2: 0.6, 3: 0.1, 4: 0.5},
    # alas: precisa de jogadores nas alas. 2-3-1 tem 2 médios ala, 3-1-2 e 3-2-1 têm 2 laterais; a 2-2-2 não tem
    # ninguém nas zonas laterais.
    "alas":          {1: 0.8, 2: 0.6, 3: -1.0, 4: 0.4},
    # park the bus: precisa de muita gente atrás da bola. 3-2-1 (5 atrás, 3 defesas) e 2-3-1 (5 atrás) são as melhores;
    # a 2-2-2 só tem 4 e dois avançados que não ajudam a defender.
    "autocarro":     {1: 0.1, 2: 0.2, 3: -0.9, 4: 1.0},
}
AJUSTE_TATICA: dict[str, dict[int, float]] = {
    estilo: {t: round(v - sum(valores.values()) / len(valores), 4) for t, v in valores.items()}
    for estilo, valores in _AJUSTE_TATICA_BRUTO.items()
}

# Função (id) que sustenta (+) ou contraria (−) cada estilo, de -1 a +1. O que não aparece conta 0 (neutro; a função
# «Equilibrada» e a «Tradicional» do guarda-redes são sempre neutras).
SINERGIA_FUNCAO: dict[str, dict[str, float]] = {
    "posse": {
        "libero": 1.0, "construtor": 1.0, "interior": 1.0, "organizador": 1.0, "apoio": 1.0, "criativo": 0.7,
        "corta_para_dentro": 0.5, "ofensivo": 0.3, "area_a_area": 0.3,
        "profundidade": -0.7, "pivo": -0.3, "extremo": -0.2, "defensivo": -0.2, "posicional": -0.2, "sobe": -0.2,
    },
    "bola_longa": {
        "pivo": 1.0, "profundidade": 1.0, "area_a_area": 0.6, "recuperador": 0.6, "libero": 0.5, "sobe": 0.5,
        "extremo": 0.3, "de_ala": 0.3, "finalizador": 0.3,
        "interior": -0.8, "organizador": -0.6, "apoio": -0.6, "construtor": -0.5, "criativo": -0.3,
        "corta_para_dentro": -0.3,
    },
    "contra_ataque": {
        "profundidade": 1.0, "cobertura": 0.8, "recuperador": 0.8, "extremo": 0.8, "trabalhador": 0.8, "de_ala": 0.6,
        "area_a_area": 0.5, "defensivo": 0.5, "finalizador": 0.3, "pivo": 0.2,
        "organizador": -0.4, "construtor": -0.4, "apoio": -0.4, "sobe": -0.4, "interior": -0.3, "criativo": -0.2,
    },
    "alas": {
        "extremo": 1.0, "ofensivo": 1.0, "de_ala": 1.0, "finalizador": 0.5, "sobe": 0.4, "trabalhador": 0.4,
        "area_a_area": 0.3, "pivo": 0.2,
        "interior": -1.0, "defensivo": -0.4, "corta_para_dentro": -0.3, "apoio": -0.3,
    },
    "autocarro": {
        "posicional": 1.0, "cobertura": 1.0, "defensivo": 1.0, "recuperador": 1.0, "trabalhador": 0.8, "apoio": 0.6,
        "ofensivo": -1.0, "sobe": -1.0, "extremo": -0.8, "area_a_area": -0.5, "libero": -0.5, "criativo": -0.5,
        "de_ala": -0.5, "profundidade": -0.4, "corta_para_dentro": -0.4, "construtor": -0.2, "interior": -0.2,
        "organizador": -0.1,
    },
}

# Quanto cada componente conta para a eficácia do plano de jogo (ver `Equipa.ef` no motor de jogo).
PESO_AJUSTE_TATICA = 0.18     # a tática que não encaixa no estilo custa, mas não decide o jogo (era 0,30: 2-2-2 com alas e 3-2-1 com bola longa perdiam quase sempre)
PESO_AJUSTE_FUNCOES = 0.45


def adequacao(tatica_id: int, funcoes: Mapping[str, str], estilo_id: str) -> tuple[float, float]:
    """(ajuste da tática ao estilo, ajuste das funções ao estilo), cada um entre -1 e +1."""
    por_tatica = AJUSTE_TATICA.get(estilo_id, {}).get(tatica_id, 0.0)
    sinergias = SINERGIA_FUNCAO.get(estilo_id, {})
    soma = sum(sinergias.get(funcao_id, 0.0) for funcao_id in funcoes.values())
    return por_tatica, max(-1.0, min(1.0, soma / 6.0))


def eficacia_do_plano(tatica_id: int, funcoes: Mapping[str, str], estilo_id: str) -> float:
    """Eficácia com que a equipa consegue pôr o estilo em prática: 1,0 = neutro; entre 0,45 e 1,55."""
    a_tatica, a_funcoes = adequacao(tatica_id, funcoes, estilo_id)
    return max(0.45, min(1.55, 1.0 + PESO_AJUSTE_TATICA * a_tatica + PESO_AJUSTE_FUNCOES * a_funcoes))


# --------------------------------------------------------------------------- #
# Bolas paradas
# --------------------------------------------------------------------------- #

LIVRES, CANTOS = "livres", "cantos"
TIPOS_BOLA_PARADA = (LIVRES, CANTOS)

# Média de livres perigosos por jogo (pouquíssimos, sem abusar: enunciado, «mais ou menos 1,6»).
LIVRES_POR_JOGO = 1.6

# Atributos (colunas do Excel online) de que depende o sucesso. Só o motor de jogo (Passo 7) os usa.
ATRIBUTOS_DE_QUEM_BATE = {LIVRES: ("Bola Parada",), CANTOS: ("Bola Parada",)}
ATRIBUTOS_DE_QUEM_VAI_A_BOLA_NO_CANTO = ("Cabeceamento", "Impulsão", "Altura(m)")


def marcador_valido(tatica: taticas.Tatica, escalacao: Mapping[str, str], jogador) -> bool:
    """Quem bate livres e cantos é um dos jogadores de campo (o guarda-redes fica na baliza)."""
    if not isinstance(jogador, str):
        return False
    guarda_redes = next(p.id for p in tatica.posicoes if p.papel == taticas.GR)
    return jogador in escalacao.values() and escalacao.get(guarda_redes) != jogador


def jogadores_de_campo(tatica: taticas.Tatica, escalacao: Mapping[str, str]) -> list[str]:
    """Os que podem bater livres e cantos, pela ordem das posições da tática."""
    return [escalacao[p.id] for p in tatica.posicoes if p.papel != taticas.GR]


def marcador_padrao(tatica: taticas.Tatica, escalacao: Mapping[str, str]) -> str:
    """Quem bate se o utilizador não escolher: o primeiro jogador de campo da tática (nada que dependa dos atributos)."""
    return jogadores_de_campo(tatica, escalacao)[0]


# --------------------------------------------------------------------------- #
# Para o motor de jogo (Passo 7)
# --------------------------------------------------------------------------- #

def multiplicadores(tatica: taticas.Tatica, posicao_id: str, funcao_id: str, estilo_id: str) -> dict[str, float]:
    """Multiplicadores finais dos atributos de quem joga nesta posição: função × estilo (pelo papel da posição).

    Só traz os atributos que mudam. O resultado fica sempre entre PESO_MIN² e PESO_MAX² (cerca de 0,72 a 1,82),
    por isso nenhum atributo deixa de contar.
    """
    posicao = next(p for p in tatica.posicoes if p.id == posicao_id)
    funcao = obter_funcao(tatica, posicao_id, funcao_id)
    estilo = obter_estilo(estilo_id)
    if funcao is None or estilo is None:
        raise ValueError("Função ou estilo inexistente.")
    resultado: dict[str, float] = dict(funcao.pesos)
    for atributo, fator in estilo.pesos.get(posicao.papel, {}).items():
        resultado[atributo] = round(resultado.get(atributo, 1.0) * fator, 4)
    return resultado


# --------------------------------------------------------------------------- #
# Validações (corridas no arranque do servidor e nos testes)
# --------------------------------------------------------------------------- #

def atributos_referidos() -> set[str]:
    """Todos os atributos citados nos dados deste módulo."""
    nomes: set[str] = set()
    for lista in LISTAS.values():
        for funcao in lista:
            nomes |= set(funcao.pesos)
    for estilo in ESTILOS:
        for pesos in estilo.pesos.values():
            nomes |= set(pesos)
    for grupo in ATRIBUTOS_DE_QUEM_BATE.values():
        nomes |= set(grupo)
    nomes |= set(ATRIBUTOS_DE_QUEM_VAI_A_BOLA_NO_CANTO)
    return nomes


def validar(colunas: Sequence[str]) -> None:
    """Falha cedo se algum atributo citado aqui não existe no Excel online, ou se os dados estão mal feitos."""
    desconhecidos = sorted(atributos_referidos() - set(colunas))
    if desconhecidos:
        raise ValueError(f"funcoes.py cita atributos que não existem no Excel online: {desconhecidos}")

    for chave, lista in LISTAS.items():
        ids = [f.id for f in lista]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Funções repetidas na lista {chave!r}")
        if sum(f.padrao for f in lista) != 1:
            raise ValueError(f"A lista {chave!r} tem de ter exatamente uma função por defeito")
        for f in lista:
            if not f.nome or not f.descricao:
                raise ValueError(f"Função sem nome/descrição: {chave}/{f.id}")
            if f.padrao and (f.pesos or f.mov):
                raise ValueError(f"A função por defeito não pode mexer nos pesos nem no movimento: {chave}/{f.id}")
            if not all(-12 <= v <= 12 for v in f.mov.values()) or not set(f.mov) <= {"ataque", "defesa", "largura"}:
                raise ValueError(f"Movimento inválido em {chave}/{f.id}")
            if not all(PESO_MIN <= v <= PESO_MAX for v in f.pesos.values()):
                raise ValueError(f"Multiplicador fora dos limites em {chave}/{f.id}")
    ids = [e.id for e in ESTILOS]
    if len(set(ids)) != len(ids) or len(ids) != 5:
        raise ValueError("Estilos: tem de haver exatamente 5, sem ids repetidos")
    for e in ESTILOS:
        if not e.nome or not e.descricao:
            raise ValueError(f"Estilo sem nome/descrição: {e.id}")
        if set(e.pesos) != {taticas.GR, taticas.DEF, taticas.MED, taticas.AVA}:
            raise ValueError(f"O estilo {e.id} tem de dizer algo para cada tipo de posição")
        if not set(e.tendencias) <= set(TENDENCIAS) or not all(-1 <= v <= 1 for v in e.tendencias.values()):
            raise ValueError(f"Tendências inválidas no estilo {e.id}")
        for papel, pesos in e.pesos.items():
            if not all(PESO_MIN <= v <= PESO_MAX for v in pesos.values()):
                raise ValueError(f"Multiplicador fora dos limites no estilo {e.id}/{papel}")
    # Cada posição de cada tática tem de ter uma lista (e a lista uma função por defeito).
    for tatica_ in taticas.TATICAS.values():
        for posicao in tatica_.posicoes:
            funcao_padrao(tatica_, posicao)
    # Tabelas de ajuste ao estilo: todos os estilos, táticas e funções citados existem; valores entre -1 e +1;
    # a tática é centrada (nenhuma é «melhor em tudo»).
    funcoes_existentes = {f.id for lista in LISTAS.values() for f in lista}
    if set(AJUSTE_TATICA) != set(ids) or set(SINERGIA_FUNCAO) != set(ids):
        raise ValueError("As tabelas de ajuste ao estilo têm de cobrir exatamente os 5 estilos")
    for estilo_id, por_tatica in AJUSTE_TATICA.items():
        if set(por_tatica) != set(taticas.TATICAS) or not all(-2 <= v <= 2 for v in por_tatica.values()):
            raise ValueError(f"Ajuste tática × estilo inválido: {estilo_id}")
        if abs(sum(por_tatica.values())) > 1e-3:
            raise ValueError(f"O ajuste tática × estilo de {estilo_id} tem de ser centrado (média 0)")
    for estilo_id, sinergias in SINERGIA_FUNCAO.items():
        desconhecidas = sorted(set(sinergias) - funcoes_existentes)
        if desconhecidas:
            raise ValueError(f"Sinergia função × estilo cita funções que não existem ({estilo_id}): {desconhecidas}")
        if not all(-1 <= v <= 1 for v in sinergias.values()):
            raise ValueError(f"Sinergia função × estilo fora de -1..+1 ({estilo_id})")
