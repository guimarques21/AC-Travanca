"""
data_loader.py — leitura dos Excel do AC Travanca (pandas)
===========================================================

REGRA DE OURO: separação rigorosa entre os modos de jogo.

    carregar_jogadores_offline()  -> lê SÓ  dados/Jogadores_e_Estatísticas.xlsx
    carregar_jogadores_online()   -> lê SÓ  dados/Jogadores e Estatísticas ModoOnline.xlsx
    carregar_equipas_offline()    -> lê SÓ  dados/Lista_de_equipas_e_Força.xlsx
                                            (adversárias da liga offline)

Cada função tem o seu ficheiro fixo: nenhuma recebe o caminho por argumento,
por isso é impossível o modo online ler o Excel do offline (e vice-versa).

O total de jogadores disponíveis no sorteio é SEMPRE o número de linhas lidas:
    total = len(carregar_jogadores_offline())   # ou ..._online()
Se o Excel for editado (jogadores acrescentados/removidos), o total muda sozinho.

Nota sobre o Excel OFFLINE: a folha tem DUAS tabelas lado a lado (guarda-redes à
esquerda, jogadores de campo à direita, separadas por uma coluna vazia). Ler a
folha "à bruta" daria só as linhas da tabela maior. Aqui as tabelas são
detetadas dinamicamente e juntadas, sem depender de letras de colunas.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------- #
# Localização dos ficheiros
# --------------------------------------------------------------------------- #

# Caminho relativo a ESTE ficheiro (e não à pasta de onde se corre o programa):
# assim funciona igual no PC, no Render ou com o gunicorn.
PASTA_DADOS = Path(__file__).resolve().parent / "dados"

FICHEIRO_JOGADORES_OFFLINE = "Jogadores_e_Estatísticas.xlsx"
FICHEIRO_JOGADORES_ONLINE = "Jogadores e Estatísticas ModoOnline.xlsx"
FICHEIRO_EQUIPAS_OFFLINE = "Lista_de_equipas_e_Força.xlsx"

# --------------------------------------------------------------------------- #
# Colunas esperadas (validação — se alguém mudar o Excel, o erro é claro)
# --------------------------------------------------------------------------- #

# Offline — tabela dos guarda-redes
COLUNAS_GR_OFFLINE = ["Nome", "Posição", "Habilidade como Guarda-Redes"]
# Offline — tabela dos jogadores de campo
COLUNAS_CAMPO_OFFLINE = [
    "Nome", "Posição", "Habilidade Defesa", "Habilidade Drible",
    "Habilidade Remate", "Habilidade Físico", "Habilidade Passe",
    "Habilidade Velocidade",
]

# Online — colunas de texto; TODAS as outras são atributos numéricos.
# (assim, se acrescentares um atributo novo ao Excel, ele entra sem mexer no código)
COLUNAS_TEXTO_ONLINE = {"Nome", "Posição(ões)", "Pé Preferido", "Traços"}
COLUNAS_OBRIGATORIAS_ONLINE = ["Nome", "Posição(ões)", "Altura(m)", "Pé Preferido"]

COLUNAS_EQUIPAS_OFFLINE = ["Nome da Equipa", "Força da Equipa"]


class ErroDados(Exception):
    """Problema ao ler/validar um Excel do jogo (mensagem pensada para quem edita o Excel)."""


# --------------------------------------------------------------------------- #
# Utilitários internos
# --------------------------------------------------------------------------- #

def _normalizar(texto: str) -> str:
    """Normaliza acentos (NFC) e maiúsculas, para comparar nomes de ficheiros.

    Porquê: o mesmo "í" pode ser guardado de duas formas em Unicode. No Windows
    é raro dar problema, mas em Linux (Render) um nome "diferente por bytes"
    não é encontrado. Comparando normalizado, o ficheiro é sempre achado.
    """
    return unicodedata.normalize("NFC", texto).casefold()


def _pastas_candidatas() -> list[Path]:
    """Onde procurar os Excel, por ordem: a pasta «dados» (qualquer combinação de maiúsculas/minúsculas,
    porque o Linux do Render distingue «dados» de «Dados» e o Windows não) e, em último caso, a própria
    pasta do código (Excel soltos ao lado do app.py)."""
    base = PASTA_DADOS.parent
    candidatas = [PASTA_DADOS] if PASTA_DADOS.is_dir() else []
    if base.is_dir():
        alvo = _normalizar(PASTA_DADOS.name)
        candidatas += [p for p in sorted(base.iterdir())
                       if p.is_dir() and p != PASTA_DADOS and _normalizar(p.name) == alvo]
        candidatas.append(base)
    return candidatas


def _localizar_ficheiro(nome: str) -> Path:
    """Devolve o caminho do ficheiro dentro de PASTA_DADOS (tolerante a Unicode/maiúsculas)."""
    alvo = _normalizar(nome)
    vistos: dict[Path, list[str]] = {}
    for pasta in _pastas_candidatas():
        existentes = sorted(f.name for f in pasta.iterdir() if f.is_file())
        vistos[pasta] = existentes
        for existente in existentes:
            if _normalizar(existente) == alvo:
                return pasta / existente

    # Não achou: diz onde procurou e o que lá está (para se perceber logo o que falta no GitHub/no Render).
    base = PASTA_DADOS.parent
    raiz = sorted((p.name + "/") if p.is_dir() else p.name for p in base.iterdir()) if base.is_dir() else []
    procurou = [str(p) for p in vistos] or [f"{PASTA_DADOS} (a pasta não existe)"]
    raise ErroDados(
        f"Ficheiro '{nome}' não encontrado. Procurei em: {procurou}. "
        f"Ficheiros .xlsx vistos: {sorted({f for fs in vistos.values() for f in fs if f.lower().endswith('.xlsx')}) or 'nenhum'}. "
        f"O que há na pasta do código ({base}): {raiz}"
    )


def _exigir_colunas(df: pd.DataFrame, obrigatorias: list[str], onde: str) -> None:
    em_falta = [c for c in obrigatorias if c not in df.columns]
    if em_falta:
        raise ErroDados(f"{onde}: faltam as colunas {em_falta}. Colunas lidas: {list(df.columns)}")


def _limpar_texto(df: pd.DataFrame, colunas: list[str]) -> None:
    """Tira espaços nas pontas e normaliza o Unicode das colunas de texto (in-place)."""
    for coluna in colunas:
        if coluna in df.columns:
            df[coluna] = df[coluna].map(
                lambda v: unicodedata.normalize("NFC", str(v)).strip() if pd.notna(v) else v
            )


def _converter_numericas(df: pd.DataFrame, colunas: list[str], onde: str) -> None:
    """Converte colunas para número; falha com a linha do Excel se houver lixo ou vazios."""
    for coluna in colunas:
        convertida = pd.to_numeric(df[coluna], errors="coerce")
        problemas = df.index[convertida.isna()]
        if len(problemas):
            # +2: o índice começa em 0 e a linha 1 do Excel é o cabeçalho.
            linhas = [int(i) + 2 for i in problemas]
            raise ErroDados(f"{onde}: coluna '{coluna}' vazia ou não numérica (linhas ~{linhas}).")
        df[coluna] = convertida


def _exigir_nomes_unicos(df: pd.DataFrame, coluna: str, onde: str) -> None:
    """O sorteio depende de cada jogador/equipa ser único."""
    if df[coluna].isna().any() or (df[coluna].astype(str).str.strip() == "").any():
        raise ErroDados(f"{onde}: há linhas com '{coluna}' vazio.")
    repetidos = sorted(df.loc[df[coluna].str.casefold().duplicated(keep=False), coluna].unique())
    if repetidos:
        raise ErroDados(f"{onde}: '{coluna}' repetido: {repetidos}")


def _separar_tabelas_lado_a_lado(bruto: pd.DataFrame) -> list[pd.DataFrame]:
    """Divide uma folha com várias tabelas lado a lado (separadas por colunas totalmente vazias).

    `bruto` foi lido com header=None; a 1.ª linha de cada bloco é o seu cabeçalho.
    """
    colunas_vazias = bruto.isna().all(axis=0)

    grupos: list[list[int]] = []
    atual: list[int] = []
    for coluna, vazia in colunas_vazias.items():
        if vazia:
            if atual:
                grupos.append(atual)
                atual = []
        else:
            atual.append(coluna)
    if atual:
        grupos.append(atual)

    tabelas = []
    for colunas in grupos:
        bloco = bruto[colunas]
        cabecalho = [str(c).strip() for c in bloco.iloc[0]]
        dados = bloco.iloc[1:].copy()
        dados.columns = cabecalho
        tabelas.append(dados.dropna(how="all").reset_index(drop=True))
    return tabelas


# --------------------------------------------------------------------------- #
# Leitura (com cache invalidada automaticamente quando o Excel muda)
# --------------------------------------------------------------------------- #
# Cada leitor interno recebe (caminho, data de modificação). Se o ficheiro for
# alterado, a data muda e o Excel é relido; senão devolve a cópia em memória.

@lru_cache(maxsize=2)
def _ler_jogadores_offline(caminho: str, _versao: int) -> pd.DataFrame:
    bruto = pd.read_excel(caminho, header=None, dtype=object)
    tabelas = _separar_tabelas_lado_a_lado(bruto)

    guarda_redes = next((t for t in tabelas if "Habilidade como Guarda-Redes" in t.columns), None)
    campo = next((t for t in tabelas if "Habilidade Defesa" in t.columns), None)
    if guarda_redes is None or campo is None:
        raise ErroDados(
            f"{FICHEIRO_JOGADORES_OFFLINE}: esperava 2 tabelas lado a lado (guarda-redes e campo) "
            f"mas encontrei {len(tabelas)} com as colunas {[list(t.columns) for t in tabelas]}."
        )

    _exigir_colunas(guarda_redes, COLUNAS_GR_OFFLINE, "Offline/guarda-redes")
    _exigir_colunas(campo, COLUNAS_CAMPO_OFFLINE, "Offline/campo")

    # Cada tabela só tem os seus próprios atributos preenchidos.
    for tabela, colunas, onde in (
        (guarda_redes, COLUNAS_GR_OFFLINE, "Offline/guarda-redes"),
        (campo, COLUNAS_CAMPO_OFFLINE, "Offline/campo"),
    ):
        _limpar_texto(tabela, ["Nome", "Posição"])
        _converter_numericas(tabela, [c for c in colunas if c.startswith("Habilidade")], onde)

    # Junta as duas tabelas. Onde um atributo não se aplica (ex.: "Habilidade Defesa"
    # de um guarda-redes) fica NaN — as regras de "fora de posição" tratam disso mais tarde.
    jogadores = pd.concat([guarda_redes, campo], ignore_index=True)
    _exigir_nomes_unicos(jogadores, "Nome", "Offline")
    return jogadores


@lru_cache(maxsize=2)
def _ler_jogadores_online(caminho: str, _versao: int) -> pd.DataFrame:
    jogadores = pd.read_excel(caminho, dtype=object)
    jogadores.columns = [str(c).strip() for c in jogadores.columns]
    jogadores = jogadores.dropna(how="all").reset_index(drop=True)

    _exigir_colunas(jogadores, COLUNAS_OBRIGATORIAS_ONLINE, "Online")
    _limpar_texto(jogadores, sorted(COLUNAS_TEXTO_ONLINE))
    if "Traços" in jogadores.columns:
        jogadores["Traços"] = jogadores["Traços"].fillna("")  # sem traços = texto vazio

    numericas = [c for c in jogadores.columns if c not in COLUNAS_TEXTO_ONLINE]
    _converter_numericas(jogadores, numericas, "Online")
    _exigir_nomes_unicos(jogadores, "Nome", "Online")
    return jogadores


@lru_cache(maxsize=2)
def _ler_equipas_offline(caminho: str, _versao: int) -> pd.DataFrame:
    equipas = pd.read_excel(caminho, dtype=object)
    equipas.columns = [str(c).strip() for c in equipas.columns]
    equipas = equipas.dropna(how="all").reset_index(drop=True)

    _exigir_colunas(equipas, COLUNAS_EQUIPAS_OFFLINE, "Equipas")
    equipas = equipas[COLUNAS_EQUIPAS_OFFLINE].copy()
    _limpar_texto(equipas, ["Nome da Equipa"])
    _converter_numericas(equipas, ["Força da Equipa"], "Equipas")
    _exigir_nomes_unicos(equipas, "Nome da Equipa", "Equipas")
    return equipas


def _com_versao(nome_ficheiro: str) -> tuple[str, int]:
    caminho = _localizar_ficheiro(nome_ficheiro)
    return str(caminho), caminho.stat().st_mtime_ns


# --------------------------------------------------------------------------- #
# API pública — uma função por ficheiro, sem argumentos de caminho
# --------------------------------------------------------------------------- #

def carregar_jogadores_offline() -> pd.DataFrame:
    """Jogadores do MODO OFFLINE (guarda-redes + campo juntos). len(df) = total do sorteio."""
    return _ler_jogadores_offline(*_com_versao(FICHEIRO_JOGADORES_OFFLINE)).copy()


def carregar_jogadores_online() -> pd.DataFrame:
    """Jogadores do MODO ONLINE (todos os atributos detalhados). len(df) = total do sorteio."""
    return _ler_jogadores_online(*_com_versao(FICHEIRO_JOGADORES_ONLINE)).copy()


def carregar_equipas_offline() -> pd.DataFrame:
    """Equipas adversárias e respetiva força (só para a liga do modo offline)."""
    return _ler_equipas_offline(*_com_versao(FICHEIRO_EQUIPAS_OFFLINE)).copy()


# --------------------------------------------------------------------------- #
# Verificação rápida:  python data_loader.py
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    offline = carregar_jogadores_offline()
    online = carregar_jogadores_online()
    equipas = carregar_equipas_offline()
    print(f"Offline : {len(offline):>3} jogadores  ({FICHEIRO_JOGADORES_OFFLINE})")
    print(f"Online  : {len(online):>3} jogadores  ({FICHEIRO_JOGADORES_ONLINE})")
    print(f"Equipas : {len(equipas):>3} equipas   ({FICHEIRO_EQUIPAS_OFFLINE})")
