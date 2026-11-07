"""
testar_base_de_dados.py — confirma que a base de dados do Top 10 está bem ligada.

Como usar (no PC):
    1. Define o endereço da base de dados (o mesmo que vais pôr no Render):
         PowerShell:   $env:DATABASE_URL = "postgresql://..."
         cmd:          set DATABASE_URL=postgresql://...
    2. Corre:  python testar_base_de_dados.py

Faz isto: liga-se, grava uma liga de teste, lê-a de volta, vê onde ficava no Top 10 e apaga-a.
Não deixa nada na classificação. Sem DATABASE_URL testa o ficheiro SQLite local.
"""

import os
import sys
import tempfile

from armazem import Armazem, ArmazemIndisponivel

url = (os.environ.get("DATABASE_URL") or "").strip()
if url:
    destino = url
else:
    destino = os.path.join(tempfile.mkdtemp(), "teste.sqlite3")
    print("DATABASE_URL não está definida: a testar um ficheiro SQLite temporário.")

try:
    armazem = Armazem(destino)
    print("A ligar a:", armazem.descricao())
    antes = armazem.total()
    print("Ligas já guardadas:", antes)

    liga_de_teste = {
        "resumo": {"pontos": 999, "saldo": 99, "golos_marcados": 99},
        "nota": "liga de teste (é apagada logo a seguir)",
    }
    id_, token = armazem.guardar_liga("TESTE-LIGACAO", liga_de_teste)
    print("Gravei uma liga de teste (id %s)." % id_)

    lida = armazem.obter_liga(token)
    assert lida is not None and lida["nome"] == "TESTE-LIGACAO" and lida["dados"] == liga_de_teste, "o que li não é o que gravei"
    linha = armazem.posicao(id_)
    assert linha is not None and linha["posicao"] >= 1
    print("Li-a de volta e estava certa (ficava em %sº no Top 10)." % linha["posicao"])

    armazem.apagar_liga(token)
    assert armazem.obter_liga(token) is None and armazem.total() == antes
    print("Apaguei-a. Ligas guardadas:", armazem.total())
    print()
    print("TUDO OK: a base de dados funciona.")
except (ArmazemIndisponivel, AssertionError, RuntimeError) as erro:
    print()
    print("FALHOU:", erro)
    sys.exit(1)
