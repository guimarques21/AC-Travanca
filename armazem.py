"""
armazem.py — guarda as ligas jogadas e a classificação geral (top 10 de todos os utilizadores)
==============================================================================================

Cada liga simulada fica guardada com o resultado completo. Isto serve para duas coisas:
  1. Atualizar a página (F5) mostra SEMPRE a mesma liga: o resultado não se volta a sortear.
  2. A classificação geral: todas as ligas de todos os utilizadores, ordenadas por
     pontos, depois saldo de golos, depois golos marcados, e em caso de empate total
     fica à frente quem jogou primeiro.

A sessão do utilizador só guarda um `token` (aleatório e impossível de adivinhar) para
voltar a encontrar a sua liga. O resultado guardado só tem golos, nomes e pontos: nunca forças.

Onde fica guardado (escolhido pelas variáveis de ambiente, ver app.py):
  - DATABASE_URL definida (postgresql://…): numa base de dados PostgreSQL EXTERNA. É assim que o
    Top 10 fica guardado para sempre sem pagar (por exemplo, no plano gratuito do Neon): o disco
    do Render gratuito é apagado a cada reinício, mas a base de dados externa não.
  - Caso contrário: num ficheiro SQLite (vem com o Python; é o que se usa no PC).
O resto do código só fala com a classe `Armazem` e não sabe qual dos dois está por baixo.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:                                     # só é preciso com DATABASE_URL (ver requirements.txt)
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


class ArmazemIndisponivel(Exception):
    """A base de dados não respondeu (ligação recusada, rede, disco cheio…). O jogo mostra «tenta daqui a pouco»."""


# Duas variantes só nas partes em que o SQL é diferente (a chave automática).
_ESQUEMA = {
    "sqlite": """
        CREATE TABLE IF NOT EXISTS ligas (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            token     TEXT    NOT NULL UNIQUE,
            nome      TEXT    NOT NULL,
            pontos    INTEGER NOT NULL,
            saldo     INTEGER NOT NULL,
            golos     INTEGER NOT NULL,
            criada_em TEXT    NOT NULL,
            dados     TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_classificacao ON ligas (pontos DESC, saldo DESC, golos DESC, id ASC);
    """,
    "postgres": """
        CREATE TABLE IF NOT EXISTS ligas (
            id        BIGSERIAL PRIMARY KEY,
            token     TEXT    NOT NULL UNIQUE,
            nome      TEXT    NOT NULL,
            pontos    INTEGER NOT NULL,
            saldo     INTEGER NOT NULL,
            golos     INTEGER NOT NULL,
            criada_em TEXT    NOT NULL,
            dados     TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_classificacao ON ligas (pontos DESC, saldo DESC, golos DESC, id ASC)
    """,
}

# Ordem da classificação geral. O id (ordem de chegada) desempata: quem jogou primeiro fica à frente.
_ORDEM = "pontos DESC, saldo DESC, golos DESC, id ASC"


def e_url_postgres(destino) -> bool:
    return isinstance(destino, str) and destino.strip().lower().startswith(("postgres://", "postgresql://"))


# --------------------------------------------------------------------------- #
# Os dois «motores»: sabem ligar-se e correr SQL (escrito com `?`), mais nada.
# --------------------------------------------------------------------------- #

class _MotorSQLite:
    nome = "sqlite"

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)

    def descricao(self) -> str:
        return f"SQLite ({self.caminho})"

    def _ligar(self) -> sqlite3.Connection:
        ligacao = sqlite3.connect(self.caminho, timeout=10)
        ligacao.row_factory = sqlite3.Row
        return ligacao

    def preparar(self) -> None:
        try:
            with self._ligar() as ligacao:
                ligacao.executescript(_ESQUEMA["sqlite"])
        except sqlite3.Error as erro:
            raise ArmazemIndisponivel(str(erro)) from erro

    def consultar(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            with self._ligar() as ligacao:
                return [dict(linha) for linha in ligacao.execute(sql, params).fetchall()]
        except sqlite3.Error as erro:
            raise ArmazemIndisponivel(str(erro)) from erro

    def inserir(self, sql: str, params: tuple) -> int:
        try:
            with self._ligar() as ligacao:
                return ligacao.execute(sql, params).lastrowid
        except sqlite3.Error as erro:
            raise ArmazemIndisponivel(str(erro)) from erro

    def executar(self, sql: str, params: tuple = ()) -> None:
        try:
            with self._ligar() as ligacao:
                ligacao.execute(sql, params)
        except sqlite3.Error as erro:
            raise ArmazemIndisponivel(str(erro)) from erro


class _MotorPostgres:
    nome = "postgres"
    TENTATIVAS = 2                       # a base gratuita «adormece» e a 1.ª ligação pode falhar: tenta 2 vezes

    def __init__(self, url: str):
        if psycopg is None:
            raise RuntimeError(
                "DATABASE_URL está definida mas falta o pacote psycopg. Instala com: pip install \"psycopg[binary]\""
            )
        self.url = url.strip()

    def descricao(self) -> str:
        # Nunca mostra o utilizador nem a palavra-passe do endereço.
        anfitriao = urlparse(self.url).hostname or "?"
        return f"PostgreSQL ({anfitriao})"

    @staticmethod
    def _adaptar(sql: str) -> str:
        return sql.replace("?", "%s")

    def _correr(self, trabalho):
        """Liga-se, corre `trabalho(cursor)` numa transação e fecha. Tenta de novo se a ligação falhar."""
        ultimo = None
        for tentativa in range(self.TENTATIVAS):
            try:
                # prepare_threshold=None: sem «prepared statements» no servidor (alguns pooladores não os aceitam)
                with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10,
                                     prepare_threshold=None) as ligacao:
                    with ligacao.cursor() as cursor:
                        return trabalho(cursor)
            except psycopg.OperationalError as erro:
                ultimo = erro
                if tentativa + 1 < self.TENTATIVAS:
                    time.sleep(0.5 * (tentativa + 1))
            except psycopg.Error as erro:
                raise ArmazemIndisponivel(str(erro)) from erro
        raise ArmazemIndisponivel(str(ultimo)) from ultimo

    def preparar(self) -> None:
        def criar(cursor):
            for instrucao in _ESQUEMA["postgres"].split(";"):
                if instrucao.strip():
                    cursor.execute(instrucao)
        self._correr(criar)

    def consultar(self, sql: str, params: tuple = ()) -> list[dict]:
        sql = self._adaptar(sql)

        def ler(cursor):
            cursor.execute(sql, params)
            return [dict(linha) for linha in cursor.fetchall()]
        return self._correr(ler)

    def inserir(self, sql: str, params: tuple) -> int:
        sql = self._adaptar(sql) + " RETURNING id"

        def gravar(cursor):
            cursor.execute(sql, params)
            return cursor.fetchone()["id"]
        return self._correr(gravar)

    def executar(self, sql: str, params: tuple = ()) -> None:
        sql = self._adaptar(sql)
        self._correr(lambda cursor: cursor.execute(sql, params))


# --------------------------------------------------------------------------- #
# A classe que o resto do jogo usa
# --------------------------------------------------------------------------- #

class Armazem:
    """Acesso à base de dados. `destino` é um caminho de ficheiro (SQLite) ou um endereço postgresql://…"""

    def __init__(self, destino: str | Path):
        self._motor = _MotorPostgres(destino) if e_url_postgres(destino) else _MotorSQLite(destino)
        self._preparado = False
        self._tentar_preparar()

    @property
    def tipo(self) -> str:
        return self._motor.nome

    def descricao(self) -> str:
        """Texto para os registos (sem palavras-passe)."""
        return self._motor.descricao()

    def _tentar_preparar(self) -> bool:
        """Cria a tabela (se ainda não existe). Se a base externa não responde agora, tenta na próxima operação."""
        if not self._preparado:
            try:
                self._motor.preparar()
                self._preparado = True
            except ArmazemIndisponivel:
                if self._motor.nome == "sqlite":
                    raise                   # um ficheiro local que não abre é um erro de configuração: falha já
        return self._preparado

    def _pronto(self) -> None:
        if not self._tentar_preparar():
            raise ArmazemIndisponivel("A base de dados ainda não respondeu.")

    # ------------------------------------------------------------------ escrever

    def guardar_liga(self, nome: str, dados: dict) -> tuple[int, str]:
        """Guarda uma liga acabada de simular. `dados` é o resultado (ver liga.ResultadoLiga.para_dict).

        Devolve (id, token): o token é o que a sessão do utilizador guarda para a voltar a encontrar.
        """
        self._pronto()
        resumo = dados["resumo"]
        token = secrets.token_urlsafe(24)
        id_ = self._motor.inserir(
            "INSERT INTO ligas (token, nome, pontos, saldo, golos, criada_em, dados) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token, nome, resumo["pontos"], resumo["saldo"], resumo["golos_marcados"],
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                json.dumps(dados, ensure_ascii=False),
            ),
        )
        return id_, token

    def apagar_liga(self, token: str) -> None:
        """Apaga uma liga (usado só pelo script testar_base_de_dados.py)."""
        self._pronto()
        self._motor.executar("DELETE FROM ligas WHERE token = ?", (token,))

    # ------------------------------------------------------------------ ler

    def obter_liga(self, token: str) -> dict | None:
        """A liga com este token, ou None se não existe."""
        if not isinstance(token, str) or not token:
            return None
        self._pronto()
        linhas = self._motor.consultar("SELECT id, nome, dados FROM ligas WHERE token = ?", (token,))
        if not linhas:
            return None
        return {"id": linhas[0]["id"], "nome": linhas[0]["nome"], "dados": json.loads(linhas[0]["dados"])}

    def top(self, limite: int = 10) -> list[dict]:
        """As melhores ligas de todos os utilizadores: posição, id, nome, pontos, saldo, golos."""
        self._pronto()
        linhas = self._motor.consultar(
            f"SELECT id, nome, pontos, saldo, golos FROM ligas ORDER BY {_ORDEM} LIMIT ?", (int(limite),)
        )
        return [{"posicao": i, **linha} for i, linha in enumerate(linhas, start=1)]

    def posicao(self, id_liga: int) -> dict | None:
        """A linha desta liga na classificação geral (com a sua posição), ou None se não existe."""
        self._pronto()
        linhas = self._motor.consultar(
            "SELECT id, nome, pontos, saldo, golos FROM ligas WHERE id = ?", (id_liga,)
        )
        if not linhas:
            return None
        linha = linhas[0]
        p, s, g, i = linha["pontos"], linha["saldo"], linha["golos"], linha["id"]
        antes = self._motor.consultar(
            """
            SELECT COUNT(*) AS n FROM ligas WHERE
                pontos > ?
                OR (pontos = ? AND saldo > ?)
                OR (pontos = ? AND saldo = ? AND golos > ?)
                OR (pontos = ? AND saldo = ? AND golos = ? AND id < ?)
            """,
            (p, p, s, p, s, g, p, s, g, i),
        )[0]["n"]
        return {"posicao": antes + 1, **linha}

    def total(self) -> int:
        """Quantas ligas já foram jogadas (por todos os utilizadores)."""
        self._pronto()
        return self._motor.consultar("SELECT COUNT(*) AS n FROM ligas")[0]["n"]
